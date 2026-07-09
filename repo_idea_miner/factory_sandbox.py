# Docker 검증 샌드박스: 의존성 설치(제한적 network)와 실행/테스트(network 차단) 2단계 실행 모듈 (§13).
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from repo_idea_miner.redaction import contains_secret

DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_CPUS = "1"
DEFAULT_MEMORY = "512m"

# project_type → docker image (검증 샌드박스 용도, 배포 인프라 아님)
SANDBOX_IMAGES = {
    "python_cli": "python:3.12-slim",
    "node_cli": "node:20-slim",
    "static_web": "python:3.12-slim",
}

# 로컬 fallback 실행 시 자식 프로세스에 넘기는 최소 환경변수 (API key/.env 값 차단)
_LOCAL_ENV_ALLOWLIST = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC", "TEMP", "TMP", "PATHEXT", "HOME", "LANG")


@dataclass
class SandboxResult:
    ok: bool
    returncode: int | None
    stdout: str
    stderr: str
    used_docker: bool
    timed_out: bool = False
    secret_leak: bool = False
    error: str | None = None
    command: list[str] = field(default_factory=list)


_docker_cache: bool | None = None


def docker_available(refresh: bool = False) -> bool:
    """docker daemon이 실제로 응답하는지 확인한다 (결과 캐시)."""
    global _docker_cache
    if _docker_cache is not None and not refresh:
        return _docker_cache
    if shutil.which("docker") is None:
        _docker_cache = False
        return False
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=20,
        )
        _docker_cache = proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        _docker_cache = False
    return _docker_cache


def build_docker_command(
    workspace: Path,
    command: str,
    phase: str,
    image: str,
    cpus: str = DEFAULT_CPUS,
    memory: str = DEFAULT_MEMORY,
) -> list[str]:
    """§13 정책이 적용된 docker run 명령을 만든다.

    - mount는 workspace 디렉터리 1개만 (:/workspace). home/repo 루트/.env mount 금지.
    - install 단계만 network 허용, execution/test 단계는 --network none.
    - CPU/memory 제한 필수.
    """
    if phase not in ("install", "execute"):
        raise ValueError(f"잘못된 sandbox phase: {phase}")
    ws = str(Path(workspace).resolve())
    cmd = ["docker", "run", "--rm"]
    if phase == "execute":
        cmd += ["--network", "none"]
    cmd += [
        "--cpus", cpus,
        "--memory", memory,
        "-v", f"{ws}:/workspace",
        "-w", "/workspace",
        image,
        "sh", "-c", command,
    ]
    return cmd


def _local_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k.upper() in _LOCAL_ENV_ALLOWLIST}


def run_in_sandbox(
    workspace: Path,
    command: str,
    phase: str,
    project_type: str = "static_web",
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    use_docker: bool | None = None,
    secrets: list[str] | None = None,
) -> SandboxResult:
    """workspace 안에서 명령을 실행한다. docker가 가능하면 docker, 아니면 로컬 제한 실행.

    로컬 fallback은 최소 환경변수만 넘기고 timeout을 강제한다. 어느 쪽이든
    출력에 secret-like 문자열이 있으면 실패 처리한다 (§13.2).
    """
    secrets = secrets or []
    use_docker = docker_available() if use_docker is None else use_docker
    if use_docker:
        image = SANDBOX_IMAGES.get(project_type, SANDBOX_IMAGES["static_web"])
        cmd = build_docker_command(workspace, command, phase, image)
        run_kwargs: dict = {}
    else:
        cmd = ["cmd", "/c", command] if os.name == "nt" else ["sh", "-c", command]
        run_kwargs = {"cwd": str(workspace), "env": _local_env()}
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_seconds,
            errors="replace", **run_kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        return SandboxResult(
            ok=False, returncode=None,
            stdout=str(exc.stdout or ""), stderr=str(exc.stderr or ""),
            used_docker=use_docker, timed_out=True,
            error=f"timeout {timeout_seconds}s 초과", command=cmd,
        )
    except OSError as exc:
        return SandboxResult(
            ok=False, returncode=None, stdout="", stderr="",
            used_docker=use_docker, error=f"실행 불가: {exc}", command=cmd,
        )
    leak = contains_secret(proc.stdout, secrets) or contains_secret(proc.stderr, secrets)
    ok = proc.returncode == 0 and not leak
    return SandboxResult(
        ok=ok, returncode=proc.returncode,
        stdout=proc.stdout[-8000:], stderr=proc.stderr[-8000:],
        used_docker=use_docker, secret_leak=leak,
        error="출력에 secret-like 문자열 감지" if leak else None,
        command=cmd,
    )


def mount_policy_violations(cmd: list[str]) -> list[str]:
    """docker 명령이 §13 mount/network 금지 사항을 위반하는지 검사한다 (테스트/자가검증용)."""
    problems: list[str] = []
    joined = " ".join(cmd)
    home = str(Path.home().resolve())
    for i, part in enumerate(cmd):
        if part == "-v" and i + 1 < len(cmd):
            # Windows 드라이브 문자(C:)를 보존하며 src:dst에서 src만 얻는다
            m = re.match(r"^([A-Za-z]:[^:]*|[^:]*)", cmd[i + 1])
            src = m.group(1) if m else ""
            src_norm = str(Path(src).resolve()) if src else src
            if src_norm == home:
                problems.append(f"home 디렉터리 mount 금지: {cmd[i + 1]}")
            base = os.path.basename(src_norm.rstrip("/\\")).lower()
            if base in (".env",) or base.endswith(".env"):
                problems.append(f".env mount 금지: {cmd[i + 1]}")
    if "--network host" in joined or ("--network" in cmd and "host" in cmd):
        problems.append("--network host 금지")
    return problems
