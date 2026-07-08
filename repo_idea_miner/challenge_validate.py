# Challenge Mode 산출물(run 디렉터리)과 challenge.db를 검증하는 모듈.
from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from repo_idea_miner.challenge_renderer import (
    CHALLENGE_CARD_SECTIONS,
    OWNER_BRIEF_SECTIONS,
    SCREEN_STORY_SECTIONS,
)
from repo_idea_miner.challenge_schemas import (
    ChallengeCard,
    ChallengeIndex,
    OwnerBrief,
    ScreenStory,
)
from repo_idea_miner.redaction import scan_files_for_secrets

# validate-db는 challenge_db.validate_db를 그대로 노출한다.
from repo_idea_miner.challenge_db import validate_db  # noqa: F401 (re-export)


def detect_challenge_run(run_dir: Path) -> str | None:
    """challenge run 종류를 감지한다: 'single' | 'search' | None."""
    run_dir = Path(run_dir)
    if (run_dir / "challenge_index.json").exists():
        return "search"
    if (run_dir / "challenge_card.json").exists() or (run_dir / "owner_brief.json").exists():
        return "single"
    # 실패한 단일 challenge run: 카드 없이 snapshot/validation_report만 남는다
    if (run_dir / "validation_report.json").exists() or (run_dir / "snapshot.json").exists():
        return "single"
    return None


def _load_json(path: Path, problems: list[str]):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"{path.name}: JSON 파싱 실패 ({type(exc).__name__})")
        return None


def _check_sections(path: Path, sections: list[str], problems: list[str]) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    for section in sections:
        if section not in text:
            problems.append(f"{path.name}: 필수 섹션 누락 - {section}")


def check_challenge_artifacts(run_dir: str | Path, require_viewer: bool = True) -> list[str]:
    """§5.1 산출물 존재·스키마·구성 요건을 검사한다 (validation_report.json 제외)."""
    run_dir = Path(run_dir)
    problems: list[str] = []

    required = [
        "snapshot.json",
        "owner_brief.json",
        "owner_brief.md",
        "screen_story.json",
        "screen_story.md",
        "challenge_card.json",
        "challenge_card.md",
        "implementation_prompt.md",
    ]
    for name in required:
        if not (run_dir / name).exists():
            problems.append(f"{name} 없음")

    card_dict = None
    if (run_dir / "owner_brief.json").exists():
        brief = _load_json(run_dir / "owner_brief.json", problems)
        if brief is not None:
            try:
                OwnerBrief.model_validate(brief)
            except ValidationError as exc:
                problems.append(f"owner_brief.json 스키마 위반: {exc.error_count()}개 필드 오류")
    if (run_dir / "screen_story.json").exists():
        story = _load_json(run_dir / "screen_story.json", problems)
        if story is not None:
            try:
                ScreenStory.model_validate(story)
            except ValidationError as exc:
                problems.append(f"screen_story.json 스키마 위반: {exc.error_count()}개 필드 오류")
    if (run_dir / "challenge_card.json").exists():
        card_dict = _load_json(run_dir / "challenge_card.json", problems)
        if card_dict is not None:
            try:
                ChallengeCard.model_validate(card_dict)
            except ValidationError as exc:
                problems.append(f"challenge_card.json 스키마 위반: {exc.error_count()}개 필드 오류")
                card_dict = None

    if (run_dir / "owner_brief.md").exists():
        _check_sections(run_dir / "owner_brief.md", OWNER_BRIEF_SECTIONS, problems)
    if (run_dir / "screen_story.md").exists():
        _check_sections(run_dir / "screen_story.md", SCREEN_STORY_SECTIONS, problems)
    if (run_dir / "challenge_card.md").exists():
        _check_sections(run_dir / "challenge_card.md", CHALLENGE_CARD_SECTIONS, problems)

    # implementation_prompt.md ↔ challenge_card.json 정합성 (§7, §26)
    impl_path = run_dir / "implementation_prompt.md"
    if impl_path.exists() and card_dict is not None:
        impl_text = impl_path.read_text(encoding="utf-8", errors="replace")
        field_text = (card_dict.get("implementation_prompt") or "").strip()
        if field_text and field_text not in impl_text:
            problems.append("implementation_prompt.md: challenge_card.json의 implementation_prompt 원문 불일치")
        for anchor in card_dict.get("difficulty_anchors") or []:
            if anchor not in impl_text:
                problems.append(f"implementation_prompt.md: Difficulty Anchor 미반영 - {anchor}")
        for forbidden in card_dict.get("forbidden_simplifications") or []:
            if forbidden not in impl_text:
                problems.append(f"implementation_prompt.md: Forbidden Simplification 미반영 - {forbidden}")

    if require_viewer:
        problems.extend(check_challenge_viewer(run_dir, kind="single"))

    return problems


