# 수집 결과를 debug/evidence_packet.md 형식으로 렌더링하는 모듈.
from __future__ import annotations

from repo_idea_miner.github_api import readme_signals


def _yesno(v) -> str:
    return "YES" if v else "NO"


def _issue_block(rec: dict) -> str:
    return "\n".join(
        [
            f"- title: {rec.get('title')}",
            f"  - number: #{rec.get('number')}",
            f"  - labels: {', '.join(rec.get('labels') or []) or '(없음)'}",
            f"  - comments_count: {rec.get('comments_count')}",
            f"  - unique_commenters_count: {rec.get('unique_commenters_count')}",
            f"  - maintainer_comment_ratio: {rec.get('maintainer_comment_ratio')}",
            f"  - bot_comment_count: {rec.get('bot_comment_count')}",
            f"  - bike_shedding_possible: {_yesno(rec.get('bike_shedding_possible'))}",
            f"  - updated_at: {rec.get('updated_at')}",
            f"  - signal_tags: {', '.join(rec.get('signal_tags') or [])}",
            f"  - body_sample: {(rec.get('body_sample') or '').replace(chr(10), ' ')[:600]}",
        ]
    )


def render_evidence_packet(collected: dict, preflight_status: str, preflight_reason: str, input_mode: str) -> str:
    meta = collected.get("metadata") or {}
    meta_status = collected.get("metadata_status", "OK" if meta else "ERROR")
    readme_status = collected.get("readme_status", "MISSING")
    readme_text = collected.get("readme_text")
    rsig = readme_signals(readme_text)
    issues = collected.get("issues") or {}
    prs = collected.get("prs") or {}
    tree = collected.get("tree") or {}
    dep = collected.get("dependency") or {}
    missing = collected.get("missing") or []
    notes = collected.get("collector_notes") or []

    lines: list[str] = ["# Evidence Packet", ""]

    lines += ["## Repo Metadata", f"status: {meta_status}"]
    if meta:
        lines += [
            f"- full_name: {meta.get('full_name')}",
            f"- description: {meta.get('description')}",
            f"- stars: {meta.get('stars')} / forks: {meta.get('forks')} / watchers: {meta.get('watchers')}",
            f"- topics: {', '.join(meta.get('topics') or []) or '(없음)'}",
            f"- primary_language: {meta.get('primary_language')} / languages: {', '.join(meta.get('languages') or [])}",
            f"- created_at: {meta.get('created_at')} / updated_at: {meta.get('updated_at')} / pushed_at: {meta.get('pushed_at')}",
            f"- archived: {_yesno(meta.get('archived'))} / disabled: {_yesno(meta.get('disabled'))} / fork: {_yesno(meta.get('fork'))}",
            f"- open_issues_count: {meta.get('open_issues_count')}",
            f"- license: {meta.get('license')} / homepage: {meta.get('homepage')}",
            f"- default_branch: {meta.get('default_branch')} / size: {meta.get('size')}",
        ]
    lines += ["", "## Input Mode", input_mode, ""]
    lines += ["## Preflight", f"status: {preflight_status}", f"reason: {preflight_reason}", ""]

    lines += ["## README Signal", f"status: {readme_status}"]
    if rsig.get("status") == "OK":
        lines += [
            f"- length: {rsig['length']}",
            f"- has_install: {_yesno(rsig['has_install'])} / has_usage_example: {_yesno(rsig['has_usage_example'])} / has_features: {_yesno(rsig['has_features'])}",
            f"- has_demo_or_docs_link: {_yesno(rsig['has_demo_or_docs_link'])} / mentions_api: {_yesno(rsig['mentions_api'])} / mentions_docker: {_yesno(rsig['mentions_docker'])}",
            f"- external_service_keywords: {', '.join(rsig['external_service_keywords']) or '(없음)'}",
            "",
            "### README Excerpt",
            "```",
            (readme_text or "")[:3000],
            "```",
        ]
    lines += [""]

    lines += ["## User Pain Signal", f"status: {issues.get('status', 'MISSING')}", ""]
    for heading, key in [
        ("### Recent Open Issues", "recent_open"),
        ("### High Comment Open Issues", "high_comment_open"),
        ("### Recent Closed Issues", "recent_closed"),
    ]:
        lines.append(heading)
        bucket = issues.get(key) or []
        if not bucket:
            lines.append("(없음)")
        else:
            for rec in bucket:
                lines.append(_issue_block(rec))
        lines.append("")

    lines += ["## PR Signal", f"status: {prs.get('status', 'MISSING')}", "", "### Recent Human PRs"]
    for pr in prs.get("human") or []:
        lines.append(f"- {pr.get('title')} (by {pr.get('author')}, {pr.get('updated_at')})")
    if not (prs.get("human") or []):
        lines.append("(없음)")
    lines += ["", "### Excluded Bot / Dependency PRs"]
    for pr in prs.get("excluded_bot") or []:
        lines.append(f"- {pr.get('title')} (by {pr.get('author')})")
    if not (prs.get("excluded_bot") or []):
        lines.append("(없음)")
    lines.append("")

    lines += ["## Structure Signal", f"status: {tree.get('status', 'MISSING')}", "", "### File Tree Depth 2", "```"]
    lines += (tree.get("paths") or ["(없음)"])[:200]
    lines += ["```", "", "### Docs / Examples / Demo Paths"]
    doc_paths = tree.get("docs_examples_demo") or []
    lines += [f"- {p}" for p in doc_paths] or ["(없음)"]
    lines.append("")

    lines += ["## Dependency / Runtime Evidence", f"status: {dep.get('status', 'not_collected')}"]
    lines.append(f"- files_found: {', '.join(dep.get('files_found') or []) or '(없음)'}")
    entries = dep.get("entries") or []
    if entries:
        lines.append("- entries:")
        for e in entries[:80]:
            lines.append(f"  - [{e['origin']}] {e['name']} ({e['file']})")
    docker = dep.get("docker")
    if docker:
        lines.append(f"- docker: origin={docker['origin']} / {docker['note']}")
    hits = dep.get("risk_keyword_hits") or []
    if hits:
        lines.append("- risk_keyword_hits:")
        for h in hits[:40]:
            lines.append(f"  - {h['keyword']} @ {h['where']} (origin={h['origin']})")
    lines.append("")

    lines += ["## Missing Data"]
    lines += [f"- {m}" for m in missing] or ["(없음)"]
    lines += ["", "## Collector Notes"]
    lines += [f"- {n}" for n in notes] or ["(없음)"]
    lines.append("")
    return "\n".join(lines)
