# Phase 2D-0 테스트: Gemma Productization Autopilot — evidence 판정/strict schema/hard blocker/auto order/blueprint/mock loop (주문서 §31 + 보강 I).
import json
from pathlib import Path

import pytest

from repo_idea_miner.cli import main
from repo_idea_miner.factory_autopilot_desks import (
    HARD_EVIDENCE_GAPS,
    RawPassthrough,
    build_judge_prompt,
    derive_primary_gap,
    derive_stage_from_evidence,
    enforce_evidence_ladder,
    execute_desk,
    mock_gap_classifier,
    mock_next_lane_planner,
    mock_order_slots,
    mock_product_judge,
    mock_repair_blueprint,
    mock_unified_packet,
)
from repo_idea_miner.factory_autopilot_schemas import (
    AUTO_ORDER_QUALITY_MIN,
    GAP_TO_LANE,
    GAP_TYPES,
    LANE_POLICY,
    LANE_TEMPLATES,
    LANES,
    MOCK_SAFE_LANES,
    ProductStageLabel,
    RecommendedNextLane,
    UnifiedDecisionPacket,
    _meaning_snapshot,
    schema_repair_pass,
    validate_against_hard_blockers,
    validate_desk_output,
    validate_judgment_evidence,
    validate_stage_gap_lane_consistency,
)
from repo_idea_miner.factory_desks import DeskError
from repo_idea_miner.factory_product_loop import (
    REQUIRED_OUTPUTS,
    run_judgment_desks,
    apply_hard_blockers,
    build_auto_order_json,
    compute_loop_protected_hashes,
    extract_artifact_evidence,
    extract_user_facing_quality,
    run_mock_loop_proof,
    run_product_loop,
    score_auto_order,
)
from repo_idea_miner.factory_validate import _check_phase2d0, detect_phase2d0_run

# 2C-0 테스트의 합성 green run 빌더를 재사용한다
from test_factory_review_2c0 import (  # noqa: E402
    _VIEWER_CLEAN,
    _VIEWER_MISMATCH,
    _VIEWER_READONLY,
    _build_green_run,
    _dump,
)

FIXTURE_47 = Path("runs/factory_20260709_072220")

# ---------------------------------------------------------------- fixture 빌더

_EDITOR_SMOKE_47 = {
    "editor_mode_exists": True,
    "add_node_supported": True,
    "add_edge_supported": True,
    "graph_validation_supported": True,
    "draft_schema_compatible": True,
    "draft_roundtrip_pass": True,
    "draft_export_supported": True,
    "model_level_smoke_pass": True,
    "ui_binding_evidence_pass": True,
    "js_syntax_status": "PASS",
    "runner_backed_execution_included": False,
    "original_replay_unchanged": True,
    "critical_failures": [],
}


def _47_like_run(tmp_path, challenge_id=99) -> Path:
    """#47류 합성 run: authoring viewer + editor 산출물 + runner-backed execution 없음."""
    run = _build_green_run(tmp_path, _VIEWER_CLEAN)
    rd = run / "review" / "phase2c2"
    _dump(rd / "editor_smoke_review.json", dict(_EDITOR_SMOKE_47))
    _dump(rd / "product_fitness_report_after_editor.json", {
        "recommended_fitness": "PRODUCT_CANDIDATE",
        "draft_editor_candidate": True,
        "runner_backed_execution_included": False,
        "limitations": ["runner-backed execution not included"],
        "critical_red_flags": [],
    })
    _dump(rd / "viewer_js_syntax_check.json",
          {"status": "PASS", "functions_present": {"p2c2AddNodeModel": True}})
    _dump(rd / "viewer_handler_binding_check.json", {"status": "PASS"})
    # challenge_id는 dashboard 표시 전용 — 판정에는 쓰이면 안 된다 (§12)
    _dump(run / "phase2b1b_dashboard_summary.json", {
        "challenge_id": challenge_id, "base_run_id": 1, "verdict": "REVIEW_READY",
        "promoted_to_green_base": True,
        "gates": {g: True for g in ("core_contract", "runner", "scenario_replay", "golden_output",
                                    "state_invariant", "determinism", "anti_hardcode")},
        "summary_source": "state_derived", "summary_hardcode_risk": "low",
        "gates_passed": 7, "gates_total": 7})
    return run


def _evidence(run: Path):
    ev = extract_artifact_evidence(run)
    q = extract_user_facing_quality(ev)
    hard = apply_hard_blockers(ev, q)
    return ev, q, hard


def _judged(run: Path):
    ev, q, hard = _evidence(run)
    label = mock_product_judge(ev, q, hard)
    gap = mock_gap_classifier(ev, q, label)
    lane = mock_next_lane_planner(ev, gap)
    return ev, q, hard, label, gap, lane


# ---------------------------------------------------------------- Group A: evidence 추출 (§7, §8)

def test_artifact_evidence_extraction_47_like(tmp_path):
    run = _47_like_run(tmp_path)
    ev, q, hard = _evidence(run)
    loop = ev["product_loop"]
    assert loop["can_create_or_modify_input"] is True
    assert loop["can_validate_input"] is True
    assert loop["can_execute_primary_action"] is False
    assert loop["can_observe_state_change"] is False
    assert loop["product_loop_closed"] is False
    # evidence_refs 카탈로그에 §9 스타일 refs 존재
    assert "artifact_evidence.product_loop.can_execute_primary_action=false" in ev["known_refs"]
    assert "phase2c2_editor_report.runner_backed_execution_included=false" in ev["known_refs"]


def test_user_facing_quality_extraction_47_like(tmp_path):
    run = _47_like_run(tmp_path)
    ev, q, hard = _evidence(run)
    f = q["fields"]
    assert f["first_screen_understandable"] is True
    assert f["clear_next_action"] is True
    assert f["has_example_or_seed_data"] is True
    assert f["success_feedback_visible"] is True
    assert f["failure_feedback_visible"] is False
    assert f["user_can_understand_value_in_60s"] is False
    assert "user_facing_quality_evidence.user_can_understand_value_in_60s=false" in ev["known_refs"]


