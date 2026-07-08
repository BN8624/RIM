# challenge.db(SQLite) 스키마 생성과 repos/repo_queue/challenges/owner_reviews/api_keys/events/settings 접근 헬퍼 모듈.
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DB_PATH = "challenge.db"

REQUIRED_TABLES = (
    "repos",
    "repo_queue",
    "challenges",
    "owner_reviews",
    "api_keys",
    "events",
    "settings",
)

QUEUE_STATUSES = ("queued", "in_progress", "done", "error", "skipped")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS repos (
    repo_url TEXT PRIMARY KEY,
    owner TEXT,
    name TEXT,
    description TEXT,
    stars INTEGER DEFAULT 0,
    forks INTEGER DEFAULT 0,
    language TEXT,
    topics TEXT,
    archived INTEGER DEFAULT 0,
    fork INTEGER DEFAULT 0,
    first_seen_at TEXT,
    last_seen_at TEXT,
    last_processed_at TEXT,
    process_status TEXT
);

CREATE TABLE IF NOT EXISTS repo_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_url TEXT UNIQUE,
    source_query TEXT,
    priority INTEGER DEFAULT 0,
    status TEXT DEFAULT 'queued',
    attempts INTEGER DEFAULT 0,
    next_retry_at TEXT,
    created_at TEXT,
    updated_at TEXT,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS challenges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_url TEXT,
    challenge_title TEXT,
    one_line_challenge TEXT,
    final_label TEXT,
    score_total INTEGER,
    owner_clarity_score INTEGER,
    difficulty_anchor_alive INTEGER,
    not_too_easy INTEGER,
    buildable_in_one_day INTEGER,
    visual_dependency_low INTEGER,
    immediate_demo_value INTEGER,
    user_taste_fit INTEGER,
    reuse_potential INTEGER,
    artifact_dir TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS owner_reviews (
    challenge_id INTEGER PRIMARY KEY,
    owner_status TEXT DEFAULT 'unseen',
    note TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS api_keys (
    key_id INTEGER PRIMARY KEY,
    status TEXT DEFAULT 'available',
    daily_used INTEGER DEFAULT 0,
    consecutive_errors INTEGER DEFAULT 0,
    last_error_type TEXT,
    next_available_at TEXT,
    last_success_at TEXT,
    last_used_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    event_type TEXT,
    message TEXT,
    repo_url TEXT,
    challenge_id INTEGER,
    key_id INTEGER,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
);
"""


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def open_db(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """DB를 열고 스키마를 보장한다. 스레드별로 각자 연결을 여는 것을 전제로 한다."""
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


# ---------------------------------------------------------------- settings

def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value, utcnow_iso()),
    )
    conn.commit()


def is_paused(conn: sqlite3.Connection) -> bool:
    return (get_setting(conn, "miner_paused", "false") or "false").lower() == "true"


# ---------------------------------------------------------------- events

def log_event(
    conn: sqlite3.Connection,
    event_type: str,
    message: str,
    repo_url: str | None = None,
    challenge_id: int | None = None,
    key_id: int | None = None,
    metadata: dict | None = None,
) -> None:
    conn.execute(
        "INSERT INTO events(timestamp, event_type, message, repo_url, challenge_id, key_id, metadata_json) "
        "VALUES(?,?,?,?,?,?,?)",
        (
            utcnow_iso(),
            event_type,
            message,
            repo_url,
            challenge_id,
            key_id,
            json.dumps(metadata, ensure_ascii=False) if metadata else None,
        ),
    )
    conn.commit()


# ---------------------------------------------------------------- repos

def upsert_repo(conn: sqlite3.Connection, repo: dict) -> None:
    """검색 결과/metadata dict를 repos에 저장한다. key 값은 저장하지 않는다."""
    now = utcnow_iso()
    conn.execute(
        """INSERT INTO repos(repo_url, owner, name, description, stars, forks, language, topics,
                             archived, fork, first_seen_at, last_seen_at, process_status)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,COALESCE((SELECT process_status FROM repos WHERE repo_url=?), 'new'))
           ON CONFLICT(repo_url) DO UPDATE SET
             description=excluded.description, stars=excluded.stars, forks=excluded.forks,
             language=excluded.language, topics=excluded.topics, archived=excluded.archived,
             fork=excluded.fork, last_seen_at=excluded.last_seen_at""",
        (
            repo.get("repo_url"),
            repo.get("owner"),
            repo.get("name"),
            repo.get("description"),
            repo.get("stars") or 0,
            repo.get("forks") or 0,
            repo.get("language"),
            json.dumps(repo.get("topics") or [], ensure_ascii=False),
            1 if repo.get("archived") else 0,
            1 if repo.get("fork") else 0,
            now,
            now,
            repo.get("repo_url"),
        ),
    )
    conn.commit()


def mark_repo_processed(conn: sqlite3.Connection, repo_url: str, status: str) -> None:
    conn.execute(
        "UPDATE repos SET last_processed_at=?, process_status=? WHERE repo_url=?",
        (utcnow_iso(), status, repo_url),
    )
    conn.commit()


def recently_processed(conn: sqlite3.Connection, repo_url: str, within_days: int = 14) -> bool:
    row = conn.execute("SELECT last_processed_at FROM repos WHERE repo_url=?", (repo_url,)).fetchone()
    if not row or not row["last_processed_at"]:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
    return row["last_processed_at"] >= cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- repo_queue

def enqueue_repo(conn: sqlite3.Connection, repo_url: str, source_query: str, priority: int = 0) -> bool:
    """중복 repo는 skip한다. 새로 넣었으면 True."""
    now = utcnow_iso()
    cur = conn.execute(
        "INSERT OR IGNORE INTO repo_queue(repo_url, source_query, priority, status, created_at, updated_at) "
        "VALUES(?,?,?,'queued',?,?)",
        (repo_url, source_query, priority, now, now),
    )
    conn.commit()
    return cur.rowcount > 0


def claim_next_queued(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """priority 높은 순으로 다음 queued 항목을 in_progress로 전환해 반환한다."""
    now = utcnow_iso()
    with conn:  # 트랜잭션으로 claim 경쟁 방지
        row = conn.execute(
            "SELECT * FROM repo_queue WHERE status='queued' "
            "AND (next_retry_at IS NULL OR next_retry_at <= ?) "
            "ORDER BY priority DESC, id ASC LIMIT 1",
            (now,),
        ).fetchone()
        if row is None:
            return None
        cur = conn.execute(
            "UPDATE repo_queue SET status='in_progress', attempts=attempts+1, updated_at=? "
            "WHERE id=? AND status='queued'",
            (now, row["id"]),
        )
        if cur.rowcount == 0:
            return None
    return row


def finish_queue_item(
    conn: sqlite3.Connection,
    queue_id: int,
    status: str,
    last_error: str | None = None,
    retry_delay_seconds: float | None = None,
) -> None:
    next_retry = None
    if retry_delay_seconds is not None:
        next_retry = (datetime.now(timezone.utc) + timedelta(seconds=retry_delay_seconds)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    conn.execute(
        "UPDATE repo_queue SET status=?, last_error=?, next_retry_at=?, updated_at=? WHERE id=?",
        (status, last_error, next_retry, utcnow_iso(), queue_id),
    )
    conn.commit()


def queue_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts = {s: 0 for s in QUEUE_STATUSES}
    for row in conn.execute("SELECT status, COUNT(*) AS n FROM repo_queue GROUP BY status"):
        counts[row["status"]] = row["n"]
    return counts


# ---------------------------------------------------------------- challenges

def save_challenge(conn: sqlite3.Connection, package: dict, repo_url: str, artifact_dir: str) -> int:
    """검증된 ChallengePackage dict를 challenges에 저장하고 owner_reviews를 unseen으로 초기화한다."""
    card = package["challenge_card"]
    scores = card["scores"]
    brief = package["owner_brief"]
    now = utcnow_iso()
    cur = conn.execute(
        """INSERT INTO challenges(repo_url, challenge_title, one_line_challenge, final_label,
             score_total, owner_clarity_score, difficulty_anchor_alive, not_too_easy,
             buildable_in_one_day, visual_dependency_low, immediate_demo_value,
             user_taste_fit, reuse_potential, artifact_dir, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            repo_url,
            card["challenge_title"],
            card["one_line_challenge"],
            card["final_label"],
            sum(scores.values()),
            brief["owner_clarity_score"],
            scores["difficulty_anchor_alive"],
            scores["not_too_easy"],
            scores["buildable_in_one_day"],
            scores["visual_dependency_low"],
            scores["immediate_demo_value"],
            scores["user_taste_fit"],
            scores["reuse_potential"],
            artifact_dir,
            now,
            now,
        ),
    )
    challenge_id = cur.lastrowid
    conn.execute(
        "INSERT OR IGNORE INTO owner_reviews(challenge_id, owner_status, updated_at) VALUES(?, 'unseen', ?)",
        (challenge_id, now),
    )
    conn.commit()
    return challenge_id


