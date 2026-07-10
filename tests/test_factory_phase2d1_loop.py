# Phase 2D-1 §4~§5·§8~§11 테스트: lane executor registry, acceptance/progress, closed loop orchestrator.
import json
from pathlib import Path

from repo_idea_miner.config import Settings
from repo_idea_miner.factory_autopilot_schemas import AUTOPILOT_HOLD_FOR_HUMAN
from repo_idea_miner.factory_core_prompts import mock_core_factory_overrides
from repo_idea_miner.factory_core_pipeline import run_core_factory
from repo_idea_miner.factory_lane_executors import (
    LANE_EXECUTOR_ROUTES,
    LANE_EXECUTORS,
    check_allowed_scope,
    copy_run_as_child,
    execute_lane,
    failure_signature,
)
from repo_idea_miner.factory_loop_executor import run_closed_product_loop
from repo_idea_miner.factory_pipeline import FactorySettings, sample_challenge
from repo_idea_miner.factory_product_acceptance import (
    ACCEPTANCE_CHECKS,
    build_progress_vector,
    build_requirement_coverage,
    compare_progress,
    count_regressions,
    evaluate_product_acceptance,
)
from repo_idea_miner.llm_client import LLMCallLogger, MockLLMClient

FSET = FactorySettings(use_docker="off", sandbox_timeout_seconds=60.0)
SETTINGS = Settings(google_keys={})


def _run_mock(tmp_path):
    llm = MockLLMClient(overrides=mock_core_factory_overrides(),
                        call_logger=LLMCallLogger(None))
    return run_core_factory(sample_challenge(), mode="mock", output_dir=tmp_path / "runs",
                            settings=SETTINGS, factory_settings=FSET, llm=llm)


def _snapshot(run_dir: Path) -> dict:
    return {p.relative_to(run_dir).as_posix(): p.stat().st_size
            for p in sorted(run_dir.rglob("*"))
            if p.is_file() and "phase2d1" not in p.as_posix()}


# ---------------------------------------------------------------- registry (§4, §15-2)

def test_registry_covers_all_nine_lanes():
    assert set(LANE_EXECUTORS) == {
        "SPEC_REPAIR", "CORE_PATCH", "RUNNER_PATCH", "VIEWER_POLISH", "INTERACTION_UI",
        "RUNNER_BACKED_DRAFT_EXECUTION", "UX_POLISH", "ARCHIVE", "HOLD_FOR_HUMAN"}
    assert set(LANE_EXECUTOR_ROUTES) == set(LANE_EXECUTORS)
    # 연결표가 기존 경로를 가리킨다 (§4)
    assert "factory_spec_repair" in LANE_EXECUTOR_ROUTES["SPEC_REPAIR"]
    assert "factory_continue" in LANE_EXECUTOR_ROUTES["CORE_PATCH"]
    assert "factory_product_polish" in LANE_EXECUTOR_ROUTES["VIEWER_POLISH"]
    assert "factory_product_editor" in LANE_EXECUTOR_ROUTES["INTERACTION_UI"]
    assert "factory_draft_execution" in LANE_EXECUTOR_ROUTES["RUNNER_BACKED_DRAFT_EXECUTION"]


def test_check_allowed_scope():
    assert check_allowed_scope("VIEWER_POLISH", ["product/viewer/index.html"]) == "PASS"
    assert check_allowed_scope("VIEWER_POLISH", ["src/core/engine.py"]) == "FAIL"
    assert check_allowed_scope("SPEC_REPAIR", ["golden/expected_001.json"]) == "PASS"
    assert check_allowed_scope("SPEC_REPAIR", ["product/viewer/index.html"]) == "FAIL"
    assert check_allowed_scope("CORE_PATCH", []) == "PASS"


def test_failure_signature_stable_and_none_on_success():
    a = failure_signature("CORE_PATCH", ["gate fail: runner"], None)
    b = failure_signature("CORE_PATCH", ["gate fail: runner"], None)
    assert a == b and a is not None
    assert failure_signature("CORE_PATCH", [], None) is None


def test_ux_polish_stub_blocks_honestly(tmp_path):
    res = LANE_EXECUTORS["UX_POLISH"]({"parent_run_dir": tmp_path})
    assert res["status"] == "BLOCKED"
    assert res["child_run_dir"] is None
    assert any("미구현" in p for p in res["problems"])


def test_archive_and_hold_do_not_apply(tmp_path):
    it_dir = tmp_path / "iter"
    res = LANE_EXECUTORS["ARCHIVE"]({"parent_run_dir": tmp_path, "iteration_dir": it_dir})
    assert res["status"] == "NO_CHANGE" and res["changed_files"] == []
    assert (it_dir / "archive_report.json").is_file()
    res = LANE_EXECUTORS["HOLD_FOR_HUMAN"]({"parent_run_dir": tmp_path})
    assert res["status"] == "NO_CHANGE" and res["child_run_dir"] is None


# ---------------------------------------------------------------- child run + base 불변 (§15-1)

