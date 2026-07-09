# Repo Idea Miner 납품 체크리스트

RIM_FANAL.md §35/§37 기준. 2026-07-08 완료.

## 검수 (§35)
- [x] 35.1 단일 레포 mock 검수 — `runs/20260708_062637` (validate PASS)
- [x] 35.2 단일 레포 live 검수 — `runs/20260708_062704` (gemma-4-31b-it, key 회전 1→6, failover 1회 처리, validate PASS)
- [x] 35.3 검색어 mock 검수 — `runs/20260708_063201` (5후보, validate PASS)
- [x] 35.4 검색어 live 검수 — `runs/20260708_063306` (3후보, 11개 key 전부 회전, validate PASS)
- [x] 35.5 pytest — 113 passed

## 납품물 (§37)
- [x] 전체 소스코드 (`repo_idea_miner/`)
- [x] README.md (설치/실행 예시/환경변수)
- [x] .env.example (.env는 미포함, .gitignore 처리)
- [x] 테스트 코드 (`tests/`, §34 전체)
- [x] 샘플 산출물 (`samples/` — idea_card, run_report, top_ideas, search_report, evidence_packet, worker JSON, llm_calls.jsonl)
- [x] google_genai_gemma provider / key pool / rotation / retry / failover
- [x] secret redaction + 테스트
- [x] 구현/미구현 범위 명시 (SCOPE.md)

## 남은 작업
- (없음)

# Challenge Mode 추가 (ChallengeMode주문서.md) — 2026-07-09 완료

## 구현 (§3~§26)
- [x] challenge_schemas.py — OwnerBrief/ScreenStory/ChallengeCard/ChallengePackage/ChallengeIndex + §9 자동 판정 규칙
- [x] challenge_prompts.py — 통합 challenge_package prompt(§10~§11) + mock 고정 샘플(§24)
- [x] challenge_renderer.py — owner_brief/screen_story/challenge_card/implementation_prompt.md + viewer.html
- [x] challenge_db.py — challenge.db 7개 테이블(§16) + validate_db
- [x] challenge_pipeline.py / challenge_search_pipeline.py — LLM 1회 호출, §23 정렬, 실패 격리
- [x] challenge_key_scheduler.py — 11-key controlled parallel pool, 429/500 per-key cooldown(§18~§19)
- [x] challenge_daemon.py — seed refill/queue/병렬 처리/pause·resume/status(§17)
- [x] challenge_dashboard.py — Today/목록 필터/상세 탭/SAVE·MAYBE·DROP·BUILD NEXT·MARK BUILT(§22)
- [x] challenge_validate.py + cli.py 8개 명령 추가 (기존 run/search/view/serve/validate 무변경)

## 검수 (§29~§30)
- [x] challenge mock — `runs/20260708_153455` (validate PASS)
- [x] challenge live — `runs/20260708_153519` (GOOD_CHALLENGE, validate PASS)
- [x] challenge-search mock — `runs/20260708_153725` (3건, validate PASS)
- [x] challenge-search live — `runs/20260708_153754` (2건, validate --db PASS)
- [x] daemon --once mock — 11 key 병렬 11건 처리, 에러 0
- [x] dashboard — 목록/필터/상세 탭/판정 POST/COPY 확인
- [x] validate-db PASS / pytest 238 passed (기존 113개 포함)

# Product Factory 추가 (RIMProductFactory.md) — 2026-07-09

## 구현
- [x] factory_schemas.py — Desk 출력/manifest/contract Pydantic + Auto Promotion Gate(§6) + Codex 승격 조건(§16)
- [x] factory_db.py — product_runs/product_tasks/product_events/product_artifacts(§18) + factory_status/validate + worker_key_label(KEY_NN)
- [x] factory_workspace.py — 안전 파일 쓰기(경로 탈출 차단)/green base snapshot·rollback/events.jsonl/debug_history.jsonl(§9)
- [x] factory_sandbox.py — Docker install(제한 network)/execute(--network none) 2단계, workspace-only mount, CPU/memory/timeout(§13), 로컬 fallback은 최소 env
- [x] factory_gates.py — Static/Contract(V1: 파일·entrypoint·import graph reachability·주요 모듈·anchor 마커)/Syntax(py_compile·node --check·json·html)/Smoke(§7.5~7.8, §14)
- [x] factory_prompts.py — Desk별 prompt + mock 고정 멀티파일 workspace(Command Center Mini, §20)
- [x] factory_desks.py — DeskExecutor(공유 key scheduler 연동, §12) + md 렌더러
- [x] factory_pipeline.py — Desk 체인/debug 루프(최대 횟수)/자동 verdict/Final Artifact/codex_export(§4, §16) + select_patch_candidate(§11.2)
- [x] factory_runner.py — factory 명령(--once/--max-runs 기본 안전 모드, --continuous 명시 필요, §19.1)
- [x] factory_validate.py — Final Artifact 구조(단일파일 실패)/manifest·contract 정합성/secret scan
- [x] cli.py — factory/factory-build/factory-status/factory-validate (기존 13개 명령 무변경)
- [x] challenge_dashboard.py — /products, /product/<id>, KEEP/DROP/PRODUCTIZE/RETRY/ARCHIVE + verdict 추천 버튼(§15, §17)

