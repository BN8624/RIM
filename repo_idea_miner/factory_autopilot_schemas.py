# Phase 2D-0 Gemma Productization Autopilot의 stage/gap/lane 정의, strict 스키마, evidence_refs 검증, schema repair pass 모듈.
from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, ValidationError

# ---------------------------------------------------------------- Stage / Gap / Lane (§4, §13, §14)

# 제품성 stage ladder — 순서가 곧 사다리(§4). ARCHIVE는 사다리 밖 별도 판정.
STAGE_LADDER = (
    "CORE_GREEN",
    "REVIEWABLE_ARTIFACT",
    "POLISHABLE_PROTOTYPE",
    "INTERACTION_CANDIDATE",
    "EXECUTION_CANDIDATE",
    "PRODUCT_CANDIDATE",
)
STAGES = STAGE_LADDER + ("ARCHIVE",)
STAGE_RANK = {s: i for i, s in enumerate(STAGE_LADDER)}

GAP_TYPES = (
    "SPEC_REPAIR_REQUIRED",
    "CORE_PATCH_REQUIRED",
    "RUNNER_PATCH_REQUIRED",
    "VIEWER_POLISH_REQUIRED",
    "INTERACTION_UI_REQUIRED",
    "RUNNER_BACKED_EXECUTION_REQUIRED",
    "UX_POLISH_REQUIRED",
    "EVIDENCE_INSUFFICIENT",
    "SCOPE_CREEP_RISK",
    "ARCHIVE_RECOMMENDED",
)

LANES = (
    "SPEC_REPAIR",
    "CORE_PATCH",
    "RUNNER_PATCH",
    "VIEWER_POLISH",
    "INTERACTION_UI",
    "RUNNER_BACKED_DRAFT_EXECUTION",
    "UX_POLISH",
    "ARCHIVE",
    "HOLD_FOR_HUMAN",
)

# primary_gap → 다음 lane 매핑 (§14). validate가 stage/gap/lane 정합성 검사에 사용한다.
GAP_TO_LANE = {
    "SPEC_REPAIR_REQUIRED": "SPEC_REPAIR",
    "CORE_PATCH_REQUIRED": "CORE_PATCH",
    "RUNNER_PATCH_REQUIRED": "RUNNER_PATCH",
    "VIEWER_POLISH_REQUIRED": "VIEWER_POLISH",
    "INTERACTION_UI_REQUIRED": "INTERACTION_UI",
    "RUNNER_BACKED_EXECUTION_REQUIRED": "RUNNER_BACKED_DRAFT_EXECUTION",
    "UX_POLISH_REQUIRED": "UX_POLISH",
    "EVIDENCE_INSUFFICIENT": "HOLD_FOR_HUMAN",
    "SCOPE_CREEP_RISK": "HOLD_FOR_HUMAN",
    "ARCHIVE_RECOMMENDED": "ARCHIVE",
}

# semantic hold를 뜻하는 gap — 이 gap 또는 HOLD_FOR_HUMAN lane일 때만 사람 의미 결정이 필요하다 (이슈 #12)
SEMANTIC_HOLD_GAPS = ("EVIDENCE_INSUFFICIENT", "SCOPE_CREEP_RISK")

# lane risk / 실행 정책 (§14.1). auto_execute는 mock/safe lane에서만 일부 허용.
LANE_POLICY = {
    "SPEC_REPAIR": {"lane_risk": "high", "dry_run_allowed": True,
                    "auto_execute_allowed": False, "requires_human_approval_before_apply": True},
    "CORE_PATCH": {"lane_risk": "high", "dry_run_allowed": True,
                   "auto_execute_allowed": False, "requires_human_approval_before_apply": True},
    "RUNNER_PATCH": {"lane_risk": "medium", "dry_run_allowed": True,
                     "auto_execute_allowed": False, "requires_human_approval_before_apply": True},
    "VIEWER_POLISH": {"lane_risk": "low", "dry_run_allowed": True,
                      "auto_execute_allowed": True, "auto_execute_scope": "mock_safe_only",
                      "requires_human_approval_before_apply": True},
    "INTERACTION_UI": {"lane_risk": "low-medium", "dry_run_allowed": True,
                       "auto_execute_allowed": True, "auto_execute_scope": "mock_safe_only",
                       "requires_human_approval_before_apply": True},
    "RUNNER_BACKED_DRAFT_EXECUTION": {"lane_risk": "medium", "dry_run_allowed": True,
                                      "auto_execute_allowed": False,
                                      "requires_human_approval_before_apply": True},
    "UX_POLISH": {"lane_risk": "low", "dry_run_allowed": True,
                  "auto_execute_allowed": True, "auto_execute_scope": "mock_safe_only",
                  "requires_human_approval_before_apply": True},
    "ARCHIVE": {"lane_risk": "low", "dry_run_allowed": True,
                "auto_execute_allowed": False, "requires_human_approval_before_apply": False},
    "HOLD_FOR_HUMAN": {"lane_risk": "variable", "dry_run_allowed": False,
                       "auto_execute_allowed": False, "requires_human_approval_before_apply": True},
}

# mock/safe loop에서만 auto repair가 허용되는 lane (§22)
MOCK_SAFE_LANES = ("VIEWER_POLISH", "INTERACTION_UI", "UX_POLISH")

