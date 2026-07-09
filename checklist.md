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