## 검수
- [x] factory-build --sample mock --mode mock — runs/factory_20260709_000420 (4 gate PASS, PROMOTE_TO_CODEX, docker smoke, factory-validate PASS)
- [x] factory --mode mock --once — 실제 challenge 47 처리, PROMOTE_TO_CODEX
- [x] factory --mode live --max-runs 1 — runs/factory_20260709_000449 (challenge 14, KEY_01~04 회전, 4 gate PASS, QA가 실제 결함 검출 → NEEDS_MORE_GEMMA_LOOP, factory-validate PASS)
- [x] pytest 342 passed (기존 254개 포함, factory 신규 88개)

# Phase 1.6 Core-first Review-Repair Harness (RIMProductFactoryPhase1.6.md) — 2026-07-09

## 구현
- [x] factory_core_schemas.py — artifact class(§5.6)/core·runner contract/scenario·golden/review 스키마 + repair 제한 상수 + candidates 정책(§2.4) + PROMOTE 금지 조건(§6.7·§11.9) + decide_core_verdict(§11)
- [x] factory_core_prompts.py — Stage별 prompt(정규화/분류/계약/시나리오·골든/빌드/리뷰/patch/product layer) + core-first build task packet 필수 문구(§7.5) + mock 고정 core workspace(결정적 python rule engine + runner + fixtures 3종 + golden exact/partial/invariant + replay viewer)
- [x] factory_core_gates.py — Core Contract/Runner/Scenario Replay/Golden Output/State Invariant/Determinism(역순 재실행=fixture 순서 변경 겸용)/Anti-Hardcode L1+간단 L2(변형 fixture 실행) (§8)
- [x] factory_core_pipeline.py — 7 Stage 오케스트레이터(§4): Draft→Review→Repair(계약 1회·시나리오 1회·patch 2회·product layer 1회 제한), NEEDS_SPEC_REPAIR 중단(§5.10·§6.9), patch의 fixtures/golden/contract 수정 거부(§9.5), product layer 필수+core output 기반 검사(§10), verdict/dashboard_summary/green_base/harness_summary(§11)
- [x] factory_db.py — product_runs에 artifact_class/harness_summary_path/core_system_summary_path/green_base_path 컬럼 추가(마이그레이션, §14)
- [x] cli.py — factory-build가 Phase 1.6 harness 실행 + --candidates 실험 옵션(live 1 강제, mock 최대 2, §13). factory(자동 배치)는 기존 파이프라인 유지
- [x] factory_validate.py — harness_summary.json 감지 시 §15 완주 산출물 기준으로 검증
- [x] challenge_dashboard.py — 목록 카드 §11.10 한국어 검수 형식(산출물 유형/코어/검증 n/7/결정성/위험/추천, 기술 로그 미노출) + 상세 코어 시스템 검증 패널 + core 요약 리포트 탭/소스 미리보기 확장
- [x] factory_schemas.py·factory_labels.py — REVIEW_READY/RUNS_BUT_WEAK 라벨·추천 매핑·한국어 표기 + artifact class 한국어

## 검수
- [x] factory-build --sample mock --mode mock — REVIEW_READY, 7 gate 전부 PASS, green_base 저장, factory-validate PASS (§15 완주)
- [x] §15 산출물 전부 생성 확인 (normalized/classification/contract 4종/fixtures 3/golden 3/oracle risk/runner/replay/각 gate summary/product layer/dashboard_summary/green_base)
- [x] pytest 466 passed (기존 378개 포함, Phase 1.6 신규 88개) / secret scan 통과(fake key 주입 테스트 포함)

# Phase 2A Continuation Queue Routing + Safe Patch Lane — 2026-07-09

## 구현
- [x] factory_frozen.py — Frozen Hash Guard(§4.6~4.7): golden/fixtures/contract/oracle sha256 before/after/check
- [x] factory_queue.py — Queue Manager: DB 우선 discovery(list_product_runs 재사용, 새 schema 없음) + runs/ fs fallback + run_id dedupe, lane 분류(PATCH_CONTINUATION/SPEC_REPAIR/EXCLUDED/REVIEW_ONLY, §3), 우선순위(§4.2), continuation_queue.json/md(§5.2), patch lane execute(limit 1), spec repair proposal/review read-only(§7, LLM 호출 없음)
- [x] factory_continue.py — lane/phase=2a/patch_result(PATCH_GREEN/PROGRESS/BLOCKED_SPEC/FAILED) 기록, frozen hash guard, PATCH_BLOCKED_SPEC 시 proposal 생성(apply 없음, §4.8), phase2a_dashboard_summary.json
- [x] factory_validate.py — lane 존재/verdict 정합(§10), 기존 1.7 run inferred_lane 호환(§4.10), frozen hash guard 검증(사후 spec 파일 수정 탐지 포함), proposal apply_allowed=false 강제, core run에도 phase2a 산출물 검사
- [x] cli.py — factory-continue-queue(--lane/--dry-run/--execute/--proposal-only/--limit): 기본 dry-run limit 20, execute 기본·최대 1, spec-repair execute/apply 거부, --limit 999 거부
- [x] challenge_dashboard.py + factory_labels.py — 목록 카드 추천 경로/이유/상태(§9), 상세 Phase 2A 패널(failure/risk/proposal/frozen hash), report 탭 5종 추가

