# CLI command handler 모듈 — 각 command의 실행·출력·종료 코드를 담당한다 (cli.py는 parser/dispatch만).
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable

from repo_idea_miner.config import load_settings

# ---------------------------------------------------------------- 공통 헬퍼


def _open_db_if_exists(db_path: str):
    """DB 파일이 이미 있을 때만 연다 (수리/검토 계열 command 공통 규약)."""
    from repo_idea_miner.factory_db import open_factory_db

    return open_factory_db(db_path) if Path(db_path).exists() else None


def _live_scheduler(db_conn):
    """live 모드에서 google key가 있으면 ChallengeKeyScheduler를 만든다."""
    from repo_idea_miner.challenge_key_scheduler import ChallengeKeyScheduler
    from repo_idea_miner.config import load_challenge_miner_settings

    settings = load_settings()
    if not settings.google_keys:
        return None
    return ChallengeKeyScheduler(db_conn, settings.google_keys, load_challenge_miner_settings())


def _missing_run_target(args) -> bool:
    """--run-dir/--run-id 둘 다 없으면 오류 출력 후 True."""
    if args.run_dir or args.run_id:
        return False
    print("오류: --run-dir 또는 --run-id가 필요합니다.", file=sys.stderr)
    return True


def _conflicting_dry_run_apply(args) -> bool:
    if not (args.dry_run and args.apply):
        return False
    print("오류: --dry-run과 --apply는 동시에 쓸 수 없습니다.", file=sys.stderr)
    return True


def _run_id_needs_db(args, db_conn) -> bool:
    if not (args.run_id and db_conn is None):
        return False
    print("오류: --run-id는 DB가 필요합니다.", file=sys.stderr)
    return True


# ---------------------------------------------------------------- Miner


def _cmd_run(args) -> int:
    from repo_idea_miner.pipeline import run_single_repo

    mode = "mock" if args.no_llm else args.mode
    result = run_single_repo(
        args.repo,
        mode=mode,
        input_mode=args.input_mode,
        output_dir=args.output_dir,
        max_issues=args.max_issues,
        max_prs=args.max_prs,
        tree_depth=args.tree_depth,
    )
    print(f"run_dir: {result['run_dir']}")
    if result.get("error"):
        print(f"실패: {result['error']}")
        return 1
    print(f"verdict: {result.get('verdict')} / score: {result.get('score')} / fast_drop: {result.get('fast_drop')}")
    return 0 if result.get("ok") else 1


def _cmd_search(args) -> int:
    from repo_idea_miner.search_pipeline import run_search

    out = run_search(
        args.query,
        limit=args.limit,
        top=args.top,
        mode=args.mode,
        output_dir=args.output_dir,
        explore=args.explore,
        targeted=args.targeted,
        max_issues=args.max_issues,
        max_prs=args.max_prs,
        tree_depth=args.tree_depth,
    )
    print(f"run_dir: {out['run_dir']}")
    print(f"analyzed: {len(out['results'])} / errors: {len(out['errors'])}")
    return 0


def _cmd_view(args) -> int:
    from repo_idea_miner.viewer import generate_viewer

    out = generate_viewer(args.run_dir)
    print(f"viewer: {out}")
    return 0


def _cmd_serve(args) -> int:
    from repo_idea_miner.serve import serve

    serve(args.run_dir, host=args.host, port=args.port)
    return 0


def _cmd_validate(args) -> int:
    from repo_idea_miner.challenge_validate import (
        detect_challenge_run,
        validate_challenge_run_dir,
        validate_db,
    )
    from repo_idea_miner.validate_run import validate_run_dir

    settings = load_settings()
    # challenge run 디렉터리는 challenge 검증으로 라우팅 (기존 idea run 검증은 그대로 유지)
    if detect_challenge_run(Path(args.run_dir)):
        ok, problems = validate_challenge_run_dir(args.run_dir, settings.secret_values())
    else:
        ok, problems = validate_run_dir(
            args.run_dir, settings.secret_values(), require_viewer=args.require_viewer
        )
    if args.db:
        db_ok, db_problems = validate_db(args.db)
        ok = ok and db_ok
        problems = problems + [f"DB: {p}" for p in db_problems]
    if ok:
        print("VALIDATION PASS")
        return 0
    for p in problems:
        print(f"FAIL: {p}")
    return 1


# ---------------------------------------------------------------- Challenge Mode


