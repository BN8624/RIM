# REENTRY

HEAD_SOURCE:
- command: git rev-parse HEAD
- origin_command: git rev-parse origin/main
- status_command: git status --porcelain=v1
- rule: Git output is authoritative; this file does not store a self-referential HEAD hash.

STATE_SNAPSHOT:
- reflects architecture and behavior as of this document's parent state
- branch: main

SYSTEM_STATUS:
- tests: full suite PASS ×2 연속 (flaky 0) at issue #7 마감;
  architecture-build 연속 2회 byte-identical; smoke = dashboard(/, /products,
  #47 run5·#54, viewer_polish panel HTTP 렌더) + browser 실동작(SRS/table
  canonical viewer initial→next→prev/reset→COMPLETE, 검증 실패·REPLAY_MISSING
  명시 표시, mock success 0) PASS
- architecture_check: PASS + WARN 채널 (literal-only artifacts 집계, route 미선언 CLI,
  AI_INDEX component query primary 초과 — 모두 §17.2 비차단)
- known_flaky: []

RECENT_SEMANTIC_CHANGES:
- A1 done: no Atlas HTML/renderer, no architecture-serve/summary CLI
- A2 done: root markdown = 4 (checklist.md deleted, git history only), docs rewritten AI-only
- A3 done: atlas.json schema V2 — repository block(head/snapshot/fingerprint/diff),
  core symbol index (AST line ranges + signatures), canonical routes, artifacts with
  role+provenance (PRODUCES/CONSUMES/LITERAL_REFERENCE; MANIFEST/AST_IO_CALL/AST_STRING_LITERAL),
  10 contracts, 11 invariants, document_routes from AI_INDEX; manifest.toml schema 2;
  [[pipeline]] removed (routes supersede)
- A4 done: architecture-context CLI — selectors --canon/--component/--route/--module/--symbol/
  --cli/--artifact/--changed (multiple), --impact=direct_static_impact (static 1-hop only),
  --compact line format, deterministic JSON; read_first symbol line ranges; LITERAL_REFERENCE
  excluded by default; do_not_modify from manifest [rules.do_not_modify]; route 17
  (architecture_context) added; README CONTEXT COMMAND = python -m form

- A5 done: check hard 항목 확장(README bootstrap 구조/REENTRY 필수 섹션/serve·summary CLI 부재/
  사람용 Atlas 토큰/AI_INDEX ATLAS_QUERY 해석 검증/contract owner/이중 빌드 결정론) + §17.2
  warning 7종·§18 문서 크기(비차단 채널); 대표 AI task fixture 8종(tests/fixtures/ai_tasks)
  recall 100% 테스트; atlas↔context import cycle 해소(공유 상수·load_manifest를 scanner로,
  context는 builder 미import — live fingerprint는 handler가 주입)

- A6 done: full pytest PASS, build×2 byte-identical, dashboard smoke, tracked md=root 4,
  HTML/serve/summary 부재 — AI-Only Atlas & Documentation Reset 마감

- A7 done: --changed 변경 탐지 정본을 `git status --porcelain=v1 -z`로 교체 (A7 주문서 §5.2/§7)
  — untracked 포함, NUL 구분(공백·한글 path 안전), rename old_path 소비;
  scanner: collect_workspace_changes/_classify_xy(CONFLICTED>RENAMED>COPIED>DELETED>ADDED>
  TYPE_CHANGED>MODIFIED)/workspace_markdown_problems(untracked 루트·소스 md = AI 문맥 오염);
  context: classify_changes 순수 함수(known/pending_build/deleted/rename/test/governance),
  UNKNOWN_PENDING_BUILD warning+component, impact.changed 스키마 개편(changed_files 원본,
  deleted_modules[previous_component/importers/possible_broken_routes·contracts],
  tests_to_run/changed_tests/related_canon_ids, atlas_rebuild_required=pending∨deleted∨fp,
  document_update_required=governance∨fp); _changed_py_stems 삭제