def test_hard_blockers_block_product_candidate(tmp_path):
    run = _47_like_run(tmp_path)
    ev, q, hard = _evidence(run)
    assert hard["product_candidate_blocked"] is True
    assert hard["max_stage"] == "INTERACTION_CANDIDATE"
    assert any("runner-backed execution 없음" in r for r in hard["applied"])


def test_hard_blocker_stops_gemma_overclaim(tmp_path):
    run = _47_like_run(tmp_path)
    ev, q, hard = _evidence(run)
    label = mock_product_judge(ev, q, hard)
    label["stage"] = "PRODUCT_CANDIDATE"  # Gemma가 과대평가했다고 가정
    problems = validate_against_hard_blockers(label, hard)
    assert problems  # hard blocker를 넘을 수 없다 (§6)


# ---------------------------------------------------------------- Group B: stage fixtures (§26, 테스트 39~45)

def test_stage_core_green_no_viewer(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_CLEAN)
    import shutil

    shutil.rmtree(run / "final_artifact" / "product")
    ev, q, hard = _evidence(run)
    assert derive_stage_from_evidence(ev, q, hard) == "CORE_GREEN"


def test_stage_reviewable_with_mismatch_viewer(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_MISMATCH)
    ev, q, hard = _evidence(run)
    assert derive_stage_from_evidence(ev, q, hard) == "REVIEWABLE_ARTIFACT"
    assert derive_primary_gap(ev, q, {"stage": "REVIEWABLE_ARTIFACT"}) == "VIEWER_POLISH_REQUIRED"


def test_stage_polishable_readonly_viewer(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_READONLY)
    ev, q, hard = _evidence(run)
    assert derive_stage_from_evidence(ev, q, hard) == "POLISHABLE_PROTOTYPE"
    assert derive_primary_gap(ev, q, {"stage": "POLISHABLE_PROTOTYPE"}) == "INTERACTION_UI_REQUIRED"


def test_stage_interaction_candidate_47_like(tmp_path):
    run = _47_like_run(tmp_path)
    ev, q, hard = _evidence(run)
    assert derive_stage_from_evidence(ev, q, hard) == "INTERACTION_CANDIDATE"


def test_stage_execution_candidate(tmp_path):
    run = _47_like_run(tmp_path)
    es = dict(_EDITOR_SMOKE_47)
    es.update(runner_backed_execution_included=True, draft_execution_result_visible=True)
    _dump(run / "review" / "phase2c2" / "editor_smoke_review.json", es)
    ev, q, hard = _evidence(run)
    assert ev["product_loop"]["can_execute_primary_action"] is True
    assert ev["product_loop"]["product_loop_closed"] is False
    assert derive_stage_from_evidence(ev, q, hard) == "EXECUTION_CANDIDATE"


def test_stage_product_candidate_full_loop(tmp_path):
    run = _47_like_run(tmp_path)
    es = dict(_EDITOR_SMOKE_47)
    es.update(runner_backed_execution_included=True, draft_execution_result_visible=True,
              draft_failure_feedback_visible=True, draft_revise_and_rerun_supported=True)
    _dump(run / "review" / "phase2c2" / "editor_smoke_review.json", es)
    ev, q, hard = _evidence(run)
    assert ev["product_loop"]["product_loop_closed"] is True
    assert hard["product_candidate_blocked"] is False
    assert derive_stage_from_evidence(ev, q, hard) == "PRODUCT_CANDIDATE"
    assert derive_primary_gap(ev, q, {"stage": "PRODUCT_CANDIDATE"}) is None


def test_stage_archive_low_value(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_READONLY)
    _dump(run / "review" / "phase2c0" / "product_fitness_report.json",
          {"recommended_fitness": "ARCHIVE", "critical_red_flags": [], "limitations": []})
    ev, q, hard = _evidence(run)
    assert derive_stage_from_evidence(ev, q, hard) == "ARCHIVE"
    assert derive_primary_gap(ev, q, {"stage": "ARCHIVE"}) == "ARCHIVE_RECOMMENDED"


def test_evidence_insufficient_fixture(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_READONLY)
    (run / "green_base.json").unlink()
    (run / "gate_rerun_after_anti_hardcode_patch.json").unlink()
    (run / "phase2b1b_dashboard_summary.json").unlink()
    ev, q, hard = _evidence(run)
    assert ev["facts"]["evidence_sufficient"] is False
    gap = derive_primary_gap(ev, q, {"stage": "POLISHABLE_PROTOTYPE"})
    assert gap == "EVIDENCE_INSUFFICIENT"
    lane = mock_next_lane_planner(ev, mock_gap_classifier(ev, q, mock_product_judge(ev, q, hard)))
    assert lane["recommended_next_lane"] == "HOLD_FOR_HUMAN"
    assert lane["human_decision_required"] is True


# ---------------------------------------------------------------- Group C: #47 hardcode 금지 (§12, 테스트 57~59)

def test_no_id_title_hardcode_in_source():
    src = ""
    for name in ("factory_autopilot_schemas.py", "factory_autopilot_desks.py",
                 "factory_product_loop.py"):
        src += (Path("repo_idea_miner") / name).read_text(encoding="utf-8")
    assert "Mini-Comfy" not in src
    assert "== 47" not in src and "==47" not in src
    assert "072220" not in src


def test_same_evidence_different_id_same_judgment(tmp_path):
    run_a = _47_like_run(tmp_path / "a", challenge_id=99)
    run_b = _47_like_run(tmp_path / "b", challenge_id=12345)
    _dump(run_b / "normalized_challenge.json", {"challenge_title": "Totally Different Title"})
    ja = _judged(run_a)
    jb = _judged(run_b)
    assert ja[3]["stage"] == jb[3]["stage"] == "INTERACTION_CANDIDATE"
    assert ja[4]["primary_gap"] == jb[4]["primary_gap"] == "RUNNER_BACKED_EXECUTION_REQUIRED"
    assert ja[5]["recommended_next_lane"] == jb[5]["recommended_next_lane"] == \
        "RUNNER_BACKED_DRAFT_EXECUTION"


