# 이슈 #24 테스트: objective viewer fault의 결정론적 gap override — live UX 오판 교정, 주관 판정 비승격, closed loop VIEWER→UX 자율 완주.
import json
from pathlib import Path

from repo_idea_miner.factory_autopilot_desks import (
    HARD_EVIDENCE_GAPS,
    RawPassthrough,
    derive_primary_gap,
    enforce_evidence_ladder,
    is_machine_checkable_viewer_fault,
    mock_gap_classifier,
    mock_next_lane_planner,
    mock_product_judge,
    mock_unified_packet,
    viewer_fault_facts,
)
from repo_idea_miner.factory_autopilot_schemas import (
    GAP_TO_LANE,
    LANE_TEMPLATES,
    STAGE_RANK,
    validate_gap_override,
    validate_stage_gap_lane_consistency,
)
from repo_idea_miner.factory_core_schemas import CORE_GATE_ORDER
from repo_idea_miner.factory_product_loop import run_judgment_desks

# 합성 run 빌더 재사용 (2C-0/2D-0 테스트 관례)
from test_factory_product_loop_2d0 import _47_like_run, _evidence  # noqa: E402
from test_factory_review_2c0 import (  # noqa: E402
    _VIEWER_FETCH_ONLY,
    _VIEWER_MISMATCH,
)

_VIEWER_REL = Path("final_artifact/product/viewer/index.html")


def _live_ux_gap(ev: dict) -> dict:
    """live desk의 파생 증상 오판(60초 gap → UX 귀속)을 재현하는 gap 출력."""
    refs = [ev["refs"]["loop.product_loop_closed"], ev["refs"]["facts.has_ux_polish_report"]]
    return {
        "gaps": [{"type": "UX_POLISH_REQUIRED", "severity": "major", "evidence_refs": refs,
                  "explanation": "value not understandable fast enough"}],
        "primary_gap": "UX_POLISH_REQUIRED",
        "primary_gap_evidence_refs": refs,
        "primary_gap_reason": "The loop runs but the product value is not understandable fast enough.",
    }


class _ScriptedExecutor:
    """desk별로 준비된 raw 출력을 돌려주는 live executor 스텁."""

    def __init__(self, outputs: dict):
        self.outputs = outputs
        self.calls: list[str] = []

    def call(self, schema_name, prompt, model_cls):
        self.calls.append(schema_name)
        return RawPassthrough.model_validate(self.outputs[schema_name]), "scripted"


# ---------------------------------------------------------------- §6.1 objective mismatch가 live UX 판정을 override

def test_objective_mismatch_overrides_live_ux(tmp_path):
    run = _47_like_run(tmp_path)
    (run / _VIEWER_REL).write_text(_VIEWER_MISMATCH, encoding="utf-8")
    ev, q, hard = _evidence(run)
    assert ev["facts"]["viewer_exists"] and ev["facts"]["mismatch_count"] >= 1
    label = mock_product_judge(ev, q, hard)
    assert derive_primary_gap(ev, q, label) == "VIEWER_POLISH_REQUIRED"

    gap, override = enforce_evidence_ladder(_live_ux_gap(ev), ev, q, label)
    assert gap["primary_gap"] == "VIEWER_POLISH_REQUIRED"
    assert override is not None
    assert override["live_gap"] == "UX_POLISH_REQUIRED"
    assert override["deterministic_gap"] == "VIEWER_POLISH_REQUIRED"
    assert override["enforced_gap"] == "VIEWER_POLISH_REQUIRED"
    assert override["override_kind"] == "OBJECTIVE_VIEWER_FAULT"
    assert override["reason"]
    assert override["viewer_faults"]["mismatch_count"] >= 1
    assert override["viewer_faults"]["viewer_exists"] is True
    assert override["evidence_refs"]
    assert all(r in ev["known_refs"] for r in override["evidence_refs"])
    assert validate_gap_override(override, ev) == []


