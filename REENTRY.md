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
- tests: full suite PASS (1057) at issue #4 Phase C repair (e0cf88c);
  architecture-build 연속 2회 byte-identical; dashboard smoke(/, /products,
  /product/5·13·19·21·22 전부 200 + 정직 상태 표시) PASS at issue #4 마감
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

- Issue #4 Phase C done (fresh 3종 blind, commit e0cf88c): Fresh-A 27 SRS(run 190458) =
  PARTIAL_PRODUCT(gates 7/7, acceptance 11/14, 남은 gap 조작 UI/loop closure 정직 표면화),
  Fresh-B 17 테이블 스튜디오(run 193103) = PARTIAL_PRODUCT(patch 0회 green_base, critical
  coverage 미충족 정직 표면화), Fresh-C 77 커맨드 팔레트(run 194814) = VALID_HOLD(golden↔runner
  의미 괴리, spec repair 사람 결정 필요). INVALID_SUCCESS 0. Round1 공통 blocker(A+C: ladder
  CORE_PATCH rung 오진/stale 반복 → 예산 소진)만 §5.5 요건 충족 → generic repair 1회(rung은
  gate_fail만 + lane 결과 SPEC_REPAIR 분류의 iteration 간 escalation, CANON-07 갱신) → Round2
  실측으로 효과 확인(A: 유령 CORE_PATCH 소멸, C: hold packet이 SPEC_REPAIR_REQUIRED 정확 표시).
  모든 loop base hash PASS, Round1 artifact 보존

OPEN_BLOCKERS:
- id: hold_54
  state: waiting_human (VALID_HOLD — viewer mock 제거·golden 의미 판정·FD-1~4 수리 완료 후 남은 blocker)
  evidence: runs/factory_20260710_174740/review/phase2d1/loop_20260711_034840/hold_for_human_packet.json
  next_action: "scenario_003의 golden 결함(root_node)과 core 결함(target_id)이 얽혀 자동 수리
    순서가 없음 — spec repair apply의 시나리오 단위 부분 적용을 허용할지, 또는 spec repair
    pending 중 core patch lane을 허용할지 사람이 결정"
- id: hold_47
  state: waiting_human
  evidence: PRODUCT_CANDIDATE 공식 성공 재현 — runs/factory_20260709_072220/review/phase2d1/
    loop_20260711_023843 (live, iteration 1, gap 없음, gates 7/7, base 불변)
  next_action: human final review/release decision

NEXT_ACTIONS:
1. 다음 추천 작업(단일, 이슈 #4 §7 실측 근거): INTERACTION_UI(2C-2) executor 도메인 중립화 —
   #47식 산출물 체인(2C-1 polish/user_review_decision)+graph 도메인(supported_node_types) 전제
   제거. fresh 2/3(A·B)의 동일 lane 반복 blocker
2. hold_54 / hold_47 인간 결정 대기 (아래 blocker 참조)
3. deferred: 대형 파일 분해 후보(factory_validate/challenge_dashboard/factory_product_loop §21),
   literal-only artifact 185개의 실증 승격은 필요 시 별도 주문

DO_NOT_REPEAT:
- do not keep untracked markdown in repo root or source paths (architecture-check hard failure)
- do not put a static current-HEAD hash back into this file (HEAD_SOURCE rule)
- do not re-add human documentation, checklist, or Atlas HTML/serve/summary
- do not touch #47/#54/fresh(190458·193103·194814) base runs on disk (tmp copies only)
- lane-result escalation (SPEC_REPAIR 분류 → 다음 iteration 승급)은 구현됨(CANON-07) —
  high-risk 예산 1로 같은 loop 내 실행까지는 안 되는 것이 설계 한도이지 버그가 아님
- LITERAL_REFERENCE artifacts stay non-promoted (§13) — do not upgrade them without AST/manifest proof

VERIFY:
- python -m repo_idea_miner architecture-check
- python -m repo_idea_miner architecture-build   # rerun twice → zero diff expected
- python -m pytest tests/test_architecture_atlas.py tests/test_architecture_scanner.py tests/test_architecture_context.py -q
- python -m pytest -q