def test_judge_prompt_has_no_expected_answer_or_title(tmp_path):
    run = _47_like_run(tmp_path)
    _dump(run / "normalized_challenge.json", {"challenge_title": "SyntheticFlowTitle"})
    ev, q, hard = _evidence(run)
    prompt = build_judge_prompt(ev, q, hard)
    assert "SyntheticFlowTitle" not in prompt
    assert "challenge_id" not in prompt
    # 기대 정답 지시 없음 — stage 정의(enum)는 허용, "~로 판정하라"는 금지
    assert "판정해야 한다" not in prompt and "정답" not in prompt


# ---------------------------------------------------------------- Group D: strict schema / repair pass (§10, §11)

def _valid_label(tmp_path):
    run = _47_like_run(tmp_path)
    ev, q, hard = _evidence(run)
    return mock_product_judge(ev, q, hard)


def test_required_field_missing_invalid(tmp_path):
    label = _valid_label(tmp_path)
    del label["stage"]
    model, problems = validate_desk_output("product_stage_label", label, ProductStageLabel)
    assert model is None and problems


def test_enum_out_of_range_invalid(tmp_path):
    label = _valid_label(tmp_path)
    label["stage"] = "SUPER_PRODUCT"
    model, problems = validate_desk_output("product_stage_label", label, ProductStageLabel)
    assert model is None
    assert any("enum" in p for p in problems)


def test_natural_language_output_rejected():
    model, problems = validate_desk_output("product_stage_label",
                                           "이 제품은 아주 좋습니다", ProductStageLabel)
    assert model is None and problems


def test_schema_repair_fixes_json_text(tmp_path):
    label = _valid_label(tmp_path)
    raw = "```json\n" + json.dumps(label, ensure_ascii=False) + ",\n```"  # trailing comma + fence
    rep = schema_repair_pass(raw, "product_stage_label", ProductStageLabel)
    assert rep["repaired"] is True
    assert rep["meaning_changed"] is False
    assert rep["model"].stage == label["stage"]  # 의미 보존 (§11)


def test_schema_repair_normalizes_enum_case(tmp_path):
    label = _valid_label(tmp_path)
    label["stage"] = "interaction_candidate"
    rep = schema_repair_pass(label, "product_stage_label", ProductStageLabel)
    assert rep["repaired"] is True
    assert rep["model"].stage == "INTERACTION_CANDIDATE"
    assert rep["meaning_changed"] is False  # 대소문자 정규화는 의미 변경이 아니다


def test_schema_repair_unwraps_single_wrapping(tmp_path):
    label = _valid_label(tmp_path)
    rep = schema_repair_pass({"product_stage_label": label}, "product_stage_label",
                             ProductStageLabel)
    assert rep["repaired"] is True


def test_schema_repair_fail_still_invalid(tmp_path):
    rep = schema_repair_pass("완전히 JSON이 아님 {{{", "product_stage_label", ProductStageLabel)
    assert rep["repaired"] is False
    assert rep["model"] is None


def test_meaning_snapshot_detects_judgment_change(tmp_path):
    label = _valid_label(tmp_path)
    changed = json.loads(json.dumps(label))
    changed["stage"] = "EXECUTION_CANDIDATE"
    assert _meaning_snapshot(label) != _meaning_snapshot(changed)


class _FailingExecutor:
    def __init__(self, kind):
        self.kind = kind

    def call(self, schema_name, prompt, model_cls):
        raise DeskError("boom", kind=self.kind)


def test_infra_fail_classification():
    out = execute_desk(_FailingExecutor("transient"), "product_stage_label", "p", ProductStageLabel)
    assert out["status"] == "FAIL"
    assert out["failure_type"] == "AUTOPILOT_INFRA_FAIL"


def test_invalid_output_classification_after_repair(tmp_path):
    out = execute_desk(None, "product_stage_label", "p", ProductStageLabel,
                       mock_output={"stage": "INTERACTION_CANDIDATE"})  # 필수 필드 누락
    assert out["status"] == "FAIL"
    assert out["failure_type"] == "AUTOPILOT_INVALID_OUTPUT"
    assert out["schema_repair_report"] is not None  # repair 1회 시도 후에도 실패 (§11)


# ---------------------------------------------------------------- Group E: evidence_refs 검증 (§9)

def test_evidence_refs_fabrication_blocked(tmp_path):
    run = _47_like_run(tmp_path)
    ev, q, hard, label, gap, lane = _judged(run)
    gap["primary_gap_evidence_refs"] = ["totally.fabricated=true", "another.fake=1"]
    problems = validate_judgment_evidence(label, gap, lane, ev["known_refs"])
    assert any("날조" in p for p in problems)


def test_primary_gap_requires_two_refs(tmp_path):
    run = _47_like_run(tmp_path)
    ev, q, hard, label, gap, lane = _judged(run)
    gap["primary_gap_evidence_refs"] = gap["primary_gap_evidence_refs"][:1]
    problems = validate_judgment_evidence(label, gap, lane, ev["known_refs"])
    assert any("최소 2개" in p for p in problems)


def test_lane_must_reference_gap_evidence(tmp_path):
    run = _47_like_run(tmp_path)
    ev, q, hard, label, gap, lane = _judged(run)
    lane["evidence_refs"] = ["artifact_evidence.facts.viewer_exists=true"]
    problems = validate_judgment_evidence(label, gap, lane, ev["known_refs"])
    assert any("primary_gap evidence" in p for p in problems)


# ---------------------------------------------------------------- Group F: gap→lane / lane policy (§13, §14)

def test_gap_to_lane_mapping_complete():
    assert set(GAP_TO_LANE) == set(GAP_TYPES)
    assert set(GAP_TO_LANE.values()) <= set(LANES)


