# challenge.db가 참조하지 않는 runs/ 고아 폴더를 찾아 정리하는 스크립트
"""
challenge.db의 challenges.artifact_dir가 가리키는 runs/<timestamp> 폴더만 보존하고,
DB에서 참조되지 않는 고아 폴더를 정리한다.

기본은 dry-run(목록만 출력). 실제 삭제는 --delete 필요.

사용:
    python scripts/clean_runs.py                 # 미리보기(삭제 안 함)
    python scripts/clean_runs.py --delete        # 고아 폴더 삭제
    python scripts/clean_runs.py --db challenge.db --runs runs
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from pathlib import Path


def top_run_folder(artifact_dir: str, runs_name: str) -> str | None:
    """artifact_dir 경로에서 최상위 runs/<timestamp> 폴더명을 뽑는다.

    검색 모드는 runs/<ts>/repos/<repo>처럼 하위에 저장되므로
    항상 runs 바로 다음 세그먼트를 보존 단위로 잡는다.
    """
    parts = Path(os.path.normpath(artifact_dir)).parts
    if runs_name in parts:
        i = parts.index(runs_name)
        if i + 1 < len(parts):
            return parts[i + 1]
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="challenge.db")
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--delete", action="store_true", help="실제로 삭제한다")
    args = ap.parse_args()

    db_path = Path(args.db)
    runs_dir = Path(args.runs)

    if not db_path.exists():
        print(f"[오류] DB 없음: {db_path}")
        return 1
    if not runs_dir.is_dir():
        print(f"[오류] runs 디렉터리 없음: {runs_dir}")
        return 1

    runs_name = runs_dir.name
    conn = sqlite3.connect(str(db_path))
    referenced: set[str] = set()
    for (d,) in conn.execute("SELECT artifact_dir FROM challenges WHERE artifact_dir IS NOT NULL"):
        folder = top_run_folder(d, runs_name)
        if folder:
            referenced.add(folder)
    conn.close()

    on_disk = {p.name for p in runs_dir.iterdir() if p.is_dir()}
    orphans = sorted(on_disk - referenced)
    missing = sorted(referenced - on_disk)

    print(f"DB 참조 폴더: {len(referenced)}개 | 디스크 폴더: {len(on_disk)}개")
    print(f"고아(디스크에만 있음): {len(orphans)}개")
    print(f"깨진 참조(DB에만 있음): {len(missing)}개")

    if missing:
        print("\n[경고] DB가 참조하지만 디스크에 없는 폴더:")
        for m in missing:
            print(f"  - {m}")

    if not orphans:
        print("\n정리할 고아 폴더가 없습니다.")
        return 0

    total_bytes = 0
    for name in orphans:
        for f in (runs_dir / name).rglob("*"):
            if f.is_file():
                total_bytes += f.stat().st_size
    print(f"\n고아 폴더 총 용량: {total_bytes / 1024 / 1024:.1f} MB")

    if not args.delete:
        print("\n[미리보기] 삭제 대상(실제 삭제 안 함). 삭제하려면 --delete 를 붙이세요.")
        for name in orphans:
            print(f"  - {name}")
        return 0

    print("\n삭제 중...")
    removed = 0
    for name in orphans:
        shutil.rmtree(runs_dir / name, ignore_errors=True)
        removed += 1
    print(f"완료: {removed}개 폴더 삭제, 약 {total_bytes / 1024 / 1024:.1f} MB 확보")
    return 0


if __name__ == "__main__":
    sys.exit(main())
