# issue 제목/본문에서 defect/feature/workflow/confusion/noise 신호 태그를 추출하는 모듈.
from __future__ import annotations

DEFECT_KEYWORDS = [
    "error", "bug", "fail", "failed", "failure", "expected", "actual", "reproduce",
    "steps", "regression", "workaround", "cannot", "can't", "crash", "slow", "performance",
    "오류", "버그", "실패", "재현", "기대", "실제", "회귀", "느림", "성능", "안됨", "깨짐",
]

FEATURE_KEYWORDS = [
    "feature", "request", "feature request", "would be great", "would be nice",
    "support", "support for", "add support", "integrate", "integration", "plugin",
    "extension", "api", "custom", "customize", "option", "config", "setting", "template",
    "기능 요청", "지원", "추가", "연동", "통합", "플러그인", "확장", "커스텀",
    "사용자 설정", "옵션", "설정", "템플릿",
]

WORKFLOW_KEYWORDS = [
    "automate", "automation", "workflow", "batch", "bulk", "export", "import", "sync",
    "schedule", "report", "dashboard", "pipeline", "repeat", "manual", "copy paste",
    "no-code", "low-code",
    "자동화", "워크플로우", "일괄 처리", "대량 처리", "내보내기", "가져오기", "동기화",
    "예약", "리포트", "보고서", "대시보드", "파이프라인", "반복", "수동", "복붙",
    "노코드", "로우코드",
]

CONFUSION_KEYWORDS = [
    "confusing", "confused", "docs", "documentation", "example", "tutorial", "how to",
    "setup", "install", "dependency", "version",
    "헷갈림", "문서", "예제", "튜토리얼", "사용법", "설치", "의존성", "버전", "설정",
]

NOISE_KEYWORDS = [
    "install error", "installation failed", "cannot install", "can't install",
    "version conflict", "incompatible version", "dependency conflict",
    "pip install", "npm install", "duplicate", "stale",
    "설치 오류", "버전 충돌", "설치가 안", "환경 문제", "중복 이슈",
]

ALL_SAMPLER_KEYWORDS = sorted(
    set(DEFECT_KEYWORDS + FEATURE_KEYWORDS + WORKFLOW_KEYWORDS + CONFUSION_KEYWORDS),
    key=len,
    reverse=True,
)

SIGNAL_TAGS = [
    "defect_signal",
    "feature_signal",
    "workflow_signal",
    "confusion_signal",
    "noise_signal",
    "uncertain_signal",
]


def _matches(text: str, keywords: list[str]) -> bool:
    return any(k in text for k in keywords)


def tag_issue(title: str, body: str | None) -> list[str]:
    """한 issue에 여러 tag가 붙을 수 있다. 아무것도 없으면 uncertain_signal."""
    text = f"{title or ''} {(body or '')[:4000]}".lower()
    tags: list[str] = []
    if _matches(text, [k.lower() for k in DEFECT_KEYWORDS]):
        tags.append("defect_signal")
    if _matches(text, [k.lower() for k in FEATURE_KEYWORDS]):
        tags.append("feature_signal")
    if _matches(text, [k.lower() for k in WORKFLOW_KEYWORDS]):
        tags.append("workflow_signal")
    if _matches(text, [k.lower() for k in CONFUSION_KEYWORDS]):
        tags.append("confusion_signal")
    if _matches(text, [k.lower() for k in NOISE_KEYWORDS]):
        tags.append("noise_signal")
    if not tags:
        tags.append("uncertain_signal")
    return tags


def compute_issue_stats(issue_records: list[dict]) -> dict:
    """sampler/tag 결과에서 결정적 issue 통계를 만든다 (judge 프롬프트에 제공)."""
    counts = {t: 0 for t in SIGNAL_TAGS}
    for rec in issue_records:
        for t in rec.get("signal_tags", []):
            if t in counts:
                counts[t] += 1
    classified = sum(1 for r in issue_records if r.get("signal_tags") and r["signal_tags"] != ["uncertain_signal"])
    sampled = len(issue_records)
    if sampled >= 8:
        confidence = "high"
    elif sampled >= 4:
        confidence = "medium"
    else:
        confidence = "low"
    return {
        "sampled_issue_count": sampled,
        "classified_issue_count": classified,
        "defect_count": counts["defect_signal"],
        "feature_request_count": counts["feature_signal"],
        "workflow_pain_count": counts["workflow_signal"],
        "confusion_count": counts["confusion_signal"],
        "install_env_version_count": counts["noise_signal"],
        "noise_count": counts["noise_signal"],
        "product_pain_count": counts["defect_signal"],
        "uncertain_count": counts["uncertain_signal"],
        "confidence": confidence,
    }