def test_lane_policy_table():
    for lane in LANES:
        pol = LANE_POLICY[lane]
        assert "lane_risk" in pol and "auto_execute_allowed" in pol
    assert LANE_POLICY["RUNNER_BACKED_DRAFT_EXECUTION"]["auto_execute_allowed"] is False
    assert LANE_POLICY["RUNNER_BACKED_DRAFT_EXECUTION"]["lane_risk"] == "medium"
    assert LANE_POLICY["SPEC_REPAIR"]["lane_risk"] == "high"
    assert LANE_POLICY["HOLD_FOR_HUMAN"]["dry_run_allowed"] is False


def test_lane_policy_mismatch_fails_consistency(tmp_path):
    run = _47_like_run(tmp_path)
    ev, q, hard, label, gap, lane = _judged(run)
    lane["auto_execute_allowed"] = True  # 정책 위반
    problems = validate_stage_gap_lane_consistency(label, gap, lane)
    assert any("lane policy 불일치" in p for p in problems)


def test_gap_lane_mismatch_fails(tmp_path):
    run = _47_like_run(tmp_path)
    ev, q, hard, label, gap, lane = _judged(run)
    lane["recommended_next_lane"] = "VIEWER_POLISH"
    lane.update({k: LANE_POLICY["VIEWER_POLISH"][k] for k in
                 ("lane_risk", "dry_run_allowed", "auto_execute_allowed",
                  "requires_human_approval_before_apply")})
    problems = validate_stage_gap_lane_consistency(label, gap, lane)
    assert any("불일치" in p for p in problems)


# ---------------------------------------------------------------- Group F-1: evidence ladder enforcement (§7 — 관측이 서술을 이긴다)

class _ScriptedExecutor:
    """desk별로 준비된 raw 출력을 돌려주는 live executor 스텁."""

    def __init__(self, outputs: dict):
        self.outputs = outputs
        self.calls: list[str] = []

    def call(self, schema_name, prompt, model_cls):
        self.calls.append(schema_name)
        return RawPassthrough.model_validate(self.outputs[schema_name]), "scripted"


def test_evidence_ladder_overrides_soft_gap_on_gate_fail(tmp_path):
    """#54류: fresh gate 실패인데 live desk가 soft gap을 고르면 hard rung으로 override한다."""
    run = _47_like_run(tmp_path)
    ev, q, hard = _evidence(run)
    ev["facts"]["gate_fail"] = True
    label = {"stage": "REVIEWABLE_ARTIFACT"}
    live_gap = {"primary_gap": "INTERACTION_UI_REQUIRED", "gaps": [],
                "primary_gap_evidence_refs": []}
    gap, override = enforce_evidence_ladder(live_gap, ev, q, label)
    assert override is not None
    assert override["live_gap"] == "INTERACTION_UI_REQUIRED"
    assert override["enforced_gap"] == "CORE_PATCH_REQUIRED"
    assert gap["primary_gap"] == "CORE_PATCH_REQUIRED"
    assert "CORE_PATCH_REQUIRED" in HARD_EVIDENCE_GAPS


def test_evidence_ladder_no_override_when_agreeing(tmp_path):
    run = _47_like_run(tmp_path)
    ev, q, hard = _evidence(run)
    ev["facts"]["gate_fail"] = True
    label = {"stage": "REVIEWABLE_ARTIFACT"}
    live_gap = mock_gap_classifier(ev, q, label)
    assert live_gap["primary_gap"] == "CORE_PATCH_REQUIRED"
    gap, override = enforce_evidence_ladder(live_gap, ev, q, label)
    assert override is None
    assert gap is live_gap


def test_evidence_ladder_respects_soft_rung_judgment(tmp_path):
    """ladder가 soft rung을 지시하면 live desk의 (다른) soft 판정을 존중한다."""
    run = _47_like_run(tmp_path)
    ev, q, hard = _evidence(run)
    label = mock_product_judge(ev, q, hard)
    assert derive_primary_gap(ev, q, label) not in HARD_EVIDENCE_GAPS
    live_gap = {"primary_gap": "UX_POLISH_REQUIRED", "gaps": [],
                "primary_gap_evidence_refs": []}
    gap, override = enforce_evidence_ladder(live_gap, ev, q, label)
    assert override is None
    assert gap is live_gap


def test_run_judgment_desks_overrides_live_gap_and_skips_lane_desk(tmp_path):
    """sequential live 흐름: gap override + hard rung은 live lane desk를 호출하지 않는다."""
    run = _47_like_run(tmp_path)
    ev, q, hard = _evidence(run)
    ev["facts"]["gate_fail"] = True
    label = mock_product_judge(ev, q, hard)
    wrong_gap = json.loads(json.dumps(mock_gap_classifier(ev, q, label)))
    wrong_gap["primary_gap"] = "INTERACTION_UI_REQUIRED"
    for g in wrong_gap["gaps"]:
        g["type"] = "INTERACTION_UI_REQUIRED"
    ex = _ScriptedExecutor({"product_stage_label": label,
                            "product_gap_classification": wrong_gap})
    out = run_judgment_desks(ex, ev, q, hard, "sequential", True, {}, include_order=False)
    assert out["status"] == "PASS"
    assert out["gap"]["primary_gap"] == "CORE_PATCH_REQUIRED"
    assert out["gap_override"]["live_gap"] == "INTERACTION_UI_REQUIRED"
    assert out["lane"]["recommended_next_lane"] == "CORE_PATCH"
    # hard rung의 lane은 GAP_TO_LANE 고정 매핑 — live desk를 부르지 않는다
    assert "recommended_next_lane" not in ex.calls
    # override 결과는 stage/gap/lane 정합성 검사를 통과해야 한다
    assert validate_stage_gap_lane_consistency(label, out["gap"], out["lane"]) == []


def test_interaction_stage_with_closed_loop_fails(tmp_path):
    run = _47_like_run(tmp_path)
    ev, q, hard, label, gap, lane = _judged(run)
    label["product_loop_evidence"]["product_loop_closed"] = True
    problems = validate_stage_gap_lane_consistency(label, gap, lane)
    assert any("product_loop_closed" in p for p in problems)


# ---------------------------------------------------------------- Group G: auto order + 품질 (§18)