def _cmd_challenge(args) -> int:
    from repo_idea_miner.challenge_db import open_db
    from repo_idea_miner.challenge_pipeline import run_challenge

    db_conn = None if args.no_db else open_db(args.db)
    try:
        result = run_challenge(
            args.repo,
            mode=args.mode,
            output_dir=args.output_dir,
            max_issues=args.max_issues,
            max_prs=args.max_prs,
            tree_depth=args.tree_depth,
            db_conn=db_conn,
        )
    finally:
        if db_conn is not None:
            db_conn.close()
    print(f"run_dir: {result['run_dir']}")
    if result.get("error"):
        print(f"실패: {result['error']}")
        return 1
    print(
        f"final_label: {result.get('final_label')} / score_total: {result.get('score_total')} "
        f"/ owner_clarity: {result.get('owner_clarity_score')}"
    )
    if result.get("challenge_id"):
        print(f"challenge_id: {result['challenge_id']} (db: {args.db})")
    return 0 if result.get("ok") else 1


def _cmd_challenge_search(args) -> int:
    from repo_idea_miner.challenge_db import open_db
    from repo_idea_miner.challenge_search_pipeline import run_challenge_search

    db_conn = None if args.no_db else open_db(args.db)
    try:
        out = run_challenge_search(
            args.query,
            limit=args.limit,
            top=args.top,
            mode=args.mode,
            output_dir=args.output_dir,
            max_issues=args.max_issues,
            max_prs=args.max_prs,
            tree_depth=args.tree_depth,
            db_conn=db_conn,
        )
    finally:
        if db_conn is not None:
            db_conn.close()
    print(f"run_dir: {out['run_dir']}")
    print(f"generated: {len(out['index_items'])} / errors: {len(out['errors'])}")
    for label, n in sorted(out["label_counts"].items()):
        print(f"  {label}: {n}")
    return 0


def _cmd_daemon(args) -> int:
    from repo_idea_miner.challenge_daemon import ChallengeDaemon

    daemon = ChallengeDaemon(
        db_path=args.db, output_dir=args.output_dir, mode=args.mode, seeds_path=args.seeds
    )
    if args.once:
        from repo_idea_miner.challenge_db import queue_counts

        info = daemon.run_cycle()
        daemon.wait_workers(timeout=600.0)
        q = queue_counts(daemon.conn)
        print(
            f"paused={info['paused']} started={info['started']} "
            f"queued={q['queued']} done={q['done']} error={q['error']}"
        )
        daemon.conn.close()
        return 0
    daemon.run_forever()
    return 0


def _cmd_dashboard(args) -> int:
    from repo_idea_miner.challenge_dashboard import serve_dashboard

    settings = load_settings()
    serve_dashboard(args.db, host=args.host, port=args.port, secrets=settings.secret_values())
    return 0


def _cmd_status(args) -> int:
    from repo_idea_miner.challenge_daemon import daemon_status

    s = daemon_status(args.db)
    q = s["queue"]
    print(f"miner_paused: {s['paused']}")
    print(f"queue: queued={q['queued']} in_progress={q['in_progress']} done={q['done']} error={q['error']} skipped={q['skipped']}")
    print(f"challenges: {s['challenge_count']} / error events: {s['error_count']}")
    for k in s["keys"]:
        print(
            f"key {k['key_id']}: {k['status']} daily_used={k['daily_used']} "
            f"errors={k['consecutive_errors']} next_available_at={k['next_available_at'] or '-'}"
        )
    for c in s["recent_challenges"]:
        print(f"recent: [{c['final_label']}] {c['challenge_title']} ({c['created_at']})")
    return 0


def _cmd_pause(args) -> int:
    from repo_idea_miner.challenge_daemon import set_paused

    set_paused(args.db, True)
    print("miner_paused=true (진행 중 작업은 안전하게 종료됩니다)")
    return 0


def _cmd_resume(args) -> int:
    from repo_idea_miner.challenge_daemon import set_paused

    set_paused(args.db, False)
    print("miner_paused=false")
    return 0


def _cmd_validate_db(args) -> int:
    from repo_idea_miner.challenge_validate import validate_db

    ok, problems = validate_db(args.db)
    if ok:
        print("DB VALIDATION PASS")
        return 0
    for p in problems:
        print(f"FAIL: {p}")
    return 1


# ---------------------------------------------------------------- Product Factory


def _cmd_factory(args) -> int:
    from repo_idea_miner.factory_runner import run_factory

    # 기본 실행은 안전 모드: --continuous를 명시하지 않으면 max_runs 제한 (§19.1)
    if args.once and args.max_runs:
        print("오류: --once와 --max-runs는 동시에 쓸 수 없습니다.", file=sys.stderr)
        return 1
    max_runs = 1 if args.once else (args.max_runs if args.max_runs else 1)
    summary = run_factory(
        db_path=args.db,
        mode=args.mode,
        output_dir=args.output_dir,
        max_runs=max_runs,
        continuous=args.continuous,
    )
    print(f"processed: {summary['processed']} / errors: {summary['errors']}")
    for r in summary["runs"]:
        status = r["verdict"] or r["error"] or "(진행 실패)"
        print(f"  challenge {r['challenge_id']}: {status} → {r['run_dir']}")
    return 0 if summary["errors"] == 0 else 1


