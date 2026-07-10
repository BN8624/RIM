# run directory 레이아웃 해석의 정본 — artifact root 선택을 한 곳에서만 결정한다 (Structural Reset R1).
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def resolve_artifact_root(run_dir: str | Path) -> Path:
    """검증·probe·judge가 읽을 artifact root를 해석한다.

    final_artifact/가 있으면 그것이 납품물이고, 없으면 workspace/가 작업 중인
    유일한 실체다(continuation child 등). 이 선택을 각 모듈이 반복 구현하지 않는다.
    """
    run_dir = Path(run_dir)
    fa = run_dir / "final_artifact"
    return fa if fa.is_dir() else run_dir / "workspace"


def resolve_run_target(run_dir=None, run_id=None, db_conn=None) -> tuple[Path | None, str | None, dict]:
    """--run-dir/--run-id에서 대상 run_dir를 확정한다 — CLI 명령 공통 정본.

    반환: (run_dir|None, 오류 메시지|None, info). run-id 사용 시 resolved run_dir와
    challenge_id를 info에 기록한다.
    """
    info = {"base_run_id": run_id, "challenge_id": None, "resolved_run_dir": None}
    if run_dir is None and run_id is not None:
        if db_conn is None:
            return None, "--run-id는 DB가 필요합니다.", info
        from repo_idea_miner.factory_db import get_product_run

        row = get_product_run(db_conn, run_id)
        if row is None:
            return None, f"run_id {run_id} 없음", info
        run_dir = Path(row["workspace_dir"]).parent
        info["challenge_id"] = row.get("challenge_id")
    if run_dir is None:
        return None, "--run-dir 또는 --run-id가 필요합니다.", info
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        return None, f"run_dir 없음: {run_dir}", info
    info["resolved_run_dir"] = str(run_dir)
    return run_dir, None, info


@dataclass(frozen=True)
class RunLayout:
    run_dir: Path
    artifact_root: Path
    has_final_artifact: bool
    has_workspace: bool
    review_dir: Path

    @property
    def artifact_root_name(self) -> str:
        return self.artifact_root.name


def resolve_run_layout(run_dir: str | Path) -> RunLayout:
    run_dir = Path(run_dir)
    return RunLayout(
        run_dir=run_dir,
        artifact_root=resolve_artifact_root(run_dir),
        has_final_artifact=(run_dir / "final_artifact").is_dir(),
        has_workspace=(run_dir / "workspace").is_dir(),
        review_dir=run_dir / "review",
    )
