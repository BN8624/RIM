# run / search / validate 서브커맨드를 제공하는 CLI 진입점 모듈.
from __future__ import annotations

import argparse
import sys

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
    """parser → command handler dispatch → exit code (business logic은 cli_handlers)."""
    from repo_idea_miner.cli_handlers import dispatch

    args = build_parser().parse_args(argv)
    try:
        return dispatch(args)
    except RIMError as exc:
        print(f"오류: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