- A7 후반 done (Independent AI Utility Validation): full module/symbol ID 정본 +
  AMBIGUOUS_*_SELECTOR 결정론 오류, 실제 test path(atlas test_paths), blind 검증 5종 —
  round1 01/05 PASS → generic repair(RC1 read_if_needed tier 랭킹: primary 직접 import >
  역 import > hub, primary 랭킹 순서; RC2 factory_closed_loop/factory_validate route steps 보강;
  RC3 INV-PROTECTED-HASH applies_to·tests 확장; scanner from-pkg 모듈 import 승격) →
  round2 새 agent 재검증: 03/04 PASS 추가, 최종 4/5 PASS.
  남은 한계(§15.2): BLIND-02 agent가 ctx tests_to_run에 있는
  tests/test_factory_phase2d1_cli_dashboard.py 를 2회 모두 선별 누락 — ctx 결함 아님(agent
  test-selection), task hardcode 수정 금지 원칙에 따라 미수정. blind fixture 5종 승격
  (tests/fixtures/ai_tasks/blind_*, 총 13종) — ctx 수준 recall은 5종 전부 회귀 고정 green.

- Atlas Usage Contract done (usage-contract 주문서): README REQUIRED READ ORDER/BEFORE EDIT/
  AFTER EDIT 재편 + CANON-12에 ATLAS_AUTHORITY~DO_NOT 7 stable key(권한·한계·workflow·
  유지 계약) + check 19+30 usage_contract_problems(계약 토큰/key/과장 표현/CLI·옵션 정합)
  + 계약 회귀 테스트 5종. AI 작업 시작 절차 정본은 README와 CANON-12.

- Issue #4 Phase A done: #47 공식 성공 재현 — fresh live loop(072220/review/phase2d1/
  loop_20260711_023843) iteration 1 PRODUCT_CANDIDATE, gates 7/7, base 불변(독립 snapshot 동일)
- Issue #4 Phase B done (FACTORY_DEFECT → generic repair, commit 1b588f0): FD-1 continue
  --run-dir live scheduler 구성, FD-2 copy_run_as_child base 포인터 child 재작성, FD-3 invariant
  평가기 entity 이름 키 singleton 해석(NOT_EXPOSED 오탐 12건 → patch 노이즈 → §8.1 spec repair
  차단 데드락 해소), FD-4 spec repair expected_events payload 값 보호 + _event_kind 'type' 키
  (runner 결함값 target_id 'system'의 golden 복사 봉쇄, 증거 runs/factory_20260710_183137/
  spec_repair_apply_plan.json) + 회귀 테스트 4건. 수리 후 재검증: child 174740 live closed
  loop(loop_20260711_034840)에서 invariant gate PASS, 정직한 HOLD_FOR_HUMAN, base 021635
  불변(보호 37파일 hash PASS). #54 상태 = VALID_HOLD. 절차 기록:
  runs/_factory_reality_validation/state.json

- Issue #5 done (#47 승인·#54 partial spec repair·INTERACTION_UI 도메인 중립화,
  커밋 e2c4e03/7dbccf7/5a50d4d/4d458f0): #47 = APPROVED/PRODUCT_CANDIDATE/READY
  (product_reviews id 1, 공식 성공 기준 사례 종결). #54 = PARTIAL_PRODUCT — scenario 단위
  partial spec repair(결정 4상태 계약, CANON-05) + 의미 확정 core patch(target_id)로
  7/7 gates·green REVIEW_READY 도달, interaction UI 적용 후 INTERACTION_CANDIDATE.
  INTERACTION_UI = generic executor(factory_interaction_ui, CANON-06 계약): 3개 도메인
  (SRS 27/테이블 17/파일시스템 54) 동일 executor로 lane APPLIED+runner-backed smoke+
  validate PASS, graph 도메인은 legacy 2C-2 adapter 격리, challenge hardcode 0,
  #47 회귀 없음, invalid success 0. runtime HTTP 실증(action→state 변경, invalid 명시 거부)

