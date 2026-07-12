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
    # 이슈 #5 §6: generic executor가 기본, graph 도메인만 legacy 2C-2 adapter
    assert "factory_interaction_ui" in LANE_EXECUTOR_ROUTES["INTERACTION_UI"]
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


def test_ux_polish_blocks_honestly_without_artifact_root(tmp_path):
    # 이슈 #8: stub → generic executor. artifact root가 없는 run에서는 여전히
    # 정직한 BLOCKED여야 한다 (성공 조작 없음).
    parent = tmp_path / "parent"
    parent.mkdir()
    res = LANE_EXECUTORS["UX_POLISH"]({"parent_run_dir": parent,
                                       "children_root": tmp_path / "children"})
    assert res["status"] == "BLOCKED"
    assert "factory_ux_polish" in LANE_EXECUTOR_ROUTES["UX_POLISH"]


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


def test_copy_run_as_child_rewrites_base_pointers(tmp_path):
    """parent 내부를 가리키는 base 포인터는 child 내부 경로로 재작성된다.

    포인터가 parent를 계속 가리키면 child continuation seed가 parent snapshot이 되어
    child 수정이 전부 무시된다. parent 밖 경로와 parent 원본 파일은 건드리지 않는다."""
    parent = tmp_path / "parent"
    (parent / "snapshot" / "continuation_core_01").mkdir(parents=True)
    parent_pointer = str(parent / "snapshot" / "continuation_core_01")
    (parent / "continuation_base.json").write_text(json.dumps({
        "base_type": "continuation_base",
        "continuation_base_path": parent_pointer,
    }), encoding="utf-8")
    (parent / "green_base.json").write_text(json.dumps({
        "base_type": "green_base",
        "green_base_path": str(tmp_path / "elsewhere" / "green_core_01"),
    }), encoding="utf-8")

    child = copy_run_as_child(parent, tmp_path / "child")

    cont = json.loads((child / "continuation_base.json").read_text(encoding="utf-8"))
    assert cont["continuation_base_path"] == \
        (child / "snapshot" / "continuation_core_01").as_posix()
    # parent 밖을 가리키는 포인터는 재작성하지 않는다
    green = json.loads((child / "green_base.json").read_text(encoding="utf-8"))
    assert green["green_base_path"] == str(tmp_path / "elsewhere" / "green_core_01")
    # parent 원본 포인터는 불변
    orig = json.loads((parent / "continuation_base.json").read_text(encoding="utf-8"))
    assert orig["continuation_base_path"] == parent_pointer


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


def test_judge_fresh_gates_restore_evidence_sufficiency(tmp_path):
    """#54류: 기록된 gate 문맥이 없어도 fresh gate rerun이 sufficiency를 충족한다 (§7).

    기록 파일 부재로 EVIDENCE_INSUFFICIENT가 되면 방금 잰 gate 실패를
    hard rung(CORE_PATCH_REQUIRED)이 잡지 못하고 HOLD로 빠진다.
    """
    from repo_idea_miner.factory_loop_executor import _judge
    from test_factory_review_2c0 import _VIEWER_CLEAN, _build_green_run

    run = _build_green_run(tmp_path, _VIEWER_CLEAN)
    (run / "green_base.json").unlink()
    (run / "gate_rerun_after_anti_hardcode_patch.json").unlink()
    (run / "phase2b1b_dashboard_summary.json").unlink()
    fresh = {g: True for g in ("core_contract", "runner", "scenario_replay", "golden_output",
                               "state_invariant", "determinism", "anti_hardcode")}
    fresh["golden_output"] = False
    judge = _judge(run, None, None, "sequential", False, fresh_gate_summary=fresh)
    facts = judge["evidence"]["facts"]
    assert facts["evidence_sufficient"] is True
    assert facts["gate_fail"] is True
    assert judge["desks"]["gap"]["primary_gap"] == "CORE_PATCH_REQUIRED"
    assert judge["desks"]["lane"]["recommended_next_lane"] == "CORE_PATCH"


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


# ---------------------------------------------------------------- lane 결과 escalation (§10)

