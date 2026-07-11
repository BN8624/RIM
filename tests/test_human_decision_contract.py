# 이슈 #12 테스트: human decision 계약 — 결정론 정규화(§13.1), live/mock semantic parity(§13.2), product loop 의미 분리(§13.3).
import json
from pathlib import Path

from repo_idea_miner.factory_autopilot_desks import (
    _HUMAN_DECISION_RULES,
    build_lane_prompt,
    build_unified_prompt,
    mock_gap_classifier,
    mock_next_lane_planner,
    mock_product_judge,
)
from repo_idea_miner.factory_autopilot_schemas import (
    GAP_TO_LANE,
    GAP_TYPES,
    LANE_POLICY,
    LANE_TEMPLATES,
    LANES,
    SEMANTIC_HOLD_GAPS,
    normalize_human_decision,
    validate_human_decision_consistency,
)
from repo_idea_miner.factory_product_loop import (
    run_judgment_desks,
    apply_hard_blockers,
    extract_artifact_evidence,
    extract_user_facing_quality,
)

from test_factory_product_loop_2d0 import _47_like_run, _ScriptedExecutor


def _evidence(run: Path):
    ev = extract_artifact_evidence(run)
    q = extract_user_facing_quality(ev)
    hard = apply_hard_blockers(ev, q)
    return ev, q, hard


def _lane_packet(lane_name: str, *, human_decision_required: bool) -> dict:
    """live desk가 출력했을 법한 lane packet — policy 필드는 정책값 그대로 (실측 Fresh-C 형태)."""
    policy = LANE_POLICY[lane_name]
    return {
        "recommended_next_lane": lane_name,
        "reason": "live shaped packet",
        "evidence_refs": ["artifact_evidence.facts.viewer_exists=true"],
        "lane_risk": policy["lane_risk"],
        "dry_run_allowed": policy["dry_run_allowed"],
        "auto_execute_allowed": policy["auto_execute_allowed"],
        "requires_human_approval_before_apply": policy["requires_human_approval_before_apply"],
        "allowed_file_scopes": [],
        "protected_file_scopes": [],
        "human_decision_required": human_decision_required,
    }


def _gap_for(lane_name: str) -> dict:
    primary = next((g for g, l in GAP_TO_LANE.items() if l == lane_name), None)
    return {"primary_gap": primary, "gaps": [], "primary_gap_evidence_refs": []}


# ---------------------------------------------------------------- §13.1 Contract Unit Tests

def test_semantic_hold_lane_requires_human_decision():
    """1. semantic HOLD(lane=HOLD_FOR_HUMAN) → human decision true."""
    rep = normalize_human_decision(_gap_for("HOLD_FOR_HUMAN"),
                                   _lane_packet("HOLD_FOR_HUMAN", human_decision_required=True))
    assert rep["normalized_human_decision_required"] is True
    assert rep["corrected"] is False
    assert rep["reason_code"] == "RAW_CONSISTENT"


def test_execution_lane_without_ambiguity_is_false():
    """2. 실행 lane + semantic 질문 없음 → false."""
    rep = normalize_human_decision(_gap_for("RUNNER_BACKED_DRAFT_EXECUTION"),
                                   _lane_packet("RUNNER_BACKED_DRAFT_EXECUTION",
                                                human_decision_required=False))
    assert rep["normalized_human_decision_required"] is False
    assert rep["corrected"] is False


def test_approval_required_alone_is_not_human_decision():
    """3. requires_human_approval_before_apply=true 단독 → human decision 아님 (INV-4)."""
    lane = _lane_packet("RUNNER_BACKED_DRAFT_EXECUTION", human_decision_required=False)
    assert lane["requires_human_approval_before_apply"] is True
    rep = normalize_human_decision(_gap_for("RUNNER_BACKED_DRAFT_EXECUTION"), lane)
    assert rep["normalized_human_decision_required"] is False
    assert validate_human_decision_consistency(
        _gap_for("RUNNER_BACKED_DRAFT_EXECUTION"), lane) == []


