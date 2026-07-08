# 단일 레포 분석 파이프라인: 수집 → preflight → worker → 검증 → 렌더링 → secret 검증.
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from repo_idea_miner.ceiling import apply_score_ceiling
from repo_idea_miner.config import Settings, load_settings
from repo_idea_miner.errors import GitHubError, LLMCallError, RIMError
from repo_idea_miner.evidence import render_evidence_packet
from repo_idea_miner.github_api import (
    GitHubClient,
    collect_dependency_evidence,
    collect_file_tree,
    collect_issues,
    collect_metadata,
    collect_prs,
    collect_readme,
)
from repo_idea_miner.key_pool import KeyPool
from repo_idea_miner.llm_client import (
    GoogleGenAIGemmaClient,
    LLMCallLogger,
    LLMClient,
    MockLLMClient,
)
from repo_idea_miner.preflight import (
    ERROR_STOP,
    FAST_DROP_PREFLIGHT,
    PreflightResult,
    preflight_from_error,
    run_preflight,
)
from repo_idea_miner.redaction import redact_text, scan_files_for_secrets
from repo_idea_miner.renderer import (
    IDEA_CARD_SECTIONS,
    render_fast_drop_card,
    render_idea_card,
    render_run_report,
)
from repo_idea_miner.schemas import WORKER_SCHEMAS
from repo_idea_miner.signals import compute_issue_stats
from repo_idea_miner.truncation import apply_length_limits
from repo_idea_miner.url_parser import parse_repo_url
from repo_idea_miner.workers import PROMPT_BUILDERS, build_judge_prompt


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def make_run_dir(output_dir: str | Path, timestamp: str | None = None, with_debug: bool = True) -> Path:
    base = Path(output_dir)
    ts = timestamp or _timestamp()
    run_dir = base / ts
    suffix = 1
    while run_dir.exists():
        run_dir = base / f"{ts}_{suffix}"
        suffix += 1
    if with_debug:
        for sub in ("debug/worker_outputs", "debug/prompts", "debug/raw"):
            (run_dir / sub).mkdir(parents=True, exist_ok=True)
    else:
        run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


class RunContext:
    """단일 run 동안의 상태/산출물 기록."""

    def __init__(self, run_dir: Path, settings: Settings, mode: str, input_mode: str, repo_url: str):
        self.run_dir = run_dir
        self.settings = settings
        self.mode = mode
        self.input_mode = input_mode
        self.repo_url = repo_url
        self.secrets = settings.secret_values()
        self.errors: list[str] = []
        self.missing: list[str] = []
        self.output_files: list[str] = []

    def write_text(self, rel_path: str, text: str) -> Path:
        path = self.run_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(redact_text(text, self.secrets), encoding="utf-8")
        if rel_path not in self.output_files:
            self.output_files.append(rel_path)
        return path

    def write_json(self, rel_path: str, obj) -> Path:
        return self.write_text(rel_path, json.dumps(obj, ensure_ascii=False, indent=2))


def collect_all(gh: GitHubClient, owner: str, repo: str, max_issues: int, max_prs: int, tree_depth: int) -> dict:
    """metadata는 실패 시 예외를 던지고, 나머지는 MISSING/ERROR로 기록한다."""
    collected: dict = {"missing": [], "collector_notes": [], "status": {}}
    metadata = collect_metadata(gh, owner, repo)  # 실패 시 예외 → ERROR_STOP
    collected["metadata"] = metadata
    collected["metadata_status"] = "OK"
    collected["status"]["metadata"] = "OK"

    def safe(name, fn, default):
        try:
            return fn()
        except GitHubError as exc:
            collected["missing"].append(name)
            collected["collector_notes"].append(f"{name} 수집 실패: {type(exc).__name__}")
            collected["status"][name] = "ERROR"
            return default

    readme_status, readme_text = safe("readme", lambda: collect_readme(gh, owner, repo), ("MISSING", None))
    collected["readme_status"] = readme_status
    collected["readme_text"] = readme_text
    collected["status"]["readme"] = readme_status
    if readme_status == "MISSING":
        collected["missing"].append("readme")

    issues = safe("issues", lambda: collect_issues(gh, owner, repo, max_issues), {"status": "ERROR", "all_records": []})
    collected["issues"] = issues
    collected["status"]["issues"] = issues.get("status", "ERROR")

    prs = safe("prs", lambda: collect_prs(gh, owner, repo, max_prs), {"status": "ERROR", "human": [], "excluded_bot": []})
    collected["prs"] = prs
    collected["status"]["prs"] = prs.get("status", "ERROR")

    tree = safe(
        "file_tree",
        lambda: collect_file_tree(gh, owner, repo, metadata.get("default_branch", "main"), tree_depth),
        {"status": "ERROR", "paths": [], "docs_examples_demo": []},
    )
    collected["tree"] = tree
    collected["status"]["file_tree"] = tree.get("status", "ERROR")

    dep = safe(
        "dependency",
        lambda: collect_dependency_evidence(gh, owner, repo, readme_text),
        {"status": "not_collected", "files_found": [], "entries": [], "docker": None, "risk_keyword_hits": []},
    )
    collected["dependency"] = dep
    collected["status"]["dependency"] = dep.get("status", "not_collected")
    return collected


