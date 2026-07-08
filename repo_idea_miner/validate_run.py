# runs/<timestamp>/ 산출물의 구조·스키마·secret 노출·필수 섹션을 검증하는 모듈.
from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from repo_idea_miner.redaction import scan_files_for_secrets
from repo_idea_miner.renderer import IDEA_CARD_SECTIONS, RUN_REPORT_SECTIONS
from repo_idea_miner.schemas import JudgeOutput


def _check_sections(path: Path, sections: list[str], problems: list[str]) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    for section in sections:
        if section not in text:
            problems.append(f"{path.name}: 필수 섹션 누락 - {section}")


def validate_single_run(run_dir: Path, problems: list[str]) -> None:
    card = run_dir / "idea_card.md"
    report = run_dir / "run_report.md"
    if not card.exists():
        problems.append("idea_card.md 없음")
    else:
        _check_sections(card, IDEA_CARD_SECTIONS, problems)
    if not report.exists():
        problems.append("run_report.md 없음")
    else:
        _check_sections(report, RUN_REPORT_SECTIONS, problems)

    evidence = run_dir / "debug" / "evidence_packet.md"
    if not evidence.exists():
        problems.append("debug/evidence_packet.md 없음")

    final_json = run_dir / "debug" / "judge_output_final.json"
    if final_json.exists():
        try:
            JudgeOutput.model_validate(json.loads(final_json.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValidationError) as exc:
            problems.append(f"judge_output_final.json 스키마 위반: {type(exc).__name__}")


def _run_failed(report_path: Path) -> bool:
    """run_report에 실패(JSON Validation != PASS)가 기록된 run인지 확인한다."""
    text = report_path.read_text(encoding="utf-8", errors="replace")
    section = text.split("## JSON Validation", 1)
    if len(section) < 2:
        return True
    return section[1].strip().splitlines()[0].strip() != "PASS"


def validate_search_run(run_dir: Path, problems: list[str]) -> None:
    for name in ("top_ideas.md", "search_report.md", "candidates.json"):
        if not (run_dir / name).exists():
            problems.append(f"{name} 없음")
    for repo_dir in sorted((run_dir / "repos").glob("*")):
        if not repo_dir.is_dir():
            continue
        report = repo_dir / "run_report.md"
        if not report.exists():
            problems.append(f"{repo_dir.name}: run_report.md 없음")
            continue
        # LLM 실패 등으로 run 실패가 기록된 후보는 카드 부재가 정상이다.
        if _run_failed(report):
            continue
        sub_problems: list[str] = []
        validate_single_run(repo_dir, sub_problems)
        problems.extend(f"{repo_dir.name}: {p}" for p in sub_problems)


def validate_viewer(run_dir: Path, problems: list[str]) -> None:
    """--require-viewer 시 viewer.html의 존재·필수 요소·secret 노출을 검사한다."""
    viewer = run_dir / "viewer.html"
    if not viewer.exists():
        problems.append("viewer.html 없음")
        return
    text = viewer.read_text(encoding="utf-8", errors="replace")
    checks = [
        ('name="viewport"', "모바일 viewport meta 누락"),
        ("data-filter", "필터 버튼 누락"),
        ('class="card"', "카드 목록 누락"),
        ('class="badge', "verdict label 누락"),
    ]
    for needle, msg in checks:
        if needle not in text:
            problems.append(f"viewer.html: {msg}")


def validate_run_dir(
    run_dir: str | Path,
    secret_values: list[str] | None = None,
    require_viewer: bool = False,
) -> tuple[bool, list[str]]:
    run_dir = Path(run_dir)
    problems: list[str] = []
    if not run_dir.is_dir():
        return False, [f"디렉터리가 아님: {run_dir}"]

    if (run_dir / "top_ideas.md").exists() or (run_dir / "candidates.json").exists():
        validate_search_run(run_dir, problems)
    else:
        validate_single_run(run_dir, problems)

    if require_viewer:
        validate_viewer(run_dir, problems)

    files = [p for p in run_dir.rglob("*") if p.is_file()]
    leaked = scan_files_for_secrets(files, secret_values or [])
    for f in leaked:
        problems.append(f"secret 노출: {f}")

    return (not problems), problems