def test_auto_execute_false_alone_is_not_human_decision():
    """4. auto_execute_allowed=false 단독 → human decision 아님 (INV-5)."""
    lane = _lane_packet("CORE_PATCH", human_decision_required=False)
    assert lane["auto_execute_allowed"] is False
    rep = normalize_human_decision(_gap_for("CORE_PATCH"), lane)
    assert rep["normalized_human_decision_required"] is False


def test_unresolved_semantic_gap_forces_true():
    """5. unresolved semantic choice(semantic-hold gap) → true."""
    for gap_type in SEMANTIC_HOLD_GAPS:
        gap = {"primary_gap": gap_type, "gaps": [], "primary_gap_evidence_refs": []}
        rep = normalize_human_decision(
            gap, _lane_packet("HOLD_FOR_HUMAN", human_decision_required=False))
        assert rep["normalized_human_decision_required"] is True


def test_hold_lane_with_raw_false_corrected():
    """6. HOLD lane + raw false → true로 교정 (Case 1)."""
    lane = _lane_packet("HOLD_FOR_HUMAN", human_decision_required=False)
    rep = normalize_human_decision(_gap_for("HOLD_FOR_HUMAN"), lane)
    assert rep["corrected"] is True
    assert rep["reason_code"] == "SEMANTIC_HOLD_FORCED_TRUE"
    assert rep["normalized_human_decision_required"] is True


def test_execution_lane_with_raw_true_corrected():
    """7. 실행 lane + raw true → false로 교정 (Case 2 — Fresh-C 실측 결함)."""
    lane = _lane_packet("RUNNER_BACKED_DRAFT_EXECUTION", human_decision_required=True)
    rep = normalize_human_decision(_gap_for("RUNNER_BACKED_DRAFT_EXECUTION"), lane)
    assert rep["corrected"] is True
    assert rep["reason_code"] == "APPROVAL_CONFUSION_CORRECTED_FALSE"
    assert rep["normalized_human_decision_required"] is False


def test_normalization_evidence_fields():
    """8. normalization evidence: raw/normalized/reason/policy refs가 남는다."""
    lane = _lane_packet("RUNNER_BACKED_DRAFT_EXECUTION", human_decision_required=True)
    rep = normalize_human_decision(_gap_for("RUNNER_BACKED_DRAFT_EXECUTION"), lane)
    assert rep["raw_human_decision_required"] is True
    assert rep["normalized_human_decision_required"] is False
    assert rep["reason_code"]
    assert rep["recommended_next_lane"] == "RUNNER_BACKED_DRAFT_EXECUTION"
    assert rep["lane_policy_refs"] == {
        "auto_execute_allowed": False, "requires_human_approval_before_apply": True}
    assert rep["semantic_hold_gaps"] == list(SEMANTIC_HOLD_GAPS)


def test_normalization_is_deterministic():
    """9. 같은 입력 → 항상 같은 출력."""
    for lane_name in LANES:
        gap = _gap_for(lane_name)
        for raw in (True, False):
            lane = _lane_packet(lane_name, human_decision_required=raw)
            reps = [normalize_human_decision(gap, dict(lane)) for _ in range(3)]
            assert reps[0] == reps[1] == reps[2]


def test_no_challenge_hardcode_in_contract_code():
    """10. normalization 코드에 Challenge ID/run ID/제품 이름 하드코딩 없음."""
    src = Path("repo_idea_miner/factory_autopilot_schemas.py").read_text(encoding="utf-8")
    for marker in ("challenge_41", "Mini-Transformers", "factory_20260711", "run_id=36"):
        assert marker not in src


def test_case4_semantic_gap_on_execution_lane_blocks():
    """Case 4: semantic-hold gap + 실행 lane + raw false → 실행 금지 (true 정규화 + INV 위반 감지)."""
    gap = {"primary_gap": "EVIDENCE_INSUFFICIENT", "gaps": [], "primary_gap_evidence_refs": []}
    lane = _lane_packet("RUNNER_BACKED_DRAFT_EXECUTION", human_decision_required=False)
    rep = normalize_human_decision(gap, lane)
    assert rep["normalized_human_decision_required"] is True  # 실행 차단
    assert validate_human_decision_consistency(gap, lane)  # 정규화 전 packet은 INV 위반


