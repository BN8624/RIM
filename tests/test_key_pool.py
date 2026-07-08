# key pool 테스트 (§34.15, §34.16): 로딩, round robin, 상태 관리.
import pytest

from repo_idea_miner.config import load_google_keys
from repo_idea_miner.errors import NoAvailableKeyError
from repo_idea_miner.key_pool import KeyPool, KeyStatus


def test_load_11_keys(fake_env):
    keys = load_google_keys(fake_env)
    assert len(keys) == 11
    assert set(keys) == set(range(1, 12))


def test_partial_keys_loaded_count():
    env = {"GOOGLE_API_KEY_1": "AQ.k1_aaaaaaaaaaaaaaaaaa", "GOOGLE_API_KEY_7": "AQ.k7_aaaaaaaaaaaaaaaaaa"}
    pool = KeyPool.from_env(env)
    assert pool.loaded_key_count == 2


def test_key_values_not_in_repr(fake_env):
    pool = KeyPool.from_env(fake_env)
    text = repr(pool)
    for value in fake_env.values():
        assert value not in text


def test_round_robin_rotation(fake_env):
    pool = KeyPool.from_env(fake_env)
    indexes = [pool.acquire()[0] for _ in range(5)]
    assert indexes == [1, 2, 3, 4, 5]
    # 11개를 지나면 다시 처음으로
    for _ in range(6):
        pool.acquire()
    assert pool.acquire()[0] == 1


def test_no_key_concentration(fake_env):
    pool = KeyPool.from_env(fake_env)
    indexes = [pool.acquire()[0] for _ in range(22)]
    assert all(indexes.count(i) == 2 for i in range(1, 12))


def test_temp_failed_skipped_in_cycle(fake_env):
    pool = KeyPool.from_env(fake_env)
    idx, _ = pool.acquire()
    pool.mark_temp_failed(idx)
    next_idx, _ = pool.acquire()
    assert next_idx != idx


def test_temp_failed_recovers_next_cycle(fake_env):
    pool = KeyPool.from_env(fake_env)
    pool.mark_temp_failed(1)
    assert pool.status_of(1) == KeyStatus.TEMP_FAILED
    pool.new_cycle()
    assert pool.status_of(1) == KeyStatus.AVAILABLE


def test_disabled_never_returned(fake_env):
    pool = KeyPool.from_env(fake_env)
    pool.mark_disabled(1)
    pool.new_cycle()
    indexes = {pool.acquire()[0] for _ in range(20)}
    assert 1 not in indexes


def test_empty_pool_raises():
    pool = KeyPool({})
    with pytest.raises(NoAvailableKeyError):
        pool.acquire()