def test_copy_run_as_child_and_base_untouched(tmp_path):
    res = _run_mock(tmp_path)
    base = Path(res["run_dir"])
    before = _snapshot(base)
    child = copy_run_as_child(base, tmp_path / "child")
    assert (child / "final_artifact" / "core_contract.json").is_file()
    assert (child / "child_run_origin.json").is_file()
    assert _snapshot(base) == before


def test_execute_lane_spec_repair_keeps_base_immutable(tmp_path):
    res = _run_mock(tmp_path)
    base = Path(res["run_dir"])
    before = _snapshot(base)
    out = execute_lane("SPEC_REPAIR", {
        "parent_run_dir": base, "children_root": tmp_path / "children",
        "mode": "mock", "settings": SETTINGS, "factory_settings": FSET})
    assert out["status"] in ("APPLIED", "BLOCKED", "NO_CHANGE", "FAILED")
    assert out["protected_hash_check"] == "PASS"
    assert _snapshot(base) == before
    # §4 공통 결과 계약
    for key in ("status", "child_run_dir", "changed_files", "allowed_scope_check",
                "protected_hash_check", "targeted_tests", "targeted_test_status",
                "failure_signature"):
        assert key in out


def test_execute_lane_unknown_lane_blocked(tmp_path):
    out = execute_lane("NOT_A_LANE", {"parent_run_dir": tmp_path})
    assert out["status"] == "BLOCKED"


# ---------------------------------------------------------------- acceptance (§8, §15-12)

_GOOD_PROBE = {"success_scenarios_passed": 2, "failure_scenarios_passed": 1,
               "revise_and_rerun_changed": True, "mock_fallback_count": 0,
               "viewer_static_ok": True, "field_consistency_ok": True,
               "critical_flow_handlers_ok": True}
_GATES_ALL = {g: True for g in ("core_contract", "runner", "scenario_replay", "golden_output",
                                "state_invariant", "determinism", "anti_hardcode")}
_LOOP_CLOSED = {"can_create_or_modify_input": True, "can_validate_input": True,
                "can_execute_primary_action": True, "can_observe_state_change": True,
                "can_understand_success": True, "can_understand_failure": True,
                "can_revise_and_retry": True, "product_loop_closed": True}
_COVERAGE_FULL = {"critical_requirement_coverage": 1.0, "difficulty_anchor_coverage": 1.0,
                  "forbidden_simplification_violation_count": 0}


def test_acceptance_passes_when_everything_holds(tmp_path):
    out = evaluate_product_acceptance(
        tmp_path, _GOOD_PROBE, _GATES_ALL, True, "PASS", "PASS",
        _COVERAGE_FULL, _LOOP_CLOSED)
    assert out["status"] == "PASS"
    assert out["product_candidate_allowed"] is True
    assert out["passed_count"] == len(ACCEPTANCE_CHECKS)


def test_acceptance_blocks_product_candidate_on_missing_critical_requirement(tmp_path):
    coverage = {**_COVERAGE_FULL, "critical_requirement_coverage": 0.75}
    out = evaluate_product_acceptance(
        tmp_path, _GOOD_PROBE, _GATES_ALL, True, "PASS", "PASS", coverage, _LOOP_CLOSED)
    assert out["product_candidate_allowed"] is False
    assert "critical_requirement_coverage_full" in out["failed_checks"]
    assert out["max_stage"] == "EXECUTION_CANDIDATE"  # §8 하한


def test_acceptance_blocks_on_mock_fallback(tmp_path):
    probe = {**_GOOD_PROBE, "mock_fallback_count": 2}
    out = evaluate_product_acceptance(
        tmp_path, probe, _GATES_ALL, True, "PASS", "PASS", _COVERAGE_FULL, _LOOP_CLOSED)
    assert out["product_candidate_allowed"] is False
    assert "mock_fallback_zero" in out["failed_checks"]


def test_requirement_coverage_unknown_without_judge(tmp_path):
    (tmp_path / "normalized_challenge.json").write_text(json.dumps({
        "success_conditions": ["A", "B"], "difficulty_anchors": ["C"],
        "forbidden_simplifications": ["D"]}), encoding="utf-8")
    out = build_requirement_coverage(tmp_path)
    assert out["critical_requirement_coverage"] == 0.0  # unknown은 산입 금지 (보수적)
    assert all(i["status"] == "unknown" for i in out["critical_requirements"])


def test_requirement_coverage_with_judge(tmp_path):
    (tmp_path / "normalized_challenge.json").write_text(json.dumps({
        "success_conditions": ["A", "B"], "difficulty_anchors": ["C"],
        "forbidden_simplifications": ["D"]}), encoding="utf-8")
    judge = {"A": {"status": "implemented", "evidence_refs": ["x"]},
             "B": {"status": "missing", "evidence_refs": []},
             "C": {"status": "implemented", "evidence_refs": ["y"]},
             "D": {"status": "violated", "evidence_refs": ["z"]}}
    out = build_requirement_coverage(tmp_path, judge)
    assert out["critical_requirement_coverage"] == 0.5
    assert out["difficulty_anchor_coverage"] == 1.0
    assert out["forbidden_simplification_violation_count"] == 1


