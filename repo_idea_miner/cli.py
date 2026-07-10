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

    fb_p = sub.add_parser("factory-build", help="단일 Challenge로 Product Factory 실행 (Phase 1.6 Core-first Harness)")
    fb_p.add_argument("--challenge-id", type=int, default=None, help="challenge.db의 challenge id (source of truth)")
    fb_p.add_argument("--challenge-dir", default=None, help="DB 없이 run artifact 디렉터리로 실행 (fallback)")
    fb_p.add_argument("--sample", choices=["mock"], default=None, help="고정 sample challenge로 실행")
    fb_p.add_argument("--mode", choices=["mock", "live"], default="mock")
    fb_p.add_argument("--db", default="challenge.db")
    fb_p.add_argument("--output-dir", default="runs")
    fb_p.add_argument("--no-db", action="store_true", help="DB 저장 생략")
    fb_p.add_argument("--candidates", type=int, default=None,
                      help="실험 옵션: build 후보 수 (live 기본 1, mock 최대 2, §2.4)")
    fb_p.add_argument("--live-validation", action="store_true",
                      help="Phase 1.6b live 검증 run으로 표시하고 live_validation_summary.json 생성")

    fc_p = sub.add_parser("factory-continue",
                          help="continuation_base를 delta loop로 재검증 (Phase 1.7)")
    fc_p.add_argument("--run-id", type=int, default=None, help="기존 product run id (source of truth)")
    fc_p.add_argument("--run-dir", default=None, help="기존 run 디렉터리 (DB 없이 경로로 실행)")
    fc_p.add_argument("--mode", choices=["mock", "live"], default="mock")
    fc_p.add_argument("--db", default="challenge.db")
    fc_p.add_argument("--output-dir", default="runs")
    fc_p.add_argument("--no-db", action="store_true", help="DB 저장 생략")
    fc_p.add_argument("--max-patches", type=int, default=2, help="delta patch 최대 횟수 (기본 2, §11.2)")

    fsr_p = sub.add_parser("factory-spec-repair-apply",
                           help="단일 run Spec Repair Apply (Phase 2B-1, 기본 dry-run)")
    fsr_p.add_argument("--run-dir", default=None, help="apply 대상 run 디렉터리 (권장)")
    fsr_p.add_argument("--run-id", type=int, default=None,
                       help="보조: product run id (resolved run_dir를 출력)")
    fsr_p.add_argument("--dry-run", action="store_true", help="apply 계획만 생성 (기본 동작)")
    fsr_p.add_argument("--apply", action="store_true",
                       help="review 승인(APPROVE_FOR_PHASE2B)된 변경을 단일 run에 적용")
    fsr_p.add_argument("--mode", choices=["mock", "live"], default="mock")
    fsr_p.add_argument("--db", default="challenge.db")

    fah_p = sub.add_parser("factory-anti-hardcode-patch",
                           help="단일 run Anti-Hardcode 코드 patch (Phase 2B-1b, 기본 dry-run)")
    fah_p.add_argument("--run-dir", default=None, help="patch 대상 run 디렉터리 (권장)")
    fah_p.add_argument("--run-id", type=int, default=None,
                       help="보조: product run id (resolved run_dir를 출력)")
    fah_p.add_argument("--dry-run", action="store_true", help="patch 계획만 생성 (기본 동작)")
    fah_p.add_argument("--apply", action="store_true",
                       help="summary 하드코딩을 state 파생으로 교체 (단일 run)")
    fah_p.add_argument("--mode", choices=["mock", "live"], default="mock")
    fah_p.add_argument("--db", default="challenge.db")

    frv_p = sub.add_parser("factory-review",
                           help="단일 green run no-code-change smoke review + 제품성 추천 (Phase 2C-0)")
    frv_p.add_argument("--run-dir", default=None, help="review 대상 run 디렉터리 (권장)")
    frv_p.add_argument("--run-id", type=int, default=None,
                       help="보조: product run id (resolved run_dir를 출력)")
    frv_p.add_argument("--db", default="challenge.db")

    fpp_p = sub.add_parser("factory-product-polish",
                           help="product viewer field mapping polish (Phase 2C-1, 기본 dry-run)")
    fpp_p.add_argument("--run-dir", default=None, help="polish 대상 run 디렉터리 (권장)")
    fpp_p.add_argument("--run-id", type=int, default=None, help="보조: product run id")
    fpp_p.add_argument("--target", default="viewer-field-mapping",
                       choices=["viewer-field-mapping"], help="polish 대상")
    fpp_p.add_argument("--dry-run", action="store_true", help="polish 계획만 생성 (기본 동작)")
    fpp_p.add_argument("--apply", action="store_true", help="viewer field mapping을 실제 수정")
    fpp_p.add_argument("--db", default="challenge.db")

    fpe_p = sub.add_parser("factory-product-editor",
                           help="product viewer 최소 node draft editor 추가 (Phase 2C-2, 기본 dry-run)")
    fpe_p.add_argument("--run-dir", default=None, help="editor 대상 run 디렉터리 (권장)")
    fpe_p.add_argument("--run-id", type=int, default=None, help="보조: product run id")
    fpe_p.add_argument("--dry-run", action="store_true", help="editor 계획만 생성 (기본 동작)")
    fpe_p.add_argument("--apply", action="store_true", help="viewer에 editor mode를 실제 주입")
    fpe_p.add_argument("--db", default="challenge.db")

    fde_p = sub.add_parser("factory-draft-execution",
                           help="draft editor에 runner-backed 실행 추가 (Phase 2C-3, 기본 dry-run)")
    fde_p.add_argument("--run-dir", default=None, help="대상 run 디렉터리 (권장)")
    fde_p.add_argument("--run-id", type=int, default=None, help="보조: product run id")
    fde_p.add_argument("--dry-run", action="store_true", help="실행 계획만 생성 (기본 동작)")
    fde_p.add_argument("--apply", action="store_true",
                       help="어댑터/브리지/viewer 실행 패널을 실제 기록 (사용자 승인 필요)")
    fde_p.add_argument("--db", default="challenge.db")

    fpl_p = sub.add_parser("factory-product-loop",
                           help="Productization Autopilot — 기본 judge/order/blueprint, "
                                "--execute면 child run closed loop (Phase 2D-1)")
    fpl_p.add_argument("--run-dir", default=None, help="대상 run 디렉터리 (권장)")
    fpl_p.add_argument("--run-id", type=int, default=None, help="보조: product run id")
    fpl_p.add_argument("--mode", choices=["mock", "live"], default="mock")
    fpl_p.add_argument("--gemma-mode", choices=["sequential", "unified"], default="sequential",
                       help="desk 호출 방식 (검증 기준은 동일)")
    fpl_p.add_argument("--max-iterations", type=int, default=None,
                       help="기본: judge-only 1, --execute 4 (§10)")
    fpl_p.add_argument("--execute", action="store_true",
                       help="child run 기반 closed loop 실행 (§13 — 원본 base run은 불변, "
                            "--apply-original 같은 원본 수정 옵션은 없음)")
    fpl_p.add_argument("--output-dir", default="runs",
                       help="--execute 시 child run 생성 위치 (기본 runs)")
    fpl_p.add_argument("--db", default="challenge.db")

    fq_p = sub.add_parser("factory-continue-queue",
                          help="continuation queue 분류/라우팅 (Phase 2A, 기본 dry-run)")
    fq_p.add_argument("--lane", choices=["patch", "spec-repair"], default=None,
                      help="lane 필터 (patch=PATCH_CONTINUATION, spec-repair=SPEC_REPAIR)")
    fq_p.add_argument("--dry-run", action="store_true",
                      help="분류/queue 출력만 수행 (기본 동작과 동일)")
    fq_p.add_argument("--execute", action="store_true",
                      help="patch lane 실제 실행 (--lane patch 필수, limit 최대 1)")
    fq_p.add_argument("--proposal-only", action="store_true",
                      help="spec-repair lane proposal/review 생성 (read-only, apply 없음)")
    fq_p.add_argument("--limit", type=int, default=None,
                      help="dry-run 기본 20, execute/proposal-only 기본·최대 1")
    fq_p.add_argument("--mode", choices=["mock", "live"], default="mock")
    fq_p.add_argument("--db", default="challenge.db")
    fq_p.add_argument("--output-dir", default="runs")

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
                    settings = load_settings()
                    if settings.google_keys:
                        scheduler = ChallengeKeyScheduler(db_conn, settings.google_keys, load_challenge_miner_settings())
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

        if args.command == "factory-continue":
            from repo_idea_miner.challenge_key_scheduler import ChallengeKeyScheduler
            from repo_idea_miner.config import load_challenge_miner_settings
            from repo_idea_miner.factory_continue import run_continuation
            from repo_idea_miner.factory_db import open_factory_db

            if not (args.run_id or args.run_dir):
                print("오류: --run-id 또는 --run-dir 중 하나가 필요합니다.", file=sys.stderr)
                return 1
            db_conn = None if (args.no_db or args.run_dir and not args.run_id) else open_factory_db(args.db)
            if args.run_id and db_conn is None:
                print("오류: --run-id는 DB가 필요합니다.", file=sys.stderr)
                return 1
            try:
                scheduler = None
                if args.mode == "live" and db_conn is not None:
                    settings = load_settings()
                    if settings.google_keys:
                        scheduler = ChallengeKeyScheduler(db_conn, settings.google_keys,
                                                          load_challenge_miner_settings())
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

        if args.command == "factory-spec-repair-apply":
            from pathlib import Path as _Path

            from repo_idea_miner.challenge_key_scheduler import ChallengeKeyScheduler
            from repo_idea_miner.config import load_challenge_miner_settings
            from repo_idea_miner.factory_db import open_factory_db
            from repo_idea_miner.factory_spec_repair import run_spec_repair_apply

            if not (args.run_dir or args.run_id):
                print("오류: --run-dir 또는 --run-id가 필요합니다.", file=sys.stderr)
                return 1
            if args.dry_run and args.apply:
                print("오류: --dry-run과 --apply는 동시에 쓸 수 없습니다.", file=sys.stderr)
                return 1
            db_conn = open_factory_db(args.db) if _Path(args.db).exists() else None
            if args.run_id and db_conn is None:
                print("오류: --run-id는 DB가 필요합니다.", file=sys.stderr)
                return 1
            try:
                scheduler = None
                if args.apply and args.mode == "live" and db_conn is not None:
                    settings = load_settings()
                    if settings.google_keys:
                        scheduler = ChallengeKeyScheduler(db_conn, settings.google_keys,
                                                          load_challenge_miner_settings())
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

        if args.command == "factory-anti-hardcode-patch":
            from pathlib import Path as _Path

            from repo_idea_miner.challenge_key_scheduler import ChallengeKeyScheduler
            from repo_idea_miner.config import load_challenge_miner_settings
            from repo_idea_miner.factory_anti_hardcode import run_anti_hardcode_patch
            from repo_idea_miner.factory_db import open_factory_db

            if not (args.run_dir or args.run_id):
                print("오류: --run-dir 또는 --run-id가 필요합니다.", file=sys.stderr)
                return 1
            if args.dry_run and args.apply:
                print("오류: --dry-run과 --apply는 동시에 쓸 수 없습니다.", file=sys.stderr)
                return 1
            db_conn = open_factory_db(args.db) if _Path(args.db).exists() else None
            if args.run_id and db_conn is None:
                print("오류: --run-id는 DB가 필요합니다.", file=sys.stderr)
                return 1
            try:
                scheduler = None
                if args.apply and args.mode == "live" and db_conn is not None:
                    settings = load_settings()
                    if settings.google_keys:
                        scheduler = ChallengeKeyScheduler(db_conn, settings.google_keys,
                                                          load_challenge_miner_settings())
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

        if args.command == "factory-review":
            from pathlib import Path as _Path

            from repo_idea_miner.factory_db import open_factory_db
            from repo_idea_miner.factory_review import run_review_package

            if not (args.run_dir or args.run_id):
                print("오류: --run-dir 또는 --run-id가 필요합니다.", file=sys.stderr)
                return 1
            db_conn = open_factory_db(args.db) if _Path(args.db).exists() else None
            if args.run_id and db_conn is None:
                print("오류: --run-id는 DB가 필요합니다.", file=sys.stderr)
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

        if args.command == "factory-product-polish":
            from pathlib import Path as _Path

            from repo_idea_miner.factory_db import open_factory_db
            from repo_idea_miner.factory_product_polish import run_product_polish

            if not (args.run_dir or args.run_id):
                print("오류: --run-dir 또는 --run-id가 필요합니다.", file=sys.stderr)
                return 1
            if args.dry_run and args.apply:
                print("오류: --dry-run과 --apply는 동시에 쓸 수 없습니다.", file=sys.stderr)
                return 1
            db_conn = open_factory_db(args.db) if _Path(args.db).exists() else None
            if args.run_id and db_conn is None:
                print("오류: --run-id는 DB가 필요합니다.", file=sys.stderr)
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

        if args.command == "factory-product-editor":
            from pathlib import Path as _Path

            from repo_idea_miner.factory_db import open_factory_db
            from repo_idea_miner.factory_product_editor import run_product_editor

            if not (args.run_dir or args.run_id):
                print("오류: --run-dir 또는 --run-id가 필요합니다.", file=sys.stderr)
                return 1
            if args.dry_run and args.apply:
                print("오류: --dry-run과 --apply는 동시에 쓸 수 없습니다.", file=sys.stderr)
                return 1
            db_conn = open_factory_db(args.db) if _Path(args.db).exists() else None
            if args.run_id and db_conn is None:
                print("오류: --run-id는 DB가 필요합니다.", file=sys.stderr)
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

        if args.command == "factory-draft-execution":
            from pathlib import Path as _Path

            from repo_idea_miner.factory_db import open_factory_db
            from repo_idea_miner.factory_draft_execution import run_draft_execution

            if not (args.run_dir or args.run_id):
                print("오류: --run-dir 또는 --run-id가 필요합니다.", file=sys.stderr)
                return 1
            if args.dry_run and args.apply:
                print("오류: --dry-run과 --apply는 동시에 쓸 수 없습니다.", file=sys.stderr)
                return 1
            db_conn = open_factory_db(args.db) if _Path(args.db).exists() else None
            if args.run_id and db_conn is None:
                print("오류: --run-id는 DB가 필요합니다.", file=sys.stderr)
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

        if args.command == "factory-product-loop":
            from pathlib import Path as _Path

            from repo_idea_miner.challenge_key_scheduler import ChallengeKeyScheduler
            from repo_idea_miner.config import load_challenge_miner_settings
            from repo_idea_miner.factory_db import open_factory_db
            from repo_idea_miner.factory_product_loop import run_product_loop

            if not (args.run_dir or args.run_id):
                print("오류: --run-dir 또는 --run-id가 필요합니다.", file=sys.stderr)
                return 1
            db_conn = open_factory_db(args.db) if _Path(args.db).exists() else None
            if args.run_id and db_conn is None:
                print("오류: --run-id는 DB가 필요합니다.", file=sys.stderr)
                return 1
            try:
                scheduler = None
                if args.mode == "live" and db_conn is not None:
                    settings = load_settings()
                    if settings.google_keys:
                        scheduler = ChallengeKeyScheduler(db_conn, settings.google_keys,
                                                          load_challenge_miner_settings())
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

        if args.command == "factory-continue-queue":
            from repo_idea_miner.challenge_key_scheduler import ChallengeKeyScheduler
            from repo_idea_miner.config import load_challenge_miner_settings
            from repo_idea_miner.factory_db import open_factory_db
            from repo_idea_miner.factory_queue import run_continuation_queue

            from pathlib import Path as _Path

            db_conn = open_factory_db(args.db) if _Path(args.db).exists() else None
            try:
                scheduler = None
                if args.execute and args.mode == "live" and db_conn is not None:
                    settings = load_settings()
                    if settings.google_keys:
                        scheduler = ChallengeKeyScheduler(db_conn, settings.google_keys,
                                                          load_challenge_miner_settings())
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
            from repo_idea_miner.factory_validate import (
                RUN_TYPE_CONTINUATION,
                detect_run_type,
                validate_continuation_run_dir,
                validate_product_run_dir,
            )

            settings = load_settings()
            secrets = settings.secret_values()
            run_type = detect_run_type(args.product_run_dir)
            # Phase 1.7 continuation run은 별도 run type으로 검증하고 상세를 표시한다 (§4.2)
            if run_type == RUN_TYPE_CONTINUATION:
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
    except RIMError as exc:
        print(f"오류: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0