# 공통 보호 대상 — 어떤 lane도 core spec/golden/replay/기존 review 산출물을 건드리지 않는다
_COMMON_PROTECTED = [
    "final_artifact/golden/", "final_artifact/fixtures/", "final_artifact/replay/",
    "final_artifact/core_contract.json", "final_artifact/state_contract.json",
    "final_artifact/action_contract.json", "final_artifact/runner_contract.json",
    "workspace/golden/", "workspace/fixtures/", "workspace/replay/",
    "review/phase2c0/", "review/phase2c1/", "review/phase2c2/",
]

_COMMON_FORBIDDEN = [
    "golden/fixtures/contract/replay 의미 변경 금지",
    "challenge_id/run_id/title 기반 stage/gap/lane 하드코딩 금지",
    "gate/validate 없이 성공 처리 금지",
    "기존 review/phase2c0·2c1·2c2 산출물 수정 금지",
]

# lane template — Gemma는 이 구조의 빈칸(slots)만 채운다 (§18.1)
LANE_TEMPLATES: dict[str, dict] = {
    "RUNNER_BACKED_DRAFT_EXECUTION": {
        "title": "RIM Product Factory Phase 2C-3 Runner-backed Draft Execution",
        "allowed_scopes": ["final_artifact/product/", "workspace/product/",
                           "final_artifact/src/adapters/", "workspace/src/adapters/"],
        "protected_scopes": _COMMON_PROTECTED + ["final_artifact/src/core/", "workspace/src/core/"],
        "forbidden_actions": _COMMON_FORBIDDEN + [
            "core engine 로직 수정 금지", "원본 replay를 draft 실행 결과로 덮어쓰기 금지"],
        "expected_patch_shape": [
            "draft_to_runner_input_adapter", "runner execution command wiring",
            "result capture", "viewer result display", "edit_validate_execute_result_revise smoke"],
        "acceptance_tests": [
            "draft JSON을 runner input으로 변환한다",
            "runner를 실행하고 exit code/출력 계약 필드를 확인한다",
            "result capture가 실행 결과를 저장한다",
            "viewer에 draft 실행 result가 표시된다",
            "edit → validate → execute → result → revise loop smoke가 통과한다"],
        "expected_outputs": ["draft 실행 adapter", "실행 result capture 산출물",
                             "viewer result 표시", "edit_validate_execute_result_revise smoke 리포트"],
    },
    "VIEWER_POLISH": {
        "title": "RIM Product Factory Viewer Polish Order",
        "allowed_scopes": ["final_artifact/product/", "workspace/product/"],
        "protected_scopes": _COMMON_PROTECTED + ["final_artifact/src/", "workspace/src/"],
        "forbidden_actions": _COMMON_FORBIDDEN + ["src/ 수정 금지"],
        "expected_patch_shape": ["viewer field mapping normalize", "deterministic layout"],
        "acceptance_tests": ["viewer 필드 mismatch가 0이 된다", "runner/viewer 일치 필드가 유지된다"],
        "expected_outputs": ["폴리시된 product viewer", "mismatch 재검사 리포트"],
    },
    "INTERACTION_UI": {
        "title": "RIM Product Factory Interaction UI Order",
        "allowed_scopes": ["final_artifact/product/", "workspace/product/"],
        "protected_scopes": _COMMON_PROTECTED + ["final_artifact/src/", "workspace/src/"],
        "forbidden_actions": _COMMON_FORBIDDEN + ["src/ 수정 금지"],
        "expected_patch_shape": ["authoring UI 추가", "validation UI", "draft export"],
        "acceptance_tests": ["사용자가 노드/엣지를 추가·편집·삭제할 수 있다", "draft export가 schema 호환이다"],
        "expected_outputs": ["editor mode가 추가된 viewer", "draft export 검증 리포트"],
    },
    "UX_POLISH": {
        "title": "RIM Product Factory UX Polish Order",
        "allowed_scopes": ["final_artifact/product/", "workspace/product/"],
        "protected_scopes": _COMMON_PROTECTED + ["final_artifact/src/", "workspace/src/"],
        "forbidden_actions": _COMMON_FORBIDDEN + ["src/ 수정 금지"],
        "expected_patch_shape": ["first screen 안내", "example/seed data", "성공/실패 피드백 표시"],
        "acceptance_tests": ["첫 화면에서 무엇인지 이해된다", "성공/실패 피드백이 보인다"],
        "expected_outputs": ["UX 개선된 viewer", "60초 이해성 재검수 스크립트"],
    },
    "SPEC_REPAIR": {
        "title": "RIM Product Factory Spec Repair Order",
        "allowed_scopes": ["final_artifact/golden/", "final_artifact/fixtures/",
                           "workspace/golden/", "workspace/fixtures/"],
        "protected_scopes": ["final_artifact/src/", "workspace/src/",
                             "final_artifact/product/", "workspace/product/",
                             "review/phase2c0/", "review/phase2c1/", "review/phase2c2/"],
        "forbidden_actions": ["comparison_mode 약화 금지", "expected field 삭제 금지",
                              "invariant warning화 금지", "구현 코드 수정 금지"],
        "expected_patch_shape": ["golden 스키마 정합 수정", "gate 재실행"],
        "acceptance_tests": ["gate 7종 재실행 결과 기록", "diff summary에 금지 변경 없음"],
        "expected_outputs": ["spec repair proposal/review/apply 산출물", "gate rerun summary"],
    },
    "CORE_PATCH": {
        "title": "RIM Product Factory Core Patch Order",
        "allowed_scopes": ["final_artifact/src/core/", "workspace/src/core/"],
        "protected_scopes": _COMMON_PROTECTED + ["final_artifact/product/", "workspace/product/"],
        "forbidden_actions": _COMMON_FORBIDDEN,
        "expected_patch_shape": ["core engine 결함 수정", "gate 재실행"],
        "acceptance_tests": ["실패 gate가 PASS로 바뀐다", "frozen hash 불변"],
        "expected_outputs": ["core patch diff", "gate rerun summary"],
    },
    "RUNNER_PATCH": {
        "title": "RIM Product Factory Runner Patch Order",
        "allowed_scopes": ["final_artifact/src/", "workspace/src/"],
        "protected_scopes": _COMMON_PROTECTED + ["final_artifact/product/", "workspace/product/"],
        "forbidden_actions": _COMMON_FORBIDDEN,
        "expected_patch_shape": ["runner dispatch/output 수정", "runner smoke 재실행"],
        "acceptance_tests": ["runner exit=0 + 출력 계약 필드 충족"],
        "expected_outputs": ["runner patch diff", "runner smoke evidence"],
    },
    "ARCHIVE": {
        "title": "RIM Product Factory Archive Order",
        "allowed_scopes": ["review/phase2d0/"],
        "protected_scopes": _COMMON_PROTECTED + ["final_artifact/", "workspace/"],
        "forbidden_actions": _COMMON_FORBIDDEN + ["artifact 파일 수정 금지 (기록만 남긴다)"],
        "expected_patch_shape": ["archive 사유 기록"],
        "acceptance_tests": ["archive 사유와 evidence가 기록된다"],
        "expected_outputs": ["archive 판정 기록"],
    },
    "HOLD_FOR_HUMAN": {
        "title": "RIM Product Factory Hold For Human Order",
        "allowed_scopes": ["review/phase2d0/"],
        "protected_scopes": _COMMON_PROTECTED + ["final_artifact/", "workspace/"],
        "forbidden_actions": _COMMON_FORBIDDEN + ["사람 결정 전 어떤 수리도 금지"],
        "expected_patch_shape": ["사람 결정 요청 기록"],
        "acceptance_tests": ["사람이 결정할 질문과 evidence가 기록된다"],
        "expected_outputs": ["human decision 요청 기록"],
    },
}