def test_consistency_validator_passes_after_normalization():
    """정규화를 적용한 packet은 INV-1~3을 항상 만족한다."""
    for lane_name in LANES:
        gap = _gap_for(lane_name)
        for raw in (True, False):
            lane = _lane_packet(lane_name, human_decision_required=raw)
            rep = normalize_human_decision(gap, lane)
            lane["human_decision_required"] = rep["normalized_human_decision_required"]
            assert validate_human_decision_consistency(gap, lane) == []


def test_prompts_state_semantic_vs_approval_rule():
    """§7.1: lane/unified prompt가 semantic 결정 ≠ 승인 규칙을 명시한다 (장문 확대 금지)."""
    ev = {"known_refs": set()}
    gap = _gap_for("RUNNER_BACKED_DRAFT_EXECUTION")
    assert "복사하지 마라" in _HUMAN_DECISION_RULES
    assert _HUMAN_DECISION_RULES in build_lane_prompt(ev, gap)
    assert _HUMAN_DECISION_RULES in build_unified_prompt(
        {"known_refs": set(), "facts": {}, "product_loop": {}}, {"fields": {}}, {}, LANE_TEMPLATES)
    assert len(_HUMAN_DECISION_RULES) < 400  # 프롬프트 장문 확대 금지


# ---------------------------------------------------------------- §13.2 live/mock semantic parity

_SEMANTIC_FIELDS = ("recommended_next_lane", "human_decision_required",
                    "requires_human_approval_before_apply", "auto_execute_allowed")

_PARITY_LANES = ("HOLD_FOR_HUMAN", "RUNNER_BACKED_DRAFT_EXECUTION", "CORE_PATCH",
                 "SPEC_REPAIR", "VIEWER_POLISH", "UX_POLISH", "INTERACTION_UI",
                 "RUNNER_PATCH", "ARCHIVE")


def test_live_mock_semantic_parity_per_lane():
    """동일 gap에 대해 live-shaped packet(정규화 후)과 mock이 의미 field에서 일치한다."""
    for lane_name in _PARITY_LANES:
        gap = _gap_for(lane_name)
        mock = mock_next_lane_planner({"refs": {}, "known_refs": set()}, gap)
        # live 결함 재현: 승인 필요를 semantic 결정으로 혼동한 raw packet
        live = _lane_packet(lane_name, human_decision_required=True)
        rep = normalize_human_decision(gap, live)
        live["human_decision_required"] = rep["normalized_human_decision_required"]
        for field in _SEMANTIC_FIELDS:
            assert live[field] == mock[field], (lane_name, field)
        # unresolved semantic decision 여부도 일치
        assert (live["human_decision_required"] is True) == \
            (lane_name == "HOLD_FOR_HUMAN"), lane_name


def test_mock_planner_is_already_canonical():
    """mock desk 출력은 정규화해도 교정이 없다 (RAW_CONSISTENT) — mock이 정본 의미다."""
    for gap_type in GAP_TYPES:
        gap = {"primary_gap": gap_type, "gaps": [], "primary_gap_evidence_refs": []}
        mock = mock_next_lane_planner({"refs": {}, "known_refs": set()}, gap)
        rep = normalize_human_decision(gap, mock)
        assert rep["corrected"] is False, gap_type
        assert rep["reason_code"] == "RAW_CONSISTENT"