def test_auto_order_template_based(tmp_path):
    run = _47_like_run(tmp_path)
    ev, q, hard, label, gap, lane = _judged(run)
    template = LANE_TEMPLATES["RUNNER_BACKED_DRAFT_EXECUTION"]
    slots = mock_order_slots(ev, gap, lane, template)
    order = build_auto_order_json("RUNNER_BACKED_DRAFT_EXECUTION", slots)
    assert order["lane_template"] == "RUNNER_BACKED_DRAFT_EXECUTION"
    assert order["title"] == "RIM Product Factory Phase 2C-3 Runner-backed Draft Execution"
    # §18.2 필수 내용
    for key in ("background", "forbidden_actions", "allowed_scopes", "protected_scopes",
                "hash_guard", "dry_run", "apply", "expected_outputs", "smoke_gate", "validate",
                "acceptance_tests", "stop_conditions", "report_format",
                "product_candidate_overclaim_guards"):
        assert order.get(key), key


def test_auto_order_quality_pass(tmp_path):
    run = _47_like_run(tmp_path)
    ev, q, hard, label, gap, lane = _judged(run)
    template = LANE_TEMPLATES["RUNNER_BACKED_DRAFT_EXECUTION"]
    order = build_auto_order_json("RUNNER_BACKED_DRAFT_EXECUTION",
                                  mock_order_slots(ev, gap, lane, template))
    rep = score_auto_order(order, gap, ev["known_refs"])
    assert rep["auto_order_quality_score"] >= AUTO_ORDER_QUALITY_MIN
    assert rep["status"] == "PASS"


def test_auto_order_quality_hold_when_degraded(tmp_path):
    run = _47_like_run(tmp_path)
    ev, q, hard, label, gap, lane = _judged(run)
    template = LANE_TEMPLATES["RUNNER_BACKED_DRAFT_EXECUTION"]
    order = build_auto_order_json("RUNNER_BACKED_DRAFT_EXECUTION",
                                  mock_order_slots(ev, gap, lane, template))
    order["allowed_scopes"] = ["final_artifact/golden/"]  # lane과 불일치
    order["evidence_refs"] = ["fabricated=1"]
    order["forbidden_actions"] = []
    rep = score_auto_order(order, gap, ev["known_refs"])
    assert rep["auto_order_quality_score"] < AUTO_ORDER_QUALITY_MIN
    assert rep["status"] == "HOLD_FOR_HUMAN"


# ---------------------------------------------------------------- Group H: repair blueprint (§19)

def test_blueprint_generated_with_expected_shape(tmp_path):
    run = _47_like_run(tmp_path)
    ev, q, hard, label, gap, lane = _judged(run)
    template = LANE_TEMPLATES["RUNNER_BACKED_DRAFT_EXECUTION"]
    bp = mock_repair_blueprint(ev, gap, lane, template)
    assert bp["apply_allowed"] is False
    assert bp["target_lane"] == "RUNNER_BACKED_DRAFT_EXECUTION"
    for item in ("draft_to_runner_input_adapter", "runner execution command wiring",
                 "result capture", "viewer result display",
                 "edit_validate_execute_result_revise smoke"):
        assert item in bp["expected_patch_shape"]
    assert bp["tests_to_run"] and bp["rollback_conditions"] and bp["failure_conditions"]
    assert bp["product_candidate_overclaim_guards"]


def test_blueprint_protected_scope_proposal_fails(tmp_path):
    from repo_idea_miner.factory_product_loop import validate_blueprint_scopes

    run = _47_like_run(tmp_path)
    ev, q, hard, label, gap, lane = _judged(run)
    bp = mock_repair_blueprint(ev, gap, lane, LANE_TEMPLATES["RUNNER_BACKED_DRAFT_EXECUTION"])
    bp["expected_changed_file_scopes"] = ["final_artifact/golden/expected_001.json"]
    problems = validate_blueprint_scopes(bp, live=True)
    assert any("protected scope 수정 제안" in p or "allowed scope 밖" in p for p in problems)


def test_blueprint_apply_true_fails_on_live(tmp_path):
    from repo_idea_miner.factory_product_loop import validate_blueprint_scopes

    run = _47_like_run(tmp_path)
    ev, q, hard, label, gap, lane = _judged(run)
    bp = mock_repair_blueprint(ev, gap, lane, LANE_TEMPLATES["RUNNER_BACKED_DRAFT_EXECUTION"])
    bp["apply_allowed"] = True
    problems = validate_blueprint_scopes(bp, live=True)
    assert any("apply_allowed" in p for p in problems)


# ---------------------------------------------------------------- Group I: mock/safe loop proof (§22)

def test_mock_loop_proof_follows_generated_order(tmp_path):
    report = run_mock_loop_proof(tmp_path / "proof")
    assert report["lane"] in MOCK_SAFE_LANES
    assert report["auto_order_read"] is True
    assert report["scope_guard_read"] is True
    assert report["repair_followed_order"] is True
    assert report["actual_file_changed"] is True
    assert report["changed_files_within_allowed_scope"] is True
    assert report["protected_files_unchanged"] is True
    assert report["smoke_ran"] and report["validate_ran"] and report["rejudge_ran"]
    assert report["stage_improved_or_honest_stop"] is True
    assert report["stage_improved"] is True  # REVIEWABLE → POLISHABLE
    assert report["mismatches_after"] == []
    assert (tmp_path / "proof" / "mock_loop_order_following_report.json").is_file()
    assert (tmp_path / "proof" / "auto_order.json").is_file()
    assert (tmp_path / "proof" / "scope_guard.json").is_file()


def test_mock_loop_repair_only_within_allowed_scope(tmp_path):
    from repo_idea_miner.factory_product_loop import build_proof_fixture, follow_auto_order

    proof = tmp_path / "proof"
    fixture = build_proof_fixture(proof)
    # golden(보호 대상)을 고치라는 order — 차단되어야 한다
    _dump(proof / "auto_order.json", {"repair_actions": [
        {"action": "replace_in_file", "file": "final_artifact/golden/expected_001.json",
         "find": "Completed", "replace": "HACKED"}]})
    _dump(proof / "scope_guard.json", {
        "lane": "VIEWER_POLISH",
        "allowed_scopes": ["final_artifact/product/"],
        "protected_scopes": ["final_artifact/golden/", "final_artifact/replay/"],
        "forbidden_actions": ["golden 수정 금지"]})
    res = follow_auto_order(fixture, proof / "auto_order.json", proof / "scope_guard.json")
    assert res["repair_followed_order"] is False
    assert res["actual_file_changed"] is False
    assert res["protected_files_unchanged"] is True
    assert any("차단" in p for p in res["problems"])


