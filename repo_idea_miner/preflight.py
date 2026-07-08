# direct/search 모드별 preflight 판정(PROCEED/LOW_SIGNAL_PROCEED/FAST_DROP_PREFLIGHT/ERROR_STOP) 모듈.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from repo_idea_miner.errors import (
    GitHubAuthError,
    GitHubRateLimitError,
    RepoNotFoundError,
)

PROCEED = "PROCEED"
LOW_SIGNAL_PROCEED = "LOW_SIGNAL_PROCEED"
FAST_DROP_PREFLIGHT = "FAST_DROP_PREFLIGHT"
ERROR_STOP = "ERROR_STOP"


@dataclass
class PreflightResult:
    status: str
    reason: str


def preflight_from_error(exc: Exception) -> PreflightResult:
    if isinstance(exc, RepoNotFoundError):
        return PreflightResult(ERROR_STOP, "repo not found 또는 private repo 접근 불가")
    if isinstance(exc, GitHubAuthError):
        return PreflightResult(ERROR_STOP, "GitHub API 인증 실패")
    if isinstance(exc, GitHubRateLimitError):
        return PreflightResult(ERROR_STOP, "metadata도 수집 불가한 GitHub rate limit")
    return PreflightResult(ERROR_STOP, f"metadata 수집 실패: {type(exc).__name__}")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def run_preflight(
    metadata: dict,
    readme_status: str,
    issue_count: int,
    input_mode: str,
    now: datetime | None = None,
) -> PreflightResult:
    now = now or datetime.now(timezone.utc)
    pushed = _parse_dt(metadata.get("pushed_at"))
    inactive_days = (now - pushed).days if pushed else None
    long_inactive = inactive_days is None or inactive_days > 365

    low_signals = []
    if (metadata.get("stars") or 0) < 5:
        low_signals.append("star 수 낮음")
    if (metadata.get("forks") or 0) < 2:
        low_signals.append("fork 수 낮음")
    if issue_count == 0:
        low_signals.append("issue 적음")
    if readme_status != "OK":
        low_signals.append("README 없음/짧음")
    if long_inactive:
        low_signals.append("최근 활동 약함")

    if input_mode == "search":
        if metadata.get("archived") and long_inactive:
            return PreflightResult(FAST_DROP_PREFLIGHT, "archived + 장기 미활동")
        if readme_status == "MISSING" and issue_count == 0:
            return PreflightResult(FAST_DROP_PREFLIGHT, "README 없음 + issue 없음")
        if (metadata.get("size") or 0) == 0:
            return PreflightResult(FAST_DROP_PREFLIGHT, "사실상 빈 레포")
        if metadata.get("is_template") or metadata.get("mirror_url"):
            return PreflightResult(FAST_DROP_PREFLIGHT, "template / mirror 레포")
        if metadata.get("fork") and long_inactive and issue_count == 0:
            return PreflightResult(FAST_DROP_PREFLIGHT, "fork-only 레포 (자체 활동 없음)")

    # direct 모드: 낮은 activity만으로 hard drop 금지
    if low_signals:
        return PreflightResult(LOW_SIGNAL_PROCEED, "낮은 신호로 계속 진행: " + ", ".join(low_signals))
    return PreflightResult(PROCEED, "정상 진행")
