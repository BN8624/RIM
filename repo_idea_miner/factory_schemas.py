# Product Factory 산출물(Desk 출력·manifest·contract·verdict)을 검증하는 Pydantic 스키마와 승격 규칙 모듈.
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------- 라벨/상수

PRODUCT_VERDICT_LABELS = (
    "PROMOTE_TO_CODEX",
    "KEEP_CANDIDATE",
    "NEEDS_MORE_GEMMA_LOOP",
    "TOO_WEAK",
    "DROP",
    # Phase 1.6 Core-first Harness verdict (§11.4)
    "REVIEW_READY",
    "RUNS_BUT_WEAK",
)

# §15 Dashboard 버튼 매핑: verdict → 추천 버튼
VERDICT_TO_RECOMMENDED_ACTION = {
    "PROMOTE_TO_CODEX": "productize",
    "KEEP_CANDIDATE": "keep",
    "NEEDS_MORE_GEMMA_LOOP": "retry",
    "TOO_WEAK": "archive",
    "DROP": "drop",
    "REVIEW_READY": "keep",
    "RUNS_BUT_WEAK": "archive",
}

# Dashboard 사람 버튼 (§17)
PRODUCT_OWNER_DECISIONS = ("keep", "drop", "productize", "retry", "archive")

PRODUCT_RUN_STATUSES = ("pending", "running", "done", "error")

# Desk 진행 순서 (§4). Debug Desk는 gate 실패 시에만 진입한다.
FACTORY_STAGES = (
    "promotion_gate",
    "planning",
    "ux_spec",
    "technical_spec",
    "build",
    "static_gate",
    "contract_gate",
    "syntax_gate",
    "smoke_gate",
    "debug",
    "qa",
    "judge",
    "final_artifact",
)


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------- Manifest / Contract


class ManifestFile(_Base):
    path: str = Field(min_length=1)
    role: str = Field(min_length=1)


class Manifest(_Base):
    project_type: Literal["static_web", "python_cli", "node_cli"] = "static_web"
    entrypoint: str = Field(min_length=1)
    run_command: str = Field(min_length=1)
    install_command: str | None = None
    check_commands: list[str] = Field(default_factory=list)
    files: list[ManifestFile] = Field(min_length=1)
    forbidden_files: list[str] = Field(default_factory=list)

    def file_paths(self) -> list[str]:
        return [f.path for f in self.files]


class ContractConnection(_Base):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)


class ContractModule(_Base):
    path: str = Field(min_length=1)
    role: str = Field(min_length=1)


class AnchorRequirement(_Base):
    anchor: str = Field(min_length=1)
    expected_files: list[str] = Field(min_length=1)
    expected_markers: list[str] = Field(default_factory=list)


class Contract(_Base):
    entrypoint: str = Field(min_length=1)
    required_files: list[str] = Field(min_length=1)
    connections: list[ContractConnection] = Field(default_factory=list)
    modules: list[ContractModule] = Field(min_length=1)
    state_model: str = Field(min_length=1)
    core_interactions: list[str] = Field(min_length=1)
    difficulty_anchor_requirements: list[AnchorRequirement] = Field(min_length=1)
    forbidden_simplification_rules: list[str] = Field(min_length=1)


# ---------------------------------------------------------------- Desk 출력


class ProductBrief(_Base):
    product_goal: str = Field(min_length=1)
    target_user: str = Field(min_length=1)
    core_loop: str = Field(min_length=1)
    first_screen_goal: str = Field(min_length=1)
    can_reduce: list[str] = Field(min_length=1)
    must_not_reduce: list[str] = Field(min_length=1)


class ScreenSpec(_Base):
    name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    elements: list[str] = Field(min_length=1)


class StateTransition(_Base):
    trigger: str = Field(min_length=1)
    from_state: str = Field(min_length=1)
    to_state: str = Field(min_length=1)
    effect: str = Field(min_length=1)


class UXFlow(_Base):
    first_screen: str = Field(min_length=1)
    screens: list[str] = Field(min_length=1)
    user_actions: list[str] = Field(min_length=1)
    state_changes: list[str] = Field(min_length=1)
    success_screen: str = Field(min_length=1)
    failure_screen: str = Field(min_length=1)
    thirty_second_demo: str = Field(min_length=1)


class UXSpec(_Base):
    ux_flow: UXFlow
    screen_spec: list[ScreenSpec] = Field(min_length=1)
    state_transitions: list[StateTransition] = Field(min_length=1)


class TechnicalSpec(_Base):
    technical_plan: str = Field(min_length=1)
    manifest: Manifest
    contract: Contract
    build_task_packet: str = Field(min_length=1)


class FileEntry(_Base):
    path: str = Field(min_length=1)
    content: str


class BuildOutput(_Base):
    files: list[FileEntry] = Field(min_length=1)
    build_report: str = Field(min_length=1)


class DebugOutput(_Base):
    files: list[FileEntry] = Field(min_length=1)
    debug_report: str = Field(min_length=1)


class QAAnchorCheck(_Base):
    anchor: str = Field(min_length=1)
    alive: bool
    evidence: str = Field(min_length=1)


class QAForbiddenCheck(_Base):
    rule: str = Field(min_length=1)
    violated: bool
    evidence: str = Field(min_length=1)


