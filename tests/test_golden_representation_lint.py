# 정답지 표현 계약 lint 테스트: output_representation 선언·golden lint·파이프라인 정직 중단.
import json
from pathlib import Path

from repo_idea_miner.config import Settings
from repo_idea_miner.factory_core_gates import lint_golden_representation
from repo_idea_miner.factory_core_pipeline import run_core_factory
from repo_idea_miner.factory_core_prompts import (
    build_core_build_prompt,
    build_core_contract_prompt,
    build_scenario_golden_prompt,
    mock_core_contract_draft,
    mock_core_factory_overrides,
    mock_scenario_golden_output,
    render_build_task_packet_md,
)
from repo_idea_miner.factory_pipeline import FactorySettings, sample_challenge
from repo_idea_miner.factory_validate import validate_product_run_dir
from repo_idea_miner.llm_client import LLMCallLogger, MockLLMClient

FSET = FactorySettings(use_docker="off", sandbox_timeout_seconds=60.0)
SETTINGS = Settings(google_keys={})

_REP_OBJECT = {
    "event_item_type": "object",
    "event_required_keys": ["type", "target_id"],
    "event_kind_key": "type",
    "event_kinds": ["NAVIGATED", "RENAMED"],
    "summary_format": "3 ok, 0 failed",
    "summary_rule": "성공/실패 액션 수로 계산",
}


def _golden(events, summary="1 ok, 0 failed", sid="scenario_001"):
    return {"scenario_id": sid, "expected_final_state": {}, "expected_events": events,
            "expected_summary": summary, "comparison_mode": "exact"}


# ---------------------------------------------------------------- lint 단위

def test_lint_not_declared_is_tolerant():
    out = lint_golden_representation({}, [_golden(["NAVIGATED"])])
    assert out["status"] == "NOT_DECLARED"
    assert out["problems"] == []


def test_lint_object_conforming_passes():
    contract = {"output_representation": _REP_OBJECT}
    events = [{"type": "NAVIGATED", "target_id": "dir_1"},
              {"type": "RENAMED", "target_id": "file_1", "extra": 1}]
    out = lint_golden_representation(contract, [_golden(events)])
    assert out["status"] == "PASS", out["problems"]


def test_lint_abstract_string_event_fails_when_object_declared():
    """#54 실사례: golden events가 'NAVIGATED' 추상 라벨 → FAIL."""
    contract = {"output_representation": _REP_OBJECT}
    out = lint_golden_representation(contract, [_golden(["NAVIGATED", "RENAMED"])])
    assert out["status"] == "FAIL"
    assert any("object가 아님" in p for p in out["problems"])


def test_lint_missing_required_key_fails():
    contract = {"output_representation": _REP_OBJECT}
    out = lint_golden_representation(contract, [_golden([{"type": "NAVIGATED"}])])
    assert out["status"] == "FAIL"
    assert any("필수 키 없음" in p and "target_id" in p for p in out["problems"])


def test_lint_unknown_kind_fails():
    contract = {"output_representation": _REP_OBJECT}
    out = lint_golden_representation(
        contract, [_golden([{"type": "JUMPED", "target_id": "x"}])])
    assert out["status"] == "FAIL"
    assert any("event_kinds에 없음" in p for p in out["problems"])


def test_lint_string_declared_object_event_fails():
    contract = {"output_representation": {"event_item_type": "string",
                                          "event_kinds": ["NAVIGATED"]}}
    out = lint_golden_representation(contract, [_golden([{"type": "NAVIGATED"}])])
    assert out["status"] == "FAIL"
    assert any("string이 아님" in p for p in out["problems"])


def test_lint_string_declared_conforming_passes():
    contract = {"output_representation": {"event_item_type": "string",
                                          "event_kinds": ["NAVIGATED"]}}
    out = lint_golden_representation(contract, [_golden(["NAVIGATED"])])
    assert out["status"] == "PASS", out["problems"]


def test_lint_non_string_summary_fails():
    """#54 실사례: runner summary가 dict인데 골든이 산문 → 하네스 표준은 문자열 고정."""
    contract = {"output_representation": _REP_OBJECT}
    out = lint_golden_representation(
        contract, [_golden([], summary={"total_actions": 4, "success": 4})])
    assert out["status"] == "FAIL"
    assert any("expected_summary가 string이 아님" in p for p in out["problems"])


def test_lint_empty_expectations_pass():
    contract = {"output_representation": _REP_OBJECT}
    out = lint_golden_representation(contract, [_golden([], summary="")])
    assert out["status"] == "PASS", out["problems"]


def test_lint_mock_fixture_conforms():
    """mock 계약/골든 자체가 표현 계약을 준수해야 한다 (파이프라인 기본 경로)."""
    contract = mock_core_contract_draft()["core_contract"]
    goldens = mock_scenario_golden_output()["goldens"]
    out = lint_golden_representation(contract, goldens)
    assert out["status"] == "PASS", out["problems"]