def test_loop_escalates_to_spec_repair_after_lane_classification(tmp_path, monkeypatch):
    """직전 lane 결과가 SPEC_REPAIR_REQUIRED를 분류하면 다음 iteration은 같은 patch lane을
    반복하지 않고 SPEC_REPAIR로 승급한다 — 관측(lane 결과)이 stale 판정보다 우선."""
    import repo_idea_miner.factory_loop_executor as fle

    run = tmp_path / "base_run"
    (run / "workspace").mkdir(parents=True)

    fake_verify = {
        "gate_summary": {}, "anti_summary": {}, "validate_ok": True, "probe": {},
        "profile": {}, "coverage": {},
        "judge": {"desks": {"status": "PASS",
                            "gap": {"primary_gap": "CORE_PATCH_REQUIRED"},
                            "lane": {"recommended_next_lane": "CORE_PATCH"}}},
        "acceptance": {"product_candidate_allowed": False, "failed_checks": [],
                       "max_stage": "REVIEWABLE_ARTIFACT"},
        "vector": {}, "stage": "REVIEWABLE_ARTIFACT",
        "effective_stage": "REVIEWABLE_ARTIFACT", "overrating_blocked": False,
    }
    monkeypatch.setattr(fle, "verify_candidate",
                        lambda *a, **k: json.loads(json.dumps(fake_verify)))

    lanes_called: list[str] = []

    def fake_execute_lane(lane, ctx):
        lanes_called.append(lane)
        return {"lane": lane, "status": "FAILED", "child_run_dir": None, "changed_files": [],
                "allowed_scope_check": "PASS", "protected_hash_check": "PASS",
                "targeted_tests": [], "targeted_test_status": "FAIL",
                "failure_signature": f"sig_{lane}", "problems": ["SPEC_REPAIR_REQUIRED"],
                "error": None, "underlying_status": "DONE", "route": ""}

    monkeypatch.setattr(fle, "execute_lane", fake_execute_lane)
    monkeypatch.setattr(fle, "compute_loop_protected_hashes", lambda p: {})
    monkeypatch.setattr(fle, "compare_protected_hashes",
                        lambda a, b: {"status": "PASS", "files_checked": 0,
                                      "changed": [], "added": [], "removed": []})

    res = fle.run_closed_product_loop(
        run_dir=run, mode="mock", execute=True,
        budgets={"max_high_risk_lane_attempts": 2, "max_iterations": 3})

    assert lanes_called[0] == "CORE_PATCH"
    assert "SPEC_REPAIR" in lanes_called
    it2 = res["iterations"][1]
    assert it2["primary_gap_before"] == "SPEC_REPAIR_REQUIRED"
    assert it2["selected_lane"] == "SPEC_REPAIR"
    assert it2["gap_escalation"]["to_gap"] == "SPEC_REPAIR_REQUIRED"


def test_loop_escalation_recorded_even_when_budget_stops(tmp_path, monkeypatch):
    """기본 예산(high-risk 1)에서도 escalation은 gap/lane 기록을 교정한다 —
    hold packet이 반복된 patch lane이 아니라 실제 필요한 spec repair를 가리켜야 한다."""
    import repo_idea_miner.factory_loop_executor as fle

    run = tmp_path / "base_run"
    (run / "workspace").mkdir(parents=True)

    fake_verify = {
        "gate_summary": {}, "anti_summary": {}, "validate_ok": True, "probe": {},
        "profile": {}, "coverage": {},
        "judge": {"desks": {"status": "PASS",
                            "gap": {"primary_gap": "CORE_PATCH_REQUIRED"},
                            "lane": {"recommended_next_lane": "CORE_PATCH"}}},
        "acceptance": {"product_candidate_allowed": False, "failed_checks": [],
                       "max_stage": "REVIEWABLE_ARTIFACT"},
        "vector": {}, "stage": "REVIEWABLE_ARTIFACT",
        "effective_stage": "REVIEWABLE_ARTIFACT", "overrating_blocked": False,
    }
    monkeypatch.setattr(fle, "verify_candidate",
                        lambda *a, **k: json.loads(json.dumps(fake_verify)))
    monkeypatch.setattr(fle, "execute_lane", lambda lane, ctx: {
        "lane": lane, "status": "FAILED", "child_run_dir": None, "changed_files": [],
        "allowed_scope_check": "PASS", "protected_hash_check": "PASS",
        "targeted_tests": [], "targeted_test_status": "FAIL",
        "failure_signature": f"sig_{lane}", "problems": ["SPEC_REPAIR_REQUIRED"],
        "error": None, "underlying_status": "DONE", "route": ""})
    monkeypatch.setattr(fle, "compute_loop_protected_hashes", lambda p: {})
    monkeypatch.setattr(fle, "compare_protected_hashes",
                        lambda a, b: {"status": "PASS", "files_checked": 0,
                                      "changed": [], "added": [], "removed": []})

    res = fle.run_closed_product_loop(run_dir=run, mode="mock", execute=True)

    it2 = res["iterations"][1]
    assert it2["primary_gap_before"] == "SPEC_REPAIR_REQUIRED"
    assert it2["selected_lane"] == "SPEC_REPAIR"
    assert res["hold_packet"] is not None
    assert "SPEC_REPAIR_REQUIRED" in res["hold_packet"]["blocking_gaps"]


