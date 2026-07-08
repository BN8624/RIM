# 환경변수(.env) 로딩과 실행 설정(Settings)을 관리하는 모듈.
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

DEFAULT_MODEL = "gemma-4-31b-it"
DEFAULT_PROVIDER = "google_genai_gemma"
MAX_KEY_SLOTS = 11


def _get_str(env, key: str, default: str) -> str:
    v = (env.get(key) or "").strip()
    return v or default


def _get_int(env, key: str, default: int) -> int:
    try:
        return int((env.get(key) or "").strip())
    except (ValueError, AttributeError):
        return default


def _get_float(env, key: str, default: float) -> float:
    try:
        return float((env.get(key) or "").strip())
    except (ValueError, AttributeError):
        return default


def _get_bool(env, key: str, default: bool) -> bool:
    v = (env.get(key) or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


@dataclass
class Settings:
    model: str = DEFAULT_MODEL
    provider: str = DEFAULT_PROVIDER
    key_pool_strategy: str = "round_robin"
    max_retries_per_call: int = 3
    retry_backoff_strategy: str = "exponential_jitter"
    retry_initial_delay_seconds: float = 2.0
    retry_max_delay_seconds: float = 60.0
    respect_retry_after: bool = True
    retry_after_max_seconds: float = 300.0
    request_timeout_seconds: float = 180.0
    temperature: float = 0.2
    json_repair_attempts: int = 1
    github_token: str | None = None
    google_keys: dict[int, str] = field(default_factory=dict, repr=False)

    @property
    def loaded_key_count(self) -> int:
        return len(self.google_keys)

    @property
    def configured_key_count(self) -> int:
        return MAX_KEY_SLOTS

    def secret_values(self) -> list[str]:
        vals = [v for v in self.google_keys.values() if v]
        if self.github_token:
            vals.append(self.github_token)
        return vals


def load_google_keys(env) -> dict[int, str]:
    keys: dict[int, str] = {}
    for i in range(1, MAX_KEY_SLOTS + 1):
        v = (env.get(f"GOOGLE_API_KEY_{i}") or "").strip()
        if v:
            keys[i] = v
    if not keys:
        # 하위호환: 단일 GOOGLE_API_KEY만 있으면 index 1로 사용
        v = (env.get("GOOGLE_API_KEY") or "").strip()
        if v:
            keys[1] = v
    return keys


def load_settings(env=None, dotenv_path: str | Path | None = None) -> Settings:
    if env is None:
        if load_dotenv is not None:
            load_dotenv(dotenv_path or (Path.cwd() / ".env"))
        env = os.environ
    return Settings(
        model=_get_str(env, "RIM_GEMMA_MODEL", DEFAULT_MODEL),
        provider=_get_str(env, "RIM_LLM_PROVIDER", DEFAULT_PROVIDER),
        key_pool_strategy=_get_str(env, "RIM_KEY_POOL_STRATEGY", "round_robin"),
        max_retries_per_call=_get_int(env, "RIM_MAX_RETRIES_PER_CALL", 3),
        retry_backoff_strategy=_get_str(env, "RIM_RETRY_BACKOFF_STRATEGY", "exponential_jitter"),
        retry_initial_delay_seconds=_get_float(env, "RIM_RETRY_INITIAL_DELAY_SECONDS", 2.0),
        retry_max_delay_seconds=_get_float(env, "RIM_RETRY_MAX_DELAY_SECONDS", 60.0),
        respect_retry_after=_get_bool(env, "RIM_RESPECT_RETRY_AFTER", True),
        retry_after_max_seconds=_get_float(env, "RIM_RETRY_AFTER_MAX_SECONDS", 300.0),
        request_timeout_seconds=_get_float(env, "RIM_REQUEST_TIMEOUT_SECONDS", 180.0),
        temperature=_get_float(env, "RIM_TEMPERATURE", 0.2),
        json_repair_attempts=_get_int(env, "RIM_JSON_REPAIR_ATTEMPTS", 1),
        github_token=(env.get("GITHUB_TOKEN") or "").strip() or None,
        google_keys=load_google_keys(env),
    )
