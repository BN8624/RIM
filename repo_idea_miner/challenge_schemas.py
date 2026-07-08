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


# 구체성 판정용 마커 — 사용자 행동/화면 요소/상태 변화/피드백 루프를 가리키는 토큰.
# difficulty_anchors나 forbidden_simplifications가 이 마커를 하나도 담지 못하면
# '일반론뿐'으로 보고 GOOD_CHALLENGE를 막는다 (Label Calibration).
_CONCRETE_MARKERS = (
    "검색", "카드", "목록", "리스트", "버튼", "메뉴", "링크", "화면", "상태",
    "액션", "루프", "입력", "실행", "결과", "선택", "갱신", "저장", "표시",
    "생성", "후속", "클릭", "드래그", "필터", "정렬", "매칭", "랭킹", "이어",
    "바뀌", "바뀐", "누른", "누르", "정적", "todo", "crud", "타이머", "메모",
    "미리보기", "단축키", "키보드", "그래프", "노드", "드롭", "확대",
)


def _item_is_concrete(text: str) -> bool:
    """항목에 구체 마커(행동/화면 요소/상태 변화)가 하나라도 들어 있으면 True."""
    low = text.lower()
    return any(marker in low for marker in _CONCRETE_MARKERS)


def is_generic_list(items: list[str]) -> bool:
    """리스트의 모든 항목이 구체 마커를 하나도 담지 못하면 True(일반론뿐).

    '좋은 UX', '자동화', '단순하게 만들지 말 것'처럼 추상 명사/일반 금지문만 있으면
    True. '결과 카드 없이 검색창만 만들지 말 것'처럼 구체 대상이 있으면 False.
    """
    return len(items) > 0 and not any(_item_is_concrete(t) for t in items)


def apply_auto_label_rules(package: ChallengePackage) -> list[str]:
    """§9 자동 판정 규칙 + Label Calibration 보정을 적용하고, 적용된 규칙 목록을 반환한다.

    package를 in-place로 수정한다. 규칙은 위에서 아래 순서로 평가하며
    먼저 걸린 규칙의 라벨이 최종 라벨이 된다.

    Label Calibration: GOOD_CHALLENGE는 원본의 핵심 난이도가 살아 있는 과제여야 한다.
    difficulty_anchor_alive / not_too_easy 기준을 4로 올리고, anchors·forbidden이
    2개 미만이거나 일반론뿐이면 GOOD_CHALLENGE를 주지 않는다.
    """
    card = package.challenge_card
    scores = card.scores
    clarity = package.owner_brief.owner_clarity_score
    anchors = card.difficulty_anchors
    forbidden = card.forbidden_simplifications
    applied: list[str] = []

    corrected: str | None = None
    if clarity < 3:
        corrected = corrected or "UNCLEAR_TO_OWNER"
        applied.append("owner_clarity_score<3 → UNCLEAR_TO_OWNER")
    if scores.buildable_in_one_day < 2:
        corrected = corrected or "TOO_BIG"
        applied.append("buildable_in_one_day<2 → TOO_BIG")
    if scores.difficulty_anchor_alive < 4:
        corrected = corrected or "TOO_EASY"
        applied.append("difficulty_anchor_alive<4 → TOO_EASY")
    if scores.not_too_easy < 4:
        corrected = corrected or "TOO_EASY"
        applied.append("not_too_easy<4 → TOO_EASY")
    if len(anchors) < 2:
        corrected = corrected or "TOO_EASY"
        applied.append("difficulty_anchors<2 → TOO_EASY")
    if len(forbidden) < 2:
        corrected = corrected or "TOO_EASY"
        applied.append("forbidden_simplifications<2 → TOO_EASY")
    if is_generic_list(anchors):
        corrected = corrected or "TOO_EASY"
        applied.append("difficulty_anchors 일반론뿐 → TOO_EASY")
    if is_generic_list(forbidden):
        corrected = corrected or "TOO_EASY"
        applied.append("forbidden_simplifications 일반론뿐 → TOO_EASY")
    if scores.immediate_demo_value < 3:
        corrected = corrected or "DROP"
        applied.append("immediate_demo_value<3 → DROP")

    # owner_clarity_score < 3이면 GOOD_CHALLENGE가 될 수 없다 (§8.1) — 첫 규칙이 이미 보장한다.
    if corrected and corrected != card.final_label:
        card.final_label = corrected
    return applied


def score_total(package: ChallengePackage) -> int:
    return package.challenge_card.scores.total()
