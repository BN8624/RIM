# Phase 2D-1 P0 선행수정 테스트: anti-hardcode 스캔 시점 통일, mock fallback 금지, representation strict mode.
import json
from pathlib import Path

from repo_idea_miner.config import Settings
from repo_idea_miner.factory_core_gates import (
    detect_mock_fallback,
    lint_golden_representation,
    run_anti_hardcode_gate,
)
from repo_idea_miner.factory_core_pipeline import run_core_factory
from repo_idea_miner.factory_core_prompts import (
    MOCK_FALLBACK_RULES,
    build_product_layer_prompt,
    build_product_layer_repair_prompt,
    mock_core_contract_draft,
    mock_core_factory_overrides,
    mock_product_layer_output,
    mock_scenario_golden_output,
)
from repo_idea_miner.factory_core_schemas import HARNESS_SCHEMA_VERSION, CoreContract
from repo_idea_miner.factory_pipeline import FactorySettings, sample_challenge
from repo_idea_miner.llm_client import LLMCallLogger, MockLLMClient

FSET = FactorySettings(use_docker="off", sandbox_timeout_seconds=60.0)
SETTINGS = Settings(google_keys={})

_FALLBACK_JS = """
async function showReplaySafe(file) {
  try {
    await showReplay(file);
  } catch (err) {
    summaryEl.textContent = "summary: 2 cards, 0 rejected";
    stateEl.textContent = JSON.stringify({ ok: true, status: "completed" });
  }
}
"""

_HONEST_FALLBACK_JS = """
async function showReplaySafe(file) {
  try {
    await showReplay(file);
  } catch (err) {
    summaryEl.textContent = "RUNNER_UNAVAILABLE";
    stateEl.textContent = "NOT_EXECUTED";
  }
}
"""


# ---------------------------------------------------------------- §2.2 detect_mock_fallback 단위

def test_detect_catch_success_mock_is_flagged():
    out = detect_mock_fallback({"product/viewer/viewer.js": _FALLBACK_JS})
    assert out["mock_fallback_count"] >= 1
    assert any("성공 mock/demo" in p for p in out["problems"])


def test_detect_honest_fallback_state_passes():
    out = detect_mock_fallback({"product/viewer/viewer.js": _HONEST_FALLBACK_JS})
    assert out["mock_fallback_count"] == 0


def test_detect_fake_result_sources_flagged():
    js = "const result = { value: Math.random(), at: Date.now() };"
    out = detect_mock_fallback({"product/app.js": js})
    assert out["mock_fallback_count"] == 2
    assert all("가짜 실행 결과" in p for p in out["problems"])


def test_detect_demo_data_without_state_token_flagged():
    js = "const demoResult = { nodes: [1, 2] };\nrender(demoResult);"
    out = detect_mock_fallback({"product/app.js": js})
    assert out["mock_fallback_count"] >= 1
    assert any("demo 데이터" in p for p in out["problems"])


def test_detect_clean_mock_viewer_passes():
    files = {e["path"]: e["content"] for e in mock_product_layer_output()["files"]}
    out = detect_mock_fallback(files)
    assert out["mock_fallback_count"] == 0, out["problems"]


# ---------------------------------------------------------------- §2.2 gate 통합

def _make_workspace(tmp_path: Path, product_js: str | None) -> Path:
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "runner.py").write_text("print('{}')\n", encoding="utf-8")
    if product_js is not None:
        (ws / "product" / "viewer").mkdir(parents=True)
        (ws / "product" / "viewer" / "viewer.js").write_text(product_js, encoding="utf-8")
    return ws


def test_gate_fails_on_product_mock_fallback(tmp_path):
    ws = _make_workspace(tmp_path, _FALLBACK_JS)
    result, summary = run_anti_hardcode_gate(
        ws, [], {}, {}, timeout_seconds=5.0, use_docker=False, secrets=[], run_level2=False)
    assert not result.ok
    assert summary["status"] == "FAIL"
    assert summary["mock_fallback_count"] >= 1
    assert summary["hardcode_risk"] == "high"


def test_gate_passes_without_product_dir(tmp_path):
    """pre-product 시점(빌드 gate)에는 product/가 없어 mock fallback 검사 대상이 0이다."""
    ws = _make_workspace(tmp_path, None)
    result, summary = run_anti_hardcode_gate(
        ws, [], {}, {}, timeout_seconds=5.0, use_docker=False, secrets=[], run_level2=False)
    assert result.ok, result.problems
    assert summary["mock_fallback_count"] == 0
    assert summary["product_files_scanned"] == []


# ---------------------------------------------------------------- §2.2 prompt 규칙

def test_product_layer_prompts_contain_mock_fallback_rules():
    assert "DEMO_ONLY" in MOCK_FALLBACK_RULES
    p = build_product_layer_prompt("{}", "{}", "", [])
    assert "Mock fallback 금지" in p
    assert "RUNNER_UNAVAILABLE" in p
    rp = build_product_layer_repair_prompt({}, "{}")
    assert "Mock fallback 금지" in rp


# ---------------------------------------------------------------- §2.3 strict lint 단위

_REP = {
    "event_item_type": "object",
    "event_required_keys": ["type", "command_id", "card_id"],
    "event_kind_key": "type",
    "event_kinds": ["command_executed"],
    "summary_format": "2 cards, 0 rejected",
    "summary_rule": "history_count로 계산",
}


