# Phase 1.6 Core-first Harness 스키마: core contract/scenario/golden/review 구조와 verdict·승격 규칙 모듈.
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------- 상수 (§5.6, §11.4)

ARTIFACT_CLASSES = (
    "RULE_ENGINE",
    "SIMULATION_ENGINE",
    "WORKFLOW_ENGINE",
    "DATA_TRANSFORM_ENGINE",
    "PLANNER_EVALUATOR",
    "INTERACTIVE_TOOL",
    "VIEWER_ONLY",
)

CORE_VERDICT_LABELS = (
    "REVIEW_READY",
    "NEEDS_MORE_GEMMA_LOOP",
    "RUNS_BUT_WEAK",
    "KEEP_CANDIDATE",
    "DROP",
    "PROMOTE_TO_CODEX",
)

COMPARISON_MODES = ("exact", "partial", "invariant", "review")

SCENARIO_CASE_TYPES = ("normal", "boundary", "invalid")

# Review-Repair 제한 (§5.10, §6.9, §9.5, §10.5)
MAX_CORE_CONTRACT_REPAIR_ATTEMPTS = 1
MAX_SCENARIO_GOLDEN_REPAIR_ATTEMPTS = 1
MAX_PATCH_ATTEMPTS = 2
MAX_PRODUCT_LAYER_REPAIR_ATTEMPTS = 1

# Runner 필수 출력 필드 (§8.4)
RUNNER_REQUIRED_OUTPUT_FIELDS = ("ok", "final_state", "events", "summary", "errors")

# 7개 Stage (§4)
CORE_STAGES = (
    "core_spec",
    "scenario_oracle",
    "core_build",
    "core_verification",
    "repair",
    "product_layer",
    "verdict",
)

# 핵심 gate 목록 (§8.2)
CORE_GATE_ORDER = (
    "core_contract",
    "runner",
    "scenario_replay",
    "golden_output",
    "state_invariant",
    "determinism",
    "anti_hardcode",
)

# verdict → Dashboard 추천 버튼 (기존 PRODUCT_OWNER_DECISIONS 재사용)
CORE_VERDICT_TO_RECOMMENDED_ACTION = {
    "PROMOTE_TO_CODEX": "productize",
    "REVIEW_READY": "keep",
    "KEEP_CANDIDATE": "keep",
    "NEEDS_MORE_GEMMA_LOOP": "retry",
    "RUNS_BUT_WEAK": "archive",
    "DROP": "drop",
}


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------- Stage 1: Core Spec (§5)


class NormalizedChallenge(_Base):
    challenge_id: str = ""
    title: str = Field(min_length=1)
    core_problem: str = Field(min_length=1)
    expected_artifact: str = Field(min_length=1)
    difficulty_anchors: list[str] = Field(default_factory=list)
    forbidden_simplifications: list[str] = Field(default_factory=list)
    success_conditions: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    owner_clarity: int = 0


class CoreArtifactClassification(_Base):
    artifact_class: Literal[
        "RULE_ENGINE",
        "SIMULATION_ENGINE",
        "WORKFLOW_ENGINE",
        "DATA_TRANSFORM_ENGINE",
        "PLANNER_EVALUATOR",
        "INTERACTIVE_TOOL",
        "VIEWER_ONLY",
    ]
    reason: str = Field(min_length=1)
    core_first: bool = True
    runner_required: bool = True
    golden_required: bool = True
    product_layer_required: bool = True


class StateEntity(_Base):
    name: str = Field(min_length=1)
    fields: list[str] = Field(default_factory=list)
    invariants: list[str] = Field(default_factory=list)


class CoreAction(_Base):
    name: str = Field(min_length=1)
    input: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    state_change: list[str] = Field(default_factory=list)
    output: list[str] = Field(default_factory=list)


class Determinism(_Base):
    random_allowed: bool = False
    seed_required: bool = True


