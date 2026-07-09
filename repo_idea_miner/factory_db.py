# challenge.db에 Product Factory 테이블(product_runs/product_tasks/product_events/product_artifacts)을 추가하는 접근 헬퍼 모듈.
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from repo_idea_miner.challenge_db import open_db, utcnow_iso
from repo_idea_miner.factory_schemas import PRODUCT_OWNER_DECISIONS, PRODUCT_RUN_STATUSES

FACTORY_TABLES = (
    "product_runs",
    "product_tasks",
    "product_events",
    "product_artifacts",
)

# product_reviews는 Phase 1.5에서 추가된 append-only 검수 기록 테이블이다.
# 기존 DB(구버전)에서도 factory-validate가 깨지지 않도록 필수 검증 대상에는 넣지 않는다.

# worker_key_id는 실제 API key가 아니라 KEY_01 형식 내부 ID만 저장한다 (§9, §18.2).
_FACTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS product_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    challenge_id INTEGER,
    status TEXT DEFAULT 'pending',
    current_stage TEXT,
    workspace_dir TEXT,
    final_artifact_dir TEXT,
    verdict TEXT,
    line TEXT,
    owner_decision TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS product_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_run_id INTEGER,
    desk_name TEXT,
    status TEXT,
    input_artifact TEXT,
    output_artifact TEXT,
    attempt_count INTEGER DEFAULT 0,
    worker_key_id TEXT,
    created_at TEXT,
    updated_at TEXT,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS product_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_run_id INTEGER,
    timestamp TEXT,
    event_type TEXT,
    message TEXT,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS product_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_run_id INTEGER,
    artifact_type TEXT,
    path TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS product_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_run_id INTEGER,
    action TEXT,
    note TEXT,
    selected_next_goal TEXT,
    reviewer_source TEXT DEFAULT 'dashboard',
    created_at TEXT
);
"""


def worker_key_label(key_id: int | None) -> str:
    """API key 내부 ID를 KEY_01 형식 문자열로 만든다. 실제 key 값은 절대 넣지 않는다."""
    if key_id is None:
        return "MOCK"
    return f"KEY_{int(key_id):02d}"


# Phase 1.6 권장 최소 필드 (§14): 기존 DB를 파괴하지 않고 컬럼만 추가한다.
_PRODUCT_RUN_EXTRA_COLUMNS = (
    ("artifact_class", "TEXT"),
    ("harness_summary_path", "TEXT"),
    ("core_system_summary_path", "TEXT"),
    ("green_base_path", "TEXT"),
)


def ensure_factory_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_FACTORY_SCHEMA)
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(product_runs)")}
    for col, col_type in _PRODUCT_RUN_EXTRA_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE product_runs ADD COLUMN {col} {col_type}")
    conn.commit()


def open_factory_db(db_path: str | Path = "challenge.db") -> sqlite3.Connection:
    """challenge.db를 열고 기존 스키마 + Factory 스키마를 보장한다."""
    conn = open_db(db_path)
    ensure_factory_schema(conn)
    return conn


# ---------------------------------------------------------------- product_runs

def create_product_run(
    conn: sqlite3.Connection,
    challenge_id: int | None,
    workspace_dir: str,
    line: str,
) -> int:
    now = utcnow_iso()
    cur = conn.execute(
        "INSERT INTO product_runs(challenge_id, status, current_stage, workspace_dir, line, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (challenge_id, "running", "promotion_gate", workspace_dir, line, now, now),
    )
    conn.commit()
    return cur.lastrowid


def update_product_run(
    conn: sqlite3.Connection,
    run_id: int,
    status: str | None = None,
    current_stage: str | None = None,
    final_artifact_dir: str | None = None,
    verdict: str | None = None,
    artifact_class: str | None = None,
    harness_summary_path: str | None = None,
    core_system_summary_path: str | None = None,
    green_base_path: str | None = None,
) -> None:
    if status is not None and status not in PRODUCT_RUN_STATUSES:
        raise ValueError(f"잘못된 product_run status: {status}")
    sets = ["updated_at=?"]
    args: list = [utcnow_iso()]
    for col, val in (
        ("status", status),
        ("current_stage", current_stage),
        ("final_artifact_dir", final_artifact_dir),
        ("verdict", verdict),
        ("artifact_class", artifact_class),
        ("harness_summary_path", harness_summary_path),
        ("core_system_summary_path", core_system_summary_path),
        ("green_base_path", green_base_path),
    ):
        if val is not None:
            sets.append(f"{col}=?")
            args.append(val)
    args.append(run_id)
    conn.execute(f"UPDATE product_runs SET {', '.join(sets)} WHERE id=?", args)
    conn.commit()


def set_owner_decision(conn: sqlite3.Connection, run_id: int, decision: str) -> None:
    if decision not in PRODUCT_OWNER_DECISIONS:
        raise ValueError(f"잘못된 owner_decision: {decision}")
    conn.execute(
        "UPDATE product_runs SET owner_decision=?, updated_at=? WHERE id=?",
        (decision, utcnow_iso(), run_id),
    )
    conn.commit()


def get_product_run(conn: sqlite3.Connection, run_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM product_runs WHERE id=?", (run_id,)).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------- product_reviews (§26, append-only)

def add_product_review(
    conn: sqlite3.Connection,
    run_id: int,
    action: str,
    note: str | None = None,
    selected_next_goal: str | None = None,
    reviewer_source: str = "dashboard",
) -> int:
    """사람 검수 판단을 append-only로 기록한다. 이전 기록은 지우지 않는다 (§26).

    호환성: product_runs.owner_decision도 최신 값으로 갱신해 challenge_has_run 등 기존
    로직이 그대로 동작하게 한다.
    """
    if action not in PRODUCT_OWNER_DECISIONS:
        raise ValueError(f"잘못된 review action: {action}")
    now = utcnow_iso()
    cur = conn.execute(
        "INSERT INTO product_reviews(product_run_id, action, note, selected_next_goal, "
        "reviewer_source, created_at) VALUES(?,?,?,?,?,?)",
        (run_id, action, note, selected_next_goal, reviewer_source, now),
    )
    conn.execute(
        "UPDATE product_runs SET owner_decision=?, updated_at=? WHERE id=?", (action, now, run_id)
    )
    conn.commit()
    return cur.lastrowid


def latest_review(conn: sqlite3.Connection, run_id: int) -> dict | None:
    """해당 run의 가장 최근 review 한 건 (§26: 최신 review만 표시)."""
    row = conn.execute(
        "SELECT * FROM product_reviews WHERE product_run_id=? ORDER BY id DESC LIMIT 1", (run_id,)
    ).fetchone()
    return dict(row) if row else None


def latest_reviews_map(conn: sqlite3.Connection) -> dict[int, dict]:
    """run_id → 최신 review dict. 목록 화면에서 한 번에 조회하기 위한 헬퍼."""
    out: dict[int, dict] = {}
    for row in conn.execute("SELECT * FROM product_reviews ORDER BY id ASC"):
        out[row["product_run_id"]] = dict(row)  # id 오름차순이므로 마지막이 최신
    return out


def list_product_runs(conn: sqlite3.Connection, limit: int = 200) -> list[dict]:
    rows = conn.execute(
        "SELECT p.*, c.challenge_title, c.repo_url, c.final_label AS challenge_label "
        "FROM product_runs p LEFT JOIN challenges c ON c.id = p.challenge_id "
        "ORDER BY p.id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def challenge_has_run(conn: sqlite3.Connection, challenge_id: int) -> bool:
    """해당 challenge에 이미 product run이 있는가. owner가 retry를 누른 run만 있으면 False."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM product_runs WHERE challenge_id=? "
        "AND (owner_decision IS NULL OR owner_decision != 'retry')",
        (challenge_id,),
    ).fetchone()
    return row["n"] > 0