def _key_pool_report(settings: Settings, pool: KeyPool | None, client) -> dict:
    report = {
        "provider": settings.provider,
        "model": settings.model,
        "configured_key_count": settings.configured_key_count,
        "loaded_key_count": settings.loaded_key_count,
        "strategy": settings.key_pool_strategy,
        "used_key_indexes": pool.used_key_indexes if pool else [],
        "disabled_key_indexes": pool.disabled_key_indexes if pool else [],
        "temp_failed_key_indexes": pool.temp_failed_key_indexes if pool else [],
        "retry_count": getattr(client, "retry_count", 0),
        "failover_count": getattr(client, "failover_count", 0),
        "retry_backoff_strategy": settings.retry_backoff_strategy,
        "retry_initial_delay_seconds": settings.retry_initial_delay_seconds,
        "retry_max_delay_seconds": settings.retry_max_delay_seconds,
        "request_timeout_seconds": settings.request_timeout_seconds,
        "respect_retry_after": settings.respect_retry_after,
    }
    return report


def _issue_sampler_report(issue_records: list[dict]) -> dict:
    stats = compute_issue_stats(issue_records)
    return {
        "sampled_issue_count": stats["sampled_issue_count"],
        "template_sections_compressed": "YES",
        "defect_count": stats["defect_count"],
        "feature_request_count": stats["feature_request_count"],
        "workflow_pain_count": stats["workflow_pain_count"],
        "confusion_count": stats["confusion_count"],
        "noise_count": stats["noise_count"],
        "uncertain_count": stats["uncertain_count"],
    }


def _comments_report(issues: dict) -> dict:
    high = issues.get("high_comment_open") or []
    all_records = issues.get("all_records") or []
    return {
        "high_comment_issue_count": len(high),
        "unique_commenters_available": "YES" if any(r.get("unique_commenters_count") is not None for r in all_records) else "NO",
        "bike_shedding_possible_count": sum(1 for r in all_records if r.get("bike_shedding_possible")),
    }


def _content_gate(card_text: str) -> str:
    return "PASS" if all(section in card_text for section in IDEA_CARD_SECTIONS) else "FAIL"


def _finalize_secret_check(ctx: RunContext, report_ctx: dict) -> None:
    """run_report 작성 전 모든 산출물 secret 스캔 → report에 기록."""
    files = [p for p in ctx.run_dir.rglob("*") if p.is_file()]
    leaked = scan_files_for_secrets(files, ctx.secrets)
    report_ctx["secret_redaction"] = "FAIL" if leaked else "PASS"
    report_ctx["token_exposure"] = "YES" if leaked else "NO"
    if leaked:
        ctx.errors.append(f"secret 노출 파일: {leaked}")


def final_secret_scan(run_dir: Path, secret_values: list[str]) -> list[str]:
    """run_report.md 포함 runs/<timestamp>/ 전체를 다시 스캔한다 (§7.6 최종 안전장치)."""
    files = [p for p in Path(run_dir).rglob("*") if p.is_file()]
    return scan_files_for_secrets(files, secret_values)