class CoreContract(_Base):
    artifact_class: str = Field(min_length=1)
    core_goal: str = Field(min_length=1)
    state_entities: list[StateEntity] = Field(min_length=1)
    actions: list[CoreAction] = Field(min_length=1)
    determinism: Determinism = Field(default_factory=Determinism)
    forbidden_shortcuts: list[str] = Field(default_factory=list)


class RunnerContract(_Base):
    runner_command: str = Field(min_length=1)
    input_format: str = "scenario_json"
    output_format: str = "json"
    required_output_fields: list[str] = Field(
        default_factory=lambda: list(RUNNER_REQUIRED_OUTPUT_FIELDS)
    )


class CoreContractDraft(_Base):
    """Core Contract Draft/Repair desk 출력: core + runner contract 묶음."""

    core_contract: CoreContract
    runner_contract: RunnerContract


class SpecReview(_Base):
    """계약 기반 리뷰 결과 (§5.10)."""

    status: Literal["PASS", "NEEDS_REPAIR", "FAIL"]
    blocking_issues: list[str] = Field(default_factory=list)
    repair_instructions: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"


# ---------------------------------------------------------------- Stage 2: Scenario Oracle (§6)


class ScenarioAction(_Base):
    type: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)


class Scenario(_Base):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    case_type: Literal["normal", "boundary", "invalid"] = "normal"
    initial_state: dict = Field(default_factory=dict)
    actions: list[ScenarioAction] = Field(default_factory=list)
    expected_behavior: list[str] = Field(default_factory=list)
    must_check: list[str] = Field(default_factory=list)


class GoldenExpected(_Base):
    scenario_id: str = Field(min_length=1)
    expected_final_state: dict = Field(default_factory=dict)
    expected_events: list = Field(default_factory=list)
    expected_summary: str = ""
    comparison_mode: Literal["exact", "partial", "invariant", "review"] = "exact"


class OracleRiskReport(_Base):
    golden_source: Literal["model_generated", "deterministic_oracle", "human_seeded"] = (
        "model_generated"
    )
    risk_level: Literal["low", "medium", "high"] = "medium"
    risk_reasons: list[str] = Field(default_factory=list)
    safe_for_auto_gate: bool = True
    requires_human_review: bool = False


class ScenarioGoldenOutput(_Base):
    scenarios: list[Scenario] = Field(min_length=1)
    goldens: list[GoldenExpected] = Field(min_length=1)
    oracle_risk: OracleRiskReport = Field(default_factory=OracleRiskReport)


class ScenarioGoldenReview(_Base):
    status: Literal["PASS", "NEEDS_REPAIR", "FAIL"]
    blocking_issues: list[str] = Field(default_factory=list)
    repair_instructions: list[str] = Field(default_factory=list)
    golden_strength: Literal["strong", "medium", "weak"] = "medium"
    safe_for_auto_gate: bool = True


def scenario_case_type_problems(scenarios: list[Scenario]) -> list[str]:
    """§6.4 최소 조건: 정상/경계/실패 케이스가 각 1개 이상인지 검사한다."""
    problems: list[str] = []
    types = {s.case_type for s in scenarios}
    for required, label in (("normal", "정상"), ("boundary", "경계"), ("invalid", "실패/무효")):
        if required not in types:
            problems.append(f"{label} 케이스({required}) 없음")
    return problems


# ---------------------------------------------------------------- Stage 3/5/6: Build / Repair / Product Layer


class CoreFileEntry(_Base):
    path: str = Field(min_length=1)
    content: str


class CoreBuildOutput(_Base):
    files: list[CoreFileEntry] = Field(min_length=1)
    build_report: str = Field(min_length=1)


class BuildReview(_Base):
    """Gate 결과 기반 Build Review (§9.4)."""

    status: Literal["PASS", "NEEDS_PATCH", "FAIL"]
    blocking_issues: list[str] = Field(default_factory=list)
    patch_instructions: list[str] = Field(default_factory=list)
    failed_scenarios: list[str] = Field(default_factory=list)
    hardcode_risk: Literal["low", "medium", "high"] = "low"
    patchable: bool = True
    next_goal: str = ""