# ---------------------------------------------------------------- product_tasks

def create_product_task(
    conn: sqlite3.Connection,
    product_run_id: int,
    desk_name: str,
    input_artifact: str | None = None,
    worker_key_id: str = "PENDING",
) -> int:
    now = utcnow_iso()
    cur = conn.execute(
        "INSERT INTO product_tasks(product_run_id, desk_name, status, input_artifact, attempt_count, "
        "worker_key_id, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (product_run_id, desk_name, "running", input_artifact, 1, worker_key_id, now, now),
    )
    conn.commit()
    return cur.lastrowid


def finish_product_task(
    conn: sqlite3.Connection,
    task_id: int,
    status: str,
    output_artifact: str | None = None,
    attempt_count: int | None = None,
    last_error: str | None = None,
) -> None:
    sets = ["status=?", "updated_at=?"]
    args: list = [status, utcnow_iso()]
    if output_artifact is not None:
        sets.append("output_artifact=?")
        args.append(output_artifact)
    if attempt_count is not None:
        sets.append("attempt_count=?")
        args.append(attempt_count)
    if last_error is not None:
        sets.append("last_error=?")
        args.append(last_error[:300])
    args.append(task_id)
    conn.execute(f"UPDATE product_tasks SET {', '.join(sets)} WHERE id=?", args)
    conn.commit()


