# 단일 repo Challenge 파이프라인: 수집 → snapshot → LLM 1회(ChallengePackage) → 렌더링 → 검증 → DB 저장.
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from repo_idea_miner.challenge_db import (
    log_event,
    mark_repo_processed,
    save_challenge,
    upsert_repo,
)
from repo_idea_miner.challenge_prompts import build_challenge_package_prompt, mock_challenge_package
from repo_idea_miner.challenge_renderer import (
    render_challenge_card_md,
    render_challenge_viewer_html,
    render_implementation_prompt_md,
    render_owner_brief_md,
    render_screen_story_md,
)
from repo_idea_miner.challenge_schemas import ChallengePackage, apply_auto_label_rules
from repo_idea_miner.config import Settings, load_settings
from repo_idea_miner.errors import GitHubError, LLMCallError, RIMError
from repo_idea_miner.github_api import GitHubClient
from repo_idea_miner.key_pool import KeyPool
from repo_idea_miner.llm_client import (
    GoogleGenAIGemmaClient,
    LLMCallLogger,
    LLMClient,
    MockLLMClient,
)
from repo_idea_miner.pipeline import collect_all, make_run_dir
from repo_idea_miner.redaction import redact_text, scan_files_for_secrets
from repo_idea_miner.url_parser import parse_repo_url

SINGLE_CHALLENGE_FILES = [
    "snapshot.json",
    "owner_brief.json",
    "owner_brief.md",
    "screen_story.json",
    "screen_story.md",
    "challenge_card.json",
    "challenge_card.md",
    "implementation_prompt.md",
    "validation_report.json",
]


def _write_text(run_dir: Path, rel: str, text: str, secrets: list[str]) -> None:
    path = run_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(redact_text(text, secrets), encoding="utf-8")


def _write_json(run_dir: Path, rel: str, obj, secrets: list[str]) -> None:
    _write_text(run_dir, rel, json.dumps(obj, ensure_ascii=False, indent=2), secrets)


def build_snapshot(collected: dict, repo_url: str, full_name: str) -> dict:
    """수집 결과를 Challenge 생성용 snapshot dict로 축약한다."""
    metadata = collected.get("metadata") or {}
    issues = collected.get("issues") or {}
    tree = collected.get("tree") or {}
    readme_text = collected.get("readme_text")
    issue_records = issues.get("all_records") or []
    return {
        "repo_url": repo_url,
        "full_name": full_name,
        "collected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metadata": {
            "description": metadata.get("description"),
            "stars": metadata.get("stars"),
            "forks": metadata.get("forks"),
            "topics": metadata.get("topics"),
            "primary_language": metadata.get("primary_language"),
            "archived": metadata.get("archived"),
            "fork": metadata.get("fork"),
            "license": metadata.get("license"),
            "homepage": metadata.get("homepage"),
            "updated_at": metadata.get("updated_at"),
        },
        "readme_status": collected.get("readme_status"),
        "readme_excerpt": (readme_text or "")[:6000] or None,
        "issue_titles": [
            {"title": r.get("title"), "tags": r.get("signal_tags")} for r in issue_records[:10]
        ],
        "file_tree_top": (tree.get("paths") or [])[:120],
        "docs_examples_demo": (tree.get("docs_examples_demo") or [])[:30],
        "missing": collected.get("missing") or [],
    }


def build_snapshot_md(snapshot: dict) -> str:
    md = snapshot.get("metadata") or {}
    lines = [
        f"# Repo Snapshot: {snapshot.get('full_name')}",
        "",
        f"- url: {snapshot.get('repo_url')}",
        f"- description: {md.get('description')}",
        f"- stars: {md.get('stars')} / forks: {md.get('forks')}",
        f"- language: {md.get('primary_language')}",
        f"- topics: {', '.join(md.get('topics') or []) or '(없음)'}",
        f"- archived: {md.get('archived')} / fork: {md.get('fork')}",
        "",
        "## Issue Titles",
    ]
    issue_titles = snapshot.get("issue_titles") or []
    if issue_titles:
        lines += [f"- {r.get('title')}" for r in issue_titles]
    else:
        lines.append("- (수집된 이슈 없음)")
    lines += ["", "## File Tree (top)"]
    lines += [f"- {p}" for p in (snapshot.get("file_tree_top") or [])[:60]] or ["- (없음)"]
    lines += ["", "## README"]
    lines.append(snapshot.get("readme_excerpt") or "(README 없음)")
    return "\n".join(lines)