def test_fresh_c_shaped_packet_normalizes_to_execution(tmp_path):
    """§13.2-7 Fresh-C 유형: RUNNER_BACKED 추천 + raw human_decision_required=true →

    run_judgment_desks가 정규화해 loop가 실행 lane으로 진행 가능해야 한다 (live 경로 통합)."""
    run = _47_like_run(tmp_path)
    ev, q, hard = _evidence(run)
    label = mock_product_judge(ev, q, hard)
    gap = mock_gap_classifier(ev, q, label)
    assert gap["primary_gap"] == "RUNNER_BACKED_EXECUTION_REQUIRED"
    live_lane = dict(mock_next_lane_planner(ev, gap))
    live_lane["human_decision_required"] = True  # Fresh-C 실측 결함 재현
    ex = _ScriptedExecutor({"product_stage_label": label,
                            "product_gap_classification": gap,
                            "recommended_next_lane": live_lane})
    out = run_judgment_desks(ex, ev, q, hard, "sequential", True, {}, include_order=False)
    assert out["status"] == "PASS"
    assert out["lane"]["recommended_next_lane"] == "RUNNER_BACKED_DRAFT_EXECUTION"
    assert out["lane"]["human_decision_required"] is False  # 교정됨 → loop 정지 없음
    norm = out["human_decision_normalization"]
    assert norm["corrected"] is True
    assert norm["raw_human_decision_required"] is True
    assert norm["reason_code"] == "APPROVAL_CONFUSION_CORRECTED_FALSE"
    assert validate_human_decision_consistency(out["gap"], out["lane"]) == []


def test_mock_flow_records_raw_consistent_normalization(tmp_path):
    """mock 경로도 같은 정규화 layer를 지난다 — 교정 0, evidence는 남는다 (live/mock 동일 계약)."""
    run = _47_like_run(tmp_path)
    ev, q, hard = _evidence(run)
    out = run_judgment_desks(None, ev, q, hard, "sequential", False, {}, include_order=False)
    assert out["status"] == "PASS"
    norm = out["human_decision_normalization"]
    assert norm["corrected"] is False
    assert norm["reason_code"] == "RAW_CONSISTENT"


def test_unified_mode_normalizes_lane(tmp_path):
    """unified packet 경로에서도 lane 정규화가 적용된다."""
    run = _47_like_run(tmp_path)
    ev, q, hard = _evidence(run)
    out = run_judgment_desks(None, ev, q, hard, "unified", False, {}, include_order=True)
    assert out["status"] == "PASS"
    assert out["human_decision_normalization"]["reason_code"] == "RAW_CONSISTENT"
    assert validate_human_decision_consistency(out["gap"], out["lane"]) == []


# ---------------------------------------------------------------- §13.3 product loop 의미 분리 (2D-1)

def _fake_verify(lane_name: str, *, human_decision_required: bool | None = None,
                 normalization: dict | None = None) -> dict:
    desks = {"status": "PASS",
             "gap": _gap_for(lane_name),
             "lane": _lane_packet(lane_name, human_decision_required=bool(human_decision_required))}
    if human_decision_required is None:
        desks["lane"].pop("human_decision_required")
    if normalization is not None:
        desks["human_decision_normalization"] = normalization
    return {
        "gate_summary": {}, "anti_summary": {}, "validate_ok": True, "probe": {},
        "profile": {}, "coverage": {},
        "judge": {"desks": desks},
        "acceptance": {"product_candidate_allowed": False, "failed_checks": [],
                       "max_stage": "INTERACTION_CANDIDATE"},
        "vector": {}, "stage": "INTERACTION_CANDIDATE",
        "effective_stage": "INTERACTION_CANDIDATE", "overrating_blocked": False,
    }


def _patch_loop_infra(monkeypatch, fle, verify: dict, lanes_called: list[str]):
    monkeypatch.setattr(fle, "verify_candidate",
                        lambda *a, **k: json.loads(json.dumps(verify)))

    def fake_execute_lane(lane, ctx):
        lanes_called.append(lane)
        return {"lane": lane, "status": "FAILED", "child_run_dir": None, "changed_files": [],
                "allowed_scope_check": "PASS", "protected_hash_check": "PASS",
                "targeted_tests": [], "targeted_test_status": "FAIL",
                "failure_signature": f"sig_{lane}", "problems": [],
                "error": None, "underlying_status": "DONE", "route": ""}

    monkeypatch.setattr(fle, "execute_lane", fake_execute_lane)
    monkeypatch.setattr(fle, "compute_loop_protected_hashes", lambda p: {})
    monkeypatch.setattr(fle, "compare_protected_hashes",
                        lambda a, b: {"status": "PASS", "files_checked": 0,
                                      "changed": [], "added": [], "removed": []})