def check_challenge_viewer(run_dir: Path, kind: str) -> list[str]:
    problems: list[str] = []
    viewer = Path(run_dir) / "viewer.html"
    if not viewer.exists():
        return ["viewer.html 없음"]
    text = viewer.read_text(encoding="utf-8", errors="replace")
    checks = [
        ('name="viewport"', "모바일 viewport meta 누락"),
        ('class="card"', "카드 누락"),
        ('class="badge', "final_label badge 누락"),
    ]
    if kind == "search":
        checks.append(("data-filter", "필터 버튼 누락"))
    for needle, msg in checks:
        if needle not in text:
            problems.append(f"viewer.html: {msg}")
    return problems


def _run_failed(repo_dir: Path) -> bool:
    """per-repo validation_report.json에 실패가 기록된 후보인지 확인한다."""
    report = repo_dir / "validation_report.json"
    if not report.exists():
        return True
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    return bool(data.get("error")) or data.get("schema_validation") not in ("PASS",)


def validate_challenge_single(run_dir: Path, problems: list[str]) -> None:
    problems.extend(check_challenge_artifacts(run_dir, require_viewer=True))
    if not (run_dir / "validation_report.json").exists():
        problems.append("validation_report.json 없음")


def validate_challenge_search(run_dir: Path, problems: list[str]) -> None:
    for name in ("challenge_index.json", "search_report.json"):
        if not (run_dir / name).exists():
            problems.append(f"{name} 없음")
    index_path = run_dir / "challenge_index.json"
    index = None
    if index_path.exists():
        data = _load_json(index_path, problems)
        if data is not None:
            try:
                index = ChallengeIndex.model_validate(data)
            except ValidationError as exc:
                problems.append(f"challenge_index.json 스키마 위반: {exc.error_count()}개 필드 오류")
    problems.extend(check_challenge_viewer(run_dir, kind="search"))

    # index의 artifact_dir 경로 정합성
    if index is not None:
        for item in index.items:
            if not Path(item.artifact_dir).is_dir():
                problems.append(f"{item.source_repo}: artifact_dir 경로 없음 - {item.artifact_dir}")

    repos_dir = run_dir / "repos"
    if repos_dir.is_dir():
        for repo_dir in sorted(repos_dir.glob("*")):
            if not repo_dir.is_dir():
                continue
            # LLM 실패 등으로 run 실패가 기록된 후보는 카드 부재가 정상이다.
            if _run_failed(repo_dir):
                continue
            sub: list[str] = []
            sub.extend(check_challenge_artifacts(repo_dir, require_viewer=False))
            problems.extend(f"{repo_dir.name}: {p}" for p in sub)


def validate_challenge_run_dir(
    run_dir: str | Path, secret_values: list[str] | None = None
) -> tuple[bool, list[str]]:
    """challenge / challenge-search run 디렉터리 산출물을 검증한다."""
    run_dir = Path(run_dir)
    problems: list[str] = []
    if not run_dir.is_dir():
        return False, [f"디렉터리가 아님: {run_dir}"]

    kind = detect_challenge_run(run_dir)
    if kind == "search":
        validate_challenge_search(run_dir, problems)
    elif kind == "single":
        validate_challenge_single(run_dir, problems)
    else:
        return False, ["challenge run 디렉터리가 아님 (challenge_card.json/challenge_index.json 없음)"]

    files = [p for p in run_dir.rglob("*") if p.is_file()]
    leaked = scan_files_for_secrets(files, secret_values or [])
    for f in leaked:
        problems.append(f"secret 노출: {f}")

    return (not problems), problems