def test_sequential_desks_route_override_to_viewer_lane(tmp_path):
    """override된 gap의 lane은 canonical GAP_TO_LANE 매핑 — live lane desk를 부르지 않는다."""
    run = _47_like_run(tmp_path)
    (run / _VIEWER_REL).write_text(_VIEWER_MISMATCH, encoding="utf-8")
    ev, q, hard = _evidence(run)
    label = mock_product_judge(ev, q, hard)
    ex = _ScriptedExecutor({"product_stage_label": label,
                            "product_gap_classification": _live_ux_gap(ev)})
    out = run_judgment_desks(ex, ev, q, hard, "sequential", True, {}, include_order=False)
    assert out["status"] == "PASS"
    assert out["gap"]["primary_gap"] == "VIEWER_POLISH_REQUIRED"
    assert out["gap_override"]["override_kind"] == "OBJECTIVE_VIEWER_FAULT"
    assert out["lane"]["recommended_next_lane"] == "VIEWER_POLISH"
    assert GAP_TO_LANE["VIEWER_POLISH_REQUIRED"] == "VIEWER_POLISH"
    assert "recommended_next_lane" not in ex.calls
    assert validate_stage_gap_lane_consistency(label, out["gap"], out["lane"]) == []


def test_unified_desks_regenerate_lane_on_viewer_override(tmp_path):
    run = _47_like_run(tmp_path)
    (run / _VIEWER_REL).write_text(_VIEWER_MISMATCH, encoding="utf-8")
    ev, q, hard = _evidence(run)
    packet = json.loads(json.dumps(mock_unified_packet(ev, q, hard)))
    packet["product_gap_classification"] = _live_ux_gap(ev)
    packet["recommended_next_lane"] = mock_next_lane_planner(
        ev, packet["product_gap_classification"])
    ex = _ScriptedExecutor({"unified_decision_packet": packet})
    out = run_judgment_desks(ex, ev, q, hard, "unified", True, {})
    assert out["status"] == "PASS"
    assert out["gap"]["primary_gap"] == "VIEWER_POLISH_REQUIRED"
    assert out["gap_override"]["override_kind"] == "OBJECTIVE_VIEWER_FAULT"
    assert out["lane"]["recommended_next_lane"] == "VIEWER_POLISH"
    assert out["slots"]["allowed_scopes"] == list(LANE_TEMPLATES["VIEWER_POLISH"]["allowed_scopes"])


# ---------------------------------------------------------------- §6.2 viewer 없음 / §6.3 replay 미연결

def test_viewer_missing_overrides_live_ux(tmp_path):
    run = _47_like_run(tmp_path)
    (run / _VIEWER_REL).unlink()
    ev, q, hard = _evidence(run)
    assert ev["facts"]["viewer_exists"] is False
    assert ev["facts"]["evidence_sufficient"] is True  # editor 근거로 판정 가능
    label = mock_product_judge(ev, q, hard)
    gap, override = enforce_evidence_ladder(_live_ux_gap(ev), ev, q, label)
    assert gap["primary_gap"] == "VIEWER_POLISH_REQUIRED"
    assert override["override_kind"] == "OBJECTIVE_VIEWER_FAULT"
    assert override["viewer_faults"]["viewer_exists"] is False
    assert validate_gap_override(override, ev) == []


def test_viewer_not_reading_replay_overrides_live_ux(tmp_path):
    run = _47_like_run(tmp_path)
    (run / _VIEWER_REL).write_text(_VIEWER_FETCH_ONLY, encoding="utf-8")
    ev, q, hard = _evidence(run)
    assert ev["facts"]["viewer_exists"] is True
    assert ev["facts"]["viewer_reads_replay"] is False
    assert ev["facts"]["mismatches"] == []
    label = mock_product_judge(ev, q, hard)
    gap, override = enforce_evidence_ladder(_live_ux_gap(ev), ev, q, label)
    assert gap["primary_gap"] == "VIEWER_POLISH_REQUIRED"
    assert override["override_kind"] == "OBJECTIVE_VIEWER_FAULT"
    assert override["viewer_faults"]["viewer_reads_replay"] is False
    assert override["viewer_faults"]["mismatch_count"] == 0


# ---------------------------------------------------------------- §6.4 정상 viewer에서는 UX override 금지

