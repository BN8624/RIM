# worker JSON 출력을 검증하는 Pydantic 모델 정의 모듈.
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VERDICTS = ("KEEP", "MAYBE", "DROP")
RISK_LEVELS = ("low", "medium", "high", "unknown", "not_collected")
APPLICATION_AREAS = (
    "코딩 하네스/검증",
    "아이디어 채굴",
    "업무 자동화/OCR",
    "게임 시뮬레이션/뷰어",
    "문서/카드 UI",
    "적용 부적합",
)


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class BouncerOutput(_Base):
    bouncer_decision: Literal["PROCEED", "FAST_DROP", "UNCERTAIN_PROCEED"]
    fast_drop: bool
    reason: str = Field(min_length=1)


class ReadmeScoutOutput(_Base):
    claimed_core_value: str
    readme_attractions: list[str]
    overclaim_risks: list[str]
    unverifiable_points: list[str]


class PainScoutOutput(_Base):
    user_pain: list[str]
    feature_requests: list[str]
    workflow_pain: list[str]
    noise_issues: list[str]
    bike_shedding_notes: list[str]


class StructureRiskScoutOutput(_Base):
    implementation_weight: Literal["light", "medium", "heavy", "unknown"]
    runtime_risk_level: Literal["low", "medium", "high", "unknown", "not_collected"]
    runtime_risk_reason: str
    dev_vs_runtime_notes: list[str]
    pattern_poc_feasibility: Literal["가능", "불가능", "불확실"]


class DependencyRuntimeRisk(_Base):
    level: Literal["low", "medium", "high", "unknown", "not_collected"]
    reason: str


class Application(_Base):
    area: Literal[
        "코딩 하네스/검증",
        "아이디어 채굴",
        "업무 자동화/OCR",
        "게임 시뮬레이션/뷰어",
        "문서/카드 UI",
        "적용 부적합",
    ]
    related_project: str
    reason: str


class OneDayMvp(_Base):
    status: Literal["가능", "축소 불가", "불확실"]
    feature: str
    input: str
    output: str
    excluded_scope: list[str]
    reason: str


class PatternPoc(_Base):
    status: Literal["가능", "불가능", "불확실"]
    idea: str
    input: str
    output: str
    reason: str


class IssueSignalStats(_Base):
    sampled_issue_count: int = Field(ge=0)
    classified_issue_count: int = Field(ge=0)
    defect_count: int = Field(ge=0)
    feature_request_count: int = Field(ge=0)
    workflow_pain_count: int = Field(ge=0)
    confusion_count: int = Field(ge=0)
    install_env_version_count: int = Field(ge=0)
    noise_count: int = Field(ge=0)
    product_pain_count: int = Field(ge=0)
    confidence: Literal["low", "medium", "high"]


class JudgeOutput(_Base):
    verdict: Literal["KEEP", "MAYBE", "DROP"]
    fast_drop: bool
    score: int = Field(ge=0, le=10)
    one_line_conclusion: str = Field(min_length=1)
    why_people_cared: str
    user_pain: list[str]
    feature_requests: list[str]
    workflow_pain: list[str]
    core_pattern: str
    what_to_ignore: list[str]
    dependency_runtime_risk: DependencyRuntimeRisk
    application: Application
    one_day_mvp: OneDayMvp
    pattern_poc: PatternPoc
    issue_signal_stats: IssueSignalStats
    why_it_fails: list[str] = Field(min_length=1)
    why_drop_or_keep: list[str] = Field(min_length=1)
    next_action: str = Field(min_length=1)
    ceiling_rules_applied: list[str] = Field(default_factory=list)


WORKER_SCHEMAS = {
    "bouncer": BouncerOutput,
    "readme_scout": ReadmeScoutOutput,
    "pain_scout": PainScoutOutput,
    "structure_risk_scout": StructureRiskScoutOutput,
    "critic_judge": JudgeOutput,
}
