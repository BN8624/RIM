# Repo Idea Miner 납품 체크리스트

phase별 납품 로그. 각 phase의 주문서(RIM_FANAL.md 등)는 납품 후 삭제됨 — git 이력에만 존재.
현행 아키텍처 정본은 PROJECT_CANON.md, 세션 상태는 REENTRY.md.
이 로그에 상세 미기재 phase: 1.5 대시보드(b6f2f5b)·한국어화(23b844f)·1.6b live검증(3e6bb46)·1.7 continuation(75b1621+3551e4e) — git log 참조.

v1.0 (RIM_FANAL.md §35/§37 기준) 2026-07-08 완료.

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
- [x] 구현/미구현 범위 명시 (SCOPE.md — 납품 후 삭제, git 이력에 보존)

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
- [x] Phase 2B = Spec Repair Apply → 2B-1(a48c980)·2B-1b(fb63fa2)로 완료 (limit≥3·다수 run 자동화는 여전히 미착수)

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
- [x] Phase 2 = 여러 run/challenge continuation 일반화 → Phase 2A queue routing(00ef8db)으로 완료

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

# Phase 2C-1 #47 Product Viewer Field Mapping Polish — 2026-07-10

## 구현
- [x] factory_product_polish.py — product viewer만 좁게 수정하는 field mapping polish. viewer <script> 블록을 폴리시된 스크립트로 교체(CSS/구조 보존): normalizeEdge(source_id/target_id→from/to), normalizeEvent(event/node_id→kind/label + deterministic message), computeLayout(좌표 없음→execution_order/topological deterministic layout, random/Date 금지), normalizeReplayForViewer(raw→display model 분리). 새 명령 **factory-product-polish --run-dir|--run-id --target viewer-field-mapping --dry-run(기본)|--apply**. 사전조건: 2C-0 fitness=NEEDS_PRODUCT_POLISH + verdict REVIEW_READY + green_base. 보호 대상 hash(src/golden/fixtures/contract/oracle/**replay 포함**, product/ 제외) before/after/check. apply 후 smoke_review 재실행(factory_review 재사용)+analyze_polish(edge/event/layout fixed, mismatches_remaining)+build_fitness 재평가.
- [x] factory_validate.py — detect_phase2c1_run(marker)+_check_phase2c1(core+continuation 양 route, marker 없으면 no-op): 산출물/hash PASS/product/ 범위 밖 변경 차단/golden·replay 변경 차단/edge·event·layout 기록/PRODUCT_CANDIDATE 엄격(edge·event·layout fixed+mismatch 없음+consistent+green+2C-0 핵심≥4).
- [x] cli.py — factory-product-polish(dry-run/apply, 동시 지정 거부).
- [x] challenge_dashboard.py — 목록 카드(2C-1 있으면 제품성 추천/검수 상태/viewer polish/다음 액션 4줄, 2C-1이 2C-0보다 우선)+상세 Phase 2C-1 패널(edge/event/layout 고쳐짐 상태)+report 탭 7종.

## 검수
- [x] #47(072220) polish dry-run(3 mismatch 감지)+apply — 보호 대상 44개 불변(hash PASS), product viewer 2개만 변경, edge/event/layout 모두 fixed, 남은 mismatch 없음. runner/viewer 일치 4필드. polish 후 Product layer 2→4, Demo 2→4.
- [x] **#47 polish 후 recommended_fitness=NEEDS_PRODUCT_POLISH 유지**(field mapping은 고쳐졌으나 저작 조작 없는 결과 뷰어 중심 → order §17 case B). green_base/REVIEW_READY 유지.
- [x] factory-validate 072220 PASS (2C-0 + 2C-1 marker 모두 인식). 폴리시된 viewer는 edge.from/ev.type/node.x 리터럴 0개, source_id/target_id/node_id/.event 읽음.
- [x] pytest — 기존 673 + 2C-1 신규 29 (test_factory_product_polish_2c1.py) = 702. 2C-0 E2E는 on-disk polish 무관하게 mismatch viewer로 리셋해 결정적.
- [x] 조작 가능한 product experience(node editor) → 2C-2(86a8007)로 완료. 다수 run 자동화는 여전히 미착수

# Phase 2C-2 #47 Minimal Interactive Node Draft Editor — 2026-07-10

## 구현
- [x] factory_product_editor.py — product viewer에만 최소 node draft editor mode를 **추가 주입**(기존 폴리시 <script> 보존, </body> 앞에 editor DOM+script, 마커로 감싸 재주입 안전). 새 명령 **factory-product-editor --run-dir|--run-id --dry-run(기본)|--apply**. 사전조건: 2C-1 fitness=NEEDS_PRODUCT_POLISH + verdict REVIEW_READY + green_base + user_review_decision.md의 "[x] Phase 2C-2 진행". supported_node_types 추출(contract 명시→replay node types 순, 실패 시 add node 차단·CANNOT_EDIT). 보호 hash에 **replay + review/phase2c0 + review/phase2c1 포함**(product 제외). editor JS는 edge.from/ev.type/.type/node.x/Math.random/Date.now 금지(bracket nd["type"]+delegation)로 smoke mismatch [] 유지.
- [x] EditorGraphModel(Python 미러) + run_model_level_smoke — load_replay→add/edit/delete node(incident edge 자동 삭제)→add/delete edge→validation(dup id/missing endpoint/unsupported type/cycle/self-loop/isolated)→export→schema compat→from/to-only edge 거부→roundtrip(displayModel 재생성)→원본 replay 불변, 전 단계 실증해 model_level_smoke_pass 산출.
- [x] check_static_dom + check_handler_binding — 7개 핵심 control(toggle/add-node/add-edge/validation/draft-json/copy/type-selector) 존재 + data-action/onclick/handler 정의/delegation 근거로 ui_binding_evidence_pass 분리 기록. check_js_syntax — script 블록 추출 후 node --check(+필수 함수 존재).
- [x] finalize_editor_fitness — build_fitness가 authoring 감지로 준 PRODUCT_CANDIDATE를 editor 조건(mode/types/add/edit/delete/validation/compat/roundtrip/js/dom/handler/model/ui/hash/no-critical/green/no-gate-fail) 미충족 시 NEEDS_PRODUCT_POLISH로 정직 하향. candidate라도 draft_editor_candidate + "runner-backed execution not included" 명시.
- [x] factory_validate.py — detect_phase2c2_run(marker)+_check_phase2c2(core+continuation 양 route, marker 없으면 no-op): 산출물 13종/hash PASS/product 범위 밖·golden·replay·phase2c0·2c1 변경 차단/runner_backed_execution_included=true FAIL/original_replay_unchanged=false FAIL/PRODUCT_CANDIDATE 엄격(editor mode·add node·add edge·validation·compat·roundtrip·export·model·ui·js·dom·handler·no-critical·limitation·draft_editor_candidate).
- [x] cli.py — factory-product-editor(dry-run/apply, 동시 지정 거부). challenge_dashboard.py — 목록 카드(2C-2>2C-1>2C-0 우선, 제품성/검수/editor 상태/다음 액션 4줄)+상세 Phase 2C-2 패널(editor 기능/JS/DOM/handler/model/ui/draft 호환·roundtrip)+report 탭 12종.

## 검수
- [x] #47(072220) editor dry-run(supported types 7종)+apply — 보호 대상 불변(hash PASS, replay/phase2c0/2c1 포함), product viewer 2개만 변경. model_level_smoke_pass·ui_binding_evidence_pass·JS syntax 모두 PASS, 두 viewer×2 script 블록 전부 node --check OK, smoke mismatch [], runner/viewer 일치 4필드.
- [x] **#47 editor 후 recommended_fitness=PRODUCT_CANDIDATE (draft editor candidate)** — order §29 case A. authoring(노드/엣지 편집 UI) 감지로 조작 가능한 첫 경험 확보. limitation "runner-backed execution not included" 명시, 실제 graph 실행 후보는 Phase 2C-3 이후.
- [x] factory-validate 072220 PASS (2C-0+2C-1+2C-2 marker 모두 인식). green_base/REVIEW_READY 유지, 원본 replay/golden/contract/core/runner 미변경.
- [x] pytest — 기존 704 + 2C-2 신규 60 (test_factory_product_editor_2c2.py) = 764. secret scan은 validate 경로 통과.
- [x] Phase 2C-3 = Runner-backed Draft Execution → 완료(b44931a, 아래 섹션).

# Phase 2D-0 Gemma Productization Autopilot — 2026-07-10

## 구현
- [x] factory_autopilot_schemas.py — stage 7종(CORE_GREEN→PRODUCT_CANDIDATE+ARCHIVE)/gap 10종/lane 9종 + GAP_TO_LANE + lane risk policy(§14.1) + lane template 9종(§18.1, RUNNER_BACKED_DRAFT_EXECUTION title="RIM Product Factory Phase 2C-3 Runner-backed Draft Execution") + strict pydantic 스키마 8종(ProductStageLabel/GapClassification/NextLane/AutoOrderSlots/ScopeGuard/RepairBlueprint/TestsToRun/UnifiedDecisionPacket) + enum 외 값 검출 + evidence_refs 검증(§9: not_product_reason≥1, primary_gap≥2, lane은 gap refs 참조, 카탈로그 밖 refs=날조 차단) + schema_repair_pass 1회(§11: JSON 문법/wrapping/enum 대소문자만, 의미 스냅샷 변경 감지→AUTOPILOT_INVALID_OUTPUT) + 실패 분류(INFRA/INVALID/EVIDENCE_INSUFFICIENT/HOLD).
- [x] factory_autopilot_desks.py — judge/gap/lane/order/blueprint/unified 프롬프트(challenge_id/title/기대정답 미포함, evidence refs 카탈로그에서 verbatim 선택 강제, hard blocker 결과=넘을 수 없는 상한으로 입력) + execute_desk(LLM/mock 공용, strict 검증+repair 1회+실패 분류) + mock desk(evidence ladder 파생 — ID 미참조).
- [x] factory_product_loop.py — extract_artifact_evidence(2c2 editor report→2c1→2c0→static viewer 분석 순, product loop 7필드+refs 카탈로그) + extract_user_facing_quality(§8 7필드) + apply_hard_blockers(§6 15규칙, max_stage cap+PRODUCT_CANDIDATE block) + lane template 기반 auto_order.md/json+scope_guard(§18.2 14섹션) + auto_order 품질 12검사(≥0.85, 미달 HOLD_FOR_HUMAN) + repair blueprint(apply_allowed=false 강제, protected scope 제안 차단)+expected_patch_plan/tests_to_run/rollback_or_failure_conditions + mock/safe loop proof(§22: fixture에 mismatch 결함 주입→judge→generated auto_order/scope_guard를 실제로 읽는 follow_auto_order(repair_actions, scope 밖 차단)→smoke→validate→rejudge→mock_loop_order_following_report) + run_product_loop(§21: max_iterations=1 기본, repair_execute/live_repair_apply=false, hash guard에 replay+review/2c0·2c1·2c2 포함, hardcode_guard(프롬프트 title/id 누수 검사), prompt trace, 산출물 21종+schemas/, stop conditions §24, 정직한 실패 기록).
- [x] factory_validate.py — detect_phase2d0_run(marker 3종)+_check_phase2d0(§30: 산출물/schema 재검증/evidence_refs/stage·gap·lane·policy 정합/hard blocker 정합/prior·autopilot 분리/order↔lane↔guard↔blueprint 정합/apply_allowed=false/protected scope 제안 FAIL/quality<0.85 FAIL/hardcode 감지 FAIL/mock repair_followed_order=false FAIL/PRODUCT_CANDIDATE 엄격 §27/60s=false+PC FAIL, 정직한 실패 run은 최소 기록만), core+continuation 양 경로 hook (marker 없으면 no-op).
- [x] cli.py — factory-product-loop(--run-dir/--run-id/--mode mock|live/--gemma-mode sequential|unified/--max-iterations). challenge_dashboard.py — 카드 4줄(prior fitness/autopilot stage/next lane/autopilot·order·blueprint status)+상세 Phase 2D-0 패널(evidence/quality/hard blockers/mock loop/stop)+report 탭 14종.

## 검수
- [x] **live #47(072220) Gemma 판정 PASS(AUTOPILOT_JUDGED)** — autopilot_stage=INTERACTION_CANDIDATE(confidence high), primary_gap=RUNNER_BACKED_EXECUTION_REQUIRED(evidence 3개: can_execute_input=false+hard blocker+editor report), next_lane=RUNNER_BACKED_DRAFT_EXECUTION, auto_order title=Phase 2C-3 Runner-backed Draft Execution, quality 1.0 PASS, blueprint 5단계 shape+apply_allowed=false, schema repair 미사용, hardcode guard PASS. prior_fitness(PRODUCT_CANDIDATE/draft_editor_candidate)와 분리 기록, 기존 2C-2 fitness 미수정(hash PASS).
- [x] live repair apply 없음 — 보호 대상(src/product/golden/fixtures/contract/replay/review 2c0·2c1·2c2) hash before/after PASS. 처음 2회는 Gemma 503/500(모델 과부하)로 AUTOPILOT_INFRA_FAIL 정직 기록 후 재시도 성공(프롬프트 51K→8.5K 축소: viewer_source 제외 수정).
- [x] mock/safe loop proof — fixture에 edge.from/to mismatch 주입, VIEWER_POLISH lane order 생성, order/scope_guard 실제 읽고 repair, allowed scope 안 1파일 변경, protected 불변, smoke/validate/rejudge 후 REVIEWABLE→POLISHABLE 개선. golden 수정 order는 차단, repair_actions 없으면 정직 실패.
- [x] factory-validate 072220 PASS (2C-0+2C-1+2C-2+2D-0 marker 모두 인식).
- [x] hardcode 방지 — 소스에 Mini-Comfy/==47/072220 없음(테스트), 동일 evidence 다른 ID/title fixture에서 동일 stage/gap/lane, 프롬프트에 title/challenge_id 미포함.
- [x] pytest — 기존 764 + 2D-0 신규 69(test_factory_product_loop_2d0.py, live acceptance 2 포함) = 833 전부 통과. secret scan은 validate 경로 통과.
- [x] Phase 2C-3 = Runner-backed Draft Execution — 사람 승인 후 완료(b44931a, 아래 섹션).

# Phase 2B-1 #47 Spec Repair Apply — 2026-07-09 (a48c980)

- [x] factory_spec_repair.py + **factory-spec-repair-apply --dry-run(기본)|--apply**(단일 run 한정, APPROVE_FOR_PHASE2B 필수). §8 보호: 기존 golden 기대값 훼손/field 삭제/contract 밖 field 추가/comparison_mode 완화 전부 차단. pre_apply_snapshot/rollback + frozen hash(범위 밖 변경=자동 rollback) + apply 후 7 gate 재실행.
- [x] #47 실제 apply — golden schema/state_invariant 수리 성공(6/7), anti_hardcode가 runner summary "Completed" 하드코딩을 잡아 green 승격 정직 거부(의도된 결과). pytest 613.

# Phase 2B-1b #47 Anti-Hardcode Patch — 2026-07-09 (fb63fa2)

- [x] factory_anti_hardcode.py + **factory-anti-hardcode-patch --dry-run(기본)|--apply**. classify_summary_source(hardcoded vs state_derived 구분, 오탐만 제거), runner summary를 summarize_execution(state 파생 helper)으로 교체, frozen hash에서 fixtures/_variants/ 제외(잠복 버그 수정).
- [x] #47 실제 patch — summary state_derived → **7/7 gate PASS → green_base 승격, verdict REVIEW_READY**. pytest 641.

# Phase 2C-3 #47 Runner-backed Draft Execution — 2026-07-10 (b44931a)

- [x] factory_draft_execution.py + **factory-draft-execution --dry-run(기본)|--apply**. draft→시나리오 어댑터(src/adapters/draft_to_runner_input.py, 순수 변환·from/to 등 거부), 브리지 서버(product/draft_server.py, POST /api/execute-draft→runner subprocess), viewer 실행 패널(PHASE2C3 마커, 금지 리터럴 0).
- [x] run_execution_smoke — temp copy에서 편집→검증→변환→실행(추가 노드 COMPLETED 반영)→revise(입력 10→20, 출력 변화)→브리지 실기동+HTTP 실행→replay 불변.
- [x] #47 apply — 6파일 기록, 보호 hash PASS, **product_loop_closed=true, PRODUCT_CANDIDATE(runner_backed_execution_included=true)**, validate marker 5종 PASS. 실서버 8799 검증. pytest 871.

# Phase 2D-1 Evidence-Driven Closed Productization Loop — 2026-07-10 (796096f~bfea041, 9커밋)

## 구현
- [x] P0 선행수정(796096f) — anti-hardcode 스캔 시점 통일(build도 product 생성 후 재실행), detect_mock_fallback(DEMO_ONLY/NOT_EXECUTED/RUNNER_UNAVAILABLE 상태 강제), harness_schema_version=2 golden representation strict lint.
- [x] factory_product_capabilities.py(1fbd04b) — 도메인 중립 capability profile(ID/title 분기 금지) + fresh probe(runner/성공 2/실패 1/revise 재실행 변화/mock·fallback/필드 정합/flow handler).
- [x] factory_lane_executors.py + factory_loop_executor.py + factory_product_acceptance.py(87b0f20) — lane 9종 registry(기존 2A/2B-1/2C-1/2C-2/2C-3 경로 재사용), child run 격리 closed loop(base run 불변), acceptance 14검사, progress vector/의미 있는 개선 판정, 예산(iter 4/lane 2/high-risk 1/무진전 2/infra 2), HOLD_FOR_HUMAN packet(단일 질문).
- [x] CLI --execute/--output-dir + 대시보드 closed loop 카드/패널 + validate _check_phase2d1(5633226~efda1bb). judge desk 경량화 include_order=False(311ff8b). gate 항상 temp copy 재실행(c0be4f5).
- [x] **evidence ladder enforcement**(ddb9431) — live 오분류 실측 후: hard fact rung 5종은 deterministic ladder가 live gap 판정 override(gap_override 기록), hard rung lane은 live desk 생략. fresh gate rerun의 evidence_sufficient 충족(bfea041).

## 검수 (완료 기준 Case A/B live)
- [x] Case A #47 — acceptance 14/14·probe 전항목·mock fallback 0인데 judge가 INTERACTION_CANDIDATE 정직 판정, 추천 lane(RUNNER_BACKED_DRAFT_EXECUTION)은 사람 승인 필수 → **HOLD_FOR_HUMAN**(loop_20260710_134033), base hash 101파일 불변, capability를 특례 ID 없이 graph로 추출.
- [x] Case B #54 — gap_override(INTERACTION_UI→CORE_PATCH_REQUIRED), CORE_PATCH lane이 child(052415)에서 continuation 실행 → 정직 FAILED(requires_spec_repair) → 예산 소진 → **HOLD_FOR_HUMAN**(loop_20260710_141947), base hash PASS, capability를 file_operation으로 추출(graph 분기 없음).
- [x] 두 도메인이 같은 orchestrator 통과 → 다수 run batch 자동화 선행 조건 충족.
- [x] pytest 962 × 3회 — 1회 전부 통과, 2회는 기존 flaky 2종만(patch_attempts=2, 격리에서도 간헐 재현=2D-1 무관, 원인 조사 별도).

# Structural Reset & Architecture Atlas — 2026-07-10 (BASE 3363bb6 → R0~R8)

## 구현
- [x] 정본 Run Resolver (run layout/판독 정본 1개)
- [x] Validation Registry (validation router 정본 1개)
- [x] Product Judgment/Closed Loop 통합 (각 정본 1개)
- [x] CLI/Dashboard 분리 (cli.py는 parser/dispatch만, dashboard는 렌더링만)
- [x] dead code 정리 (dead 심볼 6건 삭제 + 중복 상수 정본 수렴)
- [x] Architecture Atlas (architecture/ 산출물 + architecture-build/check/summary/serve, a1da6c1)

## 검수
- [x] pytest 3회 연속 — 1000 passed × 3, flaky 0 (R0에서 patch_attempts flaky 근본 수정).
- [x] #47 — characterization PASS: base hash PASS, HOLD_FOR_HUMAN 정직 유지, 제품화 artifact 판독 보존.
- [x] #54 — characterization PASS: base hash PASS, requires_spec_repair/mock fallback/HOLD 이유 은폐 없음.
- [x] legacy run — run 유형별(legacy factory/core/continuation/2C/2D-1) 회귀 판독 정상.
- [x] architecture-check 20항목 PASS (import cycle 0, allowlist 외 private import 0, orphan 0, unknown component 0).
- [x] deterministic rebuild — 연속 2회 빌드 byte-identical, fingerprint 46890aca885fdb79.
- [x] root Markdown 정확히 5개, AI_INDEX ↔ PROJECT_CANON CANON-ID 1:1, README broken link 0.

# 현재 오픈 이슈 (2026-07-10 기준, 상세는 REENTRY.md)

- [ ] #47 — hold의 blocking gap(RUNNER_BACKED_EXECUTION_REQUIRED)은 2D-1 evidence 추출이 2C-3 산출물을 안 읽던 **stale evidence였음이 확인·수정됨**(2026-07-10). 수정 후 evidence 재파생은 stage=PRODUCT_CANDIDATE·gap 없음. 남은 것: 사람 최종 검수/출시 결정(원하면 loop 재실행으로 새 판정 기록 생성).
- [ ] #54 hold packet 응답 — spec repair(golden root_node/target_id, §8이 막는 부류) + viewer mock fallback 제거 후 loop 재실행.
- [ ] lane 실패 정보의 다음 iteration 전달(escalation) 미설계 — 도입하려면 CANON-07 갱신부터.
- [ ] UX_POLISH lane stub / 다수 run batch 자동화.
- [x] ~~queue의 run 5 stale 분류~~ — R4 stale verdict 수정으로 해소 확인(2026-07-10, run 5 = REVIEW_ONLY 정상 분류).
