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
            from repo_idea_miner.validate_run import validate_run_dir

            settings = load_settings()
            ok, problems = validate_run_dir(
                args.run_dir, settings.secret_values(), require_viewer=args.require_viewer
            )
            if ok:
                print("VALIDATION PASS")
                return 0
            for p in problems:
                print(f"FAIL: {p}")
            return 1
    except RIMError as exc:
        print(f"오류: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0