def test_healthy_viewer_keeps_live_ux_judgment(tmp_path):
    run = _47_like_run(tmp_path)
    ev, q, hard = _evidence(run)
    assert is_machine_checkable_viewer_fault(ev) is False
    # closed loop + 60s 부족: 실제 UX gap 상황을 재현
    for k in ev["product_loop"]:
        ev["product_loop"][k] = True
    q["fields"]["user_can_understand_value_in_60s"] = False
    label = {"stage": "EXECUTION_CANDIDATE"}
    assert derive_primary_gap(ev, q, label) == "UX_POLISH_REQUIRED"
    live_gap = _live_ux_gap(ev)
    gap, override = enforce_evidence_ladder(live_gap, ev, q, label)
    assert override is None
    assert gap is live_gap  # live 판정 그대로 유지


# ---------------------------------------------------------------- §6.5 주관적 viewer 미관은 hard override 금지

def test_subjective_viewer_claim_is_not_promoted_to_machine_fact(tmp_path):
    run = _47_like_run(tmp_path)
    ev, q, hard = _evidence(run)
    assert is_machine_checkable_viewer_fault(ev) is False
    label = mock_product_judge(ev, q, hard)
    assert derive_primary_gap(ev, q, label) != "VIEWER_POLISH_REQUIRED"
    # live desk가 "viewer polish 필요"라고만 주장 — objective fault가 없으므로
    # 새 override 정책은 이 주장을 machine fact로 승격하지 않는다.
    refs = [ev["refs"]["facts.viewer_exists"], ev["refs"]["facts.mismatch_count"]]
    live_gap = {"gaps": [{"type": "VIEWER_POLISH_REQUIRED", "severity": "minor",
                          "evidence_refs": refs, "explanation": "viewer feels unpolished"}],
                "primary_gap": "VIEWER_POLISH_REQUIRED",
                "primary_gap_evidence_refs": refs,
                "primary_gap_reason": "viewer feels unpolished"}
    gap, override = enforce_evidence_ladder(live_gap, ev, q, label)
    assert override is None or override.get("override_kind") != "OBJECTIVE_VIEWER_FAULT"


# ---------------------------------------------------------------- §6.6 기존 hard rung 회귀 없음

def test_existing_hard_rungs_still_override(tmp_path):
    cases = [
        ("EVIDENCE_INSUFFICIENT", {"evidence_sufficient": False}),
        ("ARCHIVE_RECOMMENDED", {"archive_recommended": True}),
        ("SPEC_REPAIR_REQUIRED", {"verdict": "SPEC_REPAIR_REQUIRED"}),
        ("CORE_PATCH_REQUIRED", {"gate_fail": True}),
        ("RUNNER_PATCH_REQUIRED", {"runner_executable": False}),
    ]
    for expected, mutation in cases:
        run_root = tmp_path / expected.lower()
        run_root.mkdir()
        run = _47_like_run(run_root)
        ev, q, hard = _evidence(run)
        ev["facts"].update(mutation)
        label = {"stage": "REVIEWABLE_ARTIFACT"}
        assert derive_primary_gap(ev, q, label) == expected
        assert expected in HARD_EVIDENCE_GAPS
        gap, override = enforce_evidence_ladder(_live_ux_gap(ev), ev, q, label)
        assert gap["primary_gap"] == expected
        assert override["enforced_gap"] == expected
        assert override["override_kind"] == "HARD_EVIDENCE_RUNG"
        assert validate_gap_override(override, ev) == []


# ---------------------------------------------------------------- §6.7 override artifact 검증

def test_validator_rejects_viewer_fault_claim_without_fault(tmp_path):
    run = _47_like_run(tmp_path)  # 정상 viewer — fault 없음
    ev, q, hard = _evidence(run)
    fabricated = {
        "live_gap": "UX_POLISH_REQUIRED",
        "deterministic_gap": "VIEWER_POLISH_REQUIRED",
        "enforced_gap": "VIEWER_POLISH_REQUIRED",
        "override_kind": "OBJECTIVE_VIEWER_FAULT",
        "reason": "fabricated",
        "viewer_faults": {"viewer_exists": True, "viewer_reads_replay": True,
                          "mismatch_count": 1},
        "evidence_refs": [ev["refs"]["facts.viewer_exists"],
                          ev["refs"]["facts.mismatch_count"]],
    }
    problems = validate_gap_override(fabricated, ev)
    assert any("viewer fault가 없는데" in p for p in problems)