def set_owner_review(conn: sqlite3.Connection, challenge_id: int, owner_status: str, note: str | None = None) -> None:
    conn.execute(
        "INSERT INTO owner_reviews(challenge_id, owner_status, note, updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(challenge_id) DO UPDATE SET owner_status=excluded.owner_status, "
        "note=COALESCE(excluded.note, owner_reviews.note), updated_at=excluded.updated_at",
        (challenge_id, owner_status, note, utcnow_iso()),
    )
    conn.commit()


# ---------------------------------------------------------------- validate

def validate_db(db_path: str | Path) -> tuple[bool, list[str]]:
    """DB integrity, 필수 테이블 존재, challenges.artifact_dir 경로 정합성을 검증한다."""
    problems: list[str] = []
    db_path = Path(db_path)
    if not db_path.exists():
        return False, [f"DB 파일 없음: {db_path}"]
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            problems.append(f"integrity_check 실패: {integrity}")
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for t in REQUIRED_TABLES:
            if t not in tables:
                problems.append(f"필수 테이블 없음: {t}")
        if "challenges" in tables:
            for row in conn.execute("SELECT id, artifact_dir FROM challenges"):
                d = row["artifact_dir"]
                if not d:
                    problems.append(f"challenge {row['id']}: artifact_dir 비어 있음")
                elif not Path(d).is_dir():
                    problems.append(f"challenge {row['id']}: artifact_dir 경로 없음 - {d}")
        if "repo_queue" in tables:
            for row in conn.execute(
                "SELECT id, status FROM repo_queue WHERE status NOT IN (?,?,?,?,?)", QUEUE_STATUSES
            ):
                problems.append(f"repo_queue {row['id']}: 잘못된 status - {row['status']}")
    finally:
        conn.close()
    return (not problems), problems