def _make_llm(mode: str, settings: Settings, full_name: str, repo_url: str,
              logger: LLMCallLogger, key_pool: KeyPool | None) -> tuple[LLMClient, KeyPool | None]:
    if mode == "mock":
        return (
            MockLLMClient(
                overrides={"challenge_package": mock_challenge_package(full_name, repo_url)},
                call_logger=logger,
            ),
            key_pool,
        )
    pool = key_pool or KeyPool(settings.google_keys, settings.key_pool_strategy)
    return GoogleGenAIGemmaClient(settings, pool, call_logger=logger), pool


def run_challenge(
    repo_url: str,
    mode: str = "mock",
    output_dir: str | Path = "runs",
    max_issues: int = 10,
    max_prs: int = 10,
    tree_depth: int = 2,
    settings: Settings | None = None,
    gh: GitHubClient | None = None,
    llm: LLMClient | None = None,
    key_pool: KeyPool | None = None,
    run_dir: Path | None = None,
    db_conn=None,
    write_viewer: bool = True,
) -> dict:
    """단일 repo Challenge 생성. §5.1 산출물을 만들고 요약 dict를 반환한다."""
    settings = settings or load_settings()
    owner, repo = parse_repo_url(repo_url)
    full_name = f"{owner}/{repo}"
    run_dir = run_dir or make_run_dir(output_dir, with_debug=False)
    secrets = settings.secret_values()
    gh = gh or GitHubClient(settings.github_token)

    logger = LLMCallLogger(run_dir / "debug" / "llm_calls.jsonl", secrets)
    if llm is None:
        llm, key_pool = _make_llm(mode, settings, full_name, repo_url, logger, key_pool)

    result: dict = {
        "repo": full_name,
        "url": repo_url,
        "run_dir": str(run_dir),
        "mode": mode,
        "ok": False,
        "final_label": None,
        "score_total": None,
        "owner_clarity_score": None,
        "challenge_title": None,
        "one_line_challenge": None,
        "auto_label_adjustments": [],
        "challenge_id": None,
        "error": None,
    }

    report: dict = {
        "repo": full_name,
        "repo_url": repo_url,
        "mode": mode,
        "timestamp": run_dir.name,
        "ok": False,
        "schema_validation": None,
        "auto_label_adjustments": [],
        "artifact_problems": [],
        "secret_scan": None,
        "error": None,
    }

    def finish(package_dict: dict | None) -> dict:
        # 산출물 검증 (validation_report.json 자신은 검사 대상에서 제외된 규칙 사용)
        if package_dict is not None:
            from repo_idea_miner.challenge_validate import check_challenge_artifacts

            report["artifact_problems"] = check_challenge_artifacts(run_dir, require_viewer=write_viewer)
        leaked = scan_files_for_secrets([p for p in run_dir.rglob("*") if p.is_file()], secrets)
        report["secret_scan"] = "FAIL" if leaked else "PASS"
        if leaked:
            report["artifact_problems"].append(f"secret 노출 파일: {leaked}")
        report["ok"] = (
            package_dict is not None
            and report["schema_validation"] == "PASS"
            and not report["artifact_problems"]
            and not leaked
        )
        _write_json(run_dir, "validation_report.json", report, secrets)
        result["ok"] = bool(report["ok"])
        return result

    # 1. 수집 + snapshot
    try:
        collected = collect_all(gh, owner, repo, max_issues, max_prs, tree_depth)
    except (GitHubError, RIMError) as exc:
        msg = f"수집 실패: {type(exc).__name__}: {exc}"
        result["error"] = msg
        report["error"] = msg
        if db_conn is not None:
            log_event(db_conn, "collect_error", msg, repo_url=repo_url)
        return finish(None)

    snapshot = build_snapshot(collected, repo_url, full_name)
    _write_json(run_dir, "snapshot.json", snapshot, secrets)

    # 2. LLM 1회 호출 → ChallengePackage
    prompt = build_challenge_package_prompt(build_snapshot_md(snapshot))
    try:
        raw = llm.generate_json(prompt, "challenge_package", worker="challenge_package")
    except (LLMCallError, RIMError) as exc:
        msg = f"LLM 호출 실패: {type(exc).__name__}: {exc}"
        result["error"] = msg
        report["error"] = msg
        report["schema_validation"] = "SKIPPED"
        if db_conn is not None:
            log_event(db_conn, "llm_error", msg, repo_url=repo_url)
        return finish(None)

    # 3. schema validation (실패 시 fail-safe: raw 기록 + 실패 report)
    try:
        package = ChallengePackage.model_validate(raw)
    except ValidationError as exc:
        report["schema_validation"] = "FAIL"
        msg = f"VALIDATION_FAIL: {exc.error_count()}개 필드 오류"
        result["error"] = msg
        report["error"] = msg
        _write_json(run_dir, "debug/challenge_package_raw.json", raw, secrets)
        _write_text(run_dir, "debug/validation_errors.txt", str(exc), secrets)
        if db_conn is not None:
            log_event(db_conn, "validation_error", msg, repo_url=repo_url)
        return finish(None)
    report["schema_validation"] = "PASS"

    # 4. 자동 판정 규칙 (§9)
    adjustments = apply_auto_label_rules(package)
    report["auto_label_adjustments"] = adjustments
    result["auto_label_adjustments"] = adjustments

    pkg = package.model_dump()
    brief, story, card = pkg["owner_brief"], pkg["screen_story"], pkg["challenge_card"]
    score_total = sum(card["scores"].values())

    # 5. 산출물 렌더링
    _write_json(run_dir, "owner_brief.json", brief, secrets)
    _write_text(run_dir, "owner_brief.md", render_owner_brief_md(brief), secrets)
    _write_json(run_dir, "screen_story.json", story, secrets)
    _write_text(run_dir, "screen_story.md", render_screen_story_md(story), secrets)
    _write_json(run_dir, "challenge_card.json", card, secrets)
    _write_text(run_dir, "challenge_card.md", render_challenge_card_md(card), secrets)
    _write_text(run_dir, "implementation_prompt.md", render_implementation_prompt_md(card), secrets)

    if write_viewer:
        viewer_model = {
            "kind": "single",
            "summary": {
                "final_label": card["final_label"],
                "score_total": score_total,
                "owner_clarity_score": brief["owner_clarity_score"],
                "mode": mode,
                "timestamp": run_dir.name,
            },
            "cards": [challenge_view_item(pkg, repo_url)],
        }
        _write_text(run_dir, "viewer.html", render_challenge_viewer_html(viewer_model), secrets)

    # 6. DB 저장
    if db_conn is not None:
        metadata = collected.get("metadata") or {}
        upsert_repo(
            db_conn,
            {
                "repo_url": repo_url,
                "owner": owner,
                "name": repo,
                "description": metadata.get("description"),
                "stars": metadata.get("stars"),
                "forks": metadata.get("forks"),
                "language": metadata.get("primary_language"),
                "topics": metadata.get("topics"),
                "archived": metadata.get("archived"),
                "fork": metadata.get("fork"),
            },
        )
        challenge_id = save_challenge(db_conn, pkg, repo_url, str(run_dir))
        mark_repo_processed(db_conn, repo_url, "done")
        log_event(
            db_conn,
            "challenge_created",
            f"{full_name}: {card['final_label']}",
            repo_url=repo_url,
            challenge_id=challenge_id,
        )
        result["challenge_id"] = challenge_id

    result.update(
        final_label=card["final_label"],
        score_total=score_total,
        owner_clarity_score=brief["owner_clarity_score"],
        challenge_title=card["challenge_title"],
        one_line_challenge=card["one_line_challenge"],
    )
    return finish(pkg)


def challenge_view_item(pkg: dict, repo_url: str | None) -> dict:
    """viewer.html 카드용으로 ChallengePackage dict를 평탄화한다."""
    card = pkg.get("challenge_card") or {}
    brief = pkg.get("owner_brief") or {}
    return {
        "source_repo": card.get("source_repo"),
        "repo_url": repo_url,
        "final_label": card.get("final_label"),
        "score_total": sum((card.get("scores") or {}).values()) if card.get("scores") else None,
        "challenge_title": card.get("challenge_title"),
        "one_line_challenge": card.get("one_line_challenge"),
        "owner_brief": brief,
        "screen_story": pkg.get("screen_story") or {},
        "difficulty_anchors": card.get("difficulty_anchors"),
        "forbidden_simplifications": card.get("forbidden_simplifications"),
        "pass_criteria": card.get("pass_criteria"),
        "failure_criteria": card.get("failure_criteria"),
        "implementation_prompt": card.get("implementation_prompt"),
    }
