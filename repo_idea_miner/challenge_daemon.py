# 로컬 Challenge Miner daemon: seed 수집 → repo_queue 적재 → 11-key 병렬 Challenge 생성 → DB/runs 저장.
from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from repo_idea_miner.challenge_db import (
    claim_next_queued,
    enqueue_repo,
    finish_queue_item,
    get_setting,
    is_paused,
    log_event,
    mark_repo_processed,
    open_db,
    queue_counts,
    recently_processed,
    set_setting,
    upsert_repo,
)
from repo_idea_miner.challenge_key_scheduler import ChallengeKeyScheduler, classify_challenge_error
from repo_idea_miner.challenge_pipeline import run_challenge
from repo_idea_miner.config import (
    ChallengeMinerSettings,
    Settings,
    load_challenge_miner_settings,
    load_settings,
)
from repo_idea_miner.errors import GitHubError, LLMCallError
from repo_idea_miner.github_api import GitHubClient, search_repositories
from repo_idea_miner.key_pool import KeyPool
from repo_idea_miner.llm_client import GoogleGenAIGemmaClient, LLMCallLogger

DEFAULT_SEED_QUERIES = [
    "stars:>10000 language:TypeScript",
    "stars:>5000 language:Python",
    "topic:productivity stars:>1000",
    "topic:developer-tools stars:>1000",
    "topic:note-taking stars:>500",
    "topic:automation stars:>1000",
    "topic:visualization stars:>1000",
    "topic:local-first stars:>500",
]

MAX_QUEUE_ATTEMPTS = 3


def load_seed_queries(path: str | Path | None) -> list[str]:
    """seed query 설정 파일을 읽는다. §21의 단순 YAML 형식(queries: - "...")을 지원한다."""
    if not path:
        return list(DEFAULT_SEED_QUERIES)
    p = Path(path)
    if not p.exists():
        return list(DEFAULT_SEED_QUERIES)
    queries: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s.startswith("-"):
            continue
        q = s.lstrip("-").strip().strip("'\"")
        if q:
            queries.append(q)
    return queries or list(DEFAULT_SEED_QUERIES)


def _seed_priority(cand: dict) -> int:
    """수집 단계 필터 (§21): archived/README 부실은 낮은 우선순위. LLM 호출 없음."""
    priority = 10
    if cand.get("archived"):
        priority -= 8
    if not (cand.get("description") or "").strip():
        priority -= 2
    stars = cand.get("stars") or 0
    if stars >= 10000:
        priority += 3
    elif stars >= 1000:
        priority += 1
    return priority


def refill_queue(
    conn: sqlite3.Connection,
    gh: GitHubClient,
    seed_queries: list[str],
    target: int,
    per_query_limit: int = 30,
) -> int:
    """seed query를 실행해 repo_queue를 target까지 보충한다. 넣은 개수를 반환한다."""
    added = 0
    for query in seed_queries:
        if queue_counts(conn)["queued"] >= target:
            break
        try:
            items = search_repositories(gh, query, per_query_limit)
        except GitHubError as exc:
            log_event(conn, "seed_error", f"{query}: {type(exc).__name__}: {exc}")
            continue
        for it in items:
            url = it.get("html_url")
            full_name = it.get("full_name") or ""
            if not url or not full_name:
                continue
            if it.get("fork"):
                continue  # fork-only repo skip (§21)
            owner, _, name = full_name.partition("/")
            upsert_repo(
                conn,
                {
                    "repo_url": url,
                    "owner": owner,
                    "name": name,
                    "description": it.get("description"),
                    "stars": it.get("stargazers_count", 0),
                    "forks": it.get("forks_count", 0),
                    "language": it.get("language"),
                    "topics": it.get("topics", []),
                    "archived": it.get("archived", False),
                    "fork": it.get("fork", False),
                },
            )
            if recently_processed(conn, url):
                continue  # 최근 처리한 repo 재처리 금지 (§21)
            cand = {
                "archived": it.get("archived", False),
                "description": it.get("description"),
                "stars": it.get("stargazers_count", 0),
            }
            if enqueue_repo(conn, url, query, priority=_seed_priority(cand)):
                added += 1
    if added:
        log_event(conn, "seed_refill", f"queue에 {added}개 repo 추가")
    return added


