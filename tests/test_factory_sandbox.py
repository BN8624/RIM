# Docker 샌드박스 명령 구성(§13)·mount/network 정책·로컬 fallback 환경 차단 테스트.
from pathlib import Path

import pytest

from repo_idea_miner.factory_sandbox import (
    _local_env,
    build_docker_command,
    mount_policy_violations,
    run_in_sandbox,
)


def test_install_phase_allows_network_execute_phase_blocks(tmp_path):
    """dependency install 단계와 execution/test 단계 분리 (§22-30)."""
    install = build_docker_command(tmp_path, "pip install -r requirements.txt", "install", "python:3.12-slim")
    execute = build_docker_command(tmp_path, "python main.py --help", "execute", "python:3.12-slim")
    assert "--network" not in install  # install은 기본 network (제한적 허용)
    assert "none" in execute[execute.index("--network") + 1]


def test_docker_command_mounts_only_workspace(tmp_path):
    """.env/API key/home 디렉터리를 mount하지 않는다 (§22-31)."""
    cmd = build_docker_command(tmp_path, "echo hi", "execute", "python:3.12-slim")
    mounts = [cmd[i + 1] for i, part in enumerate(cmd) if part == "-v"]
    assert len(mounts) == 1
    assert mounts[0].split(":")[0].startswith(str(tmp_path.resolve())[:3]) or str(tmp_path) in mounts[0]
    assert str(Path.home()) != mounts[0].split(":")[0]
    assert ".env" not in mounts[0]
    assert mount_policy_violations(cmd) == []


def test_docker_command_has_cpu_memory_limits(tmp_path):
    cmd = build_docker_command(tmp_path, "echo hi", "execute", "python:3.12-slim")
    assert "--cpus" in cmd and "--memory" in cmd


def test_mount_policy_violations_detects_home_and_env(tmp_path):
    bad_home = ["docker", "run", "-v", f"{Path.home()}:/host", "img"]
    assert any("home" in p for p in mount_policy_violations(bad_home))
    bad_env = ["docker", "run", "-v", f"{tmp_path / '.env'}:/workspace/.env", "img"]
    assert any(".env" in p for p in mount_policy_violations(bad_env))
    bad_net = ["docker", "run", "--network", "host", "img"]
    assert any("network host" in p for p in mount_policy_violations(bad_net))


def test_invalid_phase_rejected(tmp_path):
    with pytest.raises(ValueError):
        build_docker_command(tmp_path, "echo", "deploy", "img")


def test_local_env_excludes_api_keys(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY_1", "AQ.secret_value_should_not_pass")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    env = _local_env()
    assert "GOOGLE_API_KEY_1" not in env
    assert "GITHUB_TOKEN" not in env
    assert "PATH" in env


def test_run_in_sandbox_local_executes_and_times_out(tmp_path):
    ok = run_in_sandbox(tmp_path, "echo hello", phase="execute", use_docker=False, timeout_seconds=30)
    assert ok.ok and "hello" in ok.stdout
    (tmp_path / "sleeper.py").write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
    slow = run_in_sandbox(
        tmp_path, "python sleeper.py", phase="execute", use_docker=False, timeout_seconds=1,
    )
    assert not slow.ok and slow.timed_out


def test_run_in_sandbox_flags_secret_output(tmp_path):
    res = run_in_sandbox(
        tmp_path, "echo AQ.abcdefghijklmnopqrstuvwxyz", phase="execute",
        use_docker=False, timeout_seconds=30,
    )
    assert not res.ok and res.secret_leak