class QAOutput(_Base):
    anchors: list[QAAnchorCheck] = Field(min_length=1)
    forbidden: list[QAForbiddenCheck] = Field(min_length=1)
    is_degenerate: bool  # 단순 TODO/검색창/정적 대시보드로 퇴화했는가
    degeneration_reason: str = Field(min_length=1)
    has_user_action: bool
    has_state_change: bool
    has_runnable_artifact: bool
    summary: str = Field(min_length=1)

    def qa_pass(self) -> bool:
        return (
            all(a.alive for a in self.anchors)
            and not any(f.violated for f in self.forbidden)
            and not self.is_degenerate
            and self.has_user_action
            and self.has_state_change
            and self.has_runnable_artifact
        )


class JudgeOutput(_Base):
    verdict: Literal[
        "PROMOTE_TO_CODEX",
        "KEEP_CANDIDATE",
        "NEEDS_MORE_GEMMA_LOOP",
        "TOO_WEAK",
        "DROP",
    ]
    reasons: list[str] = Field(min_length=1)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    next_goal: str = Field(min_length=1)


# ---------------------------------------------------------------- Auto Promotion Gate (§6)


def promotion_line(card: dict, owner_clarity_score: int | None = None) -> tuple[str | None, list[str]]:
    """Challenge Card dict를 보고 진입 라인을 결정한다.

    반환: ("standard" | "micro" | None, 판단 근거 목록).
    - GOOD_CHALLENGE → standard 라인 (§6.1)
    - STEAL_ONLY → micro-workspace 라인 (§6.2)
    - TOO_EASY/TOO_BIG/UNCLEAR_TO_OWNER/DROP/NOT_MY_TASTE → 진입 안 함 (§6.3)
    """
    reasons: list[str] = []
    label = card.get("final_label")
    scores = card.get("scores") or {}
    anchors = card.get("difficulty_anchors") or []
    forbidden = card.get("forbidden_simplifications") or []
    clarity = owner_clarity_score if owner_clarity_score is not None else scores.get("owner_clarity", 0)

    def _score(name: str) -> int:
        v = scores.get(name)
        return int(v) if v is not None else 0

    if label == "GOOD_CHALLENGE":
        checks = [
            (clarity >= 3, f"owner_clarity_score {clarity} >= 3"),
            (_score("difficulty_anchor_alive") >= 4, f"difficulty_anchor_alive {_score('difficulty_anchor_alive')} >= 4"),
            (_score("not_too_easy") >= 4, f"not_too_easy {_score('not_too_easy')} >= 4"),
            (_score("immediate_demo_value") >= 3, f"immediate_demo_value {_score('immediate_demo_value')} >= 3"),
            (len(anchors) >= 2, f"difficulty_anchors {len(anchors)}개 >= 2"),
            (len(forbidden) >= 2, f"forbidden_simplifications {len(forbidden)}개 >= 2"),
        ]
        failed = [msg for ok, msg in checks if not ok]
        if failed:
            reasons.append("GOOD_CHALLENGE 승격 기준 미달: " + "; ".join(failed))
            return None, reasons
        reasons.append("GOOD_CHALLENGE 승격 기준 충족 → standard 라인")
        return "standard", reasons

    if label == "STEAL_ONLY":
        checks = [
            (clarity >= 3, f"owner_clarity_score {clarity} >= 3"),
            (_score("difficulty_anchor_alive") >= 3, f"difficulty_anchor_alive {_score('difficulty_anchor_alive')} >= 3"),
            (_score("immediate_demo_value") >= 3, f"immediate_demo_value {_score('immediate_demo_value')} >= 3"),
            (len(anchors) >= 1, f"difficulty_anchors {len(anchors)}개 >= 1"),
            (len(forbidden) >= 1, f"forbidden_simplifications {len(forbidden)}개 >= 1"),
        ]
        failed = [msg for ok, msg in checks if not ok]
        if failed:
            reasons.append("STEAL_ONLY 승격 기준 미달: " + "; ".join(failed))
            return None, reasons
        reasons.append("STEAL_ONLY 승격 기준 충족 → micro-workspace 라인")
        return "micro", reasons

    reasons.append(f"라벨 {label}은 자동 승격 대상이 아님 (§6.3)")
    return None, reasons


# ---------------------------------------------------------------- Codex/Claude 승격 조건 (§16)


def codex_promotion_problems(gate_summary: dict, qa: QAOutput | None, debug_history_exists: bool) -> list[str]:
    """PROMOTE_TO_CODEX 최소 조건(§16)을 검사해 미충족 항목을 반환한다. 비어 있으면 승격 가능."""
    problems: list[str] = []
    for gate, label in (
        ("static", "필수 파일 존재 검사(static gate)"),
        ("syntax", "문법 검사(syntax gate)"),
        ("contract", "파일 연결 계약(contract gate)"),
        ("smoke", "기본 실행/smoke check"),
    ):
        if not gate_summary.get(gate):
            problems.append(f"{label} 미통과")
    if qa is None:
        problems.append("qa_report 없음")
    else:
        if not all(a.alive for a in qa.anchors):
            problems.append("Difficulty Anchors가 qa_report에서 확인되지 않음")
        if any(f.violated for f in qa.forbidden):
            problems.append("Forbidden Simplifications 위반 존재")
        if not (qa.has_user_action and qa.has_state_change):
            problems.append("핵심 상호작용/상태 변화가 코드에 없음")
    if not debug_history_exists:
        problems.append("debug loop 기록(debug_history.jsonl) 없음")
    return problems
