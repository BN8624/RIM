# Factory DB 테이블 생성/row 기록/worker_key_id 비밀 미포함/key 상태 저장소 공유 테스트.
import pytest

from repo_idea_miner.challenge_db import REQUIRED_TABLES
from repo_idea_miner.challenge_key_scheduler import ChallengeKeyScheduler
from repo_idea_miner.factory_db import (
    FACTORY_TABLES,
    add_product_artifact,
    challenge_has_run,
    create_product_run,
    create_product_task,
    factory_status,
    finish_product_task,
    get_product_run,
    log_product_event,
    open_factory_db,
    set_owner_decision,
    update_product_run,
    validate_factory_db,
    worker_key_label,
)


@pytest.fixture
def conn(tmp_path):
    c = open_factory_db(tmp_path / "challenge.db")
    yield c
    c.close()


def test_open_factory_db_creates_all_tables(conn):
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in FACTORY_TABLES:
        assert t in tables
    for t in REQUIRED_TABLES:  # 기존 challenge 테이블도 함께 보장
        assert t in tables


def test_product_run_task_event_artifact_rows(conn, tmp_path):
    ws = tmp_path / "runs" / "factory_x" / "workspace"
    ws.mkdir(parents=True)
    run_id = create_product_run(conn, challenge_id=None, workspace_dir=str(ws), line="standard")
    task_id = create_product_task(conn, run_id, "planning", worker_key_id="KEY_03")
    finish_product_task(conn, task_id, "done", output_artifact="product_brief")
    log_product_event(conn, run_id, "factory_start", "시작", metadata={"mode": "mock"})
    add_product_artifact(conn, run_id, "workspace", str(ws))
    update_product_run(conn, run_id, status="done", verdict="KEEP_CANDIDATE",
                       final_artifact_dir=str(ws.parent / "final_artifact"))

    run = get_product_run(conn, run_id)
    assert run["status"] == "done" and run["verdict"] == "KEEP_CANDIDATE"
    task = conn.execute("SELECT * FROM product_tasks WHERE id=?", (task_id,)).fetchone()
    assert task["status"] == "done" and task["worker_key_id"] == "KEY_03"
    assert conn.execute("SELECT COUNT(*) FROM product_events").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM product_artifacts").fetchone()[0] == 1


def test_worker_key_label_contains_no_secret(fake_env):
    for i in range(1, 12):
        label = worker_key_label(i)
        assert label == f"KEY_{i:02d}"
        for secret in fake_env.values():
            assert secret not in label
    assert worker_key_label(None) == "MOCK"


def test_owner_decision_validation(conn, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    run_id = create_product_run(conn, None, str(ws), "standard")
    set_owner_decision(conn, run_id, "retry")
    assert get_product_run(conn, run_id)["owner_decision"] == "retry"
    with pytest.raises(ValueError):
        set_owner_decision(conn, run_id, "yolo")


def test_challenge_has_run_respects_retry(conn, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    run_id = create_product_run(conn, 7, str(ws), "standard")
    assert challenge_has_run(conn, 7)
    set_owner_decision(conn, run_id, "retry")  # RETRY는 재투입 대상 (§5)
    assert not challenge_has_run(conn, 7)


def test_key_state_store_shared_with_challenge_scheduler(conn):
    """Challenge daemon과 Factory가 같은 api_keys 테이블을 공유한다 (§12)."""
    scheduler = ChallengeKeyScheduler(conn, {1: "k1", 2: "k2"})
    acquired = scheduler.acquire()
    assert acquired is not None
    key_id, _ = acquired
    row = conn.execute("SELECT status FROM api_keys WHERE key_id=?", (key_id,)).fetchone()
    assert row["status"] == "in_flight"  # factory가 여는 같은 conn에서 상태가 보인다
    scheduler.release_success(key_id)
    row = conn.execute("SELECT status, daily_used FROM api_keys WHERE key_id=?", (key_id,)).fetchone()
    assert row["status"] == "available" and row["daily_used"] == 1


def test_factory_status_and_validate(tmp_path):
    db = tmp_path / "challenge.db"
    conn = open_factory_db(db)
    ws = tmp_path / "ws"
    ws.mkdir()
    run_id = create_product_run(conn, None, str(ws), "standard")
    update_product_run(conn, run_id, status="done", verdict="PROMOTE_TO_CODEX")
    conn.close()

    s = factory_status(db)
    assert s["total_runs"] == 1
    assert s["verdict_counts"]["PROMOTE_TO_CODEX"] == 1

    ok, problems = validate_factory_db(db)
    assert ok, problems


def test_validate_factory_db_catches_bad_rows(tmp_path):
    db = tmp_path / "challenge.db"
    conn = open_factory_db(db)
    conn.execute(
        "INSERT INTO product_runs(challenge_id, status, workspace_dir, verdict) "
        "VALUES(1, 'weird', ?, 'NOT_A_LABEL')",
        (str(tmp_path / "missing"),),
    )
    conn.commit()
    conn.close()
    ok, problems = validate_factory_db(db)
    assert not ok
    assert any("workspace_dir" in p for p in problems)
    assert any("verdict" in p for p in problems)
    assert any("status" in p for p in problems)
