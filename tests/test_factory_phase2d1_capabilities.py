# Phase 2D-1 §6~§7 테스트: 도메인 중립 capability profile, 공통 loop evidence, fresh probe.
import json
from pathlib import Path

from repo_idea_miner.config import Settings
from repo_idea_miner.factory_core_prompts import mock_core_factory_overrides
from repo_idea_miner.factory_core_pipeline import run_core_factory
from repo_idea_miner.factory_pipeline import FactorySettings, sample_challenge
from repo_idea_miner.factory_product_capabilities import (
    COMMON_LOOP_EVIDENCE,
    build_capability_profile,
    classify_input_kind,
    loop_evidence_from_probe,
    mutate_scenario_for_revise,
    normalize_loop_evidence,
    run_fresh_probe,
)
from repo_idea_miner.llm_client import LLMCallLogger, MockLLMClient

FSET = FactorySettings(use_docker="off", sandbox_timeout_seconds=60.0)
SETTINGS = Settings(google_keys={})


# ---------------------------------------------------------------- input kind 분류 (§6)

def _contract(entities, actions):
    return {"state_entities": entities, "actions": actions}


def test_classify_graph_kind_without_challenge_id():
    """§15-13: Mini-Comfy류 contract 어휘만으로 graph 분류 — ID/title 없이."""
    contract = _contract(
        [{"name": "node", "fields": ["id", "x", "y", "node_type"]},
         {"name": "edge", "fields": ["from_node", "to_node"]}],
        [{"name": "add_node", "input": ["node_type"]},
         {"name": "connect_nodes", "input": ["from_node", "to_node"]}])
    assert classify_input_kind(contract) == "graph"


def test_classify_file_operation_kind_without_challenge_id():
    """§15-14: Virtual File Explorer류 contract 어휘만으로 file_operation 분류."""
    contract = _contract(
        [{"name": "file_tree", "fields": ["path", "root_node"]},
         {"name": "directory", "fields": ["name", "children"]}],
        [{"name": "create_file", "input": ["path"]},
         {"name": "move_directory", "input": ["path", "target"]}])
    assert classify_input_kind(contract) == "file_operation"


def test_classify_generic_when_no_vocabulary_hits():
    contract = _contract([{"name": "ledger", "fields": ["amount"]}],
                         [{"name": "post_entry", "input": ["amount"]}])
    assert classify_input_kind(contract) == "generic"


# ---------------------------------------------------------------- 공통 evidence 정규화 (§6)

def test_normalize_legacy_loop_evidence_names():
    legacy = {
        "can_create_input": True,
        "can_validate_input": True,
        "can_execute_input": True,
        "can_see_result_from_created_input": True,
        "can_understand_failure": False,
        "can_revise_and_rerun": False,
        "product_loop_closed": False,
    }
    out = normalize_loop_evidence(legacy)
    assert out["can_create_or_modify_input"] is True
    assert out["can_execute_primary_action"] is True
    assert out["can_observe_state_change"] is True
    assert out["can_revise_and_retry"] is False
    # 구 artifact에 없던 can_understand_success는 관측 근거에서 보수 파생
    assert out["can_understand_success"] is True
    assert set(out) <= set(COMMON_LOOP_EVIDENCE)


def test_normalize_passes_through_new_names():
    new = {name: True for name in COMMON_LOOP_EVIDENCE}
    assert normalize_loop_evidence(new) == new


# ---------------------------------------------------------------- 입력 변형 규칙 (§7-5)

def test_mutation_drops_last_action():
    scenario = {"id": "s1", "actions": [{"type": "a"}, {"type": "b"}]}
    mutated, rule = mutate_scenario_for_revise(scenario)
    assert rule == "drop_last_action"
    assert len(mutated["actions"]) == 1
    assert scenario["actions"] == [{"type": "a"}, {"type": "b"}]  # 원본 불변


def test_mutation_duplicates_single_action():
    mutated, rule = mutate_scenario_for_revise({"id": "s1", "actions": [{"type": "a"}]})
    assert rule == "duplicate_single_action"
    assert len(mutated["actions"]) == 2


def test_mutation_marks_state_when_no_actions():
    mutated, rule = mutate_scenario_for_revise({"id": "s1", "actions": []})
    assert rule == "add_initial_state_marker"
    assert mutated["initial_state"]["_probe_marker"] == 1


# ---------------------------------------------------------------- profile + probe (mock 파이프라인)

def _run_mock(tmp_path):
    llm = MockLLMClient(overrides=mock_core_factory_overrides(),
                        call_logger=LLMCallLogger(None))
    return run_core_factory(sample_challenge(), mode="mock", output_dir=tmp_path / "runs",
                            settings=SETTINGS, factory_settings=FSET, llm=llm)


