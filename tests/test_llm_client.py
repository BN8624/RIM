# LLM 클라이언트 테스트 (§34.17~§34.23): failover, invalid key, retry-after, backoff, timeout, 모델 설정.
import json
import random

import pytest

from repo_idea_miner.config import Settings, load_google_keys, load_settings
from repo_idea_miner.errors import LLMCallError, LLMConfigError
from repo_idea_miner.key_pool import KeyPool, KeyStatus
from repo_idea_miner.llm_client import (
    GoogleGenAIGemmaClient,
    compute_retry_delay,
    classify_llm_error,
)


class FakeError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def make_client(fake_env, transport, settings=None, sleeps=None):
    settings = settings or Settings(google_keys=load_google_keys(fake_env), retry_initial_delay_seconds=0.01, retry_max_delay_seconds=0.05)
    pool = KeyPool(settings.google_keys)
    recorded = sleeps if sleeps is not None else []
    client = GoogleGenAIGemmaClient(settings, pool, transport=transport, sleep_fn=recorded.append, rng=random.Random(42))
    return client, pool, recorded


GOOD_JSON = json.dumps({"ok": True})


# ---- §34.17 failover ----

@pytest.mark.parametrize("message,code", [("429 RESOURCE_EXHAUSTED", 429), ("503 UNAVAILABLE", 503), ("request timed out", None)])
def test_transient_error_fails_over_to_next_key(fake_env, message, code):
    calls = []

    def transport(api_key, prompt, model, temperature, timeout):
        calls.append(api_key)
        if len(calls) == 1:
            raise FakeError(message, code=code)
        return GOOD_JSON

    client, pool, _ = make_client(fake_env, transport)
    result = client.generate_json("p", "bouncer")
    assert result == {"ok": True}
    assert calls[0] != calls[1]  # 다른 key로 재시도
    assert client.failover_count >= 1


# ---- §34.18 invalid key ----

@pytest.mark.parametrize("message,code", [("401 UNAUTHENTICATED", 401), ("403 PERMISSION_DENIED", 403), ("API key not valid", None)])
def test_auth_error_disables_key(fake_env, message, code):
    calls = []

    def transport(api_key, prompt, model, temperature, timeout):
        calls.append(api_key)
        if len(calls) == 1:
            raise FakeError(message, code=code)
        return GOOD_JSON

    client, pool, _ = make_client(fake_env, transport)
    result = client.generate_json("p", "bouncer")
    assert result == {"ok": True}
    assert pool.status_of(1) == KeyStatus.DISABLED
    # DISABLED는 다음 cycle에도 복구되지 않음
    pool.new_cycle()
    assert pool.status_of(1) == KeyStatus.DISABLED


# ---- §34.19 model config ----

def test_default_model_is_gemma_4_31b_it():
    settings = load_settings(env={})
    assert settings.model == "gemma-4-31b-it"


def test_model_override_via_env():
    settings = load_settings(env={"RIM_GEMMA_MODEL": "gemma-4-9b-it"})
    assert settings.model == "gemma-4-9b-it"


def test_model_not_found_fails_immediately(fake_env):
    calls = []

    def transport(api_key, prompt, model, temperature, timeout):
        calls.append(1)
        raise FakeError("404 model gemma-x not found", code=404)

    client, _, _ = make_client(fake_env, transport)
    with pytest.raises(LLMConfigError):
        client.generate_json("p", "bouncer")
    assert len(calls) == 1  # 다른 key로 반복 재시도하지 않음


def test_transport_receives_model_name(fake_env):
    seen = {}

    def transport(api_key, prompt, model, temperature, timeout):
        seen["model"] = model
        return GOOD_JSON

    client, _, _ = make_client(fake_env, transport)
    client.generate_json("p", "bouncer")
    assert seen["model"] == "gemma-4-31b-it"


# ---- §34.20 Retry-After ----