def _cmd_factory_build(args) -> int:
    from repo_idea_miner.factory_core_pipeline import run_core_factory
    from repo_idea_miner.factory_db import open_factory_db
    from repo_idea_miner.factory_pipeline import (
        load_challenge_from_db,
        load_challenge_from_dir,
        sample_challenge,
    )

    if not (args.challenge_id or args.challenge_dir or args.sample):
        print("오류: --challenge-id / --challenge-dir / --sample 중 하나가 필요합니다.", file=sys.stderr)
        return 1
    db_conn = None if args.no_db else open_factory_db(args.db)
    try:
        # source of truth 우선순위: --challenge-id > --challenge-dir > --sample (§19.2)
        if args.challenge_id is not None:
            if db_conn is None:
                print("오류: --challenge-id는 DB가 필요합니다 (--no-db와 함께 쓸 수 없음).", file=sys.stderr)
                return 1
            challenge = load_challenge_from_db(db_conn, args.challenge_id)
        elif args.challenge_dir:
            challenge = load_challenge_from_dir(args.challenge_dir)
        else:
            challenge = sample_challenge()
        scheduler = None
        if args.mode == "live" and db_conn is not None:
            scheduler = _live_scheduler(db_conn)
        result = run_core_factory(
            challenge, mode=args.mode, output_dir=args.output_dir,
            db_conn=db_conn, scheduler=scheduler, candidates=args.candidates,
            live_validation=args.live_validation,
        )
    finally:
        if db_conn is not None:
            db_conn.close()
    print(f"run_dir: {result.get('run_dir')}")
    if result.get("error"):
        print(f"실패: {result['error']}")
        return 1
    if result.get("spec_status"):
        print(f"line: {result.get('line')} / spec_status: {result['spec_status']} (Build 미진행)")
        return 0
    print(f"line: {result.get('line')} / artifact_class: {result.get('artifact_class')} "
          f"/ verdict: {result.get('verdict')} (추천: {result.get('recommended_action')})")
    gates = result.get("gate_summary") or {}
    print("gates: " + " ".join(f"{g}={'PASS' if ok else 'FAIL'}" for g, ok in gates.items()))
    print(f"candidates: {result.get('candidates')} / patch_attempts: {result.get('patch_attempts')}")
    if result.get("green_base_path"):
        print(f"green_base: {result['green_base_path']}")
    if result.get("codex_export_dir"):
        print(f"codex_export: {result['codex_export_dir']}")
    if result.get("product_run_id"):
        print(f"product_run_id: {result['product_run_id']} (db: {args.db})")
    return 0


def _cmd_factory_continue(args) -> int:
    from repo_idea_miner.factory_continue import run_continuation
    from repo_idea_miner.factory_db import open_factory_db

    if not (args.run_id or args.run_dir):
        print("오류: --run-id 또는 --run-dir 중 하나가 필요합니다.", file=sys.stderr)
        return 1
    # live patch는 key scheduler가 필요하고 scheduler는 db가 필요하다 —
    # --run-dir라도 live면 db를 연다 (없으면 patch가 LLM 호출 없이 실패해 오해를 만든다).
    need_db = not args.no_db and (bool(args.run_id) or args.mode == "live")
    db_conn = open_factory_db(args.db) if need_db else None
    if _run_id_needs_db(args, db_conn):
        return 1
    try:
        scheduler = None
        if args.mode == "live" and db_conn is not None:
            scheduler = _live_scheduler(db_conn)
        result = run_continuation(
            base_run_dir=args.run_dir, base_run_id=args.run_id, mode=args.mode,
            max_patches=args.max_patches, output_dir=args.output_dir,
            db_conn=db_conn, scheduler=scheduler,
        )
    finally:
        if db_conn is not None:
            db_conn.close()
    if result.get("status") == "CANNOT_CONTINUE":
        print(f"CANNOT_CONTINUE: {result.get('error')}")
        return 1
    if result.get("error") and result.get("status") != "DONE":
        print(f"실패: {result['error']}")
        return 1
    print(f"continuation_run_dir: {result.get('continuation_run_dir')}")
    print(f"base: {result.get('base_run_dir')} / challenge_id: {result.get('challenge_id')}")
    print(f"failure_types: {result.get('failure_types')}")
    print(f"patch_attempts: {result.get('patch_attempts')} / "
          f"transient_retries: {result.get('transient_retries')} / "
          f"rejected: {len(result.get('rejected_patches') or [])}")
    print(f"resolved: {result.get('resolved')}")
    print(f"verdict: {result.get('verdict')} / "
          f"promoted_to_green_base: {result.get('promoted_to_green_base')}")
    if result.get("green_base_path"):
        print(f"green_base: {result['green_base_path']}")
    return 0


