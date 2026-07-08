# 검색어 기반 후보 수집 → 후보별 분석 → top_ideas.md / search_report.md 생성 파이프라인.
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from repo_idea_miner.config import Settings, load_settings
from repo_idea_miner.errors import GitHubError
from repo_idea_miner.github_api import GitHubClient, search_repositories
from repo_idea_miner.key_pool import KeyPool
from repo_idea_miner.pipeline import _key_pool_report, make_run_dir, run_single_repo
from repo_idea_miner.redaction import redact_text
from repo_idea_miner.renderer import render_search_report, render_top_ideas


def _safe_name(full_name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\-]", "_", full_name.replace("/", "_"))


def run_search(
    query: str,
    limit: int = 30,
    top: int = 10,
    mode: str = "mock",
    output_dir: str | Path = "runs",
    explore: bool = False,
    targeted: bool = False,
    settings: Settings | None = None,
    gh: GitHubClient | None = None,
    llm=None,
    max_issues: int = 10,
    max_prs: int = 10,
    tree_depth: int = 2,
) -> dict:
    settings = settings or load_settings()
    gh = gh or GitHubClient(settings.github_token)
    run_dir = make_run_dir(output_dir, with_debug=False)
    (run_dir / "cards").mkdir(exist_ok=True)
    (run_dir / "repos").mkdir(exist_ok=True)
    secrets = settings.secret_values()
    errors: list[str] = []

    # live 모드에서 후보 간 key pool을 공유해 round robin이 이어지게 한다
    key_pool = None
    if llm is None and mode != "mock":
        key_pool = KeyPool(settings.google_keys, settings.key_pool_strategy)

    try:
        items = search_repositories(gh, query, limit, explore=explore)
    except GitHubError as exc:
        items = []
        errors.append(f"검색 실패: {type(exc).__name__}: {exc}")

    candidates = [
        {
            "full_name": it.get("full_name"),
            "url": it.get("html_url"),
            "description": it.get("description"),
            "stars": it.get("stargazers_count", 0),
            "archived": it.get("archived", False),
            "fork": it.get("fork", False),
        }
        for it in items
    ]
    (run_dir / "candidates.json").write_text(
        redact_text(json.dumps(candidates, ensure_ascii=False, indent=2), secrets), encoding="utf-8"
    )

    results: list[dict] = []
    pf_counts = {"PROCEED": 0, "LOW_SIGNAL_PROCEED": 0, "FAST_DROP_PREFLIGHT": 0, "ERROR_STOP": 0}
    correction_count = 0
    analyzed_count = 0
    shared_llm = llm

    for cand in candidates:
        full_name = cand["full_name"]
        repo_dir = run_dir / "repos" / _safe_name(full_name)
        for sub in ("debug/worker_outputs", "debug/prompts", "debug/raw"):
            (repo_dir / sub).mkdir(parents=True, exist_ok=True)
        try:
            res = run_single_repo(
                cand["url"],
                mode=mode,
                input_mode="search",
                settings=settings,
                gh=gh,
                llm=shared_llm,
                key_pool=key_pool,
                run_dir=repo_dir,
                max_issues=max_issues,
                max_prs=max_prs,
                tree_depth=tree_depth,
            )
        except Exception as exc:  # noqa: BLE001 - 한 후보 실패가 전체 검색을 죽이면 안 됨
            errors.append(f"{full_name}: {type(exc).__name__}: {exc}")
            pf_counts["ERROR_STOP"] += 1
            continue
        pf_counts[res.get("preflight_status") or "ERROR_STOP"] = pf_counts.get(res.get("preflight_status") or "ERROR_STOP", 0) + 1
        if res.get("error"):
            errors.append(f"{full_name}: {res['error']}")
        if res.get("verdict"):
            analyzed_count += 1
        if res.get("correction_applied"):
            correction_count += 1
        card_src = repo_dir / "idea_card.md"
        if card_src.exists():
            shutil.copyfile(card_src, run_dir / "cards" / f"{_safe_name(full_name)}_idea_card.md")
        results.append(res)

    judged = [r for r in results if r.get("verdict") and not r.get("fast_drop")]
    correction_rate = (correction_count / len(judged)) if judged else 0.0

    top_ideas = render_top_ideas(query, results, top)
    (run_dir / "top_ideas.md").write_text(redact_text(top_ideas, secrets), encoding="utf-8")

    pool_for_report = key_pool
    client_for_report = shared_llm
    report = render_search_report(
        {
            "query": query,
            "requested_limit": limit,
            "collected_count": len(candidates),
            "after_preflight_count": len(candidates) - pf_counts["FAST_DROP_PREFLIGHT"],
            "analyzed_count": analyzed_count,
            "proceed_count": pf_counts["PROCEED"],
            "low_signal_count": pf_counts["LOW_SIGNAL_PROCEED"],
            "fast_drop_count": pf_counts["FAST_DROP_PREFLIGHT"],
            "error_stop_count": pf_counts["ERROR_STOP"],
            "keep_count": sum(1 for r in results if r.get("verdict") == "KEEP"),
            "maybe_count": sum(1 for r in results if r.get("verdict") == "MAYBE"),
            "drop_count": sum(1 for r in results if r.get("verdict") == "DROP"),
            "key_pool": _key_pool_report(settings, pool_for_report, client_for_report),
            "correction_count": correction_count,
            "correction_rate": correction_rate,
            "errors": errors,
            "output_files": ["top_ideas.md", "search_report.md", "candidates.json", "cards/", "repos/"],
        }
    )
    (run_dir / "search_report.md").write_text(redact_text(report, secrets), encoding="utf-8")

    return {
        "run_dir": str(run_dir),
        "results": results,
        "errors": errors,
        "correction_rate": correction_rate,
    }