CONFIDENCES = ("high", "medium", "low")
SEVERITIES = ("blocking", "major", "minor")

# Autopilot 실패 분류 (§23)
AUTOPILOT_INFRA_FAIL = "AUTOPILOT_INFRA_FAIL"
AUTOPILOT_INVALID_OUTPUT = "AUTOPILOT_INVALID_OUTPUT"
AUTOPILOT_EVIDENCE_INSUFFICIENT = "AUTOPILOT_EVIDENCE_INSUFFICIENT"
AUTOPILOT_HOLD_FOR_HUMAN = "AUTOPILOT_HOLD_FOR_HUMAN"

AUTO_ORDER_QUALITY_MIN = 0.85


# ---------------------------------------------------------------- Pydantic strict 스키마 (§10)

class ProductLoopEvidence(BaseModel):
    """사용자가 실제로 무엇을 할 수 있는가 (§7 — Phase 2D-1 §6 공통 evidence 이름)."""
    can_create_or_modify_input: bool
    can_validate_input: bool
    can_execute_primary_action: bool
    can_observe_state_change: bool
    can_understand_success: bool
    can_understand_failure: bool
    can_revise_and_retry: bool
    product_loop_closed: bool


class UserFacingQualityEvidence(BaseModel):
    """사용자-facing 제품 품질 evidence (§8)."""
    first_screen_understandable: bool
    clear_next_action: bool
    has_example_or_seed_data: bool
    success_feedback_visible: bool
    failure_feedback_visible: bool
    empty_screen_risk: bool
    user_can_understand_value_in_60s: bool


class NotProductReason(BaseModel):
    reason: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)


class ProductStageLabel(BaseModel):
    """Product Judge desk 출력 (§15.3)."""
    stage: str
    is_product_candidate: bool
    confidence: str
    evidence_refs: list[str] = Field(min_length=1)
    not_product_reasons: list[NotProductReason] = Field(default_factory=list)
    product_loop_evidence: ProductLoopEvidence
    user_facing_quality_evidence: UserFacingQualityEvidence
    hard_blockers_applied: list[str] = Field(default_factory=list)
    missing_loop_parts: list[str] = Field(default_factory=list)


class RequirementCoverageItem(BaseModel):
    """원 주문서 requirement 1건의 구현 여부 판정 (Phase 2D-1 §8)."""
    requirement: str = Field(min_length=1)
    status: str  # implemented | missing | respected | violated | unknown
    evidence_refs: list[str] = Field(default_factory=list)
    reason: str = ""


class RequirementCoverageJudgment(BaseModel):
    """Requirement Coverage desk 출력 — implemented/respected는 evidence_refs 필수 (날조 차단)."""
    items: list[RequirementCoverageItem] = Field(default_factory=list)


