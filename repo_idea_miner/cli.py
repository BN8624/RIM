# run / search / validate 서브커맨드를 제공하는 CLI 진입점 모듈.
from __future__ import annotations

import argparse
import sys

from repo_idea_miner.config import load_settings
from repo_idea_miner.errors import RIMError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="repo_idea_miner", description="Repo Idea Miner: GitHub 레포 KEEP/MAYBE/DROP 판정 도구")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="단일 레포 분석")
    run_p.add_argument("--repo", required=True, help="GitHub repository URL")
    run_p.add_argument("--mode", choices=["mock", "live"], default="mock")
    run_p.add_argument("--input-mode", choices=["direct", "search"], default="direct")
    run_p.add_argument("--output-dir", default="runs")
    run_p.add_argument("--max-issues", type=int, default=10)
    run_p.add_argument("--max-prs", type=int, default=10)
    run_p.add_argument("--tree-depth", type=int, default=2)
    run_p.add_argument("--no-llm", action="store_true", help="mock alias")

    search_p = sub.add_parser("search", help="검색어 기반 후보 분석")
    search_p.add_argument("--query", required=True)
    search_p.add_argument("--limit", type=int, default=30)
    search_p.add_argument("--top", type=int, default=10)
    search_p.add_argument("--mode", choices=["mock", "live"], default="mock")
    search_p.add_argument("--output-dir", default="runs")
    search_p.add_argument("--targeted", action="store_true", help="관심사와 가까운 레포 우선")
    search_p.add_argument("--explore", action="store_true", help="넓은 탐색 모드")
    search_p.add_argument("--max-issues", type=int, default=10)
    search_p.add_argument("--max-prs", type=int, default=10)
    search_p.add_argument("--tree-depth", type=int, default=2)

    view_p = sub.add_parser("view", help="run 디렉터리에서 모바일 viewer.html 생성")
    view_p.add_argument("run_dir")

    serve_p = sub.add_parser("serve", help="run 디렉터리를 읽기 전용으로 serve")
    serve_p.add_argument("run_dir")
    serve_p.add_argument("--host", default="127.0.0.1", help="기본 127.0.0.1; Tailscale은 0.0.0.0 또는 100.x.x.x")
    serve_p.add_argument("--port", type=int, default=8787)

    val_p = sub.add_parser("validate", help="run 디렉터리 산출물 검증")
    val_p.add_argument("run_dir")
    val_p.add_argument("--require-viewer", action="store_true", help="viewer.html 존재·필수 요소 검사")
    val_p.add_argument("--db", default=None, help="지정 시 challenge.db 검증도 함께 수행")

    # ---------------------------------------------------------- Challenge Mode
    ch_p = sub.add_parser("challenge", help="단일 레포를 구현 도전 과제(Challenge)로 변환")
    ch_p.add_argument("--repo", required=True, help="GitHub repository URL")
    ch_p.add_argument("--mode", choices=["mock", "live"], default="mock")
    ch_p.add_argument("--output-dir", default="runs")
    ch_p.add_argument("--max-issues", type=int, default=10)
    ch_p.add_argument("--max-prs", type=int, default=10)
    ch_p.add_argument("--tree-depth", type=int, default=2)
    ch_p.add_argument("--db", default="challenge.db", help="결과를 저장할 SQLite DB (--no-db로 생략)")
    ch_p.add_argument("--no-db", action="store_true", help="DB 저장 생략")

    chs_p = sub.add_parser("challenge-search", help="GitHub 검색 결과를 Challenge 후보로 변환")
    chs_p.add_argument("--query", required=True)
    chs_p.add_argument("--limit", type=int, default=50, help="GitHub Search에서 가져올 최대 repo 수")
    chs_p.add_argument("--top", type=int, default=20, help="필터/정렬 후 Challenge 생성 대상 최대 repo 수")
    chs_p.add_argument("--mode", choices=["mock", "live"], default="mock")
    chs_p.add_argument("--output-dir", default="runs")
    chs_p.add_argument("--max-issues", type=int, default=10)
    chs_p.add_argument("--max-prs", type=int, default=10)
    chs_p.add_argument("--tree-depth", type=int, default=2)
    chs_p.add_argument("--db", default="challenge.db", help="결과를 저장할 SQLite DB (--no-db로 생략)")
    chs_p.add_argument("--no-db", action="store_true", help="DB 저장 생략")

    d_p = sub.add_parser("daemon", help="로컬 Challenge Miner 실행 (seed 수집 + 병렬 Challenge 생성)")
    d_p.add_argument("--db", default="challenge.db")
    d_p.add_argument("--output-dir", default="runs")
    d_p.add_argument("--mode", choices=["mock", "live"], default="live")
    d_p.add_argument("--seeds", default=None, help="seed query 설정 파일 (기본: 내장 seed)")
    d_p.add_argument("--once", action="store_true", help="한 사이클만 실행하고 종료 (검증용)")

    db_p = sub.add_parser("dashboard", help="Challenge Dashboard 실행 (challenge.db 확인함)")
    db_p.add_argument("--db", default="challenge.db")
    db_p.add_argument("--host", default="127.0.0.1", help="기본 127.0.0.1; 0.0.0.0은 Tailscale 등 사설망에서만")
    db_p.add_argument("--port", type=int, default=8787)

    st_p = sub.add_parser("status", help="Challenge Miner 상태 표시")
    st_p.add_argument("--db", default="challenge.db")

    pa_p = sub.add_parser("pause", help="Challenge Miner 새 작업 배정 중단")
    pa_p.add_argument("--db", default="challenge.db")

    re_p = sub.add_parser("resume", help="Challenge Miner 새 작업 배정 재개")
    re_p.add_argument("--db", default="challenge.db")

    vdb_p = sub.add_parser("validate-db", help="challenge.db integrity/테이블/artifact_dir 정합성 검증")
    vdb_p.add_argument("--db", default="challenge.db")

    # ---------------------------------------------------------- Product Factory
    f_p = sub.add_parser("factory", help="승격 대상 Challenge를 자동으로 Product Factory에 흘려보냄")
    f_p.add_argument("--mode", choices=["mock", "live"], default="mock")
    f_p.add_argument("--db", default="challenge.db")
    f_p.add_argument("--output-dir", default="runs")
    f_p.add_argument("--once", action="store_true", help="1건만 처리하고 종료")
    f_p.add_argument("--max-runs", type=int, default=None, help="최대 처리 건수 (기본 1, 안전 모드)")
    f_p.add_argument("--continuous", action="store_true", help="명시한 경우에만 계속 실행")

    fb_p = sub.add_parser("factory-build", help="단일 Challenge로 Product Factory 실행")
    fb_p.add_argument("--challenge-id", type=int, default=None, help="challenge.db의 challenge id (source of truth)")
    fb_p.add_argument("--challenge-dir", default=None, help="DB 없이 run artifact 디렉터리로 실행 (fallback)")
    fb_p.add_argument("--sample", choices=["mock"], default=None, help="고정 sample challenge로 실행")
    fb_p.add_argument("--mode", choices=["mock", "live"], default="mock")
    fb_p.add_argument("--db", default="challenge.db")
    fb_p.add_argument("--output-dir", default="runs")
    fb_p.add_argument("--no-db", action="store_true", help="DB 저장 생략")

    fs_p = sub.add_parser("factory-status", help="Product Factory 상태 표시")
    fs_p.add_argument("--db", default="challenge.db")

    fv_p = sub.add_parser("factory-validate", help="product run 디렉터리의 Final Artifact 검증")
    fv_p.add_argument("product_run_dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "run":
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

        if args.command == "search":
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

        if args.command == "view":
            from repo_idea_miner.viewer import generate_viewer

            out = generate_viewer(args.run_dir)
            print(f"viewer: {out}")
            return 0

        if args.command == "serve":
            from repo_idea_miner.serve import serve

            serve(args.run_dir, host=args.host, port=args.port)
            return 0

        if args.command == "validate":
            from pathlib import Path

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

        if args.command == "challenge":
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

        if args.command == "challenge-search":
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

        if args.command == "daemon":
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

        if args.command == "dashboard":
            from repo_idea_miner.challenge_dashboard import serve_dashboard

            settings = load_settings()
            serve_dashboard(args.db, host=args.host, port=args.port, secrets=settings.secret_values())
            return 0

        if args.command == "status":
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

        if args.command == "pause":
            from repo_idea_miner.challenge_daemon import set_paused

            set_paused(args.db, True)
            print("miner_paused=true (진행 중 작업은 안전하게 종료됩니다)")
            return 0

        if args.command == "resume":
            from repo_idea_miner.challenge_daemon import set_paused

            set_paused(args.db, False)
            print("miner_paused=false")
            return 0

        if args.command == "validate-db":
            from repo_idea_miner.challenge_validate import validate_db

            ok, problems = validate_db(args.db)
            if ok:
                print("DB VALIDATION PASS")
                return 0
            for p in problems:
                print(f"FAIL: {p}")
            return 1

        if args.command == "factory":
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

        if args.command == "factory-build":
            from repo_idea_miner.challenge_key_scheduler import ChallengeKeyScheduler
            from repo_idea_miner.config import load_challenge_miner_settings
            from repo_idea_miner.factory_db import open_factory_db
            from repo_idea_miner.factory_pipeline import (
                load_challenge_from_db,
                load_challenge_from_dir,
                run_product_factory,
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
                    settings = load_settings()
                    if settings.google_keys:
                        scheduler = ChallengeKeyScheduler(db_conn, settings.google_keys, load_challenge_miner_settings())
                result = run_product_factory(
                    challenge, mode=args.mode, output_dir=args.output_dir,
                    db_conn=db_conn, scheduler=scheduler,
                )
            finally:
                if db_conn is not None:
                    db_conn.close()
            print(f"run_dir: {result.get('run_dir')}")
            if result.get("error"):
                print(f"실패: {result['error']}")
                return 1
            print(f"line: {result.get('line')} / verdict: {result.get('verdict')} "
                  f"(추천: {result.get('recommended_action')})")
            gates = result.get("gate_summary") or {}
            print("gates: " + " ".join(f"{g}={'PASS' if ok else 'FAIL'}" for g, ok in gates.items()))
            if result.get("codex_export_dir"):
                print(f"codex_export: {result['codex_export_dir']}")
            if result.get("product_run_id"):
                print(f"product_run_id: {result['product_run_id']} (db: {args.db})")
            return 0

        if args.command == "factory-status":
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

        if args.command == "factory-validate":
            from repo_idea_miner.factory_validate import validate_product_run_dir

            settings = load_settings()
            ok, problems = validate_product_run_dir(args.product_run_dir, settings.secret_values())
            if ok:
                print("FACTORY VALIDATION PASS")
                return 0
            for p in problems:
                print(f"FAIL: {p}")
            return 1
    except RIMError as exc:
        print(f"오류: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0
