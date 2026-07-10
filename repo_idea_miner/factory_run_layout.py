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