# ---------------------------------------------------------------- prompt 규칙

def test_contract_prompt_requires_representation():
    p = build_core_contract_prompt("{}", "{}")
    assert "output_representation" in p
    assert "summary_format" in p


def test_scenario_golden_prompt_has_representation_rules():
    p = build_scenario_golden_prompt("{}", "{}")
    assert "표현 계약" in p
    assert "추상 라벨" in p
    assert "산문" in p


def test_build_prompt_and_packet_enforce_representation():
    packet = render_build_task_packet_md("{}", {"runner_command": "x",
                                                "required_output_fields": ["ok"]}, ["s1"])
    assert "output_representation" in packet
    p = build_core_build_prompt(packet, "{}", "[]", [])
    assert "output_representation" in p


# ---------------------------------------------------------------- 파이프라인 통합 (mock)

def _run_mock(tmp_path, overrides=None):
    llm = MockLLMClient(overrides={**mock_core_factory_overrides(), **(overrides or {})},
                        call_logger=LLMCallLogger(None))
    return run_core_factory(sample_challenge(), mode="mock", output_dir=tmp_path / "runs",
                            settings=SETTINGS, factory_settings=FSET, llm=llm)


def _harness(run_dir: Path) -> dict:
    return json.loads((run_dir / "harness_summary.json").read_text(encoding="utf-8"))


def test_pipeline_writes_lint_artifact_pass(tmp_path):
    res = _run_mock(tmp_path)
    run_dir = Path(res["run_dir"])
    lint = json.loads((run_dir / "golden_representation_lint.json").read_text(encoding="utf-8"))
    assert lint["status"] == "PASS"
    assert _harness(run_dir)["stages"]["scenario_oracle"]["representation_lint"] == "PASS"


def test_pipeline_stops_on_violating_golden(tmp_path):
    """골든이 표현 계약 위반(추상 라벨 이벤트)이고 수리도 실패하면 Build로 넘기지 않는다."""
    bad_sg = mock_scenario_golden_output()
    bad_sg["goldens"][0]["expected_events"] = ["NAVIGATED", "RENAMED"]
    res = _run_mock(tmp_path, overrides={"scenario_golden": bad_sg,
                                         "scenario_golden_repair": bad_sg})
    assert res["spec_status"] == "NEEDS_SPEC_REPAIR"
    run_dir = Path(res["run_dir"])
    lint = json.loads((run_dir / "golden_representation_lint.json").read_text(encoding="utf-8"))
    assert lint["status"] == "FAIL"
    assert not (run_dir / "final_artifact").is_dir()  # Build 미진행


def test_pipeline_repair_fixes_violation(tmp_path):
    """수리 데스크가 표현 계약에 맞게 고치면 정상 진행된다."""
    bad_sg = mock_scenario_golden_output()
    bad_sg["goldens"][0]["expected_events"] = ["NAVIGATED"]
    good_sg = mock_scenario_golden_output()
    res = _run_mock(tmp_path, overrides={"scenario_golden": bad_sg,
                                         "scenario_golden_repair": good_sg})
    assert res["spec_status"] is None
    stage = _harness(Path(res["run_dir"]))["stages"]["scenario_oracle"]
    assert stage["repair_attempts"] == 1
    assert stage["representation_lint"] == "PASS"


# ---------------------------------------------------------------- validate 연동

def test_validate_flags_lint_fail_with_green_verdict(tmp_path):
    res = _run_mock(tmp_path)
    run_dir = Path(res["run_dir"])
    (run_dir / "golden_representation_lint.json").write_text(
        json.dumps({"status": "FAIL", "problems": ["scenario_001: expected_events[0]가 object가 아님"]}),
        encoding="utf-8")
    _ok, problems = validate_product_run_dir(run_dir, [])
    assert any("representation lint FAIL" in p for p in problems)


def test_validate_tolerates_lint_fail_with_honest_verdict(tmp_path):
    res = _run_mock(tmp_path)
    run_dir = Path(res["run_dir"])
    (run_dir / "golden_representation_lint.json").write_text(
        json.dumps({"status": "FAIL", "problems": ["x"]}), encoding="utf-8")
    dsum_path = run_dir / "dashboard_summary.json"
    dsum = json.loads(dsum_path.read_text(encoding="utf-8"))
    dsum["verdict"] = "NEEDS_MORE_GEMMA_LOOP"
    dsum_path.write_text(json.dumps(dsum, ensure_ascii=False), encoding="utf-8")
    _ok, problems = validate_product_run_dir(run_dir, [])
    assert not any("representation lint FAIL" in p for p in problems)