class ChallengeDaemon:
    """Challenge Miner 본체. run_cycle()을 반복 호출하는 구조라 테스트 가능하다."""

    def __init__(
        self,
        db_path: str | Path = "challenge.db",
        output_dir: str | Path = "runs",
        mode: str = "live",
        seeds_path: str | Path | None = None,
        settings: Settings | None = None,
        miner_settings: ChallengeMinerSettings | None = None,
        gh: GitHubClient | None = None,
        now_fn=None,
    ):
        self.db_path = str(db_path)
        self.output_dir = Path(output_dir)
        self.mode = mode
        self.settings = settings or load_settings()
        self.miner = miner_settings or load_challenge_miner_settings()
        self.gh = gh or GitHubClient(self.settings.github_token)
        self.seed_queries = load_seed_queries(seeds_path)
        # daemon 스레드들이 scheduler conn을 공유하므로 check_same_thread를 끈다 (내부 lock으로 보호)
        self.conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        open_db(self.db_path).close()  # 스키마 보장
        # 이전 실행이 비정상 종료돼 in_progress로 멈춘 큐 항목을 다시 대기로 되돌린다
        self.conn.execute("UPDATE repo_queue SET status='queued' WHERE status='in_progress'")
        self.conn.commit()
        keys = self.settings.google_keys
        if mode == "mock" and not keys:
            keys = {i: f"mock-key-{i}" for i in range(1, 12)}
        self.scheduler = ChallengeKeyScheduler(self.conn, keys, self.miner, now_fn=now_fn)
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()

    # ------------------------------------------------------------ seed

    def _seed_due(self) -> bool:
        counts = queue_counts(self.conn)
        if counts["queued"] < self.miner.queue_refill_threshold:
            return True
        last = get_setting(self.conn, "last_seed_at", "")
        if not last:
            return True
        try:
            last_dt = datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return True
        elapsed_min = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
        return elapsed_min >= self.miner.seed_interval_minutes

    def maybe_refill(self) -> int:
        if not self._seed_due():
            return 0
        added = refill_queue(self.conn, self.gh, self.seed_queries, self.miner.queue_refill_target)
        set_setting(self.conn, "last_seed_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        return added

    # ------------------------------------------------------------ worker

    def _process_one(self, key_id: int, api_key: str, queue_row: dict) -> None:
        """worker 스레드: 자기 전용 DB 연결로 repo 하나를 처리한다."""
        conn = open_db(self.db_path)
        repo_url = queue_row["repo_url"]
        queue_id = queue_row["id"]
        try:
            llm = None
            if self.mode != "mock":
                pool = KeyPool({key_id: api_key}, "round_robin")
                llm = GoogleGenAIGemmaClient(self.settings, pool, call_logger=LLMCallLogger(None))
            res = run_challenge(
                repo_url,
                mode=self.mode,
                output_dir=self.output_dir,
                settings=self.settings,
                gh=self.gh,
                llm=llm,
                db_conn=conn,
            )
            if res.get("error"):
                raise LLMCallError(res["error"])
            self.scheduler.release_success(key_id)
            finish_queue_item(conn, queue_id, "done")
        except Exception as exc:  # noqa: BLE001 - 한 repo 실패가 daemon을 죽이면 안 됨
            kind, msg = classify_challenge_error(exc)
            cooldown = self.scheduler.release_error(key_id, kind, msg)
            attempts = queue_row["attempts"]
            if attempts >= MAX_QUEUE_ATTEMPTS:
                finish_queue_item(conn, queue_id, "error", last_error=msg[:300])
                mark_repo_processed(conn, repo_url, "error")
            else:
                finish_queue_item(conn, queue_id, "queued", last_error=msg[:300], retry_delay_seconds=max(cooldown, 30.0))
            log_event(
                conn,
                "repo_error",
                f"{repo_url}: {kind}: {msg[:200]}",
                repo_url=repo_url,
                key_id=key_id,
                metadata={"cooldown_seconds": cooldown},
            )
        finally:
            conn.close()

    def dispatch(self) -> int:
        """가능한 key마다 queue 작업을 배정한다. 시작한 worker 수를 반환한다."""
        started = 0
        self._threads = [t for t in self._threads if t.is_alive()]
        while len(self._threads) < self.miner.max_concurrent_keys:
            if is_paused(self.conn):
                break
            acquired = self.scheduler.acquire()
            if acquired is None:
                break
            key_id, api_key = acquired
            row = claim_next_queued(self.conn)
            if row is None:
                # 작업이 없으면 key를 되돌린다 (성공/실패 카운트 없이)
                self.scheduler.release_idle(key_id)
                break
            t = threading.Thread(
                target=self._process_one, args=(key_id, api_key, dict(row)), daemon=True
            )
            t.start()
            self._threads.append(t)
            started += 1
        return started

    # ------------------------------------------------------------ loop

    def run_cycle(self) -> dict:
        """한 사이클: daily reset → (pause 확인) → seed refill → dispatch."""
        self.scheduler.maybe_daily_reset()
        if is_paused(self.conn):
            return {"paused": True, "started": 0, "queue": queue_counts(self.conn)}
        self.maybe_refill()
        started = self.dispatch()
        return {"paused": False, "started": started, "queue": queue_counts(self.conn)}

    def wait_workers(self, timeout: float | None = None) -> None:
        for t in list(self._threads):
            t.join(timeout)

    def run_forever(self, poll_seconds: float = 5.0, max_cycles: int | None = None) -> None:
        cycles = 0
        log_event(self.conn, "daemon_start", f"mode={self.mode} keys={len(self.scheduler.keys)}")
        try:
            while not self._stop.is_set():
                info = self.run_cycle()
                cycles += 1
                if max_cycles is not None and cycles >= max_cycles:
                    break
                q = info["queue"]
                print(
                    f"[daemon] paused={info['paused']} started={info['started']} "
                    f"queued={q['queued']} in_progress={q['in_progress']} done={q['done']} error={q['error']}"
                )
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            print("\n[daemon] 중지 요청 — 진행 중 작업을 기다립니다.")
        finally:
            self.wait_workers(timeout=60.0)
            log_event(self.conn, "daemon_stop", "daemon 종료")
            self.conn.close()


# ---------------------------------------------------------------- status/pause/resume

def daemon_status(db_path: str | Path = "challenge.db") -> dict:
    conn = open_db(db_path)
    try:
        counts = queue_counts(conn)
        challenge_count = conn.execute("SELECT COUNT(*) FROM challenges").fetchone()[0]
        error_count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type IN ('repo_error','llm_error','seed_error')"
        ).fetchone()[0]
        keys = [dict(r) for r in conn.execute("SELECT * FROM api_keys ORDER BY key_id")]
        recent = [
            dict(r)
            for r in conn.execute(
                "SELECT challenge_title, final_label, created_at FROM challenges ORDER BY id DESC LIMIT 5"
            )
        ]
        return {
            "paused": is_paused(conn),
            "queue": counts,
            "challenge_count": challenge_count,
            "error_count": error_count,
            "keys": keys,
            "recent_challenges": recent,
        }
    finally:
        conn.close()


def set_paused(db_path: str | Path, paused: bool) -> None:
    conn = open_db(db_path)
    try:
        set_setting(conn, "miner_paused", "true" if paused else "false")
        log_event(conn, "miner_paused" if paused else "miner_resumed", f"miner_paused={paused}")
    finally:
        conn.close()