def test_mock_loop_no_order_is_honest_failure(tmp_path):
    from repo_idea_miner.factory_product_loop import build_proof_fixture, follow_auto_order

    proof = tmp_path / "proof"
    fixture = build_proof_fixture(proof)
    _dump(proof / "auto_order.json", {"repair_actions": []})
    _dump(proof / "scope_guard.json", {"lane": "VIEWER_POLISH",
                                       "allowed_scopes": ["final_artifact/product/"],
                                       "protected_scopes": ["final_artifact/golden/"],
                                       "forbidden_actions": ["x"]})
    res = follow_auto_order(fixture, proof / "auto_order.json", proof / "scope_guard.json")
    assert res["auto_order_read"] and res["scope_guard_read"]
    assert res["repair_followed_order"] is False  # hardcoded repair로 덮지 않는다


# ---------------------------------------------------------------- Group J: run_product_loop 오케스트레이터 (§21, §28)

def test_loop_generates_all_required_outputs(tmp_path):
    run = _47_like_run(tmp_path)
    out = run_product_loop(run_dir=run, mode="mock")
    assert out["ok"] is True and out["status"] == "AUTOPILOT_JUDGED"
    rd = run / "review" / "phase2d0"
    for rel in REQUIRED_OUTPUTS:
        assert (rd / rel).is_file(), rel
    assert (rd / "schemas" / "product_stage_label.schema.json").is_file()
    assert (rd / "hardcode_guard.json").is_file()


def test_loop_defaults_and_no_repair(tmp_path):
    run = _47_like_run(tmp_path)
    before = compute_loop_protected_hashes(run)
    out = run_product_loop(run_dir=run, mode="mock")
    after = compute_loop_protected_hashes(run)
    assert before == after  # repair apply 없음 (§2)
    assert out["live_repair_apply"] is False and out["repair_execute"] is False
    summary = json.loads((run / "review/phase2d0/product_loop_iteration_summary.json")
                         .read_text("utf-8"))
    assert summary["max_iterations"] == 1
    assert summary["live_repair_apply"] is False


def test_loop_47_like_expected_judgment(tmp_path):
    run = _47_like_run(tmp_path)
    out = run_product_loop(run_dir=run, mode="mock")
    assert out["autopilot_stage"] == "INTERACTION_CANDIDATE"
    assert out["autopilot_stage"] != "PRODUCT_CANDIDATE"
    assert out["primary_gap"] == "RUNNER_BACKED_EXECUTION_REQUIRED"
    assert out["next_lane"] == "RUNNER_BACKED_DRAFT_EXECUTION"
    order = json.loads((run / "review/phase2d0/auto_order.json").read_text("utf-8"))
    assert order["title"] == "RIM Product Factory Phase 2C-3 Runner-backed Draft Execution"
    label = json.loads((run / "review/phase2d0/product_stage_label.json").read_text("utf-8"))
    assert label["prior_fitness_label"] == "PRODUCT_CANDIDATE"
    assert label["prior_fitness_qualifier"] == "draft_editor_candidate"
    assert label["autopilot_stage"] == "INTERACTION_CANDIDATE"
    assert label["autopilot_is_product_candidate"] is False
    bp = json.loads((run / "review/phase2d0/repair_blueprint.json").read_text("utf-8"))
    assert bp["apply_allowed"] is False


def test_loop_does_not_modify_prior_fitness_report(tmp_path):
    run = _47_like_run(tmp_path)
    prior_path = run / "review/phase2c2/product_fitness_report_after_editor.json"
    before = prior_path.read_text("utf-8")
    run_product_loop(run_dir=run, mode="mock")
    assert prior_path.read_text("utf-8") == before  # §14 기존 fitness 미수정
    check = json.loads((run / "review/phase2d0/phase2d0_hash_check.json").read_text("utf-8"))
    assert check["status"] == "PASS"


def test_loop_stop_same_primary_gap_twice(tmp_path):
    run = _47_like_run(tmp_path)
    out = run_product_loop(run_dir=run, mode="mock", max_iterations=3)
    assert "same primary_gap 2회 반복" in out["stop_conditions"]


def test_loop_stop_max_iterations_and_lane_policy(tmp_path):
    run = _47_like_run(tmp_path)
    out = run_product_loop(run_dir=run, mode="mock")
    assert "max_iterations 도달" in out["stop_conditions"]
    assert "lane policy상 auto_execute_allowed = false" in out["stop_conditions"]


def test_loop_hold_for_human_on_insufficient_evidence(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_READONLY)
    (run / "green_base.json").unlink()
    (run / "gate_rerun_after_anti_hardcode_patch.json").unlink()
    (run / "phase2b1b_dashboard_summary.json").unlink()
    out = run_product_loop(run_dir=run, mode="mock")
    assert out["status"] == "AUTOPILOT_HOLD_FOR_HUMAN"
    assert out["next_lane"] == "HOLD_FOR_HUMAN"
    assert "human_decision_required = true" in out["stop_conditions"]


def test_loop_product_candidate_stops(tmp_path):
    run = _47_like_run(tmp_path)
    es = dict(_EDITOR_SMOKE_47)
    es.update(runner_backed_execution_included=True, draft_execution_result_visible=True,
              draft_failure_feedback_visible=True, draft_revise_and_rerun_supported=True)
    _dump(run / "review" / "phase2c2" / "editor_smoke_review.json", es)
    out = run_product_loop(run_dir=run, mode="mock")
    assert out["autopilot_stage"] == "PRODUCT_CANDIDATE"
    assert "PRODUCT_CANDIDATE 도달" in out["stop_conditions"]
    assert out["primary_gap"] is None