def test_validator_rejects_empty_reason_and_foreign_refs(tmp_path):
    run = _47_like_run(tmp_path)
    (run / _VIEWER_REL).write_text(_VIEWER_MISMATCH, encoding="utf-8")
    ev, q, hard = _evidence(run)
    label = mock_product_judge(ev, q, hard)
    _gap, override = enforce_evidence_ladder(_live_ux_gap(ev), ev, q, label)
    assert validate_gap_override(override, ev) == []

    no_reason = dict(override, reason="")
    assert any("reason" in p for p in validate_gap_override(no_reason, ev))

    foreign = dict(override, evidence_refs=["made.up.ref=true"])
    assert any("known refs 밖" in p for p in validate_gap_override(foreign, ev))

    missing_live = {k: v for k, v in override.items() if k != "live_gap"}
    assert any("live_gap" in p for p in validate_gap_override(missing_live, ev))

    drifted = dict(override, deterministic_gap="UX_POLISH_REQUIRED")
    assert any("deterministic_gap" in p for p in validate_gap_override(drifted, ev))


def test_run_judgment_desks_fails_closed_on_invalid_override(tmp_path, monkeypatch):
    """override 기록이 계약 위반이면 silent 채택 대신 invalid desk output으로 FAIL."""
    import repo_idea_miner.factory_product_loop as fpl

    run = _47_like_run(tmp_path)
    (run / _VIEWER_REL).write_text(_VIEWER_MISMATCH, encoding="utf-8")
    ev, q, hard = _evidence(run)
    label = mock_product_judge(ev, q, hard)
    corrupt = {"live_gap": "UX_POLISH_REQUIRED", "enforced_gap": "VIEWER_POLISH_REQUIRED",
               "deterministic_gap": "VIEWER_POLISH_REQUIRED",
               "override_kind": "OBJECTIVE_VIEWER_FAULT", "reason": "",
               "viewer_faults": None, "evidence_refs": []}
    enforced_gap = mock_gap_classifier(ev, q, label)
    monkeypatch.setattr(fpl, "enforce_evidence_ladder",
                        lambda *a, **k: (enforced_gap, corrupt))
    ex = _ScriptedExecutor({"product_stage_label": label,
                            "product_gap_classification": _live_ux_gap(ev)})
    out = run_judgment_desks(ex, ev, q, hard, "sequential", True, {}, include_order=False)
    assert out["status"] == "FAIL"
    assert any("reason" in p or "viewer_faults" in p for p in out["problems"])


# ---------------------------------------------------------------- §6.8~6.10 closed loop 자율 순서 (skip 불가 합성 fixture)

def _synthetic_state(mismatches: list, sixty_seconds: bool, ux_report: bool):
    """runs/ 실런 없이 어떤 환경에서도 재현되는 최소 evidence fixture."""
    facts = {
        "viewer_exists": True, "viewer_reads_replay": True,
        "mismatches": list(mismatches), "mismatch_count": len(mismatches),
        "authoring_ui": True, "evidence_sufficient": True, "gate_fail": False,
        "archive_recommended": False, "verdict": "REVIEW_READY", "green_base": True,
        "runner_executable": True, "replay_count": 3,
        "has_interaction_report": True, "has_execution_report": True,
        "has_ux_polish_report": ux_report,
    }
    loop = {k: True for k in (
        "can_create_or_modify_input", "can_validate_input", "can_execute_primary_action",
        "can_observe_state_change", "can_understand_success", "can_understand_failure",
        "can_revise_and_retry")}
    loop["product_loop_closed"] = True
    qf = {"first_screen_understandable": sixty_seconds, "clear_next_action": True,
          "has_example_or_seed_data": True, "success_feedback_visible": True,
          "failure_feedback_visible": True, "empty_screen_risk": False,
          "user_can_understand_value_in_60s": sixty_seconds}
    refs: dict = {}
    for k, v in loop.items():
        refs[f"loop.{k}"] = f"artifact_evidence.product_loop.{k}={str(bool(v)).lower()}"
    for k in ("viewer_exists", "viewer_reads_replay", "authoring_ui", "green_base",
              "gate_fail", "evidence_sufficient", "archive_recommended", "mismatch_count",
              "replay_count", "runner_executable", "verdict", "has_ux_polish_report"):
        refs[f"facts.{k}"] = f"artifact_evidence.facts.{k}={str(facts.get(k)).lower()}"
    refs["quality.user_can_understand_value_in_60s"] = (
        "user_facing_quality.user_can_understand_value_in_60s="
        f"{str(bool(qf['user_can_understand_value_in_60s'])).lower()}")
    ev = {"facts": facts, "product_loop": loop, "refs": refs,
          "known_refs": set(refs.values())}
    return ev, {"fields": qf}