def test_capability_profile_from_mock_run(tmp_path):
    res = _run_mock(tmp_path)
    run_dir = Path(res["run_dir"])
    profile = build_capability_profile(run_dir)
    assert profile["status"] == "PASS", profile["problems"]
    assert profile["editable_entities"] == ["history", "counters"]
    assert profile["primary_user_actions"] == ["execute_command", "follow_up"]
    assert profile["execution_command"]
    assert profile["validation_command"] == profile["execution_command"]
    assert profile["viewer_entrypoint"] == "product/viewer/index.html"
    assert "final_state" in profile["result_required_fields"]
    assert profile["failure_required_fields"] == ["ok", "errors"]
    assert len(profile["critical_user_flows"]) >= 1


def test_fresh_probe_on_mock_run(tmp_path):
    res = _run_mock(tmp_path)
    run_dir = Path(res["run_dir"])
    out_dir = tmp_path / "probe_out"
    report = run_fresh_probe(run_dir, out_dir, timeout=60.0, use_docker=False)
    assert report["status"] == "PASS", report["problems"]
    assert report["success_scenarios_passed"] >= 2
    assert report["failure_scenarios_passed"] >= 1
    assert report["revise_and_rerun_changed"] is True
    assert report["mock_fallback_count"] == 0
    assert report["viewer_static_ok"] is True
    assert report["field_consistency_ok"] is True
    assert report["critical_flow_handlers_ok"] is True
    # §7 기록 필드: 실행 probe에 command/exit/입출력 hash/artifact 경로
    runner_probes = [p for p in report["probes"] if p["method"] == "runner_execution"]
    assert runner_probes
    for p in runner_probes:
        assert p["command"] and p["exit_code"] == 0
        assert p["input_sha256"] and p["output_sha256"]
        assert Path(p["artifact_path"]).is_file()
    # viewer probe는 static_analysis로 정직하게 표시 (§7-7·10 과대 기록 금지)
    static_probes = {p["probe_id"] for p in report["probes"] if p["method"] == "static_analysis"}
    assert {"probe07_viewer_display", "probe08_mock_fallback",
            "probe09_field_consistency", "probe10_flow_handlers"} <= static_probes
    assert (out_dir / "fresh_probe_report.json").is_file()


def test_fresh_probe_never_touches_base_run(tmp_path):
    """§1-1: probe는 temp copy에서만 실행 — 원본 final_artifact 불변."""
    res = _run_mock(tmp_path)
    run_dir = Path(res["run_dir"])
    ws = run_dir / "final_artifact"
    before = {p.relative_to(ws).as_posix(): p.stat().st_mtime_ns
              for p in sorted(ws.rglob("*")) if p.is_file()}
    run_fresh_probe(run_dir, tmp_path / "probe_out2", timeout=60.0, use_docker=False)
    after = {p.relative_to(ws).as_posix(): p.stat().st_mtime_ns
             for p in sorted(ws.rglob("*")) if p.is_file()}
    assert before == after


def test_probe_report_boolean_manipulation_does_not_matter(tmp_path):
    """§15-7: 기존 report boolean을 조작해도 fresh probe는 실제 실행 결과를 쓴다."""
    res = _run_mock(tmp_path)
    run_dir = Path(res["run_dir"])
    # 가짜로 낙관적인 기존 report를 심어도 probe 결과와 무관해야 한다
    fake = run_dir / "review" / "phase2c0" / "smoke_review.json"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_text(json.dumps({"runner_executable": False, "product_viewer_exists": False}),
                    encoding="utf-8")
    report = run_fresh_probe(run_dir, tmp_path / "probe_out3", timeout=60.0, use_docker=False)
    assert report["status"] == "PASS", report["problems"]
    assert report["viewer_static_ok"] is True


def test_loop_evidence_from_probe_prefers_probe_observation():
    probe = {"success_scenarios_passed": 2, "failure_scenarios_passed": 1,
             "revise_and_rerun_changed": True, "viewer_static_ok": True,
             "field_consistency_ok": True, "mock_fallback_count": 0}
    prior = {"can_create_input": True, "can_validate_input": True}
    out = loop_evidence_from_probe(probe, prior)
    assert out["can_create_or_modify_input"] is True
    assert out["can_execute_primary_action"] is True
    assert out["can_observe_state_change"] is True
    assert out["can_understand_success"] is True
    assert out["can_understand_failure"] is True
    assert out["can_revise_and_retry"] is True
    assert out["product_loop_closed"] is True


def test_loop_evidence_open_when_probe_fails():
    probe = {"success_scenarios_passed": 0, "failure_scenarios_passed": 0,
             "revise_and_rerun_changed": False, "viewer_static_ok": False,
             "field_consistency_ok": False, "mock_fallback_count": 3}
    out = loop_evidence_from_probe(probe, {})
    assert out["product_loop_closed"] is False
    assert out["can_execute_primary_action"] is False