- Issue #4 Phase C done (fresh 3종 blind, commit e0cf88c): Fresh-A 27 SRS(run 190458) =
  PARTIAL_PRODUCT(gates 7/7, acceptance 11/14, 남은 gap 조작 UI/loop closure 정직 표면화),
  Fresh-B 17 테이블 스튜디오(run 193103) = PARTIAL_PRODUCT(patch 0회 green_base, critical
  coverage 미충족 정직 표면화), Fresh-C 77 커맨드 팔레트(run 194814) = VALID_HOLD(golden↔runner
  의미 괴리, spec repair 사람 결정 필요). INVALID_SUCCESS 0. Round1 공통 blocker(A+C: ladder
  CORE_PATCH rung 오진/stale 반복 → 예산 소진)만 §5.5 요건 충족 → generic repair 1회(rung은
  gate_fail만 + lane 결과 SPEC_REPAIR 분류의 iteration 간 escalation, CANON-07 갱신) → Round2
  실측으로 효과 확인(A: 유령 CORE_PATCH 소멸, C: hold packet이 SPEC_REPAIR_REQUIRED 정확 표시).
  모든 loop base hash PASS, Round1 artifact 보존

- Issue #6 done (RUNNER_BACKED_DRAFT_EXECUTION 도메인 중립화, 커밋 113902e/55ab9ec):
  executor = factory_runner_backed_execution.run_runner_backed_execution — 도메인 중립
  (execution contract는 build_interaction_contract 재사용, side effect = temp copy+protected
  hash, 상태 enum pre 7종+실행 8종, EXECUTED≠제품 성공). 검증 도메인 3종 동일 executor:
  SRS 27(child 030900)·table 17(child 030900_1)·filesystem 54(child 030809) 전부
  EXECUTED+validate PASS, graph는 legacy 2C-3 adapter 격리. #54 최종 상태 =
  PRODUCT_CANDIDATE (strict, acceptance 14/14, mock loop iter1 lane APPLIED — 실질 승격 1건).
  fresh 2종(27·17)은 has_execution_report false→true·RUNNER_BACKED rung 제거,
  남은 gap은 실행과 무관한 진짜 viewer 결함(VIEWER_POLISH_REQUIRED)으로 정직 HOLD.
  base 3종+parent 3종 hash 불변, invalid/mock success 0

- Issue #8 done (UX_POLISH 도메인 중립화, 커밋 17aae15/68e7bdf):
  executor = factory_ux_polish.run_ux_polish — canonical UX contract(기존
  interaction/viewer/runner contract 재사용) → 결정론적 진단 15종(정적
  DOM/CSS/JS, LLM 감상 금지) → 제한된 operation catalog 12종(data-ux-op
  marker block만, 자유 형식 patch 금지, 예산 op 5·surface 3) → 재진단
  validation+rollback → machine-checkable evidence(viewport 1280x800/375x812,
  keyboard focusability, runtime은 기존 runner-backed evidence 참조).
  도메인/graph 분기 없음. probe07 detector 수리: canonical viewer의
  contract-매개 replay 읽기를 sha256 일치로 인정(raw substring 규칙의 영구
  오탐 데드락 해소). derive_primary_gap UX rung: UX 실증(report included)
  없으면 gap 유지, 있으면 None. 검증: SRS 27 UX child 062013 = ops 2종
  APPLIED → INTERACTION_CANDIDATE→EXECUTION_CANDIDATE 승격(acceptance
  10/14→12/14), Table 17 UX child 062015 = 동일 APPLIED, UX gap 소멸
  (gap=None, EXECUTION_CANDIDATE 정직 HOLD). 잔여 acceptance 실패는 양쪽
  모두 요구사항 coverage 2종(PRODUCT_REQUIREMENT — UX로 덮지 않음).
  #47/#54 회귀 없음(validate PASS, UX 진단 dry-run UX_READY 수리 대상 0),
  base 6종 hash 불변, invalid/mock success 0