def test_loop_proceeds_into_execution_lane_after_normalization(tmp_path, monkeypatch):
    """§13.3-3: 정규화된 false면 loop는 실행 lane에 실제 진입한다 (Fresh-C 조기 정지 제거)."""
    import repo_idea_miner.factory_loop_executor as fle

    run = tmp_path / "base_run"
    (run / "workspace").mkdir(parents=True)
    lanes_called: list[str] = []
    norm = {"raw_human_decision_required": True, "normalized_human_decision_required": False,
            "corrected": True, "reason_code": "APPROVAL_CONFUSION_CORRECTED_FALSE"}
    _patch_loop_infra(monkeypatch, fle,
                      _fake_verify("RUNNER_BACKED_DRAFT_EXECUTION",
                                   human_decision_required=False, normalization=norm),
                      lanes_called)
    res = fle.run_closed_product_loop(run_dir=run, mode="mock", execute=True,
                                      budgets={"max_iterations": 1})
    assert lanes_called == ["RUNNER_BACKED_DRAFT_EXECUTION"]
    it1 = res["iterations"][0]
    # §9: approval-before-apply는 semantic HOLD가 아니라 apply-approval 의미로 분리 기록된다
    assert it1["execution_policy"]["handling"] == "APPLY_APPROVAL_PENDING"
    assert it1["execution_policy"]["requires_human_approval_before_apply"] is True
    assert "human_decision_required" not in res["stop_conditions"]


def test_loop_semantic_hold_records_class_and_evidence(tmp_path, monkeypatch):
    """§13.3-1: semantic HOLD 정지는 hold_reason_class=SEMANTIC_HOLD + 정규화 evidence를 남긴다."""
    import repo_idea_miner.factory_loop_executor as fle

    run = tmp_path / "base_run"
    (run / "workspace").mkdir(parents=True)
    lanes_called: list[str] = []
    norm = {"raw_human_decision_required": True, "normalized_human_decision_required": True,
            "corrected": False, "reason_code": "RAW_CONSISTENT"}
    _patch_loop_infra(monkeypatch, fle,
                      _fake_verify("HOLD_FOR_HUMAN",
                                   human_decision_required=True, normalization=norm),
                      lanes_called)
    res = fle.run_closed_product_loop(run_dir=run, mode="mock", execute=True,
                                      budgets={"max_iterations": 1})
    assert lanes_called == []  # 사람 결정 전 어떤 lane도 실행하지 않는다
    assert "human_decision_required" in res["stop_conditions"]
    packet = res["hold_packet"]
    assert packet["hold_reason_class"] == "SEMANTIC_HOLD"
    assert packet["human_decision_normalization"] == norm
    loop_dir = Path(res["loop_dir"])
    written = json.loads((loop_dir / "hold_for_human_packet.json").read_text("utf-8"))
    assert written["hold_reason_class"] == "SEMANTIC_HOLD"


def test_loop_execution_failure_is_not_semantic_hold(tmp_path, monkeypatch):
    """§13.3: 실행 실패(무개선) HOLD는 EXECUTION_BLOCKED — semantic HOLD로 마스킹되지 않는다."""
    import repo_idea_miner.factory_loop_executor as fle

    run = tmp_path / "base_run"
    (run / "workspace").mkdir(parents=True)
    lanes_called: list[str] = []
    _patch_loop_infra(monkeypatch, fle,
                      _fake_verify("RUNNER_BACKED_DRAFT_EXECUTION",
                                   human_decision_required=False),
                      lanes_called)
    res = fle.run_closed_product_loop(run_dir=run, mode="mock", execute=True,
                                      budgets={"max_iterations": 4,
                                               "max_consecutive_no_progress": 2})
    assert lanes_called  # 실행 lane에는 진입했다
    packet = res["hold_packet"]
    assert packet is not None
    assert packet["hold_reason_class"] != "SEMANTIC_HOLD"
    assert packet["human_decision_normalization"] is None
