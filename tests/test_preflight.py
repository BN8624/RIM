# preflight 판정 테스트 (§34.2).
from datetime import datetime, timezone

from repo_idea_miner.errors import RepoNotFoundError
from repo_idea_miner.preflight import (
    ERROR_STOP,
    FAST_DROP_PREFLIGHT,
    LOW_SIGNAL_PROCEED,
    PROCEED,
    preflight_from_error,
    run_preflight,
)

NOW = datetime(2026, 7, 8, tzinfo=timezone.utc)


def meta(**kw):
    base = {
        "stars": 100,
        "forks": 20,
        "archived": False,
        "fork": False,
        "is_template": False,
        "mirror_url": None,
        "size": 500,
        "pushed_at": "2026-07-01T00:00:00Z",
    }
    base.update(kw)
    return base


def test_direct_low_stars_no_fast_drop():
    result = run_preflight(meta(stars=0, forks=0), "OK", 0, "direct", now=NOW)
    assert result.status == LOW_SIGNAL_PROCEED


def test_direct_normal_proceed():
    result = run_preflight(meta(), "OK", 5, "direct", now=NOW)
    assert result.status == PROCEED


def test_search_archived_inactive_fast_drop():
    result = run_preflight(
        meta(archived=True, pushed_at="2023-01-01T00:00:00Z"), "OK", 3, "search", now=NOW
    )
    assert result.status == FAST_DROP_PREFLIGHT


def test_search_empty_repo_fast_drop():
    result = run_preflight(meta(size=0), "MISSING", 0, "search", now=NOW)
    assert result.status == FAST_DROP_PREFLIGHT


def test_search_active_repo_proceeds():
    result = run_preflight(meta(), "OK", 5, "search", now=NOW)
    assert result.status == PROCEED


def test_repo_not_found_error_stop():
    result = preflight_from_error(RepoNotFoundError("x"))
    assert result.status == ERROR_STOP
