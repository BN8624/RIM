# Phase 2A Frozen Hash Guard: golden/fixtures/contract/oracle 파일 hash를 전후 비교해 spec 불변을 검증하는 모듈.
from __future__ import annotations

import hashlib
import json
from pathlib import Path

# hash 보호 대상 (주문서 §4.6, §4.7)
FROZEN_HASH_FILES = (
    "core_contract.json",
    "state_contract.json",
    "action_contract.json",
    "runner_contract.json",
    "oracle_risk_report.json",
)
FROZEN_HASH_PREFIXES = ("golden/", "fixtures/")

FROZEN_HASH_BEFORE = "frozen_hash_before.json"
FROZEN_HASH_AFTER = "frozen_hash_after.json"
FROZEN_HASH_CHECK = "frozen_hash_check.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_frozen_hashes(workspace: Path | None, run_dir: Path | None = None) -> dict[str, str]:
    """workspace(없으면 run_dir 직속) 기준 frozen 파일들의 sha256 map을 만든다.

    run_dir가 주어지면 run 루트의 oracle_risk_report.json 등 workspace 밖 frozen 파일도 포함한다.
    """
    out: dict[str, str] = {}

    def _scan(root: Path, tag: str) -> None:
        if root is None or not root.is_dir():
            return
        for rel in FROZEN_HASH_FILES:
            p = root / rel
            if p.is_file():
                out.setdefault(f"{tag}{rel}", _sha256(p))
        for prefix in FROZEN_HASH_PREFIXES:
            d = root / prefix.rstrip("/")
            if d.is_dir():
                for p in sorted(d.rglob("*")):
                    if p.is_file():
                        rel = p.relative_to(root).as_posix()
                        out.setdefault(f"{tag}{rel}", _sha256(p))

    if workspace is not None:
        _scan(Path(workspace), "")
    if run_dir is not None:
        run_dir = Path(run_dir)
        for rel in FROZEN_HASH_FILES:
            p = run_dir / rel
            if p.is_file():
                out.setdefault(f"run:{rel}", _sha256(p))
    return out


def compare_frozen_hashes(before: dict[str, str], after: dict[str, str]) -> dict:
    """before/after hash map을 비교해 check 결과 dict를 만든다. 변화가 있으면 FAIL."""
    changed = sorted(k for k in before if k in after and before[k] != after[k])
    removed = sorted(k for k in before if k not in after)
    added = sorted(k for k in after if k not in before)
    ok = not (changed or removed or added)
    return {
        "status": "PASS" if ok else "FAIL",
        "files_checked": len(before),
        "changed": changed,
        "added": added,
        "removed": removed,
    }


def write_frozen_hash_guard(target_dir: Path, before: dict[str, str], after: dict[str, str]) -> dict:
    """frozen_hash_before/after/check.json 3종을 target_dir에 기록하고 check dict를 반환한다."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    check = compare_frozen_hashes(before, after)
    for name, data in ((FROZEN_HASH_BEFORE, before), (FROZEN_HASH_AFTER, after),
                       (FROZEN_HASH_CHECK, check)):
        (target_dir / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return check
