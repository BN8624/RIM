# 최대 11개 Google API key를 round-robin으로 회전시키는 key pool 모듈.
from __future__ import annotations

from enum import Enum

from repo_idea_miner.config import MAX_KEY_SLOTS
from repo_idea_miner.errors import NoAvailableKeyError


class KeyStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    TEMP_FAILED = "TEMP_FAILED"
    DISABLED = "DISABLED"


class KeyPool:
    """key 값은 절대 노출하지 않고 key index(1~11)만 기록한다."""

    def __init__(self, keys: dict[int, str], strategy: str = "round_robin"):
        self._keys = dict(keys)
        self._status: dict[int, KeyStatus] = {i: KeyStatus.AVAILABLE for i in self._keys}
        self._order = sorted(self._keys)
        self._cursor = 0
        self.strategy = strategy
        self.used_key_indexes: list[int] = []
        self.temp_failed_key_indexes: list[int] = []  # 누적 기록 (report용)

    @classmethod
    def from_env(cls, env, strategy: str = "round_robin") -> "KeyPool":
        from repo_idea_miner.config import load_google_keys

        return cls(load_google_keys(env), strategy=strategy)

    def __repr__(self) -> str:  # key 값 노출 방지
        return f"KeyPool(loaded={self.loaded_key_count}, disabled={self.disabled_key_indexes})"

    @property
    def loaded_key_count(self) -> int:
        return len(self._keys)

    @property
    def disabled_key_indexes(self) -> list[int]:
        return [i for i, s in self._status.items() if s == KeyStatus.DISABLED]

    def status_of(self, index: int) -> KeyStatus:
        return self._status[index]

    def new_cycle(self) -> None:
        """retry cycle 시작: TEMP_FAILED key를 다시 사용 가능하게 한다."""
        for i, s in self._status.items():
            if s == KeyStatus.TEMP_FAILED:
                self._status[i] = KeyStatus.AVAILABLE

    def acquire(self) -> tuple[int, str]:
        """round robin으로 다음 AVAILABLE key를 반환한다."""
        if not self._order:
            raise NoAvailableKeyError("로드된 Google API key가 없습니다.")
        n = len(self._order)
        for step in range(n):
            idx = self._order[(self._cursor + step) % n]
            if self._status[idx] == KeyStatus.AVAILABLE:
                self._cursor = (self._cursor + step + 1) % n
                if idx not in self.used_key_indexes:
                    self.used_key_indexes.append(idx)
                return idx, self._keys[idx]
        raise NoAvailableKeyError("현재 retry cycle에서 사용 가능한 key가 없습니다.")

    def mark_temp_failed(self, index: int) -> None:
        if self._status.get(index) == KeyStatus.AVAILABLE:
            self._status[index] = KeyStatus.TEMP_FAILED
        if index not in self.temp_failed_key_indexes:
            self.temp_failed_key_indexes.append(index)

    def mark_disabled(self, index: int) -> None:
        if index in self._status:
            self._status[index] = KeyStatus.DISABLED