class PatchOutput(_Base):
    files: list[CoreFileEntry] = Field(min_length=1)
    patch_report: str = Field(min_length=1)


class ProductLayerOutput(_Base):
    files: list[CoreFileEntry] = Field(min_length=1)
    product_report: str = Field(min_length=1)


class ProductLayerReview(_Base):
    status: Literal["PASS", "NEEDS_REPAIR", "FAIL"]
    blocking_issues: list[str] = Field(default_factory=list)
    repair_instructions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- 후보 수 정책 (§2.4, §7.7, §13)


def effective_candidates(mode: str, requested: int | None) -> tuple[int, list[str]]:
    """--candidates 정책: live 기본 1, mock 1~2 허용. (유효 후보 수, 조정 사유) 반환."""
    notes: list[str] = []
    n = requested if requested is not None else 1
    if n < 1:
        notes.append(f"candidates {n} < 1 → 1로 보정")
        n = 1
    if mode == "live" and n > 1:
        notes.append(f"live 기본 candidates=1 정책으로 {n} → 1 보정 (§2.4)")
        n = 1
    if mode != "live" and n > 2:
        notes.append(f"mock candidates 최대 2 정책으로 {n} → 2 보정 (§2.4)")
        n = 2
    return n, notes


# ---------------------------------------------------------------- Golden 강도 정책 (§6.7)


def golden_mode_stats(goldens: list[dict]) -> dict:
    """golden 목록에서 comparison_mode 분포와 exact 개수를 계산한다."""
    modes: dict[str, int] = {m: 0 for m in COMPARISON_MODES}
    for g in goldens:
        mode = g.get("comparison_mode") or "exact"
        if mode in modes:
            modes[mode] += 1
    return {
        "modes": modes,
        "total": len(goldens),
        "exact_count": modes["exact"],
        "auto_gate_count": modes["exact"] + modes["partial"] + modes["invariant"],
        "review_count": modes["review"],
    }


# ---------------------------------------------------------------- PROMOTE_TO_CODEX 금지 조건 (§11.9)


def promote_to_codex_problems(
    gate_summary: dict,
    exact_golden_count: int,
    oracle_risk_level: str,
    hardcode_risk: str,
    artifact_class: str,
    product_layer_status: str,
    golden_total: int = 0,
    review_golden_count: int = 0,
) -> list[str]:
    """PROMOTE_TO_CODEX 금지 조건(§6.7, §11.9)을 검사한다. 비어 있으면 승격 가능."""
    problems: list[str] = []
    for gate, label in (
        ("core_contract", "core contract gate"),
        ("runner", "runner gate"),
        ("scenario_replay", "scenario replay gate"),
        ("golden_output", "golden output gate"),
        ("state_invariant", "state invariant gate"),
        ("determinism", "determinism gate"),
        ("anti_hardcode", "anti-hardcode gate"),
    ):
        if not gate_summary.get(gate):
            problems.append(f"{label} 미통과")
    if exact_golden_count < 1:
        problems.append("exact golden 0개 (§6.7: PROMOTE_TO_CODEX 금지)")
    if oracle_risk_level == "high":
        problems.append("oracle risk high (§6.7: PROMOTE_TO_CODEX 금지)")
    if hardcode_risk == "high":
        problems.append("hardcode risk high (§11.9 금지)")
    if artifact_class == "VIEWER_ONLY":
        problems.append("viewer-only 산출물 (§11.9 금지)")
    if product_layer_status != "PASS":
        problems.append("product layer review 미통과")
    if golden_total > 0 and review_golden_count == golden_total:
        problems.append("comparison_mode=review에만 의존 (§11.9 금지)")
    return problems


# ---------------------------------------------------------------- Live Validation 정직성 검사 (Phase 1.6b §9)