def _golden(events=None, final_state=None, summary=""):
    return {"scenario_id": "scenario_001", "expected_final_state": final_state or {},
            "expected_events": events or [], "expected_summary": summary,
            "comparison_mode": "exact"}


def test_strict_missing_representation_fails():
    contract = {"harness_schema_version": 2}
    out = lint_golden_representation(contract, [_golden(final_state={"tick": 1})])
    assert out["status"] == "FAIL"
    assert out["strict"] is True
    assert any("output_representation 미선언" in p for p in out["problems"])


def test_legacy_missing_representation_stays_not_declared():
    out = lint_golden_representation({}, [_golden()])
    assert out["status"] == "NOT_DECLARED"
    assert out["strict"] is False


def test_strict_missing_summary_format_fails():
    rep = {**_REP, "summary_format": ""}
    contract = {"harness_schema_version": 2, "output_representation": rep}
    out = lint_golden_representation(contract, [_golden(final_state={"tick": 1})])
    assert out["status"] == "FAIL"
    assert any("summary_format 미선언" in p for p in out["problems"])


def test_strict_object_without_required_keys_fails():
    rep = {**_REP, "event_required_keys": []}
    contract = {"harness_schema_version": 2, "output_representation": rep}
    out = lint_golden_representation(contract, [_golden(final_state={"tick": 1})])
    assert out["status"] == "FAIL"
    assert any("event_required_keys 미선언" in p for p in out["problems"])


def test_strict_empty_golden_fails():
    contract = {"harness_schema_version": 2, "output_representation": _REP}
    out = lint_golden_representation(contract, [_golden()])
    assert out["status"] == "FAIL"
    assert any("빈 정답지" in p for p in out["problems"])


def test_strict_conforming_mock_contract_passes():
    contract = {**mock_core_contract_draft()["core_contract"],
                "harness_schema_version": HARNESS_SCHEMA_VERSION}
    out = lint_golden_representation(contract, mock_scenario_golden_output()["goldens"])
    assert out["status"] == "PASS", out["problems"]
    assert out["strict"] is True


def test_core_contract_schema_defaults_to_legacy_version():
    contract = CoreContract.model_validate(mock_core_contract_draft()["core_contract"])
    assert contract.harness_schema_version == 1


# ---------------------------------------------------------------- 파이프라인 통합 (mock)

def _run_mock(tmp_path, overrides=None):
    llm = MockLLMClient(overrides={**mock_core_factory_overrides(), **(overrides or {})},
                        call_logger=LLMCallLogger(None))
    return run_core_factory(sample_challenge(), mode="mock", output_dir=tmp_path / "runs",
                            settings=SETTINGS, factory_settings=FSET, llm=llm)


def test_pipeline_injects_harness_schema_version(tmp_path):
    res = _run_mock(tmp_path)
    ws = Path(res["run_dir"]) / "final_artifact"
    contract = json.loads((ws / "core_contract.json").read_text(encoding="utf-8"))
    assert contract["harness_schema_version"] == HARNESS_SCHEMA_VERSION


def test_pipeline_runs_post_product_anti_hardcode(tmp_path):
    """§2.1: product layer 생성 후 anti-hardcode가 product/ 포함으로 재실행된다."""
    res = _run_mock(tmp_path)
    ws = Path(res["run_dir"]) / "final_artifact"
    post = json.loads((ws / "post_product_anti_hardcode.json").read_text(encoding="utf-8"))
    assert post["status"] == "PASS"
    assert post["scan_point"] == "post_product_layer"
    assert any(p.startswith("product/") for p in post["product_files_scanned"])
    harness = json.loads((Path(res["run_dir"]) / "harness_summary.json").read_text(encoding="utf-8"))
    assert harness["stages"]["product_layer"]["post_anti_hardcode"] == "PASS"
    assert res["verdict"] == "REVIEW_READY"


def test_pipeline_mock_fallback_blocks_green(tmp_path):
    """§2.2/§15-5: 최초 build도 continuation과 동일하게 product mock fallback을 잡는다."""
    bad_product = mock_product_layer_output()
    for entry in bad_product["files"]:
        if entry["path"].endswith("viewer.js"):
            entry["content"] += _FALLBACK_JS
    res = _run_mock(tmp_path, overrides={"product_layer": bad_product,
                                         "product_layer_repair": bad_product})
    ws = Path(res["run_dir"]) / "final_artifact"
    post = json.loads((ws / "post_product_anti_hardcode.json").read_text(encoding="utf-8"))
    assert post["status"] == "FAIL"
    assert post["mock_fallback_count"] >= 1
    gate_results = json.loads((ws / "gate_results.json").read_text(encoding="utf-8"))
    assert gate_results["anti_hardcode"]["ok"] is False
    assert any("post-product" in p for p in gate_results["anti_hardcode"]["problems"])
    assert res["verdict"] != "REVIEW_READY"
    assert res["green_base_path"] is None


def test_pipeline_strict_lint_stops_run_without_representation(tmp_path):
    """§2.3: 새 run(version 주입)은 output_representation 미선언이면 정직하게 중단된다."""
    draft = mock_core_contract_draft()
    del draft["core_contract"]["output_representation"]
    res = _run_mock(tmp_path, overrides={"core_contract_draft": draft,
                                         "core_contract_repair": draft})
    assert res["spec_status"] == "NEEDS_SPEC_REPAIR"
    run_dir = Path(res["run_dir"])
    lint = json.loads((run_dir / "golden_representation_lint.json").read_text(encoding="utf-8"))
    assert lint["status"] == "FAIL"
    assert lint["strict"] is True