def _cmd_factory_spec_repair_apply(args) -> int:
    from repo_idea_miner.factory_spec_repair import run_spec_repair_apply

    if _missing_run_target(args) or _conflicting_dry_run_apply(args):
        return 1
    db_conn = _open_db_if_exists(args.db)
    if _run_id_needs_db(args, db_conn):
        return 1
    try:
        scheduler = None
        if args.apply and args.mode == "live" and db_conn is not None:
            scheduler = _live_scheduler(db_conn)
        out = run_spec_repair_apply(
            run_dir=args.run_dir, run_id=args.run_id, apply=args.apply,
            mode=args.mode, db_conn=db_conn, scheduler=scheduler,
        )
    finally:
        if db_conn is not None:
            db_conn.close()
    print("SPEC REPAIR APPLY" + (" (apply)" if args.apply else " (dry-run)"))
    print(f"- resolved_run_dir: {out.get('resolved_run_dir')}")
    print(f"- base_run_id: {out.get('base_run_id')} / challenge_id: {out.get('challenge_id')}")
    if out.get("history_run_ids"):
        print(f"- continuation/history run ids: {out['history_run_ids']}")
    print(f"- status: {out.get('status')}")
    for p in out.get("problems") or []:
        print(f"  BLOCKED: {p}")
    if out.get("error"):
        print(f"오류: {out['error']}", file=sys.stderr)
    if out.get("plan"):
        print(f"- planned files: {out['plan']['planned_files']}")
        print(f"- plan: {out['resolved_run_dir']}\\spec_repair_apply_plan.json")
    if out.get("applied"):
        print(f"- applied files: {out['applied_files']}")
        print(f"- frozen hash apply check: {out['frozen_hash_apply_status']}")
        gates = out.get("gates") or {}
        print("- gates: " + " ".join(f"{g}={'PASS' if ok else 'FAIL'}" for g, ok in gates.items()))
        print(f"- factory-validate: {'PASS' if out.get('validate_ok') else 'FAIL'}")
        print(f"- promoted_to_green_base: {out['promoted_to_green_base']} "
              f"/ new_verdict: {out['new_verdict']}")
    if out.get("rollback_executed"):
        print("- rollback: 수행됨 (rollback_report.json)")
    return 0 if out.get("ok") else 1


def _cmd_factory_anti_hardcode_patch(args) -> int:
    from repo_idea_miner.factory_anti_hardcode import run_anti_hardcode_patch

    if _missing_run_target(args) or _conflicting_dry_run_apply(args):
        return 1
    db_conn = _open_db_if_exists(args.db)
    if _run_id_needs_db(args, db_conn):
        return 1
    try:
        scheduler = None
        if args.apply and args.mode == "live" and db_conn is not None:
            scheduler = _live_scheduler(db_conn)
        out = run_anti_hardcode_patch(
            run_dir=args.run_dir, run_id=args.run_id, apply=args.apply,
            mode=args.mode, db_conn=db_conn, scheduler=scheduler,
        )
    finally:
        if db_conn is not None:
            db_conn.close()
    print("ANTI-HARDCODE PATCH" + (" (apply)" if args.apply else " (dry-run)"))
    print(f"- resolved_run_dir: {out.get('resolved_run_dir')}")
    print(f"- base_run_id: {out.get('base_run_id')} / challenge_id: {out.get('challenge_id')}")
    print(f"- status: {out.get('status')}")
    print(f"- summary_source: {out.get('summary_source')}")
    for p in out.get("problems") or []:
        print(f"  BLOCKED: {p}")
    if out.get("error"):
        print(f"오류: {out['error']}", file=sys.stderr)
    if out.get("plan"):
        print(f"- hardcoded literals: {out['plan']['hardcoded_literals']}")
        print(f"- planned files: {out['plan']['planned_files']}")
    if out.get("applied"):
        print(f"- applied files: {out['applied_files']}")
        print(f"- frozen hash check: {out['frozen_hash_status']}")
        gates = out.get("gates") or {}
        print("- gates: " + " ".join(f"{g}={'PASS' if ok else 'FAIL'}" for g, ok in gates.items()))
        print(f"- factory-validate: {'PASS' if out.get('validate_ok') else 'FAIL'}")
        print(f"- promoted_to_green_base: {out['promoted_to_green_base']} "
              f"/ new_verdict: {out['new_verdict']}")
    return 0 if out.get("ok") else 1