class _LiveUXJudgeDouble:
    """live-compatible desk double: 60초 이해성 gap을 항상 UX로만 귀속하는 실측 오판 재현."""

    def __init__(self, ev, quality, hard, final: bool):
        self.calls: list[str] = []
        label = mock_product_judge(ev, quality, hard)
        self.outputs = {"product_stage_label": label}
        if final:
            self.outputs["product_gap_classification"] = {
                "gaps": [], "primary_gap": None, "primary_gap_evidence_refs": [],
                "primary_gap_reason": None}
        else:
            gap = _live_ux_gap(ev)
            self.outputs["product_gap_classification"] = gap
            self.outputs["recommended_next_lane"] = mock_next_lane_planner(ev, gap)

    def call(self, schema_name, prompt, model_cls):
        self.calls.append(schema_name)
        return RawPassthrough.model_validate(self.outputs[schema_name]), "scripted"


def test_closed_loop_autonomously_runs_viewer_then_ux_to_product_candidate(tmp_path, monkeypatch):
    """§6.8: run_closed_product_loop(execute=True)가 기본 예산에서 스스로
    live UX 오판 → VIEWER override → VIEWER_POLISH 적용 → fresh rejudge → UX_POLISH 적용
    → PRODUCT_CANDIDATE 순서를 수행한다. 수동 execute_lane 조립 없음."""
    import repo_idea_miner.factory_loop_executor as fle

    base = tmp_path / "parent"
    (base / "workspace").mkdir(parents=True)

    states = {
        # 시작 parent: objective mismatch + 60s 이해 불가 (live는 UX로 오판)
        "parent": {"ev_q": _synthetic_state(["viewer field 'node.status' not in replay nodes"],
                                            sixty_seconds=False, ux_report=True),
                   "final": False, "stage_rank_hint": "EXECUTION_CANDIDATE",
                   "acceptance_passed": 11},
        # viewer child: mismatch 0, canonical viewer가 CTA를 무효화 → UX evidence 부족
        "viewer_child": {"ev_q": _synthetic_state([], sixty_seconds=False, ux_report=False),
                         "final": False, "stage_rank_hint": "EXECUTION_CANDIDATE",
                         "acceptance_passed": 12},
        # ux child: CTA 재주입 완료 → PRODUCT_CANDIDATE
        "ux_child": {"ev_q": _synthetic_state([], sixty_seconds=True, ux_report=True),
                     "final": True, "stage_rank_hint": "PRODUCT_CANDIDATE",
                     "acceptance_passed": 14},
    }
    judged: list[tuple[str, dict]] = []

    def fake_verify(run_dir, out_dir, **kw):
        name = Path(run_dir).name
        st = states[name]
        ev, quality = st["ev_q"]
        hard = {"max_stage": None, "product_candidate_blocked": False, "blockers": []}
        double = _LiveUXJudgeDouble(ev, quality, hard, final=st["final"])
        desks = run_judgment_desks(double, ev, quality, hard, "sequential", True, {},
                                   include_order=False)
        judged.append((name, desks))
        stage = (desks.get("stage_label") or {}).get("stage")
        acceptance = {"product_candidate_allowed": st["final"], "failed_checks": [],
                      "max_stage": stage, "passed_count": st["acceptance_passed"]}
        vector = {"stage_rank": STAGE_RANK.get(stage, -1), "stage": stage,
                  "core_gates_passed": 7,
                  "product_acceptance_passed": st["acceptance_passed"],
                  "hard_blocker_count": 0, "critical_requirement_coverage": 1.0,
                  "difficulty_anchor_coverage": 1.0, "product_loop_parts_passed": 7,
                  "success_scenarios_passed": 2, "failure_scenarios_passed": 1,
                  "mock_fallback_count": 0, "regression_count": 0}
        return {"gate_summary": {g: True for g in CORE_GATE_ORDER}, "anti_summary": {},
                "validate_ok": True, "probe": {}, "profile": {}, "coverage": {},
                "judge": {"desks": desks, "evidence": ev, "quality": quality, "hard": hard},
                "acceptance": acceptance, "vector": vector, "stage": stage,
                "effective_stage": stage, "overrating_blocked": False}

    lanes_called: list[str] = []
    child_of = {"parent": "viewer_child", "viewer_child": "ux_child"}

    def fake_execute_lane(lane, ctx):
        lanes_called.append(lane)
        child = tmp_path / "children" / child_of[Path(ctx["parent_run_dir"]).name]
        child.mkdir(parents=True, exist_ok=True)
        return {"lane": lane, "status": "APPLIED", "child_run_dir": str(child),
                "changed_files": ["final_artifact/product/viewer/index.html"],
                "allowed_scope_check": "PASS", "protected_hash_check": "PASS",
                "targeted_tests": [], "targeted_test_status": "PASS",
                "failure_signature": None, "problems": [], "error": None,
                "underlying_status": "APPLIED", "route": "canonical"}

    monkeypatch.setattr(fle, "verify_candidate", fake_verify)
    monkeypatch.setattr(fle, "execute_lane", fake_execute_lane)
    monkeypatch.setattr(fle, "compute_loop_protected_hashes", lambda p: {})
    monkeypatch.setattr(fle, "compare_protected_hashes",
                        lambda a, b: {"status": "PASS", "files_checked": 0,
                                      "changed": [], "added": [], "removed": []})

    # §6.9: 기본 lane budget 그대로 — budgets 인자를 넘기지 않는다
    res = fle.run_closed_product_loop(run_dir=base, mode="mock", execute=True)

    # lane sequence: VIEWER_POLISH → UX_POLISH (자율, 조립 없음)
    assert lanes_called == ["VIEWER_POLISH", "UX_POLISH"]
    assert res["status"] == "PRODUCT_CANDIDATE"
    assert any("엄격한 PRODUCT_CANDIDATE 도달" in s for s in res["stop_conditions"])
    assert not any("예산" in s for s in res["stop_conditions"])

    # iteration 1: live UX 오판이 objective mismatch로 VIEWER override됨
    it1 = res["iterations"][0]
    assert it1["primary_gap_before"] == "VIEWER_POLISH_REQUIRED"
    assert it1["selected_lane"] == "VIEWER_POLISH"
    parent_desks = judged[0][1]
    assert parent_desks["gap_override"]["live_gap"] == "UX_POLISH_REQUIRED"
    assert parent_desks["gap_override"]["override_kind"] == "OBJECTIVE_VIEWER_FAULT"

    # iteration 2: viewer 수리 후 fresh rejudge가 (override 없이) UX를 선택
    it2 = res["iterations"][1]
    assert it2["primary_gap_before"] == "UX_POLISH_REQUIRED"
    assert it2["selected_lane"] == "UX_POLISH"
    viewer_child_desks = next(d for n, d in judged if n == "viewer_child")
    assert viewer_child_desks.get("gap_override") is None

    # 최종 rejudge: PRODUCT_CANDIDATE + acceptance 허용
    assert it2["stage_after"] == "PRODUCT_CANDIDATE"
    assert res["final_stage"] == "PRODUCT_CANDIDATE"
    assert res["base_hash_status"] == "PASS"
