# challenge.db 스키마/settings/owner_reviews/queue/validate-db 테스트.
from repo_idea_miner.challenge_db import (
    REQUIRED_TABLES,
    claim_next_queued,
    enqueue_repo,
    finish_queue_item,
    get_setting,
    is_paused,
    log_event,
    open_db,
    queue_counts,
    save_challenge,
    set_owner_review,
    set_setting,
    validate_db,
)
from repo_idea_miner.challenge_prompts import mock_challenge_package


def test_open_db_creates_required_tables(tmp_path):
    conn = open_db(tmp_path / "challenge.db")
    try:
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in REQUIRED_TABLES:
            assert t in tables
    finally:
        conn.close()


def test_settings_miner_paused_roundtrip(tmp_path):
    conn = open_db(tmp_path / "challenge.db")
    try:
        assert is_paused(conn) is False
        set_setting(conn, "miner_paused", "true")
        assert get_setting(conn, "miner_paused") == "true"
        assert is_paused(conn) is True
        set_setting(conn, "miner_paused", "false")
        assert is_paused(conn) is False
    finally:
        conn.close()


def test_owner_status_save_and_update(tmp_path):
    conn = open_db(tmp_path / "challenge.db")
    try:
        pkg = mock_challenge_package("a/b")
        artifact = tmp_path / "run"
        artifact.mkdir()
        cid = save_challenge(conn, pkg, "https://github.com/a/b", str(artifact))
        row = conn.execute("SELECT owner_status FROM owner_reviews WHERE challenge_id=?", (cid,)).fetchone()
        assert row["owner_status"] == "unseen"
        set_owner_review(conn, cid, "build_next", note="이거 먼저")
        row = conn.execute("SELECT * FROM owner_reviews WHERE challenge_id=?", (cid,)).fetchone()
        assert row["owner_status"] == "build_next"
        assert row["note"] == "이거 먼저"
        # LLM 라벨과 사용자 판정은 분리 유지
        label = conn.execute("SELECT final_label FROM challenges WHERE id=?", (cid,)).fetchone()[0]
        assert label == "GOOD_CHALLENGE"
    finally:
        conn.close()


def test_queue_enqueue_dedup_and_claim(tmp_path):
    conn = open_db(tmp_path / "challenge.db")
    try:
        assert enqueue_repo(conn, "https://github.com/a/b", "q1", priority=5) is True
        assert enqueue_repo(conn, "https://github.com/a/b", "q1", priority=5) is False  # 중복 skip
        assert enqueue_repo(conn, "https://github.com/a/c", "q1", priority=9) is True
        row = claim_next_queued(conn)
        assert row["repo_url"] == "https://github.com/a/c"  # priority 우선
        counts = queue_counts(conn)
        assert counts["in_progress"] == 1 and counts["queued"] == 1
        finish_queue_item(conn, row["id"], "done")
        assert queue_counts(conn)["done"] == 1
    finally:
        conn.close()


def test_validate_db_pass_and_fail(tmp_path):
    db_path = tmp_path / "challenge.db"
    conn = open_db(db_path)
    try:
        artifact = tmp_path / "run"
        artifact.mkdir()
        save_challenge(conn, mock_challenge_package(), "https://github.com/a/b", str(artifact))
        log_event(conn, "test", "ok")
    finally:
        conn.close()
    ok, problems = validate_db(db_path)
    assert ok, problems

    # artifact_dir 경로가 사라지면 실패
    conn = open_db(db_path)
    try:
        save_challenge(conn, mock_challenge_package(), "https://github.com/a/c", str(tmp_path / "없는경로"))
    finally:
        conn.close()
    ok, problems = validate_db(db_path)
    assert not ok
    assert any("artifact_dir" in p for p in problems)


def test_validate_db_missing_table_fails(tmp_path):
    db_path = tmp_path / "challenge.db"
    conn = open_db(db_path)
    try:
        conn.execute("DROP TABLE events")
        conn.commit()
    finally:
        conn.close()
    ok, problems = validate_db(db_path)
    assert not ok
    assert any("events" in p for p in problems)


def test_validate_db_missing_file(tmp_path):
    ok, problems = validate_db(tmp_path / "없다.db")
    assert not ok
