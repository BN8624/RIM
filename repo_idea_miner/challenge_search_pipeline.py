# GitHub 검색 결과를 Challenge 후보로 변환해 challenge_index.json/viewer를 생성하는 파이프라인.
from __future__ import annotations

import json
from pathlib import Path

from repo_idea_miner.challenge_db import log_event, upsert_repo
from repo_idea_miner.challenge_pipeline import challenge_view_item, run_challenge
from repo_idea_miner.challenge_renderer import render_challenge_viewer_html
from repo_idea_miner.challenge_schemas import LABEL_PRIORITY, ChallengeIndex, ChallengeIndexItem
from repo_idea_miner.config import Settings, load_settings
from repo_idea_miner.errors import GitHubError
from repo_idea_miner.github_api import GitHubClient, search_repositories
from repo_idea_miner.key_pool import KeyPool
from repo_idea_miner.pipeline import make_run_dir
from repo_idea_miner.redaction import redact_text
from repo_idea_miner.search_pipeline import _safe_name


def prioritize_candidates(candidates: list[dict], top: int) -> list[dict]:
    """중복 제거 → fork skip → archived 낮은 우선순위 → star 내림차순 → 상위 top개."""
    seen: set[str] = set()
    unique: list[dict] = []
    for c in candidates:
        name = c.get("full_name")
        if not name or name in seen:
            continue
        seen.add(name)
        if c.get("fork"):
            continue
        unique.append(c)
    unique.sort(key=lambda c: (1 if c.get("archived") else 0, -(c.get("stars") or 0)))
    return unique[:top]


def _sort_key(item: dict, scores: dict) -> tuple:
    """§23 정렬: 라벨 우선순위 → 지정된 점수 내림차순."""
    return (
        LABEL_PRIORITY.get(item.get("final_label"), 99),
        -(scores.get("difficulty_anchor_alive") or 0),
        -(scores.get("not_too_easy") or 0),
        -(scores.get("immediate_demo_value") or 0),
        -(scores.get("owner_clarity") or 0),
        -(scores.get("user_taste_fit") or 0),
        -(scores.get("reuse_potential") or 0),
    )


