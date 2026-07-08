# Challenge Miner용 DB-backed 11-key controlled parallel pool 스케줄러 (§18~§19).
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from repo_idea_miner.config import ChallengeMinerSettings

KEY_STATUSES = ("available", "in_flight", "cooldown", "exhausted", "disabled")

_QUOTA_MARKERS = ("daily", "per day", "rpd", "quota exceeded", "quota_exceeded")


def is_daily_quota_exhausted(message: str) -> bool:
    """명확한 daily quota/RPD exhausted 메시지인지 판단한다. 단순 429는 False."""
    msg = (message or "").lower()
    if "quota" not in msg and "rpd" not in msg:
        return False
    return any(m in msg for m in _QUOTA_MARKERS)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ChallengeKeyScheduler:
    """api_keys 테이블 기반 key 스케줄러.

    - key 1개당 동시 1개 작업 (in_flight)
    - 에러 난 key만 cooldown, 나머지는 계속 작업
    - 429/500 → transient backoff 시퀀스 (30→60→120→300)
    - timeout → timeout backoff 시퀀스 (60→120→300)
    - 명확한 daily quota exhausted 메시지에만 exhausted 처리
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        keys: dict[int, str],
        settings: ChallengeMinerSettings | None = None,
        now_fn=None,
    ):
        self.conn = conn
        self.keys = dict(keys)
        self.settings = settings or ChallengeMinerSettings()
        self._now = now_fn or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._success_streak: dict[int, int] = {}
        self._sync_rows()

    # ------------------------------------------------------------ 내부

    def _sync_rows(self) -> None:
        with self._lock:
            for key_id in self.keys:
                self.conn.execute(
                    "INSERT OR IGNORE INTO api_keys(key_id, status) VALUES(?, 'available')", (key_id,)
                )
            # 이전 실행에서 in_flight로 남은 key는 복구한다
            self.conn.execute("UPDATE api_keys SET status='available' WHERE status='in_flight'")
            self.conn.commit()

    def _row(self, key_id: int) -> sqlite3.Row:
        return self.conn.execute("SELECT * FROM api_keys WHERE key_id=?", (key_id,)).fetchone()

    # ------------------------------------------------------------ 획득/반납

    def acquire(self) -> tuple[int, str] | None:
        """사용 가능한 key를 in_flight로 전환해 (key_id, key)를 반환한다. 없으면 None."""
        now = self._now()
        now_iso = _iso(now)
        min_interval = timedelta(seconds=self.settings.key_min_interval_seconds)
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM api_keys WHERE key_id IN ({}) ORDER BY last_used_at IS NOT NULL, last_used_at".format(
                    ",".join("?" * len(self.keys))
                ),
                tuple(self.keys),
            ).fetchall()
            for row in rows:
                if row["status"] == "cooldown" and (row["next_available_at"] or "") <= now_iso:
                    # cooldown 만료 → 다시 사용 가능
                    pass
                elif row["status"] != "available":
                    continue
                if row["daily_used"] >= self.settings.key_daily_rpd_limit:
                    continue
                if row["last_used_at"]:
                    last = datetime.strptime(row["last_used_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                        tzinfo=timezone.utc
                    )
                    if now - last < min_interval:
                        continue
                key_id = row["key_id"]
                self.conn.execute(
                    "UPDATE api_keys SET status='in_flight', last_used_at=? WHERE key_id=?",
                    (now_iso, key_id),
                )
                self.conn.commit()
                return key_id, self.keys[key_id]
        return None

    def release_success(self, key_id: int) -> None:
        now_iso = _iso(self._now())
        with self._lock:
            streak = self._success_streak.get(key_id, 0) + 1
            self._success_streak[key_id] = streak
            reset_errors = streak >= self.settings.backoff_reset_after_success
            if reset_errors:
                self.conn.execute(
                    "UPDATE api_keys SET status='available', daily_used=daily_used+1, "
                    "consecutive_errors=0, last_error_type=NULL, last_success_at=?, next_available_at=NULL "
                    "WHERE key_id=?",
                    (now_iso, key_id),
                )
            else:
                self.conn.execute(
                    "UPDATE api_keys SET status='available', daily_used=daily_used+1, "
                    "last_success_at=?, next_available_at=NULL WHERE key_id=?",
                    (now_iso, key_id),
                )
            self.conn.commit()

    def release_idle(self, key_id: int) -> None:
        """작업 배정 없이 획득만 했던 key를 available로 되돌린다."""
        with self._lock:
            self.conn.execute(
                "UPDATE api_keys SET status='available' WHERE key_id=? AND status='in_flight'",
                (key_id,),
            )
            self.conn.commit()

    def release_error(self, key_id: int, error_kind: str, message: str = "") -> float:
        """에러 종류에 따라 해당 key만 cooldown/exhausted/disabled 처리한다.

        반환값은 적용된 cooldown 초 (없으면 0). 다른 key는 영향을 받지 않는다.
        """
        now = self._now()
        with self._lock:
            self._success_streak[key_id] = 0
            row = self._row(key_id)
            errors = (row["consecutive_errors"] if row else 0) + 1

            if error_kind == "auth":
                self.conn.execute(
                    "UPDATE api_keys SET status='disabled', consecutive_errors=?, last_error_type=? "
                    "WHERE key_id=?",
                    (errors, f"auth:{message[:120]}", key_id),
                )
                self.conn.commit()
                return 0.0

            if error_kind == "exhausted" or is_daily_quota_exhausted(message):
                next_avail = _iso(now + timedelta(hours=24))
                self.conn.execute(
                    "UPDATE api_keys SET status='exhausted', consecutive_errors=?, last_error_type=?, "
                    "next_available_at=? WHERE key_id=?",
                    (errors, f"exhausted:{message[:120]}", next_avail, key_id),
                )
                self.conn.commit()
                return 0.0

            seq = (
                self.settings.timeout_backoff_sequence
                if error_kind == "timeout"
                else self.settings.transient_backoff_sequence
            )
            cooldown = seq[min(errors - 1, len(seq) - 1)]
            next_avail = _iso(now + timedelta(seconds=cooldown))
            self.conn.execute(
                "UPDATE api_keys SET status='cooldown', consecutive_errors=?, last_error_type=?, "
                "next_available_at=? WHERE key_id=?",
                (errors, f"{error_kind}:{message[:120]}", next_avail, key_id),
            )
            self.conn.commit()
            return cooldown

    # ------------------------------------------------------------ daily reset

    def _reset_period_start(self, now: datetime) -> str:
        local_now = now.astimezone()  # RIM_DAILY_USAGE_TIMEZONE=local 기준
        start = local_now.replace(
            hour=self.settings.daily_usage_reset_hour, minute=0, second=0, microsecond=0
        )
        if local_now < start:
            start -= timedelta(days=1)
        return _iso(start)

    def maybe_daily_reset(self) -> bool:
        """로컬 날짜 기준 reset 시각이 지났으면 daily_used를 초기화한다."""
        from repo_idea_miner.challenge_db import get_setting, set_setting

        now = self._now()
        period_start = self._reset_period_start(now)
        with self._lock:
            last = get_setting(self.conn, "daily_usage_last_reset", "")
        if (last or "") >= period_start:
            return False
        with self._lock:
            self.conn.execute(
                "UPDATE api_keys SET daily_used=0, status='available', next_available_at=NULL "
                "WHERE status='exhausted'"
            )
            self.conn.execute("UPDATE api_keys SET daily_used=0")
            self.conn.commit()
        set_setting(self.conn, "daily_usage_last_reset", _iso(now))
        return True

    # ------------------------------------------------------------ 상태

    def snapshot(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute("SELECT * FROM api_keys ORDER BY key_id").fetchall()
        return [dict(r) for r in rows]


def classify_challenge_error(exc: Exception) -> tuple[str, str]:
    """예외를 scheduler용 ('transient'|'timeout'|'exhausted'|'auth'|'fatal', message)로 분류한다."""
    from repo_idea_miner.errors import LLMAuthError, LLMConfigError
    from repo_idea_miner.llm_client import classify_llm_error

    msg = str(exc)
    if isinstance(exc, LLMAuthError):
        return "auth", msg
    if isinstance(exc, LLMConfigError):
        return "fatal", msg
    if is_daily_quota_exhausted(msg):
        return "exhausted", msg
    lower = msg.lower()
    if "timeout" in lower or "timed out" in lower or "deadline" in lower:
        return "timeout", msg
    kind, _ = classify_llm_error(exc)
    if kind == "auth":
        return "auth", msg
    if kind in ("fatal", "fatal_model"):
        return "fatal", msg
    return "transient", msg
