# factory-validate: product run 디렉터리의 Final Artifact 구조·manifest 정합성·secret을 검증하는 모듈.
from __future__ import annotations

import json
from pathlib import Path

from repo_idea_miner.factory_pipeline import FINAL_ARTIFACT_REQUIRED_FILES
from repo_idea_miner.factory_schemas import PRODUCT_VERDICT_LABELS
from repo_idea_miner.redaction import scan_files_for_secrets

MIN_SRC_FILES = 2

CODEX_EXPORT_REQUIRED = (
    "source_workspace",
    "manifest.json",
    "contract.json",
    "challenge_card.md",
    "product_brief.md",
    "ux_flow.md",
    "technical_plan.md",
    "syntax_report.md",
    "smoke_report.md",
    "qa_report.md",
    "debug_history.jsonl",
    "known_issues.md",
    "next_goal.md",
)


def _final_artifact_dir(run_dir: Path) -> Path | None:
    if (run_dir / "final_artifact").is_dir():
        return run_dir / "final_artifact"
    if (run_dir / "product_verdict.md").is_file() and (run_dir / "manifest.json").is_file():
        return run_dir  # final_artifact 디렉터리를 직접 지정한 경우
    return None


def validate_final_artifact(final_dir: Path) -> list[str]:
    """Final Artifact 최소 구조(§1)를 검사한다. 단일파일 산출물은 실패다."""
    problems: list[str] = []
    for rel in FINAL_ARTIFACT_REQUIRED_FILES:
        if not (final_dir / rel).is_file():
            problems.append(f"필수 파일 없음: {rel}")

    src = final_dir / "src"
    src_files = [p for p in src.rglob("*") if p.is_file()] if src.is_dir() else []
    if len(src_files) < MIN_SRC_FILES:
        problems.append(f"단일파일 산출물: src 파일 {len(src_files)}개 < {MIN_SRC_FILES} (Final Artifact 실패 조건)")

    if not any((final_dir / d).is_dir() and any((final_dir / d).iterdir()) for d in ("checks", "tests")):
        problems.append("checks/ 또는 tests/ 없음")

    manifest_path = final_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"manifest.json parse 실패: {exc}")
            manifest = {}
        for f in manifest.get("files") or []:
            if not (final_dir / f["path"]).is_file():
                problems.append(f"manifest에 있으나 실제 파일 없음: {f['path']}")
        entrypoint = manifest.get("entrypoint")
        if entrypoint and not (final_dir / entrypoint).is_file():
            problems.append(f"entrypoint 없음: {entrypoint}")

    contract_path = final_dir / "contract.json"
    if contract_path.is_file():
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"contract.json parse 실패: {exc}")
            contract = {}
        for rel in contract.get("required_files") or []:
            if not (final_dir / rel).is_file():
                problems.append(f"contract 필수 파일 없음: {rel}")

    verdict_path = final_dir / "product_verdict.md"
    if verdict_path.is_file():
        text = verdict_path.read_text(encoding="utf-8", errors="replace")
        if not any(label in text for label in PRODUCT_VERDICT_LABELS):
            problems.append("product_verdict.md에 유효한 verdict 라벨 없음")
    return problems


def validate_codex_export(export_dir: Path) -> list[str]:
    problems: list[str] = []
    for rel in CODEX_EXPORT_REQUIRED:
        p = export_dir / rel
        if not (p.is_file() or p.is_dir()):
            problems.append(f"codex_export 필수 항목 없음: {rel}")
    return problems


def validate_product_run_dir(run_dir: str | Path, secrets: list[str]) -> tuple[bool, list[str]]:
    """product run 디렉터리 전체를 검증한다. (ok, problems) 반환."""
    run_dir = Path(run_dir)
    problems: list[str] = []
    if not run_dir.is_dir():
        return False, [f"디렉터리 없음: {run_dir}"]

    final_dir = _final_artifact_dir(run_dir)
    if final_dir is None:
        problems.append("final_artifact/ 없음 (Final Artifact 미생성)")
    else:
        problems += validate_final_artifact(final_dir)

    if final_dir is not run_dir:
        for rel in ("events.jsonl", "debug_history.jsonl", "product_verdict.md"):
            if not (run_dir / rel).is_file():
                problems.append(f"run 기록 파일 없음: {rel}")

    export_dir = run_dir / "codex_export"
    if export_dir.is_dir():
        problems += validate_codex_export(export_dir)

    leaked = scan_files_for_secrets([p for p in run_dir.rglob("*") if p.is_file()], secrets)
    if leaked:
        problems.append(f"secret 노출 파일: {leaked}")
    return (not problems), problems
