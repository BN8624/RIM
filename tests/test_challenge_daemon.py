# Challenge Miner daemon 테스트: seed refill/queue 처리/pause/status를 mock으로 검증.
import time

from repo_idea_miner.challenge_daemon import (
    ChallengeDaemon,
    daemon_status,
    load_seed_queries,
    refill_queue,
    set_paused,
)
from repo_idea_miner.challenge_db import open_db, queue_counts
from repo_idea_miner.config import ChallengeMinerSettings, Settings
from tests.test_challenge_search_mock import FakeSearchGitHub, _items


def _daemon(tmp_path, gh=None, **miner_overrides):
    miner = ChallengeMinerSettings(
        key_min_interval_seconds=0,
        queue_refill_threshold=100,
        queue_refill_target=10,
        **miner_overrides,
    )
    return ChallengeDaemon(
        db_path=tmp_path / "challenge.db",
        output_dir=tmp_path / "runs",
        mode="mock",
        settings=Settings(google_keys={}),
        miner_settings=miner,
        gh=gh or FakeSearchGitHub(_items(3)),
    )


def _wait_all(daemon, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        daemon.wait_workers(timeout=1.0)
        counts = queue_counts(daemon.conn)
        if counts["in_progress"] == 0:
            return counts
    raise AssertionError("worker가 제시간에 끝나지 않음")


def test_load_seed_queries_yaml_subset(tmp_path):
    p = tmp_path / "seeds.yaml"
    p.write_text('queries:\n  - "stars:>10000 language:TypeScript"\n  - "topic:automation stars:>1000"\n', encoding="utf-8")
    assert load_seed_queries(p) == [
        "stars:>10000 language:TypeScript",
        "topic:automation stars:>1000",
    ]
    # 파일이 없으면 기본 seed
    assert len(load_seed_queries(tmp_path / "없음.yaml")) >= 5


def test_refill_queue_skips_duplicates(tmp_path):
    conn = open_db(tmp_path / "challenge.db")
    try:
        gh = FakeSearchGitHub(_items(3))
        added = refill_queue(conn, gh, ["q1"], target=10)
        assert added == 3
        added2 = refill_queue(conn, gh, ["q1"], target=10)
        assert added2 == 0  # 중복 repo skip
        assert conn.execute("SELECT COUNT(*) FROM repos").fetchone()[0] == 3
    finally:
        conn.close()


def test_daemon_cycle_processes_queue_and_saves_challenges(tmp_path):
    daemon = _daemon(tmp_path)
    info = daemon.run_cycle()
    assert info["paused"] is False
    assert info["started"] == 3  # repo 3개 → worker 3개 (11-key 여유)
    counts = _wait_all(daemon)
    assert counts["done"] == 3
    challenges = daemon.conn.execute("SELECT COUNT(*) FROM challenges").fetchone()[0]
    assert challenges == 3
    daemon.conn.close()


def test_paused_daemon_does_not_dispatch(tmp_path):
    daemon = _daemon(tmp_path)
    set_paused(daemon.db_path, True)
    info = daemon.run_cycle()
    assert info["paused"] is True
    assert info["started"] == 0
    set_paused(daemon.db_path, False)
    info = daemon.run_cycle()
    assert info["started"] > 0
    _wait_all(daemon)
    daemon.conn.close()


def test_daemon_recovers_stranded_in_progress(tmp_path):
    from repo_idea_miner.challenge_db import enqueue_repo, open_db

    db = tmp_path / "challenge.db"
    conn = open_db(db)
    enqueue_repo(conn, "https://github.com/a/b", "q")
    conn.execute("UPDATE repo_queue SET status='in_progress'")
    conn.commit()
    conn.close()
    # 새 daemon 시작 시 멈춘 항목이 다시 queued로 복구되어야 한다
    daemon = _daemon(tmp_path)
    assert queue_counts(daemon.conn)["in_progress"] == 0
    assert queue_counts(daemon.conn)["queued"] >= 1
    daemon.conn.close()


def test_daemon_status_reports_counts(tmp_path):
    daemon = _daemon(tmp_path)
    daemon.run_cycle()
    _wait_all(daemon)
    daemon.conn.close()
    s = daemon_status(tmp_path / "challenge.db")
    assert s["paused"] is False
    assert s["challenge_count"] == 3
    assert s["queue"]["done"] == 3
    assert len(s["keys"]) == 11
    assert len(s["recent_challenges"]) == 3
