# Challenge Mode 산출물(ChallengePackage 등)을 검증하는 Pydantic 스키마와 자동 판정 규칙 모듈.
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CHALLENGE_LABELS = (
    "GOOD_CHALLENGE",
    "TOO_EASY",
    "TOO_BIG",
    "NOT_MY_TASTE",
    "STEAL_ONLY",
    "UNCLEAR_TO_OWNER",
    "DROP",
)

# challenge-search 정렬 우선순위 (§23): 낮을수록 상단
LABEL_PRIORITY = {
    "GOOD_CHALLENGE": 0,
    "STEAL_ONLY": 1,
    "NOT_MY_TASTE": 2,
    "TOO_BIG": 3,
    "UNCLEAR_TO_OWNER": 4,
    "TOO_EASY": 5,
    "DROP": 6,
}

OWNER_STATUSES = ("unseen", "saved", "maybe", "dropped", "build_next", "built")


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class OwnerBrief(_Base):
    source_repo: str = Field(min_length=1)
    what_is_this: str = Field(min_length=1)
    why_people_like_it: str = Field(min_length=1)
    what_we_steal: str = Field(min_length=1)
    what_screen_looks_like: str = Field(min_length=1)
    what_user_does: list[str] = Field(min_length=1)
    why_it_might_be_fun_or_useful: str = Field(min_length=1)
    how_it_differs_from_easy_version: str = Field(min_length=1)
    owner_clarity_score: int = Field(ge=1, le=5)
    owner_clarity_risk: str


class ScreenStory(_Base):
    first_screen: str = Field(min_length=1)
    user_actions: list[str] = Field(min_length=1)
    thirty_second_demo: str = Field(min_length=1)
    success_feeling: str = Field(min_length=1)
    failure_screen: str = Field(min_length=1)


class CoreInteraction(_Base):
    actor: str = Field(min_length=1)
    trigger: str = Field(min_length=1)
    loop: str = Field(min_length=1)
    reward: str = Field(min_length=1)
    state_change: str = Field(min_length=1)
    hard_part: str = Field(min_length=1)


class ChallengeScores(_Base):
    difficulty_anchor_alive: int = Field(ge=1, le=5)
    not_too_easy: int = Field(ge=1, le=5)
    buildable_in_one_day: int = Field(ge=1, le=5)
    visual_dependency_low: int = Field(ge=1, le=5)
    immediate_demo_value: int = Field(ge=1, le=5)
    owner_clarity: int = Field(ge=1, le=5)
    user_taste_fit: int = Field(ge=1, le=5)
    reuse_potential: int = Field(ge=1, le=5)

    def total(self) -> int:
        return sum(getattr(self, name) for name in type(self).model_fields)


class ChallengeCard(_Base):
    source_repo: str = Field(min_length=1)
    repo_summary: str = Field(min_length=1)

    surface_features: list[str] = Field(min_length=1)
    core_interaction: CoreInteraction

    difficulty_anchors: list[str] = Field(min_length=1)
    forbidden_simplifications: list[str] = Field(min_length=1)
    allowed_simplifications: list[str] = Field(default_factory=list)

    challenge_title: str = Field(min_length=1)
    one_line_challenge: str = Field(min_length=1)

    poc_30_min: str = Field(min_length=1)
    build_1_day: str = Field(min_length=1)
    expansion_3_day: str = Field(min_length=1)

    pass_criteria: list[str] = Field(min_length=1)
    failure_criteria: list[str] = Field(min_length=1)

    scores: ChallengeScores

    final_label: Literal[
        "GOOD_CHALLENGE",
        "TOO_EASY",
        "TOO_BIG",
        "NOT_MY_TASTE",
        "STEAL_ONLY",
        "UNCLEAR_TO_OWNER",
        "DROP",
    ]

    taste_risk: str
    implementation_prompt: str = Field(min_length=1)


class ChallengePackage(_Base):
    owner_brief: OwnerBrief
    screen_story: ScreenStory
    challenge_card: ChallengeCard


class ChallengeIndexItem(_Base):
    source_repo: str
    repo_url: str
    challenge_title: str
    one_line_challenge: str
    final_label: str
    owner_clarity_score: int
    score_total: int
    difficulty_anchors: list[str]
    short_reason: str
    artifact_dir: str


class ChallengeIndex(_Base):
    query: str | None
    mode: str
    total_candidates: int
    generated_count: int
    items: list[ChallengeIndexItem]


def apply_auto_label_rules(package: ChallengePackage) -> list[str]:
    """§9 자동 판정 규칙을 적용해 final_label을 보정하고, 적용된 규칙 목록을 반환한다.

    package를 in-place로 수정한다. 규칙은 위에서 아래 순서로 평가하며
    먼저 걸린 규칙의 라벨이 최종 라벨이 된다.
    """
    card = package.challenge_card
    scores = card.scores
    clarity = package.owner_brief.owner_clarity_score
    applied: list[str] = []

    corrected: str | None = None
    if clarity < 3:
        corrected = corrected or "UNCLEAR_TO_OWNER"
        applied.append("owner_clarity_score<3 → UNCLEAR_TO_OWNER")
    if scores.difficulty_anchor_alive < 3:
        corrected = corrected or "TOO_EASY"
        applied.append("difficulty_anchor_alive<3 → TOO_EASY")
    if scores.not_too_easy < 3:
        corrected = corrected or "TOO_EASY"
        applied.append("not_too_easy<3 → TOO_EASY")
    if scores.buildable_in_one_day < 2:
        corrected = corrected or "TOO_BIG"
        applied.append("buildable_in_one_day<2 → TOO_BIG")
    if scores.immediate_demo_value < 3:
        corrected = corrected or "DROP"
        applied.append("immediate_demo_value<3 → DROP")

    # owner_clarity_score < 3이면 GOOD_CHALLENGE가 될 수 없다 (§8.1) — 첫 규칙이 이미 보장한다.
    if corrected and corrected != card.final_label:
        card.final_label = corrected
    return applied


def score_total(package: ChallengePackage) -> int:
    return package.challenge_card.scores.total()
