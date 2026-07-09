# Product Dashboard 표시 문구 전용 모듈: 내부 enum/기술 용어를 사용자 검수용 한국어로 변환한다 (표시만, 내부값 불변).
from __future__ import annotations

import re

# ---------------------------------------------------------------- Product Verdict (§2)

VERDICT_LABELS = {
    "PROMOTE_TO_CODEX": "제품화 후보",
    "KEEP_CANDIDATE": "보관 후보",
    "NEEDS_MORE_GEMMA_LOOP": "더 돌려야 함",
    "TOO_WEAK": "약함",
    "DROP": "버림",
}

VERDICT_DESC = {
    "PROMOTE_TO_CODEX": "Codex/Claude에 넘겨 정리·확장할 만한 후보",
    "KEEP_CANDIDATE": "지금 바로 제품화하긴 애매하지만 남겨둘 만한 후보",
    "NEEDS_MORE_GEMMA_LOOP": "가능성은 있지만 아직 기능 연결이나 완성도가 부족해 한 번 더 개선해야 하는 후보",
    "TOO_WEAK": "실행은 되지만 제품 느낌이나 핵심 기능이 부족한 후보",
    "DROP": "더 진행할 가치가 낮은 후보",
}

# ---------------------------------------------------------------- Run Status (§3)

STATUS_LABELS = {
    "done": "완료",
    "completed": "완료",
    "running": "실행 중",
    "error": "오류",
    "failed": "실패",
    "pending": "대기 중",
    "paused": "일시정지",
    "unknown": "알 수 없음",
}

# ---------------------------------------------------------------- Review Action (§4)

REVIEW_LABELS = {
    "keep": "보관",
    "drop": "버림",
    "productize": "제품화",
    "retry": "다시 돌리기",
    "archive": "보류",
}

# ---------------------------------------------------------------- Gate (§6)

GATE_LABELS = {
    "static": "파일 구조 검사",
    "contract": "구현 연결 검사",
    "syntax": "문법 검사",
    "smoke": "기본 실행 검사",
}

GATE_STATUS_LABELS = {
    "PASS": "통과",
    "FAIL": "실패",
    "SKIP": "건너뜀",
    "UNKNOWN": "알 수 없음",
}

# ---------------------------------------------------------------- QA (§7)

QA_STATUS_LABELS = {
    "PASS": "좋음",
    "PARTIAL": "일부 부족",
    "FAIL": "실패",
    "UNKNOWN": "알 수 없음",
}

QA_FIELD_LABELS = {
    "anchor": "핵심 조건",
    "forbidden": "금지된 단순화",
    "core_interaction": "핵심 조작",
    "evidence": "근거",
    "issue": "문제",
    "next_goal": "다음 목표",
    "known_issues": "알려진 문제",
}

# ---------------------------------------------------------------- 추천 액션 (§5)

_RECOMMEND_BY_VERDICT = {
    "PROMOTE_TO_CODEX": "제품화",
    "KEEP_CANDIDATE": "보관",
    "NEEDS_MORE_GEMMA_LOOP": "다시 돌리기",
    "TOO_WEAK": "보류 또는 버림",
    "DROP": "버림",
}


def format_verdict_label(verdict: str | None) -> str:
    if not verdict:
        return "판정 없음"
    return VERDICT_LABELS.get(verdict, verdict)


def format_verdict_desc(verdict: str | None) -> str:
    return VERDICT_DESC.get(verdict or "", "")


def format_status_label(status: str | None) -> str:
    return STATUS_LABELS.get((status or "unknown").lower(), STATUS_LABELS["unknown"])


def format_review_label(action: str | None) -> str:
    if not action:
        return "미검수"
    return REVIEW_LABELS.get(action.lower(), action)


def format_gate_label(key: str) -> str:
    return GATE_LABELS.get(key, key)


def format_gate_status(status: str | None) -> str:
    return GATE_STATUS_LABELS.get((status or "UNKNOWN").upper(), GATE_STATUS_LABELS["UNKNOWN"])


def format_qa_status(status: str | None) -> str:
    return QA_STATUS_LABELS.get((status or "UNKNOWN").upper(), QA_STATUS_LABELS["UNKNOWN"])


def format_recommended(verdict: str | None, status: str | None = None) -> str:
    """추천 액션을 한국어로. status=error/failed면 verdict와 무관하게 '보류 또는 버림' (§5)."""
    if (status or "").lower() in ("error", "failed"):
        return "보류 또는 버림"
    return _RECOMMEND_BY_VERDICT.get(verdict or "", "보류 또는 버림")


# ---------------------------------------------------------------- 기술 용어 → 사람 말 (§8~§10)

# 자주 나오는 영어 기술 로그 문장을 통째로 사람 문장으로 치환 (우선 적용)
_HUMAN_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"onjump|scrubber.*(missing|not\s*(wire|implement|connect|jump))|does not wire onjump", re.I),
     "타임라인을 움직여도 사진이 바뀌지 않음"),
    (re.compile(r"smoke\s*gate\s*timeout|smoke.*timeout|기본 실행.*(초과)|timeout .*exceed", re.I),
     "기본 실행 중 시간이 초과됨"),
    (re.compile(r"contract\s*gate\s*passed.*reachab|import\s*graph\s*reachab", re.I),
     "파일 연결 구조는 정상임"),
    (re.compile(r"missing\s*state\s*transition", re.I),
     "사진 선택 상태가 바뀌도록 연결되지 않음"),
    (re.compile(r"button\s*exists\s*but.*(click\s*)?handler\s*not\s*implement", re.I),
     "버튼은 있지만 눌러도 동작하지 않음"),
    (re.compile(r"^\s*artifact\s*generated\s*$", re.I),
     "결과물 생성됨"),
]

# 부분 용어 치환 사전 (긴 표현 우선). 파일명 자체는 대상 아님.
_TERM_DICT: list[tuple[str, str]] = sorted(
    [
        ("timeline scrubber", "사진 타임라인"),
        ("final artifact", "최종 결과물"),
        ("codex export", "제품화 전달 묶음"),
        ("smoke output", "실행 결과"),
        ("debug history", "수정 기록"),
        ("scrubber", "타임라인 슬라이더"),
        ("onjump", "이동 동작 연결"),
        ("handler", "동작 연결"),
        ("artifact", "결과물"),
        ("workspace", "작업 폴더"),
        ("stdout", "실행 출력"),
        ("stderr", "오류 출력"),
        ("events", "진행 기록"),
        ("anchors", "핵심 조건"),
        ("anchor", "핵심 조건"),
        ("forbidden", "금지된 단순화"),
    ],
    key=lambda kv: len(kv[0]),
    reverse=True,
)


def humanize_issue(text: str | None) -> str:
    """기술 로그/영어 용어가 섞인 이유·문제 문장을 사용자 검수 문장으로 바꾼다 (§8~§10).

    - 통째 매칭되는 대표 패턴이 있으면 그 문장으로 치환한다.
    - 아니면 남은 영어 기술 용어를 사전으로 풀어 쓴다.
    - 화면 표시용일 뿐 내부 값은 바꾸지 않는다.
    """
    if not text:
        return text or ""
    for pattern, human in _HUMAN_PATTERNS:
        if pattern.search(text):
            return human
    out = text
    for term, ko in _TERM_DICT:
        out = re.sub(re.escape(term), ko, out, flags=re.IGNORECASE)
    return out