def test_loop_unified_mode_same_judgment(tmp_path):
    run = _47_like_run(tmp_path)
    out = run_product_loop(run_dir=run, mode="mock", gemma_mode="unified")
    assert out["ok"] is True
    assert out["autopilot_stage"] == "INTERACTION_CANDIDATE"
    assert out["primary_gap"] == "RUNNER_BACKED_EXECUTION_REQUIRED"
    assert out["next_lane"] == "RUNNER_BACKED_DRAFT_EXECUTION"
    summary = json.loads((run / "review/phase2d0/product_loop_iteration_summary.json")
                         .read_text("utf-8"))
    assert summary["selected_mode"] == "unified" and summary["shared_validator"] is True


def test_unified_packet_schema_validated(tmp_path):
    run = _47_like_run(tmp_path)
    ev, q, hard = _evidence(run)
    packet = mock_unified_packet(ev, q, hard)
    model, problems = validate_desk_output("unified_decision_packet", packet,
                                           UnifiedDecisionPacket)
    assert model is not None, problems


def test_unified_mode_shares_validator_rejects_bad_lane(tmp_path):
    from repo_idea_miner.llm_client import MockLLMClient

    run = _47_like_run(tmp_path)
    ev, q, hard = _evidence(run)
    packet = mock_unified_packet(ev, q, hard)
    packet["recommended_next_lane"]["recommended_next_lane"] = "VIEWER_POLISH"  # gap과 불일치
    llm = MockLLMClient(overrides={"unified_decision_packet": packet})
    out = run_product_loop(run_dir=run, mode="mock", gemma_mode="unified", llm=llm)
    assert out["ok"] is False
    assert out["failure_type"] == "AUTOPILOT_INVALID_OUTPUT"


def test_loop_via_llm_schema_repair_recorded(tmp_path):
    from repo_idea_miner.llm_client import MockLLMClient

    run = _47_like_run(tmp_path)
    ev, q, hard = _evidence(run)
    label = mock_product_judge(ev, q, hard)
    label["stage"] = "interaction_candidate"  # 소문자 → repair pass 필요
    gap = mock_gap_classifier(ev, q, {**label, "stage": "INTERACTION_CANDIDATE"})
    lane = mock_next_lane_planner(ev, gap)
    template = LANE_TEMPLATES[lane["recommended_next_lane"]]
    llm = MockLLMClient(overrides={
        "product_stage_label": label,
        "product_gap_classification": gap,
        "recommended_next_lane": lane,
        "auto_order": mock_order_slots(ev, gap, lane, template),
        "repair_blueprint": mock_repair_blueprint(ev, gap, lane, template),
    })
    out = run_product_loop(run_dir=run, mode="mock", llm=llm)
    assert out["ok"] is True
    assert out["autopilot_stage"] == "INTERACTION_CANDIDATE"
    assert (run / "review/phase2d0/schema_repair_report.json").is_file()
    summary = json.loads((run / "review/phase2d0/product_loop_iteration_summary.json")
                         .read_text("utf-8"))
    assert summary["schema_repair_used"] is True


def test_loop_quality_below_threshold_holds(tmp_path):
    from repo_idea_miner.llm_client import MockLLMClient

    run = _47_like_run(tmp_path)
    ev, q, hard = _evidence(run)
    label = mock_product_judge(ev, q, hard)
    gap = mock_gap_classifier(ev, q, label)
    lane = mock_next_lane_planner(ev, gap)
    template = LANE_TEMPLATES[lane["recommended_next_lane"]]
    slots = mock_order_slots(ev, gap, lane, template)
    slots["allowed_scopes"] = ["final_artifact/golden/"]  # lane과 불일치 (2개 이상 감점)
    slots["protected_scopes"] = ["review/phase2c0/"]
    llm = MockLLMClient(overrides={
        "product_stage_label": label,
        "product_gap_classification": gap,
        "recommended_next_lane": lane,
        "auto_order": slots,
        "repair_blueprint": mock_repair_blueprint(ev, gap, lane, template),
    })
    out = run_product_loop(run_dir=run, mode="mock", llm=llm)
    assert out["ok"] is False
    assert out["auto_order_quality_status"] == "HOLD_FOR_HUMAN"
    assert "auto_order_quality_score < 0.85" in out["stop_conditions"]


# ---------------------------------------------------------------- Group K: validate (§30)

def test_detect_and_validate_phase2d0(tmp_path):
    run = _47_like_run(tmp_path)
    assert detect_phase2d0_run(run) is False
    run_product_loop(run_dir=run, mode="mock")
    assert detect_phase2d0_run(run) is True
    assert _check_phase2d0(run) == []


def test_validate_noop_without_marker(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_CLEAN)
    assert _check_phase2d0(run) == []


def test_validate_fails_blueprint_apply_true(tmp_path):
    run = _47_like_run(tmp_path)
    run_product_loop(run_dir=run, mode="mock")
    bp_path = run / "review/phase2d0/repair_blueprint.json"
    bp = json.loads(bp_path.read_text("utf-8"))
    bp["apply_allowed"] = True
    _dump(bp_path, bp)
    assert any("apply_allowed" in p for p in _check_phase2d0(run))


def test_validate_fails_patch_plan_protected_scope(tmp_path):
    run = _47_like_run(tmp_path)
    run_product_loop(run_dir=run, mode="mock")
    bp_path = run / "review/phase2d0/repair_blueprint.json"
    bp = json.loads(bp_path.read_text("utf-8"))
    bp["expected_changed_file_scopes"] = ["final_artifact/golden/"]
    _dump(bp_path, bp)
    assert any("protected scope" in p or "allowed scope 밖" in p for p in _check_phase2d0(run))


def test_validate_fails_mock_report_not_following(tmp_path):
    run = _47_like_run(tmp_path)
    run_product_loop(run_dir=run, mode="mock")
    path = run / "review/phase2d0/mock_loop_order_following_report.json"
    rep = json.loads(path.read_text("utf-8"))
    rep["repair_followed_order"] = False
    _dump(path, rep)
    assert any("repair_followed_order=false" in p for p in _check_phase2d0(run))


