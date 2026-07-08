# 11-key controlled parallel pool 스케줄러 테스트: per-key cooldown/backoff/exhausted/daily reset.
from datetime import datetime, timedelta, timezone

from repo_idea_miner.challenge_db import open_db
from repo_idea_miner.challenge_key_scheduler import (
    ChallengeKeyScheduler,
    classify_challenge_error,
    is_daily_quota_exhausted,
)
from repo_idea_miner.config import ChallengeMinerSettings


class Clock:
    def __init__(self):
        self.now = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


def _scheduler(tmp_path, n_keys=11, **settings_overrides):
    conn = open_db(tmp_path / "challenge.db")
    settings = ChallengeMinerSettings(key_min_interval_seconds=0, **settings_overrides)
    clock = Clock()
    keys = {i: f"mock-key-{i}" for i in range(1, n_keys + 1)}
    return ChallengeKeyScheduler(conn, keys, settings, now_fn=clock), clock, conn


def test_acquire_all_keys_in_parallel(tmp_path):
    sched, clock, conn = _scheduler(tmp_path)
    acquired = []
    while True:
        got = sched.acquire()
        if got is None:
            break
        acquired.append(got[0])
    assert len(acquired) == 11  # 최대 11개 key 동시 작업
    assert sched.acquire() is None  # key당 in_flight 1개


def test_error_cooldown_only_affects_that_key(tmp_path):
    sched, clock, conn = _scheduler(tmp_path, n_keys=3)
    k1, _ = sched.acquire()
    cooldown = sched.release_error(k1, "transient", "429 rate limit")
    assert cooldown == 30.0  # 첫 transient는 30초
    # 다른 key는 계속 작업 가능 (전체 miner를 멈추지 않음)
    others = {sched.acquire()[0], sched.acquire()[0]}
    assert k1 not in others
    assert len(others) == 2
    # cooldown이 지나면 다시 사용 가능
    for k in others:
        sched.release_success(k)
    clock.advance(31)
    available = set()
    while True:
        got = sched.acquire()
        if got is None:
            break
        available.add(got[0])
    assert k1 in available


def test_transient_backoff_escalates_30_60_120_300(tmp_path):
    sched, clock, conn = _scheduler(tmp_path, n_keys=1)
    expected = [30.0, 60.0, 120.0, 300.0, 300.0]
    for exp in expected:
        clock.advance(400)
        got = sched.acquire()
        assert got is not None
        cooldown = sched.release_error(got[0], "transient", "500 internal")
        assert cooldown == exp


def test_timeout_backoff_uses_timeout_sequence(tmp_path):
    sched, clock, conn = _scheduler(tmp_path, n_keys=1)
    got = sched.acquire()
    assert sched.release_error(got[0], "timeout", "request timed out") == 60.0


def test_success_streak_resets_consecutive_errors(tmp_path):
    sched, clock, conn = _scheduler(tmp_path, n_keys=1)
    key = 1
    got = sched.acquire()
    sched.release_error(key, "transient", "429")
    clock.advance(400)
    # 3회 연속 성공 후 consecutive_errors reset (§19)
    for i in range(3):
        got = sched.acquire()
        assert got is not None
        sched.release_success(key)
        clock.advance(1)
        row = conn.execute("SELECT * FROM api_keys WHERE key_id=1").fetchone()
        if i < 2:
            assert row["consecutive_errors"] == 1
        else:
            assert row["consecutive_errors"] == 0
    row = conn.execute("SELECT daily_used FROM api_keys WHERE key_id=1").fetchone()
    assert row["daily_used"] == 3


def test_simple_429_is_not_exhausted(tmp_path):
    assert not is_daily_quota_exhausted("429 RESOURCE_EXHAUSTED rate limit")
    assert is_daily_quota_exhausted("Quota exceeded for requests per day (RPD)")
    sched, clock, conn = _scheduler(tmp_path, n_keys=1)
    got = sched.acquire()
    sched.release_error(got[0], "transient", "429 too many requests")
    row = conn.execute("SELECT status FROM api_keys WHERE key_id=1").fetchone()
    assert row["status"] == "cooldown"  # exhausted가 아니라 짧은 cooldown


def test_explicit_daily_quota_marks_exhausted(tmp_path):
    sched, clock, conn = _scheduler(tmp_path, n_keys=1)
    got = sched.acquire()
    sched.release_error(got[0], "transient", "quota exceeded: requests per day")
    row = conn.execute("SELECT status FROM api_keys WHERE key_id=1").fetchone()
    assert row["status"] == "exhausted"


def test_daily_reset_restores_exhausted_keys(tmp_path):
    sched, clock, conn = _scheduler(tmp_path, n_keys=2)
    got = sched.acquire()
    sched.release_error(got[0], "exhausted", "quota exceeded per day")
    sched.maybe_daily_reset()  # 같은 날에는 이미 reset된 상태 유지
    clock.advance(24 * 3600)
    assert sched.maybe_daily_reset() is True
    row = conn.execute("SELECT status, daily_used FROM api_keys WHERE key_id=1").fetchone()
    assert row["status"] == "available"
    assert row["daily_used"] == 0


def test_rpd_limit_blocks_key(tmp_path):
    sched, clock, conn = _scheduler(tmp_path, n_keys=1, key_daily_rpd_limit=2)
    for _ in range(2):
        got = sched.acquire()
        assert got is not None
        sched.release_success(got[0])
        clock.advance(1)
    assert sched.acquire() is None  # 로컬 안전 카운터 도달


def test_auth_error_disables_key(tmp_path):
    sched, clock, conn = _scheduler(tmp_path, n_keys=2)
    got = sched.acquire()
    sched.release_error(got[0], "auth", "API key not valid")
    row = conn.execute("SELECT status FROM api_keys WHERE key_id=?", (got[0],)).fetchone()
    assert row["status"] == "disabled"
    clock.advance(3600)
    remaining = sched.acquire()
    assert remaining is not None and remaining[0] != got[0]


def test_classify_challenge_error():
    from repo_idea_miner.errors import LLMAuthError, LLMCallError

    assert classify_challenge_error(LLMCallError("429 rate limit"))[0] == "transient"
    assert classify_challenge_error(LLMCallError("500 internal error"))[0] == "transient"
    assert classify_challenge_error(LLMCallError("request timed out"))[0] == "timeout"
    assert classify_challenge_error(LLMCallError("quota exceeded per day"))[0] == "exhausted"
    assert classify_challenge_error(LLMAuthError("all keys disabled"))[0] == "auth"