def _cmd_factory_review(args) -> int:
    from repo_idea_miner.factory_review import run_review_package

    if _missing_run_target(args):
        return 1
    db_conn = _open_db_if_exists(args.db)
    if _run_id_needs_db(args, db_conn):
        return 1
    try:
        out = run_review_package(run_dir=args.run_dir, run_id=args.run_id, db_conn=db_conn)
    finally:
        if db_conn is not None:
            db_conn.close()
    print("PHASE 2C-0 REVIEW")
    print(f"- resolved_run_dir: {out.get('resolved_run_dir')}")
    print(f"- challenge_id: {out.get('challenge_id')}")
    if out.get("error"):
        print(f"오류: {out['error']}", file=sys.stderr)
        return 1
    smoke = out.get("smoke") or {}
    print(f"- runner executable: {smoke.get('runner_executable')} "
          f"(exit={smoke.get('runner_exit_code')})")
    print(f"- product viewer reads replay: {smoke.get('product_viewer_reads_replay')} "
          f"({len(smoke.get('product_viewer_reads_replay_evidence') or [])} evidence)")
    print(f"- runner/viewer consistent: {smoke.get('runner_viewer_consistent')} "
          f"{smoke.get('runner_viewer_consistency_fields')}")
    print(f"- no-code-change: {out.get('no_code_change_status')}")
    print(f"- recommended_fitness: {out.get('recommended_fitness')}")
    for r in out.get("critical_red_flags") or []:
        print(f"  red flag: {r}")
    print(f"- review dir: {out.get('review_dir')}")
    return 0 if out.get("ok") else 1


def _cmd_factory_product_polish(args) -> int:
    from repo_idea_miner.factory_product_polish import run_product_polish

    if _missing_run_target(args) or _conflicting_dry_run_apply(args):
        return 1
    db_conn = _open_db_if_exists(args.db)
    if _run_id_needs_db(args, db_conn):
        return 1
    try:
        out = run_product_polish(run_dir=args.run_dir, run_id=args.run_id,
                                 target=args.target, apply=args.apply, db_conn=db_conn)
    finally:
        if db_conn is not None:
            db_conn.close()
    print("PRODUCT VIEWER POLISH" + (" (apply)" if args.apply else " (dry-run)"))
    print(f"- resolved_run_dir: {out.get('resolved_run_dir')}")
    print(f"- challenge_id: {out.get('challenge_id')} / status: {out.get('status')}")
    for p in out.get("problems") or []:
        print(f"  BLOCKED: {p}")
    if out.get("error"):
        print(f"오류: {out['error']}", file=sys.stderr)
    if out.get("plan"):
        print(f"- detected mismatches: {len(out['plan']['detected_mismatches'])}")
        print(f"- planned files: {out['plan']['planned_files']}")
    if out.get("applied"):
        print(f"- patched files: {out['patched_files']}")
        print(f"- protected hash: {out['hash_status']}")
        ex = out.get("extra") or {}
        print(f"- edge/event/layout fixed: {ex.get('edge_mapping_fixed')}/"
              f"{ex.get('event_mapping_fixed')}/{ex.get('node_layout_generated')}")
        print(f"- recommended_fitness: {out.get('recommended_fitness')}")
    print(f"- review dir: {out.get('review_dir')}")
    return 0 if out.get("ok") else 1


def _cmd_factory_product_editor(args) -> int:
    from repo_idea_miner.factory_product_editor import run_product_editor

    if _missing_run_target(args) or _conflicting_dry_run_apply(args):
        return 1
    db_conn = _open_db_if_exists(args.db)
    if _run_id_needs_db(args, db_conn):
        return 1
    try:
        out = run_product_editor(run_dir=args.run_dir, run_id=args.run_id,
                                 apply=args.apply, db_conn=db_conn)
    finally:
        if db_conn is not None:
            db_conn.close()
    print("PRODUCT VIEWER EDITOR" + (" (apply)" if args.apply else " (dry-run)"))
    print(f"- resolved_run_dir: {out.get('resolved_run_dir')}")
    print(f"- challenge_id: {out.get('challenge_id')} / status: {out.get('status')}")
    print(f"- supported_node_types: {out.get('supported_node_types')}")
    for p in out.get("problems") or []:
        print(f"  BLOCKED: {p}")
    if out.get("error"):
        print(f"오류: {out['error']}", file=sys.stderr)
    if out.get("plan"):
        print(f"- planned editor features: {len(out['plan']['planned_editor_features'])}")
        print(f"- planned files: {out['plan']['planned_files']}")
    if out.get("applied"):
        es = out.get("editor_smoke") or {}
        print(f"- patched files: {out['patched_files']}")
        print(f"- protected hash: {out['hash_status']}")
        print(f"- model_level_smoke_pass: {es.get('model_level_smoke_pass')} / "
              f"ui_binding_evidence_pass: {es.get('ui_binding_evidence_pass')} / "
              f"JS syntax: {es.get('js_syntax_status')}")
        print(f"- recommended_fitness: {out.get('recommended_fitness')} "
              f"(draft editor candidate: {(out.get('fitness') or {}).get('draft_editor_candidate')})")
    print(f"- review dir: {out.get('review_dir')}")
    return 0 if out.get("ok") else 1