def test_validate_fails_prompt_title_leak(tmp_path):
    run = _47_like_run(tmp_path)
    run_product_loop(run_dir=run, mode="mock")
    _dump(run / "review/phase2d0/judge_prompt_trace.json",
          {"prompt": "...", "contains_challenge_id": False, "contains_title": True})
    assert any("hardcode" in p for p in _check_phase2d0(run))


def test_validate_fails_lane_gap_mismatch(tmp_path):
    run = _47_like_run(tmp_path)
    run_product_loop(run_dir=run, mode="mock")
    lane_path = run / "review/phase2d0/recommended_next_lane.json"
    lane = json.loads(lane_path.read_text("utf-8"))
    lane["recommended_next_lane"] = "VIEWER_POLISH"
    lane.update({k: LANE_POLICY["VIEWER_POLISH"][k] for k in
                 ("lane_risk", "dry_run_allowed", "auto_execute_allowed",
                  "requires_human_approval_before_apply")})
    _dump(lane_path, lane)
    assert any("불일치" in p for p in _check_phase2d0(run))


def test_validate_fails_product_candidate_with_60s_false(tmp_path):
    run = _47_like_run(tmp_path)
    run_product_loop(run_dir=run, mode="mock")
    label_path = run / "review/phase2d0/product_stage_label.json"
    label = json.loads(label_path.read_text("utf-8"))
    label["autopilot_stage"] = "PRODUCT_CANDIDATE"
    label["stage"] = "PRODUCT_CANDIDATE"
    label["is_product_candidate"] = True
    _dump(label_path, label)
    problems = _check_phase2d0(run)
    assert any("user_can_understand_value_in_60s" in p for p in problems)
    assert any("hard blocker" in p.lower() for p in problems)


def test_validate_fails_missing_outputs(tmp_path):
    run = _47_like_run(tmp_path)
    run_product_loop(run_dir=run, mode="mock")
    (run / "review/phase2d0/auto_order.md").unlink()
    (run / "review/phase2d0/user_facing_quality_evidence.json").unlink()
    problems = _check_phase2d0(run)
    assert any("auto_order.md" in p for p in problems)
    assert any("user_facing_quality_evidence.json" in p for p in problems)


def test_validate_quality_blocks_product_candidate_fields(tmp_path):
    # 보강 F: quality 항목별 PRODUCT_CANDIDATE 차단 (first_screen/clear_next_action/seed/failure)
    run = _47_like_run(tmp_path)
    run_product_loop(run_dir=run, mode="mock")
    label_path = run / "review/phase2d0/product_stage_label.json"
    label = json.loads(label_path.read_text("utf-8"))
    label["autopilot_stage"] = label["stage"] = "PRODUCT_CANDIDATE"
    label["is_product_candidate"] = True
    label["product_loop_evidence"] = {k: True for k in label["product_loop_evidence"]}
    for field in ("first_screen_understandable", "clear_next_action",
                  "has_example_or_seed_data", "failure_feedback_visible"):
        label["user_facing_quality_evidence"] = {
            **{k: True for k in label["user_facing_quality_evidence"]}, field: False}
        _dump(label_path, label)
        assert any(field in p for p in _check_phase2d0(run)), field


# ---------------------------------------------------------------- Group L: CLI (§21)

def test_cli_product_loop_mock(tmp_path, capsys):
    run = _47_like_run(tmp_path)
    rc = main(["factory-product-loop", "--run-dir", str(run), "--db",
               str(tmp_path / "no.db")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "autopilot_stage: INTERACTION_CANDIDATE" in out
    assert "live_repair_apply: False" in out


def test_cli_requires_target(tmp_path, capsys):
    rc = main(["factory-product-loop", "--db", str(tmp_path / "no.db")])
    assert rc == 1


# ---------------------------------------------------------------- Group M: 실제 #47 (live 산출물 존재 시)

@pytest.mark.skipif(not (FIXTURE_47 / "review/phase2d0/product_loop_dashboard_summary.json").is_file(),
                    reason="#47 live Phase 2D-0 산출물 없음")
def test_live_47_acceptance():
    rd = FIXTURE_47 / "review/phase2d0"
    label = json.loads((rd / "product_stage_label.json").read_text("utf-8"))
    assert label["prior_fitness_label"] == "PRODUCT_CANDIDATE"
    assert label["prior_fitness_qualifier"] == "draft_editor_candidate"
    assert label["autopilot_stage"] == "INTERACTION_CANDIDATE"
    assert label["autopilot_is_product_candidate"] is False
    gap = json.loads((rd / "product_gap_classification.json").read_text("utf-8"))
    assert gap["primary_gap"] == "RUNNER_BACKED_EXECUTION_REQUIRED"
    lane = json.loads((rd / "recommended_next_lane.json").read_text("utf-8"))
    assert lane["recommended_next_lane"] == "RUNNER_BACKED_DRAFT_EXECUTION"
    order = json.loads((rd / "auto_order.json").read_text("utf-8"))
    assert order["title"] == "RIM Product Factory Phase 2C-3 Runner-backed Draft Execution"
    bp = json.loads((rd / "repair_blueprint.json").read_text("utf-8"))
    assert bp["apply_allowed"] is False
    assert _check_phase2d0(FIXTURE_47) == []


@pytest.mark.skipif(not (FIXTURE_47 / "review/phase2d0/product_loop_dashboard_summary.json").is_file(),
                    reason="#47 live Phase 2D-0 산출물 없음")
def test_live_47_no_repair_apply():
    summary = json.loads((FIXTURE_47 / "review/phase2d0/product_loop_iteration_summary.json")
                         .read_text("utf-8"))
    assert summary["live_repair_apply"] is False
    assert summary["repair_execute"] is False
    check = json.loads((FIXTURE_47 / "review/phase2d0/phase2d0_hash_check.json").read_text("utf-8"))
    assert check["status"] == "PASS"