def test_retry_after_respected(fake_env):
    calls = []

    def transport(api_key, prompt, model, temperature, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise FakeError('429 RESOURCE_EXHAUSTED retryDelay: "7s"', code=429)
        return GOOD_JSON

    client, _, sleeps = make_client(fake_env, transport)
    client.generate_json("p", "bouncer")
    assert sleeps and sleeps[0] == pytest.approx(7.0)


def test_retry_after_capped(fake_env):
    calls = []

    def transport(api_key, prompt, model, temperature, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise FakeError("429 rate limit, Retry-After: 9999", code=429)
        return GOOD_JSON

    settings = Settings(google_keys=load_google_keys(fake_env), retry_after_max_seconds=300)
    client, _, sleeps = make_client(fake_env, transport, settings=settings)
    client.generate_json("p", "bouncer")
    assert sleeps[0] <= 300


def test_backoff_used_when_no_retry_after(fake_env):
    calls = []

    def transport(api_key, prompt, model, temperature, timeout):
        calls.append(1)
        if len(calls) < 3:
            raise FakeError("503 UNAVAILABLE", code=503)
        return GOOD_JSON

    client, _, sleeps = make_client(fake_env, transport)
    client.generate_json("p", "bouncer")
    assert len(sleeps) == 2
    assert all(s > 0 for s in sleeps)


# ---- §34.21 exponential backoff ----

def test_backoff_increases_and_capped():
    rng = random.Random(0)
    delays = [compute_retry_delay(a, initial=2.0, max_delay=60.0, rng=rng) for a in range(6)]
    assert delays[0] >= 2.0
    # base가 지수적으로 증가한다 (base 부분 비교)
    assert 2.0 * (2**1) <= delays[1] + 1e9  # sanity
    bases = [min(60.0, 2.0 * (2**a)) for a in range(6)]
    for d, b in zip(delays, bases):
        assert b <= d <= b * 1.25 + 1e-9
    assert max(delays) <= 60.0 * 1.25


def test_backoff_has_jitter():
    rng = random.Random(1)
    delays = {compute_retry_delay(2, rng=rng) for _ in range(10)}
    assert len(delays) > 1


# ---- §34.22 같은 retry cycle 내 key 재사용 금지 ----

def test_failed_key_not_reused_in_same_cycle(fake_env):
    used = []

    def transport(api_key, prompt, model, temperature, timeout):
        used.append(api_key)
        raise FakeError("429 RESOURCE_EXHAUSTED", code=429)

    client, _, _ = make_client(fake_env, transport)
    with pytest.raises(LLMCallError):
        client.generate_json("p", "bouncer", max_retries=3)
    assert len(used) == len(set(used))  # 같은 key 즉시 재사용 없음


def test_next_worker_call_can_reuse_temp_failed_key(fake_env):
    calls = {"n": 0}

    def transport(api_key, prompt, model, temperature, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise FakeError("429", code=429)
        return GOOD_JSON

    client, pool, _ = make_client(fake_env, transport)
    client.generate_json("p", "bouncer")
    pool_status_after = pool.status_of(1)
    # 다음 worker 호출 시 new_cycle로 TEMP_FAILED가 풀린다
    client.generate_json("p", "readme_scout")
    assert pool.status_of(1) == KeyStatus.AVAILABLE


# ---- 단일 키 pool 백오프 재시도 (Challenge Miner 워커) ----

def test_single_key_retries_same_key_then_succeeds():
    """키 1개 pool은 transient 후 NoAvailableKeyError로 죽지 않고 같은 키로 재시도한다."""
    settings = Settings(google_keys={1: "AQ.single_key_aaaaaaaaaaaaaaaa"},
                        retry_initial_delay_seconds=0.01, retry_max_delay_seconds=0.05)
    pool = KeyPool(settings.google_keys)
    calls = {"n": 0}

    def transport(api_key, prompt, model, temperature, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise FakeError("500 internal", code=500)
        return GOOD_JSON

    client = GoogleGenAIGemmaClient(settings, pool, transport=transport, sleep_fn=lambda s: None)
    assert client.generate_json("p", "challenge_package") == {"ok": True}
    assert calls["n"] == 2  # 같은 키로 재시도해 성공


def test_single_key_persistent_transient_raises_llmcallerror():
    """지속 transient면 NoAvailableKeyError가 아니라 원인이 담긴 LLMCallError를 던진다."""
    settings = Settings(google_keys={1: "AQ.single_key_bbbbbbbbbbbbbbbb"},
                        retry_initial_delay_seconds=0.01, retry_max_delay_seconds=0.05)
    pool = KeyPool(settings.google_keys)

    def transport(api_key, prompt, model, temperature, timeout):
        raise FakeError("429 RESOURCE_EXHAUSTED", code=429)

    client = GoogleGenAIGemmaClient(settings, pool, transport=transport, sleep_fn=lambda s: None)
    with pytest.raises(LLMCallError) as exc:
        client.generate_json("p", "challenge_package", max_retries=3)
    assert "429" in str(exc.value)  # 원인 전파 → scheduler가 transient로 분류 가능


# ---- §34.23 request timeout ----

def test_timeout_setting_passed_to_transport(fake_env):
    seen = {}

    def transport(api_key, prompt, model, temperature, timeout):
        seen["timeout"] = timeout
        return GOOD_JSON

    settings = Settings(google_keys=load_google_keys(fake_env), request_timeout_seconds=123.0)
    client, _, _ = make_client(fake_env, transport, settings=settings)
    client.generate_json("p", "bouncer")
    assert seen["timeout"] == 123.0


def test_timeout_default_180():
    settings = load_settings(env={})
    assert settings.request_timeout_seconds == 180.0


def test_timeout_env_override():
    settings = load_settings(env={"RIM_REQUEST_TIMEOUT_SECONDS": "60"})
    assert settings.request_timeout_seconds == 60.0


# ---- key index 회전 (§7.4 worker별 회전) ----

def test_workers_rotate_key_indexes(fake_env):
    def transport(api_key, prompt, model, temperature, timeout):
        return GOOD_JSON

    client, pool, _ = make_client(fake_env, transport)
    for worker in ("bouncer", "readme_scout", "pain_scout", "structure_risk_scout", "critic_judge"):
        client.generate_json("p", worker, worker=worker)
    assert pool.used_key_indexes == [1, 2, 3, 4, 5]


# ---- error 분류 단위 테스트 ----

def test_classify_transient():
    kind, _ = classify_llm_error(FakeError("429 RESOURCE_EXHAUSTED", code=429))
    assert kind == "transient"


def test_classify_auth():
    kind, _ = classify_llm_error(FakeError("API key not valid"))
    assert kind == "auth"
