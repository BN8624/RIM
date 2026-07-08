# 테스트 공용 fixture: mock judge JSON, 가짜 key 환경 등.
from __future__ import annotations

import pytest

from repo_idea_miner.workers import mock_output


@pytest.fixture
def judge_json() -> dict:
    return mock_output("critic_judge")


@pytest.fixture
def fake_env() -> dict:
    env = {f"GOOGLE_API_KEY_{i}": f"AQ.fake_key_value_{i:02d}_abcdefghijklmnop" for i in range(1, 12)}
    env["GITHUB_TOKEN"] = "ghp_faketoken1234567890abcd"
    return env