# ---------------------------------------------------------------- blocked lane 재선택 금지 (batch 4 A1)

def test_loop_does_not_reselect_precondition_blocked_lane(tmp_path, monkeypatch):
    """batch 4 A1: 전제조건 부재로 BLOCKED된 lane은 parent가 그대로인 한 재실행해도 같은
    이유로 막힌다 — 재선택으로 예산을 태우지 않고 즉시 EXECUTION_BLOCKED로 정직 HOLD."""
    import repo_idea_miner.factory_loop_executor as fle

    run = tmp_path / "base_run"
    (run / "workspace").mkdir(parents=True)

    fake_verify = {
        "gate_summary": {}, "anti_summary": {}, "validate_ok": True, "probe": {},
        "profile": {}, "coverage": {},
        "judge": {"desks": {"status": "PASS",
                            "gap": {"primary_gap": "CORE_PATCH_REQUIRED"},
                            "lane": {"recommended_next_lane": "CORE_PATCH"}}},
        "acceptance": {"product_candidate_allowed": False, "failed_checks": [],
                       "max_stage": "REVIEWABLE_ARTIFACT"},
        "vector": {}, "stage": "REVIEWABLE_ARTIFACT",
        "effective_stage": "REVIEWABLE_ARTIFACT", "overrating_blocked": False,
    }
    monkeypatch.setattr(fle, "verify_candidate",
                        lambda *a, **k: json.loads(json.dumps(fake_verify)))

    lanes_called: list[str] = []

    def fake_execute_lane(lane, ctx):
        lanes_called.append(lane)
        return {"lane": lane, "status": "BLOCKED", "child_run_dir": None, "changed_files": [],
                "allowed_scope_check": "PASS", "protected_hash_check": "PASS",
                "targeted_tests": [], "targeted_test_status": "SKIPPED",
                "failure_signature": None,
                "problems": [], "error": "continuation_base 없음", "underlying_status": None,
                "route": ""}

    monkeypatch.setattr(fle, "execute_lane", fake_execute_lane)
    monkeypatch.setattr(fle, "compute_loop_protected_hashes", lambda p: {})
    monkeypatch.setattr(fle, "compare_protected_hashes",
                        lambda a, b: {"status": "PASS", "files_checked": 0,
                                      "changed": [], "added": [], "removed": []})

    res = fle.run_closed_product_loop(
        run_dir=run, mode="mock", execute=True,
        budgets={"max_high_risk_lane_attempts": 3, "max_iterations": 4})

    # BLOCKED lane은 딱 한 번만 실행되고 재선택되지 않는다
    assert lanes_called == ["CORE_PATCH"]
    assert any("전제조건 부재" in s for s in res["stop_conditions"])
    assert res["hold_packet"] is not None
    assert res["hold_packet"]["hold_reason_class"] == "EXECUTION_BLOCKED"