def _cmd_factory_draft_execution(args) -> int:
    from repo_idea_miner.factory_draft_execution import run_draft_execution

    if _missing_run_target(args) or _conflicting_dry_run_apply(args):
        return 1
    db_conn = _open_db_if_exists(args.db)
    if _run_id_needs_db(args, db_conn):
        return 1
    try:
        out = run_draft_execution(run_dir=args.run_dir, run_id=args.run_id,
                                  apply=args.apply, db_conn=db_conn)
    finally:
        if db_conn is not None:
            db_conn.close()
    print("RUNNER-BACKED DRAFT EXECUTION" + (" (apply)" if args.apply else " (dry-run)"))
    print(f"- resolved_run_dir: {out.get('resolved_run_dir')}")
    print(f"- challenge_id: {out.get('challenge_id')} / status: {out.get('status')}")
    for p in out.get("problems") or []:
        print(f"  BLOCKED: {p}")
    if out.get("error"):
        print(f"오류: {out['error']}", file=sys.stderr)
    if out.get("applied"):
        es = out.get("execution_smoke") or {}
        print(f"- patched files: {out['patched_files']}")
        print(f"- protected hash: {out['hash_status']}")
        print(f"- execution smoke: adapter={es.get('adapter_ok')} "
              f"runner={es.get('runner_execution_ok')} bridge={es.get('bridge_server_ok')} "
              f"revise={es.get('revise_cycle_changes_result')}")
        print(f"- product_loop_closed: {es.get('product_loop_closed')}")
        print(f"- recommended_fitness: {out.get('recommended_fitness')} "
              f"(runner_backed_execution_included: "
              f"{(out.get('fitness') or {}).get('runner_backed_execution_included')})")
    print(f"- review dir: {out.get('review_dir')}")
    return 0 if out.get("ok") else 1


def _cmd_factory_product_loop(args) -> int:
    from repo_idea_miner.factory_product_loop import run_product_loop

    if _missing_run_target(args):
        return 1
    db_conn = _open_db_if_exists(args.db)
    if _run_id_needs_db(args, db_conn):
        return 1
    try:
        scheduler = None
        if args.mode == "live" and db_conn is not None:
            scheduler = _live_scheduler(db_conn)
        if args.execute:
            from repo_idea_miner.factory_loop_executor import run_closed_product_loop
            out = run_closed_product_loop(
                run_dir=args.run_dir, run_id=args.run_id, mode=args.mode,
                gemma_mode=args.gemma_mode, execute=True,
                max_iterations=args.max_iterations or 4,
                output_dir=args.output_dir,
                db_conn=db_conn, scheduler=scheduler,
            )
        else:
            out = run_product_loop(
                run_dir=args.run_dir, run_id=args.run_id, mode=args.mode,
                gemma_mode=args.gemma_mode, max_iterations=args.max_iterations or 1,
                db_conn=db_conn, scheduler=scheduler,
            )
    finally:
        if db_conn is not None:
            db_conn.close()
    if args.execute:
        print(f"CLOSED PRODUCT LOOP ({args.mode} / Phase 2D-1)")
        print(f"- resolved_run_dir: {out.get('resolved_run_dir')}")
        print(f"- loop_dir: {out.get('loop_dir')} / status: {out.get('status')}")
        if out.get("error"):
            print(f"오류: {out['error']}", file=sys.stderr)
            return 1
        print(f"- final_stage: {out.get('final_stage')}")
        print(f"- active candidate: {out.get('active_candidate_run_dir')}")
        print(f"- base hash: {out.get('base_hash_status')}")
        for it in out.get("iterations") or []:
            print(f"  iter{it.get('iteration')}: stage={it.get('stage_before')} "
                  f"gap={it.get('primary_gap_before')} lane={it.get('selected_lane')} "
                  f"→ {it.get('lane_status') or it.get('progress') or '-'}")
        for c in out.get("stop_conditions") or []:
            print(f"  stop: {c}")
        if out.get("hold_packet"):
            print(f"- HOLD_FOR_HUMAN: {out['hold_packet']['single_question_for_human']}")
        return 0 if out.get("ok") else 1
    print(f"PRODUCT LOOP ({args.mode} / {args.gemma_mode})")
    print(f"- resolved_run_dir: {out.get('resolved_run_dir')}")
    print(f"- challenge_id: {out.get('challenge_id')} / status: {out.get('status')}")
    if out.get("error"):
        print(f"오류: {out['error']}", file=sys.stderr)
        return 1
    print(f"- prior_fitness_label: {out.get('prior_fitness_label')}")
    print(f"- autopilot_stage: {out.get('autopilot_stage')}")
    print(f"- primary_gap: {out.get('primary_gap')}")
    print(f"- next_lane: {out.get('next_lane')}")
    print(f"- auto_order_quality: {out.get('auto_order_quality_status')} "
          f"({out.get('auto_order_quality_score')})")
    print(f"- live_repair_apply: {out.get('live_repair_apply')} / "
          f"repair_execute: {out.get('repair_execute')}")
    print(f"- protected hash: {out.get('hash_status')}")
    ml = out.get("mock_loop") or {}
    print("- mock loop: " + (" ".join(f"{k}={v}" for k, v in ml.items()) or "-"))
    for c in out.get("stop_conditions") or []:
        print(f"  stop: {c}")
    for pr in out.get("problems") or []:
        print(f"  problem: {pr}")
    if out.get("failure_type"):
        print(f"- failure_type: {out['failure_type']}")
    print(f"- review dir: {out.get('review_dir')}")
    return 0 if out.get("ok") else 1