class CoverageProbeProposal(BaseModel):
    """coverage probe spec desk가 제안하는 probe 1개 (이슈 #25 §5.5).

    LLM은 후보를 제안할 뿐이다 — check kind/glob/actions는 factory_coverage의
    결정론적 validator가 재검증하고, 실제 probe 실행 결과만 정본이 된다."""
    probe_id: str = Field(min_length=1)
    title: str = ""
    initial_state: dict = Field(default_factory=dict)
    actions: list[dict] | None = None
    checks: list[dict] = Field(min_length=1)
    covers: list[str] = Field(min_length=1)


class CoverageRequirementClassification(BaseModel):
    """requirement 1건의 adjudication_mode 분류 (이슈 #25 §4.6)."""
    requirement: str = Field(min_length=1)
    adjudication_mode: str
    reason: str = ""


class CoverageProbeSpecProposal(BaseModel):
    """coverage probe spec desk 출력 — 전 requirement 분류 + deterministic probe 후보."""
    probes: list[CoverageProbeProposal] = Field(default_factory=list)
    requirements: list[CoverageRequirementClassification] = Field(min_length=1)


class SemanticCoverageItem(BaseModel):
    """semantic adjudication desk의 requirement 1건 판정 (이슈 #25 §5.7).

    COVERED는 실제 존재하는 evidence_refs 최소 1개 필수 — 검증은 factory_coverage가 한다."""
    requirement: str = Field(min_length=1)
    coverage_status: str
    failure_class: str
    reason_code: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)


class SemanticCoverageAdjudication(BaseModel):
    """semantic requirement 전용 제한 fallback desk 출력 — matrix 병합 후에만 소비된다."""
    items: list[SemanticCoverageItem] = Field(default_factory=list)


class GapItem(BaseModel):
    type: str
    severity: str
    evidence_refs: list[str] = Field(min_length=1)
    explanation: str = Field(min_length=1)


class ProductGapClassification(BaseModel):
    """Gap Classifier desk 출력 (§16). PRODUCT_CANDIDATE/ARCHIVE면 primary_gap이 없을 수 있다."""
    gaps: list[GapItem] = Field(default_factory=list)
    primary_gap: str | None = None
    primary_gap_evidence_refs: list[str] = Field(default_factory=list)
    primary_gap_reason: str | None = None


class RecommendedNextLane(BaseModel):
    """Next Lane Planner desk 출력 (§17)."""
    recommended_next_lane: str
    reason: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    lane_risk: str
    dry_run_allowed: bool
    auto_execute_allowed: bool = Field(
        description="현재 모드·lane policy상 사람 승인 없이 자동 적용 가능한가 — semantic 결정 필요와 독립")
    requires_human_approval_before_apply: bool = Field(
        description="다음 lane 의미는 확정됐고 실제 apply 전 승인 절차만 필요한가 — semantic HOLD가 아니다")
    allowed_file_scopes: list[str] = Field(default_factory=list)
    protected_file_scopes: list[str] = Field(default_factory=list)
    human_decision_required: bool = Field(
        default=False,
        description="사람이 spec/golden/정책 의미를 선택해야 하는 unresolved semantic choice가 있는가 — "
                    "requires_human_approval_before_apply를 복사하지 않는다")


class RepairAction(BaseModel):
    """mock/safe lane에서 repair 실행기가 따라야 하는 기계 실행 가능한 액션."""
    action: str  # replace_in_file 등
    file: str
    find: str
    replace: str


class AutoOrderSlots(BaseModel):
    """Scoped Order Writer desk가 채우는 lane template slots (§18.1)."""
    background: str = Field(min_length=1)
    observed_gap: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    allowed_scopes: list[str] = Field(min_length=1)
    protected_scopes: list[str] = Field(min_length=1)
    forbidden_actions: list[str] = Field(min_length=1)
    concrete_acceptance_tests: list[str] = Field(min_length=1)
    expected_outputs: list[str] = Field(min_length=1)
    stop_conditions: list[str] = Field(min_length=1)
    report_format: list[str] = Field(min_length=1)
    repair_actions: list[RepairAction] = Field(default_factory=list)


class ScopeGuard(BaseModel):
    lane: str
    allowed_scopes: list[str] = Field(min_length=1)
    protected_scopes: list[str] = Field(min_length=1)
    forbidden_actions: list[str] = Field(min_length=1)


class RepairBlueprint(BaseModel):
    """Repair Blueprint Writer desk 출력 (§19). live에서는 apply_allowed=false 강제."""
    target_lane: str
    observed_gap: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    apply_allowed: bool
    purpose: str = Field(min_length=1)
    proposed_implementation_approach: str = Field(min_length=1)
    expected_changed_file_scopes: list[str] = Field(min_length=1)
    protected_file_scopes: list[str] = Field(min_length=1)
    expected_patch_shape: list[str] = Field(min_length=1)
    tests_to_run: list[str] = Field(min_length=1)
    rollback_conditions: list[str] = Field(min_length=1)
    failure_conditions: list[str] = Field(min_length=1)
    product_candidate_overclaim_guards: list[str] = Field(min_length=1)


class TestsToRun(BaseModel):
    target_lane: str
    tests: list[str] = Field(min_length=1)
    note: str | None = None