# ---------------------------------------------------------------- product_events / artifacts

def log_product_event(
    conn: sqlite3.Connection,
    product_run_id: int | None,
    event_type: str,
    message: str,
    metadata: dict | None = None,
) -> None:
    conn.execute(
        "INSERT INTO product_events(product_run_id, timestamp, event_type, message, metadata_json) "
        "VALUES(?,?,?,?,?)",
        (
            product_run_id,
            utcnow_iso(),
            event_type,
            message,
            json.dumps(metadata, ensure_ascii=False) if metadata else None,
        ),
    )
    conn.commit()


def add_product_artifact(
    conn: sqlite3.Connection, product_run_id: int, artifact_type: str, path: str
) -> None:
    conn.execute(
        "INSERT INTO product_artifacts(product_run_id, artifact_type, path, created_at) VALUES(?,?,?,?)",
        (product_run_id, artifact_type, path, utcnow_iso()),
    )
    conn.commit()


# ---------------------------------------------------------------- 상태/검증

def factory_status(db_path: str | Path = "challenge.db") -> dict:
    conn = open_factory_db(db_path)
    try:
        status_counts: dict[str, int] = {}
        for row in conn.execute("SELECT status, COUNT(*) AS n FROM product_runs GROUP BY status"):
            status_counts[row["status"]] = row["n"]
        verdict_counts: dict[str, int] = {}
        for row in conn.execute(
            "SELECT verdict, COUNT(*) AS n FROM product_runs WHERE verdict IS NOT NULL GROUP BY verdict"
        ):
            verdict_counts[row["verdict"]] = row["n"]
        recent = [
            dict(r)
            for r in conn.execute(
                "SELECT p.id, p.status, p.current_stage, p.verdict, p.owner_decision, c.challenge_title "
                "FROM product_runs p LEFT JOIN challenges c ON c.id = p.challenge_id "
                "ORDER BY p.id DESC LIMIT 5"
            )
        ]
        keys = [dict(r) for r in conn.execute("SELECT * FROM api_keys ORDER BY key_id")]
        return {
            "total_runs": sum(status_counts.values()),
            "status_counts": status_counts,
            "verdict_counts": verdict_counts,
            "recent_runs": recent,
            "keys": keys,
        }
    finally:
        conn.close()


def validate_factory_db(db_path: str | Path) -> tuple[bool, list[str]]:
    """Factory 테이블 존재와 product_runs 경로/verdict 정합성을 검증한다."""
    from repo_idea_miner.factory_schemas import PRODUCT_VERDICT_LABELS

    problems: list[str] = []
    db_path = Path(db_path)
    if not db_path.exists():
        return False, [f"DB 파일 없음: {db_path}"]
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for t in FACTORY_TABLES:
            if t not in tables:
                problems.append(f"필수 테이블 없음: {t}")
        if "product_runs" in tables:
            for row in conn.execute("SELECT id, workspace_dir, verdict, status FROM product_runs"):
                if row["workspace_dir"] and not Path(row["workspace_dir"]).is_dir():
                    problems.append(f"product_run {row['id']}: workspace_dir 경로 없음 - {row['workspace_dir']}")
                if row["verdict"] and row["verdict"] not in PRODUCT_VERDICT_LABELS:
                    problems.append(f"product_run {row['id']}: 잘못된 verdict - {row['verdict']}")
                if row["status"] not in PRODUCT_RUN_STATUSES:
                    problems.append(f"product_run {row['id']}: 잘못된 status - {row['status']}")
    finally:
        conn.close()
    return (not problems), problems
