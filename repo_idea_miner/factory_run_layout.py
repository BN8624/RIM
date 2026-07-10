# run directory 레이아웃 해석의 정본 — artifact root 선택과 run kind 감지를 한 곳에서만 결정한다 (Structural Reset R1·R2).
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

RUN_KIND_CONTINUATION = "CONTINUATION_RUN"
RUN_KIND_CORE = "CORE_FACTORY_RUN"
RUN_KIND_LEGACY = "LEGACY_FACTORY_RUN"
RUN_KIND_UNKNOWN = "UNKNOWN_RUN"


def detect_continuation_run(run_dir: str | Path) -> bool:
    """Phase 1.7 continuation run 디렉터리인지 감지한다 (§3 감지 기준)."""
    run_dir = Path(run_dir)
    if (run_dir / "continuation_run_summary.json").is_file():
        return True
    if (run_dir / "green_base_promotion.json").is_file():
        return True
    return (run_dir / "failure_classification.json").is_file() and (run_dir / "repair_plan.json").is_file()


def detect_core_run(run_dir: str | Path) -> bool:
    """Phase 1.6 Core-first Harness run 디렉터리인지 감지한다 (harness_summary.json 존재)."""
    return (Path(run_dir) / "harness_summary.json").is_file()


def detect_run_kind(run_dir: str | Path) -> str:
    """run directory를 보고 run kind를 감지한다. continuation → core → legacy 순."""
    run_dir = Path(run_dir)
    if detect_continuation_run(run_dir):
        return RUN_KIND_CONTINUATION
    if (detect_core_run(run_dir)
            or (run_dir / "core_system_summary.json").is_file()
            or (run_dir / "core_contract_summary.json").is_file()):
        return RUN_KIND_CORE
    if ((run_dir / "final_artifact").is_dir()
            or (run_dir / "manifest.json").is_file()
            or (run_dir / "contract.json").is_file()):
        return RUN_KIND_LEGACY
    return RUN_KIND_UNKNOWN


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