- Issue #7 done (VIEWER_POLISH 도메인 중립화, 커밋 3f218cb/687e53a):
  executor = factory_viewer_polish.run_viewer_polish — replay discovery(명시적
  replay/index.json ref 우선, compatibility는 단일 후보만, MISSING/AMBIGUOUS/
  INVALID/UNSUPPORTED 명시) → schema-shape adapter(standard_typed_event =
  SRS/table/filesystem 공통, graph_legacy_event) → canonical viewer contract
  (frames, before/after는 파생 가능한 것만 — 날조 없음) → generic viewer core
  (contract만 읽음) → navigation 실증 evidence. graph는 legacy 2C-1 adapter 격리.
  detector 수리: viewer가 실제 읽는 키만 replay에 요구(message 오탐 제거).
  검증 도메인: SRS 27 = loop iter1 lane APPLIED(child 042220) →
  REVIEWABLE_ARTIFACT→INTERACTION_CANDIDATE 승격, 남은 gap UX_POLISH(stub HOLD).
  Table 17 = detector 수리로 VIEWER 오탐 gap 소멸(gap=None,
  EXECUTION_CANDIDATE 정직 HOLD) + execute_lane child 042339 APPLIED(canonical
  변환 실증). #47/#54 회귀 없음(validate PASS, base 4종 hash 불변, graph legacy
  라우팅 실측). invalid/mock success 0

OPEN_BLOCKERS:
- id: hold_54
  state: RESOLVED — closed (이슈 #6에서 실행 통합 완료)
  evidence: "partial spec repair 체인(이슈 #5) 후 RUNNER_BACKED_DRAFT_EXECUTION lane
    APPLIED(child 030809): INTERACTION_CANDIDATE → strict PRODUCT_CANDIDATE
    (acceptance 14/14), base 021635/004810 불변. #54 최종 상태 = PRODUCT_CANDIDATE"
  next_action: 없음 — 실행 통합 완료로 종결
- id: hold_47
  state: RESOLVED — removed (이슈 #5 Decision A)
  evidence: "final human approval: APPROVED / factory verdict: PRODUCT_CANDIDATE /
    release readiness: READY — product_reviews id 1 (run 5, action=productize,
    reviewer_source=github_issue_5). 근거 run: runs/factory_20260709_072220/review/phase2d1/
    loop_20260711_023843 (iteration 1, gates 7/7, acceptance PASS, base hash 101 files PASS)"
  next_action: 없음 — #47은 공식 성공 기준 사례(official success reference)로 종결,
    추가 수리·polish 불필요

NEXT_ACTIONS:
1. 다음 후보(단일, 사람 결정): fresh 2종 UX child(062013 SRS·062015 table)의
   EXECUTION_CANDIDATE HOLD packet 응답 — 남은 blocker는 UX가 아니라 acceptance
   요구사항 coverage 2종(critical_requirement_coverage_full/
   difficulty_anchor_coverage_full). 현재 상태로 검수·종결하거나, requirement
   coverage 보강(core 기능 추가 — 자동 lane 없음)을 별도 주문으로 지시
2. deferred: 대형 파일 분해 후보(factory_validate/challenge_dashboard/factory_product_loop §21),
   literal-only artifact 실증 승격, --run-dir mode run의 db verdict stale(artifact가 정본)
   은 필요 시 별도 주문

DO_NOT_REPEAT:
- do not keep untracked markdown in repo root or source paths (architecture-check hard failure)
- do not put a static current-HEAD hash back into this file (HEAD_SOURCE rule)
- do not re-add human documentation, checklist, or Atlas HTML/serve/summary
- do not touch #47/#54/fresh(190458·193103·194814) base runs on disk (tmp copies only)
- lane-result escalation (SPEC_REPAIR 분류 → 다음 iteration 승급)은 구현됨(CANON-07) —
  high-risk 예산 1로 같은 loop 내 실행까지는 안 되는 것이 설계 한도이지 버그가 아님
- LITERAL_REFERENCE artifacts stay non-promoted (§13) — do not upgrade them without AST/manifest proof
- UX_POLISH lane의 UX_READY(진단만, patch 0)는 loop에서 NO_CHANGE로 집계되어 child가
  승격되지 않는 것이 설계 한도다 — report가 필요한 run은 execute_lane 직접 실행으로 남긴다
- UX patch는 data-ux-op marker block 주입만 — 기존 product 마크업/스크립트를 재작성하는
  operation을 추가하지 않는다 (자유 형식 수정 금지, CANON-06)

VERIFY:
- python -m repo_idea_miner architecture-check
- python -m repo_idea_miner architecture-build   # rerun twice → zero diff expected
- python -m pytest tests/test_architecture_atlas.py tests/test_architecture_scanner.py tests/test_architecture_context.py -q
- python -m pytest -q