def _cmd_factory_continue_queue(args) -> int:
    from repo_idea_miner.factory_queue import run_continuation_queue

    db_conn = _open_db_if_exists(args.db)
    try:
        scheduler = None
        if args.execute and args.mode == "live" and db_conn is not None:
            scheduler = _live_scheduler(db_conn)
        kwargs = {"scheduler": scheduler} if scheduler is not None else {}
        out = run_continuation_queue(
            db_path=None, db_conn=db_conn, output_dir=args.output_dir,
            lane=args.lane, execute=args.execute, proposal_only=args.proposal_only,
            limit=args.limit, mode=args.mode, **kwargs,
        )
    finally:
        if db_conn is not None:
            db_conn.close()
    if not out.get("ok"):
        print(f"오류: {out.get('error')}", file=sys.stderr)
        return 1
    print(f"CONTINUATION QUEUE ({out['operation']})")
    counts = out.get("lane_counts") or {}
    print("lanes: " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "-")
    for e in out.get("entries") or []:
        pr = e["priority"] if e["priority"] is not None else "-"
        print(f"  [{pr}] run {e['run_id'] or '-'} ch{e['challenge_id'] or '-'} "
              f"{e['current_verdict'] or '-'} → {e['recommended_lane']} "
              f"(can_patch={e['can_patch']}, risk={e['risk_level']})")
        print(f"      reason: {e['reason']}"
              + (f" / blocking: {e['blocking_reason']}" if e["blocking_reason"] else ""))
    print(f"queue: {out['queue_json']}")
    if out.get("status"):
        print(f"status: {out['status']}")
    for x in out.get("executed") or []:
        print(f"  patch run {x['run_id']}: {x['patch_result']} verdict={x['verdict']} "
              f"frozen_hash={x['frozen_hash_status']} → {x['continuation_run_dir']}")
    for x in out.get("proposals") or []:
        print(f"  spec-repair run {x['run_id']}: review={x['review_result']} "
              f"apply_performed={x['apply_performed']} frozen_hash={x['frozen_hash_status']}")
        print(f"      proposal: {x['proposal_path']}")
    return 0


def _cmd_factory_status(args) -> int:
    from repo_idea_miner.factory_db import factory_status

    s = factory_status(args.db)
    print(f"product_runs: {s['total_runs']}")
    for st, n in sorted(s["status_counts"].items()):
        print(f"  status {st}: {n}")
    for v, n in sorted(s["verdict_counts"].items()):
        print(f"  verdict {v}: {n}")
    for r in s["recent_runs"]:
        print(
            f"recent: run {r['id']} [{r['verdict'] or r['current_stage']}] "
            f"{r['challenge_title'] or '(sample)'} owner={r['owner_decision'] or '-'}"
        )
    return 0


def _cmd_factory_validate(args) -> int:
    from repo_idea_miner.factory_run_layout import RUN_KIND_CONTINUATION, detect_run_kind
    from repo_idea_miner.factory_validate import (
        validate_continuation_run_dir,
        validate_product_run_dir,
    )

    settings = load_settings()
    secrets = settings.secret_values()
    run_type = detect_run_kind(args.product_run_dir)
    # Phase 1.7 continuation run은 별도 run type으로 검증하고 상세를 표시한다 (§4.2)
    if run_type == RUN_KIND_CONTINUATION:
        ok, problems, info = validate_continuation_run_dir(args.product_run_dir, secrets)
        print("FACTORY VALIDATION")
        print(f"- run type: {info['run_type']}")
        print(f"- base run_id: {info['base_run_id']}")
        print(f"- challenge_id: {info['challenge_id']}")
        print(f"- verdict: {info['verdict']}")
        print(f"- promoted_to_green_base: {info['promoted_to_green_base']}")
        print(f"- failure types: {', '.join(info['failure_types'])}")
        print(f"- patch attempts: {info['patch_attempts']}")
        print(f"- gate rerun: {info['gate_rerun']}")
        print(f"- lane: {info.get('lane') or '-'}"
              + (f" (inferred: {info['inferred_lane']})" if info.get("inferred_lane") else ""))
        if info.get("patch_result"):
            print(f"- patch result: {info['patch_result']}")
        print(f"- validation: {'PASS' if ok else 'FAIL'}")
        for p in problems:
            print(f"FAIL: {p}")
        return 0 if ok else 1

    ok, problems = validate_product_run_dir(args.product_run_dir, secrets)
    if ok:
        print(f"FACTORY VALIDATION PASS (run type: {run_type})")
        return 0
    for p in problems:
        print(f"FAIL: {p}")
    return 1