class UnifiedDecisionPacket(BaseModel):
    """unified_decision_packet mode 출력 (§20). 검증 기준은 sequential과 동일."""
    product_stage_label: ProductStageLabel
    product_gap_classification: ProductGapClassification
    recommended_next_lane: RecommendedNextLane
    repair_blueprint: RepairBlueprint
    auto_order_slots: AutoOrderSlots
    scope_guard_draft: ScopeGuard


# desk schema 이름 → 모델 (schemas/*.schema.json 파일 생성에도 사용, §28)
DESK_SCHEMAS: dict[str, type[BaseModel]] = {
    "product_stage_label": ProductStageLabel,
    "product_gap_classification": ProductGapClassification,
    "recommended_next_lane": RecommendedNextLane,
    "auto_order": AutoOrderSlots,
    "scope_guard": ScopeGuard,
    "auto_order_quality_report": None,  # 코드 생성물 — 아래에서 dict schema로 대체
    "repair_blueprint": RepairBlueprint,
    "tests_to_run": TestsToRun,
    "unified_decision_packet": UnifiedDecisionPacket,
}

# enum 값을 갖는 필드 — schema repair pass의 대소문자 정규화 대상 (§11)
_ENUM_FIELDS = {
    "stage": STAGES,
    "confidence": CONFIDENCES,
    "type": GAP_TYPES,
    "severity": SEVERITIES,
    "primary_gap": GAP_TYPES,
    "recommended_next_lane": LANES,
    "target_lane": LANES,
    "lane": LANES,
}

# schema repair가 절대 바꾸면 안 되는 판단 필드 (§11 금지)
_MEANING_FIELDS = ("stage", "primary_gap", "recommended_next_lane", "target_lane",
                   "is_product_candidate", "apply_allowed")


# ---------------------------------------------------------------- strict 검증 (§10)