# ---------------------------------------------------------------- progress (§9, §15-8·9)

def _vector(**over):
    base = {"stage_rank": 2, "stage": "POLISHABLE_PROTOTYPE", "core_gates_passed": 7,
            "product_acceptance_passed": 10, "hard_blocker_count": 2,
            "critical_requirement_coverage": 0.5, "difficulty_anchor_coverage": 0.5,
            "product_loop_parts_passed": 4, "success_scenarios_passed": 2,
            "failure_scenarios_passed": 1, "mock_fallback_count": 0, "regression_count": 0}
    return {**base, **over}


def test_progress_meaningful_on_stage_up():
    out = compare_progress(_vector(), _vector(stage_rank=3), "PASS")
    assert out["meaningful_progress"] is True
    assert "stage rank 상승" in out["improvements"]


def test_cosmetic_change_is_not_progress():
    """§15-8: 의미 없는 문구 변경 → metric 불변 → NO_MEANINGFUL_PROGRESS."""
    out = compare_progress(_vector(), _vector(), "PASS")
    assert out["meaningful_progress"] is False
    assert out["verdict"] == "NO_MEANINGFUL_PROGRESS"


def test_regression_blocks_progress_even_with_improvement():
    """§15-9: 기존 PASS gate가 FAIL로 뒤집히면 stage가 올라도 승격 금지."""
    after = _vector(stage_rank=3, core_gates_passed=6, regression_count=1)
    out = compare_progress(_vector(), after, "PASS")
    assert out["meaningful_progress"] is False
    assert any("regression" in b for b in out["blockers"])


def test_protected_hash_fail_blocks_progress():
    out = compare_progress(_vector(), _vector(stage_rank=3), "FAIL")
    assert out["meaningful_progress"] is False


def test_count_regressions_gate_flip():
    before, after = dict(_GATES_ALL), {**_GATES_ALL, "determinism": False}
    out = count_regressions(_vector(), _vector(), before, after)
    assert out["count"] == 1
    assert "gate:determinism PASS→FAIL" in out["items"]


# ---------------------------------------------------------------- closed loop orchestrator (§5·§10·§11)

def test_loop_judge_only_by_default(tmp_path):
    res = _run_mock(tmp_path)
    base = Path(res["run_dir"])
    before = _snapshot(base)
    out = run_closed_product_loop(run_dir=base, mode="mock", execute=False,
                                  output_dir=tmp_path / "children",
                                  settings=SETTINGS, factory_settings=FSET)
    assert out["status"] == "JUDGED_ONLY"
    assert out["ok"] is True
    assert out["base_hash_status"] == "PASS"
    assert len(out["iterations"]) == 1
    assert _snapshot(base) == before  # 판정만 — artifact 불변
    loop_dir = Path(out["loop_dir"])
    assert (loop_dir / "loop_summary.json").is_file()
    assert (loop_dir / "iterations/iter01/before/probe/fresh_probe_report.json").is_file()
    assert (loop_dir / "iterations/iter01/before/product_acceptance.json").is_file()


def test_loop_execute_stops_honestly_and_keeps_base(tmp_path):
    """§15-16: 자동 진행 불가면 중간 질문 없이 HOLD_FOR_HUMAN packet으로 종료한다."""
    res = _run_mock(tmp_path)
    base = Path(res["run_dir"])
    before = _snapshot(base)
    out = run_closed_product_loop(run_dir=base, mode="mock", execute=True, max_iterations=3,
                                  output_dir=tmp_path / "children",
                                  settings=SETTINGS, factory_settings=FSET)
    assert out["base_hash_status"] == "PASS"
    assert _snapshot(base) == before
    assert out["status"] in ("PRODUCT_CANDIDATE", "ARCHIVED", AUTOPILOT_HOLD_FOR_HUMAN)
    loop_dir = Path(out["loop_dir"])
    assert (loop_dir / "lineage.json").is_file()
    assert (loop_dir / "phase2d1_dashboard_summary.json").is_file()
    if out["status"] == AUTOPILOT_HOLD_FOR_HUMAN:
        packet = json.loads((loop_dir / "hold_for_human_packet.json").read_text("utf-8"))
        assert packet["single_question_for_human"]
        assert packet["recommended_options"]
        assert packet["lane_attempts"]


def test_loop_lineage_records_required_fields(tmp_path):
    res = _run_mock(tmp_path)
    base = Path(res["run_dir"])
    out = run_closed_product_loop(run_dir=base, mode="mock", execute=True, max_iterations=2,
                                  output_dir=tmp_path / "children",
                                  settings=SETTINGS, factory_settings=FSET)
    lineage = json.loads((Path(out["loop_dir"]) / "lineage.json").read_text("utf-8"))
    for entry in lineage["entries"]:
        for key in ("loop_id", "iteration", "base_run_dir", "parent_run_dir",
                    "selected_lane", "primary_gap_before", "stage_before"):
            assert key in entry
