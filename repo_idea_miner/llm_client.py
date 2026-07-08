# google_genai_gemma provider: key pool 회전, retry/backoff/failover, JSON 파싱을 담당하는 LLM 클라이언트.
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path

from repo_idea_miner.config import Settings
from repo_idea_miner.errors import (
    LLMAuthError,
    LLMCallError,
    LLMConfigError,
    NoAvailableKeyError,
)
from repo_idea_miner.jsonutil import parse_json_with_repair
from repo_idea_miner.key_pool import KeyPool
from repo_idea_miner.redaction import redact_text


def compute_retry_delay(attempt: int, initial: float = 2.0, max_delay: float = 60.0, rng=random) -> float:
    """exponential backoff + jitter. attempt는 0부터 시작한다."""
    base = min(max_delay, initial * (2**attempt))
    jitter = rng.uniform(0, base * 0.25)
    return min(base + jitter, max_delay * 1.25)


_RETRY_AFTER_RES = [
    re.compile(r"retry[-_ ]?after[\"':\s]+(\d+(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"retryDelay[\"']?\s*:\s*[\"']?(\d+(?:\.\d+)?)s", re.IGNORECASE),
]

_TRANSIENT_MARKERS = (
    "429",
    "resource_exhausted",
    "rate limit",
    "500",
    "internal",
    "502",
    "bad_gateway",
    "bad gateway",
    "503",
    "unavailable",
    "504",
    "deadline_exceeded",
    "gateway_timeout",
    "408",
    "timeout",
    "timed out",
    "connection reset",
    "connection aborted",
    "temporarily",
)
_AUTH_MARKERS = (
    "401",
    "unauthenticated",
    "403",
    "permission_denied",
    "permission denied",
    "api key not valid",
    "api_key_invalid",
    "invalid api key",
)
_MODEL_MARKERS = ("not found", "not_found", "404")


def parse_retry_after(message: str) -> float | None:
    for r in _RETRY_AFTER_RES:
        m = r.search(message)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    return None


def classify_llm_error(exc: Exception) -> tuple[str, float | None]:
    """예외를 ('transient'|'auth'|'fatal_model'|'fatal', retry_after_seconds)로 분류한다."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    msg = str(exc).lower()
    retry_after = getattr(exc, "retry_after", None)
    if retry_after is None:
        retry_after = parse_retry_after(str(exc))

    if code in (401, 403) or any(m in msg for m in _AUTH_MARKERS):
        return "auth", None
    if (code == 404 or "404" in msg or "not found" in msg or "not_found" in msg) and "model" in msg:
        return "fatal_model", None
    if code in (408, 429, 500, 502, 503, 504) or any(m in msg for m in _TRANSIENT_MARKERS):
        return "transient", retry_after
    if code == 400 or "invalid_argument" in msg or "400" in msg:
        return "fatal", None
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return "transient", retry_after
    return "fatal", None


class LLMCallLogger:
    """debug/llm_calls.jsonl에 호출 단위 기록을 남긴다. secret은 기록하지 않는다."""

    def __init__(self, path: Path | None, secret_values: list[str] | None = None):
        self.path = Path(path) if path else None
        self.secret_values = list(secret_values or [])
        self.entries: list[dict] = []

    def log(self, **fields) -> None:
        entry = dict(fields)
        self.entries.append(entry)
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = redact_text(json.dumps(entry, ensure_ascii=False), self.secret_values)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


class LLMClient:
    """LLM provider 공통 인터페이스."""

    def generate_json(
        self,
        prompt: str,
        schema_name: str,
        model: str | None = None,
        temperature: float = 0.2,
        max_retries: int = 3,
        worker: str | None = None,
    ) -> dict:
        raise NotImplementedError


class GoogleGenAIGemmaClient(LLMClient):
    """google-genai SDK 기반 Gemma 호출 클라이언트. transport는 테스트를 위해 주입 가능하다."""

    def __init__(
        self,
        settings: Settings,
        key_pool: KeyPool,
        call_logger: LLMCallLogger | None = None,
        transport=None,
        sleep_fn=time.sleep,
        rng=random,
    ):
        self.settings = settings
        self.key_pool = key_pool
        self.logger = call_logger or LLMCallLogger(None)
        self._transport = transport or self._sdk_call
        self._sleep = sleep_fn
        self._rng = rng
        self.retry_count = 0
        self.failover_count = 0

    def _sdk_call(self, api_key: str, prompt: str, model: str, temperature: float, timeout_seconds: float) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)),
        )
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=temperature),
        )
        return response.text or ""

    def generate_json(
        self,
        prompt: str,
        schema_name: str,
        model: str | None = None,
        temperature: float | None = None,
        max_retries: int | None = None,
        worker: str | None = None,
    ) -> dict:
        model = model or self.settings.model
        temperature = self.settings.temperature if temperature is None else temperature
        max_retries = max_retries or self.settings.max_retries_per_call
        worker = worker or schema_name

        self.key_pool.new_cycle()
        attempt = 0
        last_error: str | None = None

        while attempt < max_retries:
            try:
                key_index, api_key = self.key_pool.acquire()
            except NoAvailableKeyError:
                disabled = len(self.key_pool.disabled_key_indexes)
                if disabled and disabled >= self.key_pool.loaded_key_count:
                    raise LLMAuthError(f"{worker}: 모든 key가 인증 실패(DISABLED)로 run 실패.")
                raise
            start = time.monotonic()
            error_type = None
            retry_after = None
            backoff_delay = 0.0
            text = None
            try:
                text = self._transport(api_key, prompt, model, temperature, self.settings.request_timeout_seconds)
            except Exception as exc:  # noqa: BLE001 - provider 예외 전 분류
                kind, retry_after = classify_llm_error(exc)
                error_type = type(exc).__name__ + ":" + redact_text(str(exc)[:200])
                latency_ms = int((time.monotonic() - start) * 1000)
                if kind == "auth":
                    self.key_pool.mark_disabled(key_index)
                    self.failover_count += 1
                    self._log(worker, model, key_index, attempt + 1, False, latency_ms, error_type, retry_after, 0.0, prompt, None, False, None)
                    last_error = error_type
                    continue  # 다른 key로 같은 요청 재시도 (attempt 미소진)
                if kind == "fatal_model":
                    self._log(worker, model, key_index, attempt + 1, False, latency_ms, error_type, retry_after, 0.0, prompt, None, False, None)
                    raise LLMConfigError(f"{worker}: model not found / invalid model name ({model}). 전체 설정 오류로 즉시 실패.") from exc
                if kind == "fatal":
                    self._log(worker, model, key_index, attempt + 1, False, latency_ms, error_type, retry_after, 0.0, prompt, None, False, None)
                    raise LLMConfigError(f"{worker}: 재시도 불가 오류 (invalid payload/schema/prompt bug).") from exc
                # transient
                self.key_pool.mark_temp_failed(key_index)
                self.retry_count += 1
                self.failover_count += 1
                attempt += 1
                if attempt >= max_retries:
                    self._log(worker, model, key_index, attempt, False, latency_ms, error_type, retry_after, 0.0, prompt, None, False, None)
                    last_error = error_type
                    break
                if self.settings.respect_retry_after and retry_after is not None:
                    backoff_delay = min(float(retry_after), self.settings.retry_after_max_seconds)
                else:
                    backoff_delay = compute_retry_delay(
                        attempt - 1,
                        initial=self.settings.retry_initial_delay_seconds,
                        max_delay=self.settings.retry_max_delay_seconds,
                        rng=self._rng,
                    )
                self._log(worker, model, key_index, attempt, False, latency_ms, error_type, retry_after, backoff_delay, prompt, None, False, False)
                self._sleep(backoff_delay)
                continue

            latency_ms = int((time.monotonic() - start) * 1000)
            parsed, repair_used = parse_json_with_repair(text, self.settings.json_repair_attempts)
            if parsed is None:
                self.retry_count += 1
                attempt += 1
                self._log(worker, model, key_index, attempt, False, latency_ms, "JSON_PARSE_FAIL", None, 0.0, prompt, text, False, None, repair_used)
                last_error = "JSON_PARSE_FAIL"
                continue
            self._log(worker, model, key_index, attempt + 1, True, latency_ms, None, retry_after, backoff_delay, prompt, text, True, None, repair_used)
            return parsed

        raise LLMCallError(f"{worker}: LLM 호출이 {max_retries}회 재시도 후 실패했습니다. last_error={last_error}")

    def _log(
        self,
        worker,
        model,
        key_index,
        attempt,
        success,
        latency_ms,
        error_type,
        retry_after,
        backoff_delay,
        prompt,
        output,
        json_parse_success,
        validation_success=None,  # Pydantic validation은 pipeline 단계에서 확정되므로 여기서는 null
        repair_used=False,
    ) -> None:
        self.logger.log(
            worker=worker,
            model=model,
            key_index=key_index,
            attempt=attempt,
            success=success,
            latency_ms=latency_ms,
            error_type=error_type,
            retry_after_seconds=retry_after,
            backoff_delay_seconds=round(float(backoff_delay), 3),
            input_chars=len(prompt or ""),
            output_chars=len(output or "") if output else 0,
            json_parse_success=json_parse_success,
            validation_success=validation_success,
            repair_used=repair_used,
        )


class MockLLMClient(LLMClient):
    """mock 모드: 외부 호출 없이 schema별 결정적 JSON을 반환한다."""

    def __init__(self, overrides: dict[str, dict] | None = None, call_logger: LLMCallLogger | None = None):
        self.overrides = overrides or {}
        self.logger = call_logger or LLMCallLogger(None)

    def generate_json(
        self,
        prompt: str,
        schema_name: str,
        model: str | None = None,
        temperature: float = 0.2,
        max_retries: int = 3,
        worker: str | None = None,
    ) -> dict:
        from repo_idea_miner.workers import mock_output

        out = self.overrides.get(schema_name) or mock_output(schema_name)
        self.logger.log(
            worker=worker or schema_name,
            model="mock",
            key_index=0,
            attempt=1,
            success=True,
            latency_ms=0,
            error_type=None,
            retry_after_seconds=None,
            backoff_delay_seconds=0,
            input_chars=len(prompt or ""),
            output_chars=len(json.dumps(out, ensure_ascii=False)),
            json_parse_success=True,
            validation_success=None,
            repair_used=False,
        )
        return json.loads(json.dumps(out))  # deep copy