def _enum_problems(payload: dict) -> list[str]:
    """알려진 enum 필드에 enum 외 값이 있는지 재귀 검사한다."""
    problems: list[str] = []

    def walk(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                p = f"{path}.{k}" if path else k
                if k in _ENUM_FIELDS and isinstance(v, str) and v not in _ENUM_FIELDS[k]:
                    problems.append(f"enum 외 값: {p}={v}")
                walk(v, p)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")

    walk(payload)
    return problems


# 제품 도메인 payload(runner action type 등)를 담는 desk — desk enum 재귀 검사 대상이 아니고,
# factory_coverage의 결정론적 probe spec validator가 fail-closed로 재검증한다 (이슈 #25 §5.5)
_PRODUCT_PAYLOAD_SCHEMAS = ("coverage_probe_spec",)


def validate_desk_output(schema_name: str, raw, model_cls: type[BaseModel]) -> tuple[BaseModel | None, list[str]]:
    """desk 출력을 strict 스키마로 검증한다. (model|None, problems) 반환 — 자연어만으로는 통과 불가."""
    if not isinstance(raw, dict):
        return None, [f"{schema_name}: JSON 객체가 아님 ({type(raw).__name__})"]
    problems = [] if schema_name in _PRODUCT_PAYLOAD_SCHEMAS else _enum_problems(raw)
    if problems:
        return None, [f"{schema_name}: {p}" for p in problems]
    try:
        model = model_cls.model_validate(raw)
    except ValidationError as exc:
        return None, [f"{schema_name}: {e['loc']} {e['msg']}" for e in exc.errors()[:10]]
    return model, []


# ---------------------------------------------------------------- evidence_refs 검증 (§9)

def validate_evidence_refs(refs: list[str], known_refs: set[str], *, minimum: int = 1,
                           label: str = "") -> list[str]:
    """evidence_refs가 실제 evidence 카탈로그에서 나온 것인지 검사한다. 날조 refs는 무효다."""
    problems: list[str] = []
    if len(refs or []) < minimum:
        problems.append(f"{label}: evidence_refs {len(refs or [])}개 < 최소 {minimum}개")
    for r in refs or []:
        if r not in known_refs:
            problems.append(f"{label}: 알 수 없는 evidence_ref (날조 의심): {r}")
    return problems


def validate_judgment_evidence(stage_label: dict, gap: dict, lane: dict,
                               known_refs: set[str]) -> list[str]:
    """§9 필수 규칙: not_product_reason ≥1, primary_gap ≥2, lane은 gap evidence를 참조."""
    p: list[str] = []
    p += validate_evidence_refs(stage_label.get("evidence_refs") or [], known_refs,
                                minimum=1, label="product_stage_label")
    for i, r in enumerate(stage_label.get("not_product_reasons") or []):
        p += validate_evidence_refs(r.get("evidence_refs") or [], known_refs,
                                    minimum=1, label=f"not_product_reasons[{i}]")
    if gap.get("primary_gap"):
        p += validate_evidence_refs(gap.get("primary_gap_evidence_refs") or [], known_refs,
                                    minimum=2, label="primary_gap")
        # lane은 primary_gap evidence를 참조해야 한다 (§9)
        lane_refs = set(lane.get("evidence_refs") or [])
        gap_refs = set(gap.get("primary_gap_evidence_refs") or [])
        gap_marker = f"product_gap_classification.primary_gap={gap.get('primary_gap')}"
        if not (lane_refs & gap_refs) and gap_marker not in lane_refs:
            p.append("recommended_next_lane: primary_gap evidence_refs를 참조하지 않음")
    for g in gap.get("gaps") or []:
        p += validate_evidence_refs(g.get("evidence_refs") or [], known_refs,
                                    minimum=1, label=f"gap[{g.get('type')}]")
    p += validate_evidence_refs(lane.get("evidence_refs") or [], known_refs,
                                minimum=1, label="recommended_next_lane")
    return p


# ---------------------------------------------------------------- stage/gap/lane 정합성 + hard blocker (§6, §30.2)

def validate_stage_gap_lane_consistency(stage_label: dict, gap: dict, lane: dict) -> list[str]:
    """stage ↔ gap ↔ lane 정합성 검사. sequential/unified 공용 validator다 (§20)."""
    p: list[str] = []
    stage = stage_label.get("stage")
    if stage not in STAGES:
        p.append(f"알 수 없는 stage: {stage}")
    if stage == "PRODUCT_CANDIDATE" and stage_label.get("is_product_candidate") is not True:
        p.append("stage=PRODUCT_CANDIDATE인데 is_product_candidate != true")
    if stage != "PRODUCT_CANDIDATE" and stage_label.get("is_product_candidate") is True:
        p.append(f"stage={stage}인데 is_product_candidate=true")

    loop = stage_label.get("product_loop_evidence") or {}
    # §30.2: stage=INTERACTION_CANDIDATE인데 실행 루프가 닫혔다고 표시 → FAIL
    if stage == "INTERACTION_CANDIDATE" and loop.get("product_loop_closed") is True:
        p.append("stage=INTERACTION_CANDIDATE인데 product_loop_closed=true")
    if stage == "PRODUCT_CANDIDATE" and loop.get("product_loop_closed") is not True:
        p.append("stage=PRODUCT_CANDIDATE인데 product_loop_closed != true")

    primary = gap.get("primary_gap")
    if primary is not None and primary not in GAP_TYPES:
        p.append(f"알 수 없는 primary_gap: {primary}")
    rec_lane = lane.get("recommended_next_lane")
    if rec_lane not in LANES:
        p.append(f"알 수 없는 lane: {rec_lane}")
    # §30.2: recommended_next_lane과 primary_gap 불일치 → FAIL
    if primary and rec_lane and GAP_TO_LANE.get(primary) != rec_lane and rec_lane != "HOLD_FOR_HUMAN":
        p.append(f"primary_gap={primary}와 lane={rec_lane} 불일치 (기대: {GAP_TO_LANE.get(primary)})")
    # lane risk policy 검증 (§14.1)
    policy = LANE_POLICY.get(rec_lane)
    if policy:
        for key in ("lane_risk", "dry_run_allowed", "auto_execute_allowed",
                    "requires_human_approval_before_apply"):
            if lane.get(key) != policy[key]:
                p.append(f"lane policy 불일치: {rec_lane}.{key}={lane.get(key)} (정책: {policy[key]})")
    return p


# ---------------------------------------------------------------- gap override 검증 (이슈 #24 §4.4·§6.7)

def validate_gap_override(override: dict | None, evidence: dict) -> list[str]:
    """enforce_evidence_ladder가 남긴 gap_override 기록의 정합성 검사 (fail-closed).

    silent mutation 금지 계약: live_gap/deterministic_gap/enforced_gap/reason이 기록돼야
    하고, OBJECTIVE_VIEWER_FAULT는 artifact facts에 실제 machine-checkable viewer fault가
    있을 때만 주장할 수 있다 — mismatch 0·viewer 정상인데 fault를 주장하면 invalid다.
    """
    if override is None:
        return []
    p: list[str] = []
    facts = (evidence or {}).get("facts") or {}
    known_refs = (evidence or {}).get("known_refs") or set()
    for key in ("enforced_gap", "deterministic_gap", "override_kind"):
        if not override.get(key):
            p.append(f"gap_override: {key} 누락")
    if "live_gap" not in override:
        p.append("gap_override: live_gap 기록 누락")
    if not (override.get("reason") or "").strip():
        p.append("gap_override: override reason이 비어 있음")
    enforced = override.get("enforced_gap")
    if enforced is not None and enforced not in GAP_TYPES:
        p.append(f"gap_override: 알 수 없는 enforced_gap {enforced}")
    if override.get("deterministic_gap") != enforced:
        p.append("gap_override: enforced_gap이 deterministic_gap과 다름")
    refs = override.get("evidence_refs") or []
    bad = [r for r in refs if r not in known_refs]
    if bad:
        p.append(f"gap_override: known refs 밖의 evidence_refs {bad[:3]}")
    kind = override.get("override_kind")
    if kind == "OBJECTIVE_VIEWER_FAULT":
        if not refs:
            p.append("gap_override: viewer fault override에 evidence_refs 없음")
        vf = override.get("viewer_faults")
        if not isinstance(vf, dict):
            p.append("gap_override: viewer fault override에 viewer_faults 기록 없음")
        # 기록이 아니라 artifact facts가 정본 — 실제 fault 없이 override 주장은 invalid
        actual_fault = (not facts.get("viewer_exists")) \
            or (not facts.get("viewer_reads_replay")) \
            or len(facts.get("mismatches") or []) > 0
        if not actual_fault:
            p.append("gap_override: artifact facts에 machine-checkable viewer fault가 없는데 "
                     "OBJECTIVE_VIEWER_FAULT를 주장")
        if enforced != "VIEWER_POLISH_REQUIRED":
            p.append(f"gap_override: OBJECTIVE_VIEWER_FAULT인데 enforced_gap={enforced}")
    elif kind == "HARD_EVIDENCE_RUNG":
        pass  # hard rung의 사실 근거는 derive_primary_gap이 직접 계산 — 추가 조건 없음
    elif kind is not None:
        p.append(f"gap_override: 알 수 없는 override_kind {kind}")
    return p


# ---------------------------------------------------------------- human decision 결정론 정규화 (이슈 #12)

def normalize_human_decision(gap: dict | None, lane: dict) -> dict:
    """live desk raw human_decision_required를 lane/gap 기준으로 결정론적으로 정규화한다.

    canonical 의미: human_decision_required는 unresolved semantic choice(HOLD_FOR_HUMAN lane
    또는 SEMANTIC_HOLD_GAPS gap)일 때만 true다. requires_human_approval_before_apply(apply 전
    승인 절차)와 auto_execute_allowed(자동 실행 policy)는 semantic 결정과 독립이며 복사 금지다.
    raw 값은 교정하되 조용히 바꾸지 않는다 — raw/normalized/reason을 evidence로 반환한다.
    """
    raw = bool(lane.get("human_decision_required"))
    rec_lane = lane.get("recommended_next_lane")
    primary = (gap or {}).get("primary_gap")
    semantic_hold = rec_lane == "HOLD_FOR_HUMAN" or primary in SEMANTIC_HOLD_GAPS
    if raw == semantic_hold:
        reason_code = "RAW_CONSISTENT"
    elif semantic_hold:
        reason_code = "SEMANTIC_HOLD_FORCED_TRUE"  # Case 1: HOLD lane인데 raw false
    else:
        reason_code = "APPROVAL_CONFUSION_CORRECTED_FALSE"  # Case 2: 실행 lane인데 raw true
    policy = LANE_POLICY.get(rec_lane) or {}
    return {
        "raw_human_decision_required": raw,
        "normalized_human_decision_required": semantic_hold,
        "corrected": raw != semantic_hold,
        "reason_code": reason_code,
        "semantic_hold_expected": semantic_hold,
        "recommended_next_lane": rec_lane,
        "primary_gap": primary,
        "semantic_hold_gaps": list(SEMANTIC_HOLD_GAPS),
        "lane_policy_refs": {
            "auto_execute_allowed": policy.get("auto_execute_allowed"),
            "requires_human_approval_before_apply": policy.get("requires_human_approval_before_apply"),
        },
    }


def validate_human_decision_consistency(gap: dict | None, lane: dict) -> list[str]:
    """정규화 이후 불변식 검사 (이슈 #12 INV-1~3). 위반은 invalid desk output이다.

    INV-1/2: semantic hold(lane==HOLD_FOR_HUMAN 또는 semantic-hold gap) → true.
    INV-3: semantic hold 아님 → false. approval/auto_execute policy는 이 판정과 독립(INV-4/5).
    """
    p: list[str] = []
    rec_lane = lane.get("recommended_next_lane")
    primary = (gap or {}).get("primary_gap")
    semantic_hold = rec_lane == "HOLD_FOR_HUMAN" or primary in SEMANTIC_HOLD_GAPS
    hd = lane.get("human_decision_required")
    if semantic_hold and hd is not True:
        p.append(f"INV-1/2 위반: semantic hold(lane={rec_lane}, gap={primary})인데 "
                 f"human_decision_required={hd}")
    if not semantic_hold and hd is not False:
        p.append(f"INV-3 위반: semantic hold 아님(lane={rec_lane}, gap={primary})인데 "
                 f"human_decision_required={hd}")
    return p


def validate_against_hard_blockers(stage_label: dict, hard_blocker_result: dict) -> list[str]:
    """Gemma judge는 hard blocker를 넘을 수 없다 (§6). 위반은 invalid output이다."""
    p: list[str] = []
    stage = stage_label.get("stage")
    max_stage = hard_blocker_result.get("max_stage")
    if stage == "ARCHIVE":
        return p  # ARCHIVE는 사다리 밖
    if hard_blocker_result.get("product_candidate_blocked") and stage == "PRODUCT_CANDIDATE":
        p.append("hard blocker가 PRODUCT_CANDIDATE를 금지하는데 stage=PRODUCT_CANDIDATE")
    if max_stage in STAGE_RANK and stage in STAGE_RANK and STAGE_RANK[stage] > STAGE_RANK[max_stage]:
        p.append(f"stage={stage}가 hard blocker 상한({max_stage})을 초과")
    return p


# ---------------------------------------------------------------- Schema Repair Pass (§11)

def _normalize_enum_case(obj):
    """enum 표기 대소문자만 정규화한다 — 의미(값 자체)는 바꾸지 않는다."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in _ENUM_FIELDS and isinstance(v, str) and v not in _ENUM_FIELDS[k]:
                upper = v.strip().upper().replace("-", "_").replace(" ", "_")
                lower = v.strip().lower()
                if upper in _ENUM_FIELDS[k]:
                    v = upper
                elif lower in _ENUM_FIELDS[k]:
                    v = lower
            out[k] = _normalize_enum_case(v)
        return out
    if isinstance(obj, list):
        return [_normalize_enum_case(v) for v in obj]
    return obj


def _repair_json_text(text: str):
    """JSON 괄호/쉼표/따옴표/코드펜스만 고쳐 파싱을 시도한다. 내용은 손대지 않는다."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    start, end = t.find("{"), t.rfind("}")
    if start >= 0 and end > start:
        t = t[start:end + 1]
    t = re.sub(r",\s*([}\]])", r"\1", t)  # trailing comma 제거
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    # 마지막 시도: 닫는 괄호 보충
    opens, closes = t.count("{"), t.count("}")
    if opens > closes:
        try:
            return json.loads(t + "}" * (opens - closes))
        except json.JSONDecodeError:
            return None
    return None


def _meaning_snapshot(obj) -> dict:
    """의미 변경 감지용 판단 필드 스냅샷 (대소문자 무시)."""
    snap = {}

    def walk(o, path=""):
        if isinstance(o, dict):
            for k, v in o.items():
                p = f"{path}.{k}" if path else k
                if k in _MEANING_FIELDS and isinstance(v, (str, bool)):
                    snap[p] = str(v).strip().lower().replace("-", "_").replace(" ", "_")
                elif k == "evidence_refs" and isinstance(v, list):
                    snap[p] = sorted(str(x).strip().lower() for x in v)
                walk(v, p)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")

    walk(obj)
    return snap


def schema_repair_pass(raw, schema_name: str, model_cls: type[BaseModel]) -> dict:
    """schema validation 실패 시 1회 허용되는 구조 수리 (§11).

    허용: JSON 문법 수정, wrapping 보정, enum 대소문자 정규화.
    금지: stage/primary_gap/lane/evidence_refs/hard blocker 의미 변경 — 감지 시 meaning_changed=True.
    """
    report = {
        "schema_name": schema_name, "used": True, "repairs": [],
        "meaning_changed": False, "repaired": False, "problems": [],
    }
    obj = raw
    if isinstance(obj, str):
        parsed = _repair_json_text(obj)
        if parsed is None:
            report["problems"].append("JSON 문법 수리 실패")
            return {**report, "model": None}
        report["repairs"].append("JSON 괄호/쉼표/코드펜스 수리")
        obj = parsed
    # 배열/객체 wrapping 보정
    if isinstance(obj, list) and len(obj) == 1 and isinstance(obj[0], dict):
        obj = obj[0]
        report["repairs"].append("단일 원소 배열 wrapping 제거")
    if isinstance(obj, dict) and len(obj) == 1 and isinstance(next(iter(obj.values())), dict) \
            and next(iter(obj.keys())) in (schema_name, "output", "result", "data"):
        obj = next(iter(obj.values()))
        report["repairs"].append("불필요한 최상위 wrapping key 제거")
    if not isinstance(obj, dict):
        report["problems"].append("객체로 복구 불가")
        return {**report, "model": None}

    before = _meaning_snapshot(obj)
    repaired = _normalize_enum_case(obj)
    if repaired != obj:
        report["repairs"].append("enum 표기 대소문자 정규화")
    after = _meaning_snapshot(repaired)
    if before != after:
        # 정규화 스냅샷 기준으로 값이 달라졌다면 의미가 바뀐 것 (§11 금지)
        report["meaning_changed"] = True
        report["problems"].append("schema repair 중 판단 필드 의미 변경 감지")
        return {**report, "model": None}

    model, problems = validate_desk_output(schema_name, repaired, model_cls)
    report["problems"] += problems
    report["repaired"] = model is not None
    return {**report, "model": model, "raw": repaired}


def classify_desk_failure(problems: list[str]) -> str:
    """검증 실패를 §23 실패 분류로 매핑한다.

    schema 문제(parse/required/enum/type)는 INVALID_OUTPUT, refs 날조/부족은 EVIDENCE_INSUFFICIENT.
    """
    joined = " ".join(problems)
    if "날조" in joined or "evidence_refs" in joined and "최소" in joined:
        return AUTOPILOT_EVIDENCE_INSUFFICIENT
    return AUTOPILOT_INVALID_OUTPUT


def write_schema_files(schema_dir) -> list[str]:
    """desk 스키마를 review/phase2d0/schemas/*.schema.json으로 기록한다 (§28)."""
    from pathlib import Path

    schema_dir = Path(schema_dir)
    schema_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in DESK_SCHEMAS.items():
        if name == "unified_decision_packet":
            continue
        if model is None:  # auto_order_quality_report — 코드 생성물 스키마
            schema = {
                "title": "auto_order_quality_report",
                "type": "object",
                "required": ["auto_order_quality_score", "checks", "passed", "total", "status"],
                "properties": {
                    "auto_order_quality_score": {"type": "number"},
                    "checks": {"type": "object"},
                    "passed": {"type": "integer"},
                    "total": {"type": "integer"},
                    "status": {"enum": ["PASS", "HOLD_FOR_HUMAN"]},
                },
            }
        else:
            schema = model.model_json_schema()
        path = schema_dir / f"{name}.schema.json"
        path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(path.name)
    # unified packet schema도 기록 (§20)
    path = schema_dir / "unified_decision_packet.schema.json"
    path.write_text(json.dumps(UnifiedDecisionPacket.model_json_schema(), ensure_ascii=False, indent=2),
                    encoding="utf-8")
    written.append(path.name)
    return written