def run_challenge_search(
    query: str,
    limit: int = 50,
    top: int = 20,
    mode: str = "mock",
    output_dir: str | Path = "runs",
    settings: Settings | None = None,
    gh: GitHubClient | None = None,
    llm=None,
    max_issues: int = 10,
    max_prs: int = 10,
    tree_depth: int = 2,
    db_conn=None,
) -> dict:
    """검색 → 후보 필터/정렬 → repo별 Challenge 생성 → challenge_index.json/viewer.html."""
    settings = settings or load_settings()
    gh = gh or GitHubClient(settings.github_token)
    run_dir = make_run_dir(output_dir, with_debug=False)
    (run_dir / "repos").mkdir(exist_ok=True)
    secrets = settings.secret_values()
    errors: list[str] = []

    # live 모드에서 후보 간 key pool 공유 (round robin 유지)
    key_pool = None
    if llm is None and mode != "mock":
        key_pool = KeyPool(settings.google_keys, settings.key_pool_strategy)

    try:
        items = search_repositories(gh, query, limit)
    except GitHubError as exc:
        items = []
        errors.append(f"검색 실패: {type(exc).__name__}: {exc}")

    candidates = [
        {
            "full_name": it.get("full_name"),
            "url": it.get("html_url"),
            "description": it.get("description"),
            "stars": it.get("stargazers_count", 0),
            "forks": it.get("forks_count", 0),
            "topics": it.get("topics", []),
            "language": it.get("language"),
            "archived": it.get("archived", False),
            "fork": it.get("fork", False),
        }
        for it in items
    ]
    (run_dir / "candidates.json").write_text(
        redact_text(json.dumps(candidates, ensure_ascii=False, indent=2), secrets), encoding="utf-8"
    )
    selected = prioritize_candidates(candidates, top)

    if db_conn is not None:
        for cand in candidates:
            owner, _, name = (cand.get("full_name") or "").partition("/")
            upsert_repo(
                db_conn,
                {
                    "repo_url": cand.get("url"),
                    "owner": owner,
                    "name": name,
                    "description": cand.get("description"),
                    "stars": cand.get("stars"),
                    "forks": cand.get("forks"),
                    "language": cand.get("language"),
                    "topics": cand.get("topics"),
                    "archived": cand.get("archived"),
                    "fork": cand.get("fork"),
                },
            )

    results: list[dict] = []
    index_entries: list[tuple[dict, dict, dict]] = []  # (index_item, scores, view_item)
    label_counts: dict[str, int] = {}
    error_cards: list[dict] = []

    for cand in selected:
        full_name = cand["full_name"]
        repo_dir = run_dir / "repos" / _safe_name(full_name)
        repo_dir.mkdir(parents=True, exist_ok=True)
        try:
            res = run_challenge(
                cand["url"],
                mode=mode,
                settings=settings,
                gh=gh,
                llm=llm,
                key_pool=key_pool,
                run_dir=repo_dir,
                max_issues=max_issues,
                max_prs=max_prs,
                tree_depth=tree_depth,
                db_conn=db_conn,
                write_viewer=False,
            )
        except Exception as exc:  # noqa: BLE001 - 한 후보 실패가 전체 검색을 죽이면 안 됨
            errors.append(f"{full_name}: {type(exc).__name__}: {exc}")
            error_cards.append(
                {"source_repo": full_name, "repo_url": cand.get("url"), "final_label": "ERROR",
                 "error": f"{type(exc).__name__}: {exc}"}
            )
            continue
        results.append(res)
        if res.get("error") or not res.get("final_label"):
            errors.append(f"{full_name}: {res.get('error') or '생성 실패'}")
            error_cards.append(
                {"source_repo": full_name, "repo_url": cand.get("url"), "final_label": "ERROR",
                 "error": res.get("error") or "생성 실패"}
            )
            continue

        label = res["final_label"]
        label_counts[label] = label_counts.get(label, 0) + 1
        try:
            card = json.loads((repo_dir / "challenge_card.json").read_text(encoding="utf-8"))
            brief = json.loads((repo_dir / "owner_brief.json").read_text(encoding="utf-8"))
            story = json.loads((repo_dir / "screen_story.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{full_name}: 산출물 읽기 실패 {type(exc).__name__}")
            continue
        scores = card.get("scores") or {}
        short_reason = (
            "; ".join(res.get("auto_label_adjustments") or [])
            or (card.get("repo_summary") or "")[:120]
        )
        item = {
            "source_repo": full_name,
            "repo_url": cand.get("url") or "",
            "challenge_title": res.get("challenge_title") or "",
            "one_line_challenge": res.get("one_line_challenge") or "",
            "final_label": label,
            "owner_clarity_score": res.get("owner_clarity_score") or 0,
            "score_total": res.get("score_total") or 0,
            "difficulty_anchors": card.get("difficulty_anchors") or [],
            "short_reason": short_reason,
            "artifact_dir": str(repo_dir),
        }
        view = challenge_view_item(
            {"challenge_card": card, "owner_brief": brief, "screen_story": story}, cand.get("url")
        )
        index_entries.append((item, scores, view))

    # §23 정렬: GOOD_CHALLENGE/STEAL_ONLY 상단, TOO_EASY/DROP/UNCLEAR 하단
    index_entries.sort(key=lambda t: _sort_key(t[0], t[1]))
    sorted_items = [t[0] for t in index_entries]
    sorted_views = [t[2] for t in index_entries] + error_cards

    index = ChallengeIndex(
        query=query,
        mode=mode,
        total_candidates=len(candidates),
        generated_count=len(sorted_items),
        items=[ChallengeIndexItem.model_validate(i) for i in sorted_items],
    )
    (run_dir / "challenge_index.json").write_text(
        redact_text(index.model_dump_json(indent=2), secrets), encoding="utf-8"
    )

    report = {
        "query": query,
        "mode": mode,
        "requested_limit": limit,
        "requested_top": top,
        "collected_count": len(candidates),
        "selected_count": len(selected),
        "generated_count": len(sorted_items),
        "label_counts": label_counts,
        "error_count": len(error_cards),
        "errors": errors,
        "output_files": ["search_report.json", "challenge_index.json", "candidates.json", "viewer.html", "repos/"],
    }
    (run_dir / "search_report.json").write_text(
        redact_text(json.dumps(report, ensure_ascii=False, indent=2), secrets), encoding="utf-8"
    )

    viewer_model = {
        "kind": "search",
        "summary": {
            "query": query,
            "mode": mode,
            "generated_count": len(sorted_items),
            "good_count": label_counts.get("GOOD_CHALLENGE", 0),
            "steal_count": label_counts.get("STEAL_ONLY", 0),
            "too_easy_count": label_counts.get("TOO_EASY", 0),
            "drop_count": label_counts.get("DROP", 0),
            "error_count": len(error_cards),
        },
        "cards": sorted_views,
    }
    (run_dir / "viewer.html").write_text(
        redact_text(render_challenge_viewer_html(viewer_model), secrets), encoding="utf-8"
    )

    if db_conn is not None:
        log_event(
            db_conn,
            "challenge_search_done",
            f"query={query} generated={len(sorted_items)} errors={len(error_cards)}",
            metadata={"run_dir": str(run_dir)},
        )

    return {
        "run_dir": str(run_dir),
        "results": results,
        "index_items": sorted_items,
        "errors": errors,
        "label_counts": label_counts,
    }