## 검수
- [x] queue dry-run — run 5(#47) → SPEC_REPAIR priority 1 (reason: golden schema mismatch and invariant DSL issue)
- [x] --lane patch --execute --limit 1 — NO_PATCH_ELIGIBLE (#47 patch 대상 제외, 파일 수정 없음)
- [x] --lane spec-repair --proposal-only --limit 1 — proposal/review 생성(APPROVE_FOR_PHASE2B), apply 미수행, frozen hash PASS, 허용 8파일만 생성
- [x] factory-validate 072220(base+phase2a 산출물) PASS / 100043(legacy continuation) inferred SPEC_REPAIR PASS
- [x] spec-repair --execute, --execute --limit 2 거부 확인
- [x] pytest 578 passed (기존 533 + Phase 2A 신규 45) / secret scan 통과
- [ ] Phase 2B = Spec Repair Apply / golden 갱신 자동화 / limit≥3 (미착수)

# Phase 1.7b Continuation Run Validation Routing Fix — 2026-07-09

## 구현
- [x] factory_validate.py — detect_run_type(§3): CONTINUATION_RUN/CORE_FACTORY_RUN/LEGACY_FACTORY_RUN/UNKNOWN_RUN 감지, continuation → core → legacy 순
- [x] factory_validate.py — validate_continuation_run_dir(§5,§6): 필수 산출물(continuation_run_summary/failure_classification/repair_plan/green_base_promotion/gate_rerun_summary/phase17_dashboard_summary) + frozen/allowed touch 정합성 + verdict consistency + secret scan. (ok, problems, info) 반환
- [x] validate_product_run_dir — continuation run은 detect 후 continuation 경로로 라우팅(legacy 경로 차단)
- [x] cli.py — factory-validate가 continuation run 감지 시 run type/base run/verdict/promotion/failure/patch/gate rerun 상세 출력, 그 외는 run type 표기한 PASS/FAIL

## 검수
- [x] 실제 #47 continuation run(100043) validate — CONTINUATION_RUN, SPEC_REPAIR_REQUIRED 정직 PASS (patch_diff_summary 미생성은 있으면-검사로 처리)
- [x] mock core build validate — CORE_FACTORY_RUN PASS / legacy run validate — LEGACY_FACTORY_RUN PASS / live-validation run(072220) — CORE_FACTORY_RUN PASS (계속 유지)
- [x] pytest 533 passed (기존 508개 + Phase 1.7b 신규 25개) / secret scan 통과
- [ ] Phase 2 = 여러 run/challenge continuation 일반화 (미착수)

# Phase 2C-0 Review Package + Product Fitness Recommendation — 2026-07-09

## 구현
- [x] factory_review.py — no-code-change smoke review(원본→temp copy 실행, 보호 대상 hash before/after/check) + product fitness scoring(7항목 evidence 기반) + recommended_fitness(PRODUCT_CANDIDATE/NEEDS_PRODUCT_POLISH/NEEDS_CORE_PATCH/NEEDS_SPEC_REPAIR/ARCHIVE) + review_package/artifact_smoke_review/product_fitness_report/human_review_checklist/sixty_second_review_script/demo_manifest/phase2c0_dashboard_summary 생성 (runs/<run>/review/phase2c0/)
- [x] factory_review.py — product_viewer_reads_replay(단순 fetch 1개 불가, >=2 근거) + runner_viewer_consistent(>=2 필드, 확인불가시 unknown) + viewer 필드 스키마 불일치 감지 + product_interactive_authoring 감지
- [x] factory_validate.py — detect_phase2c0_run(marker) + _check_phase2c0(§17: 산출물/no-code-change/recommended_fitness 정합/PRODUCT_CANDIDATE 엄격/NEEDS_SPEC_REPAIR next_goal/evidence 없는 4·5점 차단), core+continuation 양 경로에 hook (marker 없으면 no-op)
- [x] cli.py — factory-review(--run-dir/--run-id/--db)
- [x] challenge_dashboard.py — 목록 카드 3줄(제품성 추천/검수 상태/사용자 다음 액션) + 상세 Phase 2C-0 패널 + report 탭 8종(review/phase2c0/*)

## 검수
- [x] #47(072220) factory-review — runner exit=0, viewer reads replay(근거 6), runner/viewer 일치(4필드), no-code-change PASS, recommended_fitness=NEEDS_PRODUCT_POLISH(viewer 필드 스키마 불일치 edge/event/좌표 + 결과 뷰어 중심)
- [x] factory-validate 072220 PASS (Phase 2C-0 marker 인식, 보호 대상 artifact 미변경)
- [x] pytest — 기존 641 + Phase 2C-0 신규 32 (test_factory_review_2c0.py) / secret scan은 validate 경로 통과
- [ ] Phase 2C 잔여 = 다수 run 검수 자동화 (미착수)