def verdict_consistency(
    verdict: str,
    gate_summary: dict,
    hardcode_risk: str,
    product_layer_status: str,
    has_state_transitions: bool,
    scenario_count: int,
) -> tuple[bool, list[str]]:
    """verdict가 gate 증거와 논리적으로 일치하는지 검사한다(정직성 heuristic, §2, §9).

    "약한데 REVIEW_READY" 같은 부정직한 판정을 자동으로 잡아낸다. 반환: (일치 여부, 불일치 사유).
    """
    issues: list[str] = []
    all_pass = all(gate_summary.get(g) for g in CORE_GATE_ORDER)
    good_verdicts = ("REVIEW_READY", "PROMOTE_TO_CODEX")
    if verdict in good_verdicts and not all_pass:
        failed = [g for g in CORE_GATE_ORDER if not gate_summary.get(g)]
        issues.append(f"{verdict}인데 gate 일부 실패: {', '.join(failed)}")
    if verdict in good_verdicts and product_layer_status != "PASS":
        issues.append(f"{verdict}인데 product layer 미통과({product_layer_status})")
    if verdict == "PROMOTE_TO_CODEX" and hardcode_risk == "high":
        issues.append("PROMOTE_TO_CODEX인데 hardcode risk high")
    if verdict != "DROP" and not gate_summary.get("runner"):
        issues.append("runner 실패인데 DROP이 아님")
    if verdict != "DROP" and not has_state_transitions:
        issues.append("state transition 없는데 DROP이 아님")
    if verdict in good_verdicts and scenario_count < 3:
        issues.append(f"{verdict}인데 scenario 빈약({scenario_count} < 3)")
    return (not issues), issues


def build_live_validation_summary(
    challenge_id,
    run_id,
    verdict: str,
    gate_summary: dict,
    hardcode_risk: str,
    product_layer_status: str,
    has_state_transitions: bool,
    scenario_count: int,
    gate_hardening_applied: list[str],
) -> dict:
    """§9 live_validation 판정 검증표를 만든다. verdict_is_honest는 gate 증거 일치 heuristic."""
    honest, issues = verdict_consistency(
        verdict, gate_summary, hardcode_risk, product_layer_status,
        has_state_transitions, scenario_count,
    )
    all_pass = all(gate_summary.get(g) for g in CORE_GATE_ORDER)
    # overrated: 증거보다 verdict가 높음 / underrated: 전 gate 통과인데 DROP·WEAK
    overrated = (not honest) and verdict in ("REVIEW_READY", "PROMOTE_TO_CODEX", "KEEP_CANDIDATE")
    underrated = all_pass and product_layer_status == "PASS" and verdict in ("DROP", "RUNS_BUT_WEAK")
    return {
        "live_validation": {
            "challenge_id": str(challenge_id) if challenge_id is not None else "",
            "run_id": run_id,
            "verdict": verdict,
            "verdict_is_honest": honest,
            "overrated": overrated,
            "underrated": underrated,
            "issues_found": issues,
            "gate_hardening_applied": gate_hardening_applied,
        }
    }


# ---------------------------------------------------------------- Verdict 판정 (§11)


