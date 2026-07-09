# Product Factory workspace 파일 쓰기·snapshot·green base rollback·events.jsonl 기록 유틸 모듈.
from __future__ import annotations

import json
import shutil
from pathlib import Path

from repo_idea_miner.challenge_db import utcnow_iso
from repo_idea_miner.redaction import redact_text

# workspace 안에 생성 금지인 경로 조각 (secret/환경 오염 방지)
FORBIDDEN_PATH_PARTS = (".env", ".git", "node_modules", "__pycache__")


class WorkspaceError(Exception):
    pass


def safe_workspace_path(workspace: Path, rel: str) -> Path:
    """workspace 밖으로 나가는 경로·금지 경로를 차단하고 절대 경로를 반환한다."""
    rel_path = Path(rel)
    if rel_path.is_absolute():
        raise WorkspaceError(f"절대 경로 금지: {rel}")
    for part in rel_path.parts:
        if part == "..":
            raise WorkspaceError(f"상위 경로 탈출 금지: {rel}")
        if part in FORBIDDEN_PATH_PARTS:
            raise WorkspaceError(f"금지 경로: {rel}")
    target = (workspace / rel_path).resolve()
    if not str(target).startswith(str(workspace.resolve())):
        raise WorkspaceError(f"workspace 밖 경로: {rel}")
    return target


def write_workspace_file(workspace: Path, rel: str, content: str, secrets: list[str]) -> Path:
    """redaction을 거쳐 workspace에 파일을 쓴다."""
    target = safe_workspace_path(workspace, rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(redact_text(content, secrets), encoding="utf-8")
    return target


def apply_file_entries(workspace: Path, entries: list[dict], secrets: list[str]) -> list[str]:
    """Desk 출력의 files([{path, content}])를 workspace에 적용하고 쓴 경로를 반환한다."""
    written: list[str] = []
    for e in entries:
        write_workspace_file(workspace, e["path"], e["content"], secrets)
        written.append(e["path"])
    return written


def list_workspace_files(workspace: Path) -> list[str]:
    """reports/snapshot 등 관리 파일을 제외한 workspace 상대 경로 목록."""
    if not workspace.is_dir():
        return []
    out = []
    for p in sorted(workspace.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(workspace).as_posix()
        if rel.startswith("reports/"):
            continue
        out.append(rel)
    return out


def src_file_count(workspace: Path) -> int:
    src = workspace / "src"
    if not src.is_dir():
        return 0
    return sum(1 for p in src.rglob("*") if p.is_file())


def read_workspace_file(workspace: Path, rel: str, limit: int = 6000) -> str:
    p = workspace / rel
    if not p.is_file():
        return f"(파일 없음: {rel})"
    text = p.read_text(encoding="utf-8", errors="replace")
    if len(text) > limit:
        return text[:limit] + "\n[길이 제한으로 잘림]"
    return text


# ---------------------------------------------------------------- snapshot / green base

def save_green_base(run_dir: Path, workspace: Path, label: str) -> Path:
    """검증 통과 상태의 workspace를 snapshot/<label>로 복사해 green base로 보존한다."""
    snap_dir = run_dir / "snapshot" / label
    if snap_dir.exists():
        shutil.rmtree(snap_dir)
    shutil.copytree(workspace, snap_dir)
    return snap_dir


def latest_green_base(run_dir: Path) -> Path | None:
    snap_root = run_dir / "snapshot"
    if not snap_root.is_dir():
        return None
    snaps = sorted([p for p in snap_root.iterdir() if p.is_dir()])
    return snaps[-1] if snaps else None


def rollback_to_green_base(run_dir: Path, workspace: Path) -> bool:
    """최근 green base로 workspace를 되돌린다. green base가 없으면 False."""
    snap = latest_green_base(run_dir)
    if snap is None:
        return False
    if workspace.exists():
        shutil.rmtree(workspace)
    shutil.copytree(snap, workspace)
    return True


# ---------------------------------------------------------------- events / debug history

def append_jsonl(path: Path, record: dict, secrets: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = redact_text(json.dumps(record, ensure_ascii=False), secrets)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def log_loop_event(
    run_dir: Path,
    secrets: list[str],
    stage: str,
    desk: str | None = None,
    worker_key_id: str | None = None,
    input_files: list[str] | None = None,
    output_files: list[str] | None = None,
    validation: str | None = None,
    error: str | None = None,
    next_state: str | None = None,
    **extra,
) -> None:
    """§9: 각 loop 후 events.jsonl에 상태를 기록한다. worker_key_id는 KEY_NN 형식만 허용."""
    record = {
        "timestamp": utcnow_iso(),
        "stage": stage,
        "desk": desk,
        "worker_key_id": worker_key_id,
        "input_files": input_files or [],
        "output_files": output_files or [],
        "validation": validation,
        "error": error,
        "next_state": next_state,
    }
    record.update(extra)
    append_jsonl(run_dir / "events.jsonl", record, secrets)


def log_debug_history(run_dir: Path, secrets: list[str], record: dict) -> None:
    rec = {"timestamp": utcnow_iso()}
    rec.update(record)
    append_jsonl(run_dir / "debug_history.jsonl", rec, secrets)