# ---------------------------------------------------------------- Architecture Atlas


def _cmd_architecture_build(args) -> int:
    from repo_idea_miner.architecture_atlas import write_atlas

    atlas = write_atlas(Path.cwd())
    h = atlas["health"]
    rep = atlas["repository"]
    print("ARCHITECTURE BUILD")
    print(f"- head: {rep['head']}")
    print(f"- structural_fingerprint: {rep['structural_fingerprint']}")
    print(f"- modules: {h['module_count']} / components: {len(atlas['components'])} "
          f"/ symbols: {len(atlas['symbols'])} / routes: {len(atlas['routes'])}")
    print("- 생성: architecture/atlas.json, atlas.schema.json")
    return 0


def _cmd_architecture_context(args) -> int:
    from repo_idea_miner.architecture_context import build_context, render_compact

    selectors = {
        "canon": args.canon, "component": args.component, "route": args.route,
        "module": args.module, "symbol": args.symbol, "cli": args.cli,
        "artifact": args.artifact, "changed": args.changed,
    }
    if not any(v for v in selectors.values()):
        print("오류: selector 최소 1개 필요 "
              "(--canon/--component/--route/--module/--symbol/--cli/--artifact/--changed)",
              file=sys.stderr)
        return 1
    live_fp = None
    if args.changed and args.impact:  # 현재 트리 재스캔 지문 — context 모듈은 builder를 import하지 않음
        from repo_idea_miner.architecture_atlas import build_atlas

        live_fp = build_atlas(Path.cwd())["repository"]["structural_fingerprint"]
    try:
        ctx = build_context(
            Path.cwd(), selectors, impact=args.impact, depth=args.depth,
            max_primary=args.max_primary_files, max_secondary=args.max_secondary_files,
            live_fingerprint=live_fp)
    except FileNotFoundError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    if "error" in ctx:  # AMBIGUOUS_*_SELECTOR (§9.3) — deterministic error JSON
        print(json.dumps(ctx, ensure_ascii=False, sort_keys=True, indent=1))
        return 1
    if args.compact:
        print(render_compact(ctx))
    else:
        print(json.dumps(ctx, ensure_ascii=False, sort_keys=True, indent=1))
    return 0


def _cmd_architecture_check(args) -> int:
    from repo_idea_miner.architecture_atlas import run_architecture_check

    settings = load_settings()
    warnings: list[str] = []
    problems = run_architecture_check(Path.cwd(), settings.secret_values(), warnings=warnings)
    for w in warnings:
        print(f"WARN: {w}")
    if not problems:
        print("ARCHITECTURE CHECK PASS")
        return 0
    for p in problems:
        print(f"FAIL: {p}")
    return 1


# command → handler 대응. cli.py의 parser command 집합과 1:1이어야 한다 (회귀 테스트가 고정).
HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "run": _cmd_run,
    "search": _cmd_search,
    "view": _cmd_view,
    "serve": _cmd_serve,
    "validate": _cmd_validate,
    "challenge": _cmd_challenge,
    "challenge-search": _cmd_challenge_search,
    "daemon": _cmd_daemon,
    "dashboard": _cmd_dashboard,
    "status": _cmd_status,
    "pause": _cmd_pause,
    "resume": _cmd_resume,
    "validate-db": _cmd_validate_db,
    "factory": _cmd_factory,
    "factory-build": _cmd_factory_build,
    "factory-continue": _cmd_factory_continue,
    "factory-spec-repair-apply": _cmd_factory_spec_repair_apply,
    "factory-anti-hardcode-patch": _cmd_factory_anti_hardcode_patch,
    "factory-review": _cmd_factory_review,
    "factory-product-polish": _cmd_factory_product_polish,
    "factory-product-editor": _cmd_factory_product_editor,
    "factory-draft-execution": _cmd_factory_draft_execution,
    "factory-product-loop": _cmd_factory_product_loop,
    "factory-continue-queue": _cmd_factory_continue_queue,
    "factory-status": _cmd_factory_status,
    "factory-validate": _cmd_factory_validate,
    "architecture-build": _cmd_architecture_build,
    "architecture-check": _cmd_architecture_check,
    "architecture-context": _cmd_architecture_context,
}


def dispatch(args: argparse.Namespace) -> int:
    """parse된 args를 해당 command handler로 보낸다."""
    return HANDLERS[args.command](args)