def decide_core_verdict(
    gate_summary: dict,
    gate_problems: dict,
    artifact_class: str,
    scenario_count: int,
    replay_failed: list[str],
    golden_failed: list[str],
    exact_golden_count: int,
    golden_stats: dict,
    oracle_risk_level: str,
    hardcode_risk: str,
    product_layer_status: str,
    golden_strength: str,
    patchable: bool,
    next_goal: str,
    has_state_transitions: bool,
) -> tuple[str, list[str]]:
    """core-system harness 결과로 verdict를 판정한다 (§11.5~§11.9).

    반환: (verdict, 판정 근거 목록). PROMOTE_TO_CODEX는 매우 보수적으로만 준다.
    """
    reasons: list[str] = []
    runner_ok = bool(gate_summary.get("runner"))
    contract_ok = bool(gate_summary.get("core_contract"))
    replay_ok = bool(gate_summary.get("scenario_replay"))
    all_gates_ok = all(gate_summary.get(g) for g in CORE_GATE_ORDER)

    # DROP (§11.8): runner 없음 / core contract 붕괴 / replay 전멸 / hardcode 심각 / 상태 전이 없음
    replay_total_fail = scenario_count > 0 and len(replay_failed) >= scenario_count
    if not runner_ok:
        reasons.append("runner 실행 불가: " + "; ".join(gate_problems.get("runner", []))[:200])
        return "DROP", reasons
    if not contract_ok:
        reasons.append("core contract 붕괴: " + "; ".join(gate_problems.get("core_contract", []))[:200])
        return "DROP", reasons
    if replay_total_fail:
        reasons.append(f"scenario replay 전부 실패 ({len(replay_failed)}/{scenario_count})")
        return "DROP", reasons
    if hardcode_risk == "high":
        reasons.append("hardcode/stub 심각 (anti-hardcode high)")
        return "DROP", reasons
    if not has_state_transitions:
        reasons.append("state transition 없음")
        return "DROP", reasons

    # RUNS_BUT_WEAK (§11.7): 실행은 되지만 core system이 약함
    review_only = golden_stats.get("total", 0) > 0 and golden_stats.get("auto_gate_count", 0) == 0
    if artifact_class == "VIEWER_ONLY":
        reasons.append("viewer-only 산출물: core system 성장 가치 낮음")
        return "RUNS_BUT_WEAK", reasons
    if scenario_count < 3:
        reasons.append(f"scenario 빈약 ({scenario_count}개 < 3)")
        return "RUNS_BUT_WEAK", reasons
    if review_only:
        reasons.append("golden이 전부 review 모드 → 자동 검증 불가")
        return "RUNS_BUT_WEAK", reasons

    # NEEDS_MORE_GEMMA_LOOP (§11.6): core 구조는 맞고 일부 실패, patch/delta로 개선 가능
    if not all_gates_ok:
        failed_gates = [g for g in CORE_GATE_ORDER if not gate_summary.get(g)]
        if patchable and next_goal:
            reasons.append(
                f"core 구조는 유지, gate 일부 실패({', '.join(failed_gates)}) → patch/delta 개선 가능"
            )
            return "NEEDS_MORE_GEMMA_LOOP", reasons
        reasons.append(f"gate 실패({', '.join(failed_gates)})이며 patch 불가 판단")
        return "RUNS_BUT_WEAK", reasons

    # 여기부터 core gates 전부 통과
    if product_layer_status != "PASS":
        reasons.append("core 검증은 통과했으나 product layer review 미통과")
        return "KEEP_CANDIDATE", reasons

    # PROMOTE_TO_CODEX (§11.9): 매우 보수적 — 전 gate 통과 + 전부 exact golden + 낮은 위험
    promote_ready = (
        exact_golden_count >= 1
        and golden_stats.get("total", 0) > 0
        and golden_stats.get("exact_count", 0) == golden_stats.get("total", 0)
        and oracle_risk_level == "low"
        and hardcode_risk == "low"
        and golden_strength == "strong"
    )
    if promote_ready:
        guard = promote_to_codex_problems(
            gate_summary, exact_golden_count, oracle_risk_level, hardcode_risk,
            artifact_class, product_layer_status,
            golden_total=golden_stats.get("total", 0),
            review_golden_count=golden_stats.get("review_count", 0),
        )
        if not guard:
            reasons.append("전 gate 통과 + 전부 exact golden + oracle/hardcode 위험 낮음 + strong golden")
            return "PROMOTE_TO_CODEX", reasons

    reasons.append("core system 검증 통과 + product layer 동작 → 사용자 검수 가능")
    if oracle_risk_level != "low":
        reasons.append(f"oracle risk {oracle_risk_level} → 검수 시 golden 신뢰도 확인 필요 (§6.7)")
    return "REVIEW_READY", reasons