def run_single_repo(
    repo_url: str,
    mode: str = "mock",
    input_mode: str = "direct",
    output_dir: str | Path = "runs",
    max_issues: int = 10,
    max_prs: int = 10,
    tree_depth: int = 2,
    settings: Settings | None = None,
    gh: GitHubClient | None = None,
    llm: LLMClient | None = None,
    key_pool: KeyPool | None = None,
    run_dir: Path | None = None,
) -> dict:
    """단일 레포 분석 실행. 결과 요약 dict를 반환한다."""
    settings = settings or load_settings()
    owner, repo = parse_repo_url(repo_url)
    full_name = f"{owner}/{repo}"
    run_dir = run_dir or make_run_dir(output_dir)
    ctx = RunContext(run_dir, settings, mode, input_mode, repo_url)
    timestamp = run_dir.name

    logger = LLMCallLogger(run_dir / "debug" / "llm_calls.jsonl", ctx.secrets)
    if llm is None:
        if mode == "mock":
            llm = MockLLMClient(call_logger=logger)
        else:
            key_pool = key_pool or KeyPool(settings.google_keys, settings.key_pool_strategy)
            llm = GoogleGenAIGemmaClient(settings, key_pool, call_logger=logger)
    pool = key_pool or getattr(llm, "key_pool", None)

    gh = gh or GitHubClient(settings.github_token)

    report_ctx: dict = {
        "repo": repo_url,
        "mode": mode,
        "input_mode": input_mode,
        "timestamp": timestamp,
        "missing_data": ctx.missing,
        "errors": ctx.errors,
        "output_files": ctx.output_files,
        "json_validation": "PASS",
        "content_gate": "FAIL",
    }
    result: dict = {
        "repo": full_name,
        "url": repo_url,
        "run_dir": str(run_dir),
        "fast_drop": False,
        "verdict": None,
        "score": None,
        "one_line_conclusion": None,
        "core_pattern": None,
        "correction_applied": False,
        "preflight_status": None,
        "error": None,
        "drop_reason": None,
    }

    def finish(exit_ok: bool) -> dict:
        report_ctx["key_pool"] = _key_pool_report(settings, pool, llm)
        result["llm_retry_count"] = getattr(llm, "retry_count", 0)
        result["llm_failover_count"] = getattr(llm, "failover_count", 0)
        _finalize_secret_check(ctx, report_ctx)
        ctx.write_text("run_report.md", render_run_report(report_ctx))
        # run_report.md 포함 전체 재스캔 — 최종 PASS/FAIL은 이 결과 기준 (§7.6)
        leaked = final_secret_scan(ctx.run_dir, ctx.secrets)
        if leaked:
            report_ctx["secret_redaction"] = "FAIL"
            report_ctx["token_exposure"] = "YES"
            ctx.errors.append(f"최종 secret scan 실패: {leaked}")
            ctx.write_text("run_report.md", render_run_report(report_ctx))
        result["ok"] = exit_ok and not leaked and report_ctx.get("secret_redaction") == "PASS"
        return result

    # 1~13: 수집 + preflight + evidence packet
    try:
        collected = collect_all(gh, owner, repo, max_issues, max_prs, tree_depth)
    except (GitHubError, RIMError) as exc:
        pf = preflight_from_error(exc)
        result["preflight_status"] = pf.status
        result["error"] = pf.reason
        report_ctx.update(preflight_status=pf.status, preflight_reason=pf.reason, json_validation="SKIPPED")
        ctx.errors.append(pf.reason)
        return finish(False)

    issue_records = (collected.get("issues") or {}).get("all_records") or []
    pf: PreflightResult = run_preflight(
        collected["metadata"], collected["readme_status"], len(issue_records), input_mode
    )
    result["preflight_status"] = pf.status
    report_ctx.update(preflight_status=pf.status, preflight_reason=pf.reason)
    report_ctx["collector_status"] = collected["status"]
    report_ctx["issue_sampler"] = _issue_sampler_report(issue_records)
    report_ctx["comments_signal"] = _comments_report(collected.get("issues") or {})

    # raw 저장
    ctx.write_json("debug/raw/metadata.json", collected["metadata"])
    ctx.write_text("debug/raw/readme.md", collected.get("readme_text") or "(MISSING)")
    ctx.write_json("debug/raw/issues.json", collected.get("issues") or {})
    ctx.write_json("debug/raw/prs.json", collected.get("prs") or {})
    ctx.write_json("debug/raw/file_tree.json", collected.get("tree") or {})
    ctx.write_json("debug/raw/dependency_evidence.json", collected.get("dependency") or {})

    evidence_md = render_evidence_packet(collected, pf.status, pf.reason, input_mode)
    ctx.write_text("debug/evidence_packet.md", evidence_md)

    if pf.status == ERROR_STOP:
        result["error"] = pf.reason
        return finish(False)
    if pf.status == FAST_DROP_PREFLIGHT:
        result.update(fast_drop=True, verdict="DROP", score=0, drop_reason=pf.reason, one_line_conclusion=pf.reason)
        card = render_fast_drop_card(full_name, pf.reason, "preflight")
        ctx.write_text("idea_card.md", card)
        report_ctx["content_gate"] = _content_gate(card)
        return finish(True)

    # 14~19: workers
    worker_outputs: dict = {}
    try:
        for name in ("bouncer", "readme_scout", "pain_scout", "structure_risk_scout"):
            prompt = PROMPT_BUILDERS[name](evidence_md)
            ctx.write_text(f"debug/prompts/{name}.md", prompt)
            raw = llm.generate_json(prompt, name, worker=name)
            validated = WORKER_SCHEMAS[name].model_validate(raw)
            worker_outputs[name] = validated.model_dump()
            ctx.write_json(f"debug/worker_outputs/{name}.json", worker_outputs[name])
            if name == "bouncer" and worker_outputs[name]["bouncer_decision"] == "FAST_DROP":
                reason = worker_outputs[name]["reason"]
                result.update(fast_drop=True, verdict="DROP", score=0, drop_reason=reason, one_line_conclusion=reason)
                card = render_fast_drop_card(full_name, reason, "bouncer")
                ctx.write_text("idea_card.md", card)
                report_ctx["content_gate"] = _content_gate(card)
                return finish(True)

        issue_stats = compute_issue_stats(issue_records)
        issue_stats_for_judge = {k: v for k, v in issue_stats.items() if k != "uncertain_count"}
        judge_prompt = build_judge_prompt(evidence_md, worker_outputs, issue_stats_for_judge)
        ctx.write_text("debug/prompts/critic_judge.md", judge_prompt)
        judge_raw = llm.generate_json(judge_prompt, "critic_judge", worker="critic_judge")
        ctx.write_json("debug/worker_outputs/critic_judge_raw.json", judge_raw)
        ctx.write_json("debug/judge_output_raw.json", judge_raw)
    except (LLMCallError, RIMError) as exc:
        msg = f"LLM 호출 실패: {type(exc).__name__}: {exc}"
        ctx.errors.append(msg)
        result["error"] = msg
        report_ctx["json_validation"] = "FAIL"
        return finish(False)

    # 20~21: validation (+ client 내부에서 syntax repair 1회 수행됨)
    try:
        judge = WORKER_SCHEMAS["critic_judge"].model_validate(judge_raw).model_dump()
    except ValidationError as exc:
        ctx.errors.append(f"VALIDATION_FAIL: {exc.error_count()}개 필드 오류")
        ctx.write_text("debug/validation_errors.txt", str(exc))
        report_ctx["json_validation"] = "FAIL"
        result["error"] = "VALIDATION_FAIL"
        return finish(False)
    report_ctx["json_validation"] = "PASS"

    # 22: score ceiling
    ceiling = apply_score_ceiling(judge)
    report_ctx["ceiling"] = {
        "judge_raw_verdict": ceiling.judge_raw_verdict,
        "judge_raw_score": ceiling.judge_raw_score,
        "validator_final_verdict": ceiling.validator_final_verdict,
        "validator_final_score": ceiling.validator_final_score,
        "correction_applied": ceiling.correction_applied,
        "correction_reason": ceiling.correction_reason,
        "ceiling_rules_applied": ceiling.ceiling_rules_applied,
    }

    # 23~24: truncation + final
    # 길이 초과는 Error가 아니라 축약 — Length Truncation 섹션에만 기록 (§7.5)
    final, truncated_fields = apply_length_limits(ceiling.final)
    report_ctx["truncation"] = {"truncated_fields": truncated_fields}
    ctx.write_json("debug/worker_outputs/critic_judge_final.json", final)
    ctx.write_json("debug/judge_output_final.json", final)

    # 25~27: 렌더링 + secret 검증
    card = render_idea_card(final, full_name)
    ctx.write_text("idea_card.md", card)
    report_ctx["content_gate"] = _content_gate(card)

    result.update(
        verdict=final["verdict"],
        score=final["score"],
        fast_drop=final.get("fast_drop", False),
        one_line_conclusion=final.get("one_line_conclusion"),
        core_pattern=final.get("core_pattern"),
        correction_applied=ceiling.correction_applied,
    )
    return finish(True)
