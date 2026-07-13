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
- tests: full suite PASS ×2 연속 1336개 (flaky 0) at issue #19 마감 (replay node evidence
  shape 테스트 29종 추가 — dict/list/empty/missing/malformed/mixed/non-graph/vacuous);
  smoke = dashboard(/, /products 200) + Fresh-G parent 134413 scratchpad 복사본 runner
  실증(valid action UNVISITED→COMPLETED, 무효 3종 명시 거부+state 불변) + viewer browser
  실조작(list nodes replay 로드, 실결함 4건 정직 관측) + 회귀 8종 digest/mtime/validate
  전부 baseline 일치
- (이전 기록) full suite PASS ×2 연속 (flaky 0) at issue #18 마감 (blind batch 4 repair 테스트
  3종 추가 — RunnerContract interpreter fail-closed/프롬프트 계약 토큰/BLOCKED lane 재선택
  금지); smoke = dashboard(/, /products 200) + Fresh-G child 104032 browser 실조작
  (unlock→complete state 전이, 375px overflow 0) + 회귀 8종 digest/mtime/validate 전부
  baseline 일치
- (이전 기록) full suite PASS ×2 연속 1304개 (flaky 0) at issue #17 마감 (Factory production/
  test 코드 변경 0 — 구현은 전부 Fresh-F child 090748 제품 workspace); smoke =
  dashboard(/, /products 200) + Fresh-F child 090748 diagnostic UI browser 실조작
  (단일/복수 diagnostic 카드→하이라이트, keyboard Tab+Enter 선택, mark 클릭 역방향,
  leading/trailing whitespace trim 0, stale→재실행, 진단 0건, invalid range fail-closed,
  375px overflow 0) + viewer replay(scenario_001/002 이벤트 {type,id}·final_state.
  CodeState.content·남은 진단 range 렌더, undefined 0) + generic 콘솔 회귀(analyze
  큐 실행 state 변화, apply_fix diag_999 명시 거부)
- (이전 기록) full suite PASS ×2 연속 1304개 (flaky 0) at issue #16 마감 (empty collection
  exposure 계약 테스트 7종 포함); smoke = dashboard(/, /products 200) + Fresh-D child
  080138 scratchpad 복사본 interaction console 실조작(초기 state에 tasks:[] 노출,
  update_stage_content → AFTER_ACTIONS 상태 변화 + DEP 이벤트 4건, 오류 0) + viewer
  replay(scenario_001/002 로드, 빈 tasks 상태 렌더) + 기존 성공 7종 validate PASS·
  수리된 evaluator로 state_invariant 재평가 전부 PASS(vacuous 발화 0)·digest 불변
- (이전 기록) full suite PASS ×2 연속 1297개 (flaky 0) at issue #15 마감 (Factory production/test
  코드 변경 0 배치 — 모든 수리는 runs/ 제품 child 내부); smoke = dashboard(/, /products
  200) + D viewer 상태 전이/E 병합·S999 거부·replay/F analyze·apply_fix·diag_999 거부
  browser 실조작 + 기존 성공 9종 validate PASS·digest/mtime 불변
- (이전 기록) full suite PASS ×2 연속 1297개 (flaky 0) at issue #14 마감 (blind batch 3 회귀
  테스트 2종 포함); smoke = dashboard(/, /products, /product/36 200) + Fresh-C structured
  console 회귀(valid object 왕복 보존, wrong type 400 fail-closed) + Fresh-D/F viewer
  replay 실렌더 + Fresh-E RUNNER_UNAVAILABLE 정직 표시
- (이전 기록) full suite PASS ×2 연속 1295개 (flaky 0) at issue #13 마감 (structured console
  input 테스트 20종 포함); smoke = dashboard(/, /products, /product/36 200) + Fresh-C
  child 165952 scratchpad 복사본 콘솔 browser 실조작(§15 전 항목: valid object/array,
  invalid JSON, wrong type 3종, primitive, 375px) + synthetic structured run
  (array/nested boolean/number/boolean/null) + server 재검증 curl 우회 실증 +
  replay viewer 실렌더
- (이전 기록) full suite PASS ×2 연속 (flaky 0) at issue #12 마감 (신규 human decision 계약
  테스트 21개 포함); smoke = dashboard(/, /products, /product/36 200, HOLD 패널
  hold_reason_class 표시) + Fresh-C fresh child live loop 실증
- (이전 기록) full suite PASS ×2 연속 1254개 (flaky 0) at issue #11 마감 (코드 변경 0 배치);
  smoke = dashboard(/, /products 200) + Fresh-C interaction 콘솔 실조작
  (runner-backed action→state 변화, invalid 명시 거부) + Fresh-B replay viewer 실렌더 PASS
- (이전 기록) full suite PASS ×2 연속 1254개 (flaky 0) at issue #10 마감; smoke =
  dashboard(/, /products 200) + Table 17 child grid 콘솔 브라우저 실조작
  (desktop+375px, Boolean false→true, invalid 명시 거부, replay viewer) PASS
- (이전 기록) full suite PASS ×2 연속 1247개 (flaky 0) at issue #9 마감;
  architecture-build 연속 2회 byte-identical; smoke = dashboard(/, /products,
  #47 run5·#54, viewer_polish panel HTTP 렌더) + browser 실동작(SRS/table
  canonical viewer initial→next→prev/reset→COMPLETE, 검증 실패·REPLAY_MISSING
  명시 표시, mock success 0) PASS
- architecture_check: PASS + WARN 채널 (literal-only artifacts 집계, route 미선언 CLI,
  AI_INDEX component query primary 초과 — 모두 §17.2 비차단)
- known_flaky: []

RECENT_SEMANTIC_CHANGES:
- Issue #19 done (Replay Evidence Shape-Safe Evaluator Repair — 커밋 a37bf48 fix /
  609eae2 test / d148955 fix(editor) / docs 마감 커밋):
  root cause = 복합(NODE_COLLECTION_TYPE_UNGUARDED 주 + ADJACENT_EVALUATOR_CONTRACT_DRIFT
  + MALFORMED_AND_EMPTY_CONFLATION) — viewer_reads_replay_evidence:165 nodes.values()가
  dict 가정, G R2 replay 3종 전부 list of dicts(정본: state_contract "nodes.length>=0")
  → AttributeError → loop verify crash. 인접 drift: viewer_field_mismatches는 dict guard로
  list 조용히 스킵, _consistency_fields .items() 동일 crash, editor
  extract_supported_node_types .values() crash(fresh loop INTERACTION_UI 실측).
  수리(production 3파일 — evidence/review/editor) = classify_node_collection 정본 helper
  (NODE_MAP/NODE_LIST/EMPTY/MISSING/MALFORMED 분리, 비dict entry는 malformed_entries로
  계수, 순서 보존 결정론; AMBIGUOUS는 canonical 경로가 final_state.nodes 단일이라 예약만),
  malformed collection/entry fail-closed mismatch, 빈 evidence에 원인 metadata
  (smoke_review.replay_node_collection), vacuous status evidence/consistency 억제(INV-7),
  node.status 미렌더링 검출(x/y와 동일 원칙). Fresh-G hardcode 0, 신규 lane/module 0.
  Fresh-G 재판정(fresh loop 093644, parent 134413 불변 digest+base_hash PASS) =
  crash 0, HOLD packet 정상 생성, gates 7/7, acceptance 9/14, stage POLISHABLE_PROTOTYPE,
  mock 0, invalid success 0 → 정직 PARTIAL_PRODUCT (§26 REPAIR_AND_REEVALUATION).
  잔여 blocker = graph 도메인 INTERACTION_UI 라우팅(legacy editor adapter 전제조건이
  autopilot과 불일치 → EXECUTION_BLOCKED) + 제품 viewer 실결함 4건(browser 실증).
  blocked_lanes parent carry-over는 세션-로컬 상태라 구조적으로 재현 불가 확인.
  CANON-06에 replay node evidence shape safety 계약 추가. H/I 상태 불변(validate PASS).
- Issue #18 done (Fresh Blind Batch 4 — 커밋 0c67ac5 fix / ad293b9 test / docs 마감 커밋.
  session state = runs/_batch4_blind/state.json, selection digest 794d7c3c…10f7):
  선정(결정론: product_runs 등장 challenge 전제외+ID 오름차순+계층화 A/B/C) = Fresh-G #7
  스킬트리(A)/H #6 Mini-Vue(B)/I #5 코딩랩(C), 후보 6+제외 8 기록.
  Round 1(무수정) = PC 0/3, zero-repair 0 — G: base 첫 7/7 zero-patch 완주(사상 최초) 후
  loop INTERACTION까지, runner가 필수 input 누락을 ok=true·errors=[]로 silent-accept →
  PARTIAL_PRODUCT(9/14). H: Gemma가 node runner_command 채택 — sandbox에 node 부재(127)
  +FROZEN 계약이라 회복 불가 → 전 gate FAIL FACTORY_DEFECT. I: golden 논리 timestamp↔
  time.time() 의미 충돌(Fresh-A 계열 반복) → VALID_HOLD. INVALID_SUCCESS 0.
  Generic repair 1회(3 production 파일): D1 RunnerContract interpreter fail-closed
  (SANDBOX_RUNNER_INTERPRETERS=python)+프롬프트 명시, D2 구조적 무효 action의 errors
  채널 명시 거부를 생성 프롬프트에 추가(has_error_signal 검출기 무변경), A1 전제조건
  부재 BLOCKED lane 재선택 차단(EXECUTION_BLOCKED 정직 HOLD). hardcode 0, 신규
  lane/executor/module 0.
  Round 2(fresh) = H: python 계약 7/7 zero-patch(D1 실측 효과) → INTERACTION+RUNNER_BACKED
  APPLIED → EXECUTION_CANDIDATE 12/14 PARTIAL_PRODUCT(잔여 2건은 coverage matrix 절차
  영역). I: spec review 정직 중단 2회 후 7/7 완주 → loop 4 iter(RBDE APPLIED 포함)
  9/14 INTERACTION_CANDIDATE PARTIAL_PRODUCT. G: 빌드 7/7 재완주했으나 loop이
  **factory_product_evidence.viewer_reads_replay_evidence의 nodes dict 가정(list면
  AttributeError)으로 crash — FACTORY_DEFECT 잔존(repair 예산 소진, 후속 1순위)**.
  판정 = GENERALIZATION_YELLOW(판정 정확·INVALID_SUCCESS 0·예산 준수), trend = STABLE
  (zero-repair PC 0/3 동일하나 base build 완주 최초 등장·H 0/7→12/14). 회귀 8종
  digest/mtime/validate 전부 baseline 일치. 남은 인간 결정 = I 시간 의미(반복),
  H R2 검수. 다음 추천(정확히 1개): Fresh-G 평가기 crash 수리 후 G 재판정.
- Issue #17 done (Fresh-F #98 Product UI Completion — Factory production/test 코드 변경 0,
  구현 전부 fresh child 내부. 커밋 = docs/atlas만):
  fresh child = runs/factory_20260712_090748 (parent 060752 복사, parent digest
  b843e7e5…21ba·세션 중 mutation 0). 순서 = (1) factory_interaction_ui 재적용으로
  stale interaction_smoke 해소(invalid_action_rejected true, 핸드오프 예측 일치),
  (2) 제품별 diagnostic 패널을 generic 콘솔 위(첫 화면)에 추가 — 단일 정본
  final_state.DiagnosticStore.issues에서 warning cards(카드=button, aria-pressed,
  Enter/Space keydown 명시 처리)와 highlight pane(분석 시점 스냅샷에 mark, 좌표 보정 0,
  INVALID_DIAGNOSTIC_RANGE fail-closed, 겹침 invalid)을 함께 그림; 소스 수정 →
  STALE(선택 해제·하이라이트 제거·카드 비활성) → 재실행 → fresh mapping,
  (3) viewer 수리 — ev.message/final_code 결함 제거({type,id}·CodeState.content 정본),
  남은 진단 range 렌더 + meta viewport + 640px 스택.
  coverage = P10/P11 신설(runner 정본 diagnostic check + static substring 복합,
  §19.3에 따라 browser 실증 review/issue17_ui/browser_runtime_evidence.json 병행) →
  SC2/DA2 COVERED, critical 3/3·anchor 3/3·forbidden 0, TRUE_CORE_GAP 0.
  정본 최종 verify(desk 포함 live, 090748/review/phase2d1/issue17_final_verify) =
  gates 7/7, validate PASS, anti_hardcode PASS, acceptance 14/14(10/14에서 승격),
  desk PASS·primary_gap None·hard blocker 0, stage=effective_stage=PRODUCT_CANDIDATE
  (정본 계산, 직접 설정 0). Google API 500 transient 3회는 전부 재시도 회복(mock 대체 0).
  회귀 = 이슈15 immutable 9종 digest MATCH + 기존 성공 7종(#47/#54/SRS27/Table17/
  Fresh-C 41/Fresh-D 49/Fresh-E 95) validate PASS·세션 중 mutation 0 + generic 콘솔
  구조화 입력/모바일 overflow 회귀 0. invalid success 0, mock success 0, 신규
  lane/executor 0, Factory production hardcode 0.
  CANON-06에 diagnostic card/highlight 계약, CANON-10에 static-only coverage 금지 추가.
  다음 추천 작업(정확히 1개, §31 규칙 3): Fresh Blind Batch 4.
- Issue #16 done (Empty Entity Collection Vacuous Attribution Repair, 커밋 1a732a3 fix /
  fedbf7c test / docs 마감 커밋):
  root cause = EXPOSURE_AND_INSTANCE_CONFLATION + VACUOUS_EVALUATION_MISSING 복합 —
  _entity_instances의 `if items` 필터가 빈 collection을 발견 단계에서 폐기, scenario_002/
  003의 tasks:[]가 exists:parent_plan_id에서 INVARIANT_NOT_EXPOSED 오판(이슈 #14 deferred
  defect). 수리(production 1파일 factory_core_gates.py) = exposure 5상태 분리
  (NOT_EXPOSED/EXPOSED_EMPTY/EXPOSED_NONEMPTY/EXPOSED_WRONG_TYPE/AMBIGUOUS_EXPOSURE;
  이름 정규화 = 대소문자 무시+'+s'만, dict/list 한정 깊이 탐색, 복수 후보 fail-closed,
  빈 dict 자동 승격 금지) + universal field invariant(entity 선언 필드 술어만)의
  VACUOUS_PASS_EMPTY_COLLECTION(instance 0 evidence) + cardinality(length 비교) 독립
  평가 유지·vacuous 우회 불가. CANON-04 exposure 계약 갱신.
  Fresh-D 재검증 = parent 045751 fresh loop(loop_20260712_165424): gates 6/7→7/7 전환
  → INTERACTION_UI APPLIED(child 075810) → RUNNER_BACKED_DRAFT_EXECUTION APPLIED(child
  080138) → strict PRODUCT_CANDIDATE. 정본 최종 verify(desk 포함, 080138/review/phase2d1/
  issue16_final_verify) = gates 7/7, validate PASS, acceptance 14/14(11/14에서 승격),
  coverage critical 1.0·anchor 1.0·forbidden 0, mock 0, gap None, hd None — 정본 계산,
  직접 설정 없음. parent 스냅샷 190파일 변경 0(신규는 loop dir 내부만), base hash PASS.
  vacuous evidence artifact = issue16_final_verify/state_invariant_evidence.json
  (EXPOSED_EMPTY·VACUOUS_PASS_EMPTY_COLLECTION·evaluated 0·cardinality none).
  회귀 = 기존 성공 7종(#47/#54/SRS27/Table17/Fresh-C 41/Fresh-E 95/Fresh-F 98) validate
  PASS + state_invariant 재평가 전부 PASS(vacuous 발화 0 — non-empty 의미 불변) + 이슈
  #15 immutable 9종 content digest MATCH. Fresh-F = PRODUCT_CORE_GAP 유지(UI gap 범위 외).
  invalid success 0, mock success 0, Fresh-D hardcode 0, 신규 lane/executor 0.
  다음 추천 작업(정확히 1개, §27 규칙 2): Fresh-F #98 제품별 UI completion
  (경고 카드↔에디터 하이라이트 전용 UI) 별도 주문.
- Issue #15 done (Fresh-D/E/F Golden–Runner Adjudication + Phase 2B Apply — Factory
  production/test 코드 변경 0, 전부 runs/ 제품 child 내부 작업. 정본 근거 =
  runs/_issue15_adjudication/state.json):
  판정·적용 (D #49) APPROVE_RUNNER_REPAIR + proposal(golden 갱신) REJECT — engine.py
  content-조건부 Outdated(무수정 golden 3/3 PASS), child 045751.
  (E #95) APPROVE_GOLDEN_REPAIR 표준 Phase 2B harness — golden 4종에 계약 state
  field(skills)만 추가, 최종 child 060018.
  (F #98) APPROVE_GOLDEN_REPAIR 위임 판정 보정 — range/공백 산술 오류 정정(독립
  slicing 계산 evidence), 최종 child 060752(+ core gap 최소 수리 055022).
  최종 status (정본 verify, desk 포함): E = PRODUCT_CANDIDATE(gates 7/7, acceptance
  14/14, coverage 3/3·3/3). F = PRODUCT_CORE_GAP(gates 7/7·validate PASS이나
  TRUE_CORE_GAP 2 = SC2/DA2 경고 카드↔에디터 하이라이트 전용 UI 부재, acceptance
  10/14 — 별도 제품 completion 주문 권고). D = FACTORY_DEFECT(제품 의미 결함 0,
  coverage 4/4·3/3, blocker = state_invariant 빈 tasks[] vacuous 평가기 한계 →
  core gate FAIL → loop이 interaction 체인 미진입. packet =
  045751/review/phase2d1/issue15_final_verify/final_status_packet.json).
  집계: PRODUCT_CANDIDATE 1, 남은 VALID_HOLD 0, golden repair 2(E 표준/F 위임),
  runner repair 1(D), combined 0, rejected proposal 1(D), Factory defect 1(빈
  entity 컬렉션 vacuous 귀속 — 이슈 #14 deferred 재확인). §27 판정 =
  PARTIAL_COMPLETION(invalid success 0, mock 0, 기존 성공 9종 digest/mtime 불변).
  다음 추천 작업(정확히 1개, §28 규칙 1): 빈 entity 컬렉션 vacuous 귀속 평가기
  수리 후 D phase2d1 loop 재실행.
- Issue #14 done (Fresh Blind Batch 3, 커밋 4aaca59 fix+test / 마감 docs 커밋):
  선정 = Fresh-D #49 Spec-Driven 파이프라인(순서·의존성)/Fresh-E #95 스킬 번들 빌더
  (구성·선택)/Fresh-F #98 미니 린터(변환·검증) — 기존 10 사례·도메인과 비중복,
  selection digest 고정. Round 1(무수정) = 3/3 base build 완주(D 5/7, E·F 6/7 gates,
  전부 golden_output FAIL 계열) → closed loop 3/3 AUTOPILOT_HOLD_FOR_HUMAN.
  실원인 = 3/3 공통으로 Gemma 생성 golden↔runner 정합(D: 미작성 Draft 하위 단계의
  Outdated 전이 의미, E: golden 4/4에 runner final_state.skills 키 부재, F: range
  off-by-one·공백 값) — frozen golden 보호 설계상 사람 spec 결정 지점 = 3/3 VALID_HOLD.
  INVALID_SUCCESS 0, mock 0, 신규 lane/executor/hardcode 0.
  Repair gate 충족(§10.1 A: D·F 반복 + D: 결정론 모순) → generic repair 1회(2 files,
  +30/-12): (1) classify_failures가 golden 값 수준 불일치를 requires_spec_repair=False로
  분류해 SPEC_REPAIR_REQUIRED 마커 미생성 → loop escalation 미발화(§4.4/§6.2 NEVER_PATCH
  계약과 코드 모순) → True로 정합, (2) _entity_instances가 entity명 대소문자
  ('Pipeline'↔'pipeline')·중첩 컬렉션(pipeline.stages) 미해석으로 INVARIANT_NOT_EXPOSED
  오탐 → 대소문자 무시+한정 깊이 중첩 탐색(자동 PASS 금지 불변). Round 2(fresh child
  3종) = 3/3 SPEC_REPAIR_REQUIRED escalation 정상 발화·child verdict SPEC_REPAIR_REQUIRED/
  PATCH_BLOCKED_SPEC(proposal 생성)·blocking_gaps에 SPEC_REPAIR_REQUIRED 정확 표면화.
  generalization = YELLOW(PC 0/3이나 3/3 hold 판정이 실원인과 일치), Batch 2 대비 trend =
  STABLE(완주 0→0이나 repair burden 감소: 이슈 2개 규모→1 round 2 files, batch 2 수리
  항목 재발 0). 회귀 = 9 run validate PASS + digest/mtime 불변 + Fresh-C structured
  console 회귀 smoke PASS. 남은 인간 결정 = D/E/F golden spec repair proposal 3건.
  잔여 defect 후보(미수리) = 빈 entity 컬렉션 vacuous 미귀속 NOT_EXPOSED(1제품),
  golden-only 실패에서 CORE_PATCH first-choice가 high-risk 예산을 선소모(설계 한도).
  CANON-04(entity resolution)·CANON-05(golden 값 괴리=spec-family) 불변식 기록.
  증거: runs/_issue14_blind_batch3/state.json
- Issue #13 done (Schema-Aware Structured Console Input, 커밋 aa83568 + 마감 커밋):
  결함 판정 = 복합(UI_RENDERING_GAP+CLIENT_PARSE_GAP: action console이 전 필드 text
  input→string 전송 + SERVER_VALIDATION_GAP: 서버 schema 재검증 0 — 서버→runner JSON
  왕복은 타입 보존, 손실 지점은 클라이언트 단일). 구현 결과 = observe_input_types
  (fixture 실사용 payload 관측이 결정론 타입 정본 — kinds/fields/items/null union),
  console structured JSON textarea(object/array schema만 명시적 parse, parse/validation
  status, invalid 대기열 차단), boolean select/number input, string은 JSON처럼 보여도
  문자열 유지(자동 추측 금지). 지원 타입 = string/number/boolean/null/object/array
  (nested 포함, null union). validation = client(INVALID_JSON/WRONG_TOP_LEVEL_TYPE/
  MISSING_REQUIRED_FIELD/INVALID_FIELD_TYPE/INVALID_ARRAY_ITEM/EXCESSIVE_NESTING)
  + server 독립 재검증(fail-closed: TYPE_MISMATCH/MISSING_REQUIRED_FIELD/
  INVALID_ARRAY_ITEM/FORBIDDEN_KEY(__proto__/prototype/constructor)/EXCESSIVE_NESTING(16)/
  body 1MB) 이중, 위반 시 runner 호출 0·state 변화 0. runtime 결과 = Fresh-C child
  165952 scratchpad 복사본(원본 불변) browser 실조작: nested object 2계층 실행·보존,
  invalid JSON/wrong type 명시 거부(POST 0), primitive string 유지; synthetic structured
  run(echo runner 타입 검증): array [3,6,9] 보존, nested boolean string 거부, number
  42.5/boolean true/null metadata 보존, 문자열 '{"looks": "like json"}' string 유지.
  §15.6에서 발견·수정 2건 = 모바일 media query의 #action-select 누락(8px overflow)
  + 대기열 li 긴 JSON 텍스트 overflow-wrap 부재(253px 파괴) → 수정 후 overflow 0,
  회귀 테스트 고정. primitive 회귀 = 기존 text/number/boolean 컨트롤 동작 유지
  (테스트 20종 + Table17/SRS27 등 회귀 제품 factory-validate 9종 PASS). remaining gap =
  없음(구조화 입력 범위 내) — union/oneOf/recursive schema는 §18 범위 외.
  CANON-06에 structured console input semantics 계약 기록.
  증거: runs/_issue13_structured_input/browser_runtime_evidence.json
- Issue #12 done (Live Desk Human Decision Contract Alignment, 커밋 0d0a725/47ba0e1/68040a8):
  결함 판정 = 복합(PROMPT_DEFECT: lane prompt에 human_decision_required 의미 정의 부재 +
  NORMALIZATION_MISSING: raw 값이 loop 정지에 직행 + VALIDATOR_MISSING: consistency 검증
  누락) — #47 live loop 2회·Fresh-C에서 동일 실측. canonical contract(CANON-07
  INV-HUMAN-DECISION-NORMALIZED) = human_decision_required는 semantic hold(HOLD_FOR_HUMAN
  lane 또는 EVIDENCE_INSUFFICIENT/SCOPE_CREEP_RISK gap)일 때만 true;
  requires_human_approval_before_apply(apply gate)·auto_execute_allowed(policy)와 독립.
  구현 = normalize_human_decision(결정론 교정 + raw/normalized/reason_code evidence) +
  validate_human_decision_consistency(INV-1~3 fail-closed) + prompt/schema 정렬 +
  loop 의미 분리(hold_reason_class SEMANTIC_HOLD|EXECUTION_BLOCKED|BUDGET_EXHAUSTED,
  실행 lane iteration에 execution_policy AUTO_EXECUTE|APPLY_APPROVAL_PENDING 기록,
  dashboard HOLD 패널 class 표시). 테스트 21종(계약 단위 10+parity 9 lane+loop 분리).
  Fresh-C 재검증 = parent 144636 fresh child live loop(loop_20260712_014718):
  live raw human_decision_required=false(정렬된 prompt가 첫 실사용에서 정정),
  normalization RAW_CONSISTENT, RUNNER_BACKED_DRAFT_EXECUTION 실제 진입 APPLIED —
  child 165952 EXECUTED(state_change_observed, invalid 거부, revise 반영), gates 7/7,
  coverage critical 1.0/anchor 1.0, acceptance 12/14→14/14, INTERACTION_CANDIDATE→
  PRODUCT_CANDIDATE(strict, 정본 계산). base 142713/parent 144636 hash 불변,
  live 500/503/504 transient는 전부 자체 재시도 회복(mock 대체 0), invalid/mock success 0.
  Fresh-A VALID_HOLD·Fresh-B PRODUCT_CORE_GAP 유지(base 불변), #47/#54/SRS27/Table17
  base hash 4종 불변. object input(generic 콘솔)은 Fresh-C 완주를 막지 않아 deferred 유지
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
  base 6종 hash 불변, invalid/mock success 0.
  마감 §18 runtime smoke(브라우저 실조작)에서 meta viewport 부재 발견 —
  주입된 media query가 모바일 fallback ~980px에서 절대 발화 안 함 → 같은
  op 일부로 meta 주입+재진단 강화(catalog 확장 없음, 커밋은 마감 fix),
  062013/062015 재적용 APPLIED·validate PASS·실렌더 innerWidth=375 column
  스택 확인. #54 viewer의 scenarios.json 데이터 경로 결함이 기존 잠복
  결함으로 표면화(이슈 #8 무관, VIEWER_POLISH 미적용 산출물 — 사람 결정
  대상). 증거: runs/_issue8_ux_polish/runtime_smoke_and_meta_fix.json

- Issue #9 done (#54 viewer 수리 + requirement coverage adjudication,
  커밋 3f6c380/13cefc0/(docs)): Phase A = #54 child 080253 viewer를 기존
  VIEWER_POLISH 계약만으로 수리(코드 변경 0, scenarios.json stale fetch 0,
  REPLAY_READY, PRODUCT_CANDIDATE 유지, base 불변). Coverage 계약 =
  factory_coverage(CANON-10 REQUIREMENT_COVERAGE): 결정론적 runner probe +
  coverage matrix, COVERED는 PASS probe ref 필수, partial 미산입, fingerprint로
  과거 evidence 복사 거부, loop가 유효 fresh matrix를 정본으로 소비
  (desk_status=COVERAGE_MATRIX). generic repair = EVIDENCE_GAP(2제품 공통,
  mock desk 전항목 unknown 강등) 1회. TRUE_CORE_GAP 최소 구현 = generic console
  localStorage 상태 지속(제품 분기 없음). SRS 27 coverage child 084204 =
  critical 4/4·anchor 3/3·violation 0 → acceptance 14/14 PRODUCT_CANDIDATE
  (12/14에서 승격). Table 17 coverage child 084349 = critical 0/3·anchor 1/3·
  forbidden violated 2·TRUE_CORE_GAP 7 정직 기록 → 11/14 EXECUTION_CANDIDATE
  HOLD 유지(grid UI+타입별 폼+Boolean core는 §9.3 초과 — 별도 주문 권고,
  HUMAN_DECISION_REQUIRED). #47/#54 회귀 없음(validate PASS), base/parent 불변,
  invalid/mock success 0, VALIDATOR_DEFECT 0, SPEC_OVERREACH 0.
  증거: runs/_issue9_coverage/state.json

- Issue #10 done (Table 17 Product Core Completion, 커밋 a76ffdc/1002979/(docs)):
  결과 = grid frontend(generic KIND_TABLE_GRID: state 모양 columns+rows 감지,
  실제 row/column grid 렌더, column type별 컨트롤 bool select/number input/text,
  typed JSON payload, 반응형 meta viewport) + child engine Boolean core
  (기본 False·missing→false, strict bool check·Number는 bool 제외,
  update_column_type 변환 규칙). fresh child run = factory_20260711_113919
  (parent 084349 복사, base/parent 불변). coverage = critical 3/3·anchor 3/3·
  forbidden violation 0 (probe 7/7 PASS: P4 Boolean 4상태+P6 invalid 거부+
  P7 typed-form static 신설, 전 행 PASS probe ref COVERED). acceptance =
  14/14 → 최종 product status = PRODUCT_CANDIDATE (11/14 EXECUTION_CANDIDATE
  HOLD에서 승격, 정본 계산·직접 설정 없음). 남은 gap = 0 (TRUE_CORE_GAP 7 전부
  해소). 인간 결정 = 없음(이슈 #10 주문 자체가 HOLD 응답). 회귀: #47/#54/SRS
  084204 factory-validate PASS, viewer 재생성 금지 준수(replay 정상).
  다음 추천 = deferred 항목(대형 파일 분해 또는 db verdict stale) 별도 주문

- Issue #11 done (Fresh Blind Batch 2 — Factory 무수정 블라인드 3종, 커밋 docs only):
  선정 = Fresh-A #1 스터디 플래너(제약 해결형)/Fresh-B #99 HITL 승인 패널(workflow형)/
  Fresh-C #41 Mini-Transformers(구성·변환형) — 전부 미사용·hardcode 0. Round 1 결과 =
  A: VALID_HOLD(golden ISO↔runner epoch 의미 괴리+engine time.time() 비결정 —
  SPEC_REPAIR 사람 결정 실재, base 124224/loop 220017), B: PRODUCT_CORE_GAP(선언 entity
  AgentWorkflowState 미구현, core_contract FAIL/DROP, base 151426/loop 002817),
  C: PARTIAL_PRODUCT(gates 7/7, INTERACTION_UI APPLIED child 144636, acceptance 12/14,
  base 142713/loop 234103). INVALID_SUCCESS 0, Factory source 변경 0, 신규 lane/executor 0,
  generic repair 0회(§10.1 gate 미충족 — 반복 defect 없음) → Round 2 없음, Round 1이 최종.
  발견된 Factory 결함 후보(1회 관측, 미수리·다음 주문 후보): (1) live desk가 의미 미정의
  human_decision_required를 policy requires_human_approval_before_apply와 혼동해 true로
  채워 실행 가능 lane(RUNNER_BACKED) 앞에서 loop 정지 — 결정론 packet 정본 의미는
  lane==HOLD_FOR_HUMAN 한정(factory_autopilot_desks.py:510), mock loop과 계약 불일치;
  (2) generic INTERACTION_UI 콘솔이 object-valued 입력을 JSON parse 없이 문자열 전송 —
  UI 실조작에서 engine 오류 실측(오류는 정직 표시), probe는 runner 직접 구동이라 미탐지.
  generalization = YELLOW(완주 0/3이나 HOLD/CORE_GAP 진단이 실원인과 일치, 정직한 진단기).
  Atlas = 3/3 CONTEXT_SUFFICIENT(--route factory_closed_loop). 회귀 = #47/#54/SRS27/Table17
  validate PASS + base hash 4종 불변. infra: Google API 500 구간(21:41~00:14)으로
  build transient 실패 A1/B5/C3회 — 전부 fresh 재시도 회복, mock 대체 0.
  증거: runs/_issue11_blind_batch2/state.json

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
1. graph 도메인 INTERACTION_UI lane 경로 수리 후 Fresh-G 재판정 (이슈 #19 §27 규칙 1
   유일 추천): lane 라우터가 state에 nodes+edges만 있으면 legacy 2C-2 editor adapter로
   보내는데, editor는 2C-1 polish 산출물·user_review_decision.md(human gate)·
   supported_node_types(contract/replay type 필드)를 전제 — autopilot fresh 제품은
   전부 결여라 graph-형 신규 제품의 interaction gap이 구조적으로 EXECUTION_BLOCKED
   (G fresh loop 실측: 정직 CANNOT_EDIT → A1 재선택 차단 → HOLD). generic interaction
   console은 graph 도메인을 설계상 거부(factory_interaction_ui:1438). 이 라우팅/전제
   불일치를 수리해야 G가 진행 가능. 부수 관찰(후속 후보): G 제품 viewer 실결함 4건
   (파일명 조립 404, data.nodes vs final_state.nodes shape, node.status vs 정본 state,
   event 필드 불일치 — 전부 제품 workspace 영역), continuation child 기록 형식
   validate FAIL(I R2 iter03), I(#5) 시간 의미 결정 반복.
   (그 외 deferred: golden-only 실패의 CORE_PATCH first-choice rung 검토, 대형 파일 분해,
   literal-only artifact 실증 승격, db verdict stale)

DO_NOT_REPEAT:
- do not keep untracked markdown in repo root or source paths (architecture-check hard failure)
- do not put a static current-HEAD hash back into this file (HEAD_SOURCE rule)
- do not re-add human documentation, checklist, or Atlas HTML/serve/summary
- do not touch #47/#54/fresh(190458·193103·194814) base runs on disk (tmp copies only)
- do not touch blind batch 2 base runs(124224·151426·142713)와 Round 1 loop artifact —
  fresh child로만 진행 (이슈 #11 Round 1 기록은 불변 증거)
- do not touch blind batch 3 base runs(194219·022630·030726)와 Round 1/2 loop·child
  artifact — spec repair는 사람 결정 + Phase 2B apply 절차로만 (이슈 #14 기록은 불변 증거)
- do not touch Fresh-F parent 060752와 정본 child 090748(이슈 #17 PRODUCT_CANDIDATE
  verify 근거) — 추가 작업은 새 fresh child로만; diagnostic range는 UI에서 절대
  보정하지 않는다(CANON-06 diagnostic card/highlight semantics)
- do not touch blind batch 4 base/child runs(G 100335·134413/104032, H 105004·150755/
  153036, I 124428·161230/165512)와 loop artifact — 후속 작업은 fresh child/loop로만
  (이슈 #18 Round 1/2 기록은 불변 증거); runs/_batch4_blind/state.json이 attempt 정본
- frozen golden↔runner 값 괴리를 patch lane으로 분류하지 않는다 — GOLDEN_SCHEMA_MISMATCH는
  형태 불문 requires_spec_repair=true(CANON-05), SPEC_REPAIR_REQUIRED 마커가 loop
  escalation의 유일한 트리거다
- do not copy requires_human_approval_before_apply into human_decision_required —
  semantic 결정과 apply 승인은 다른 의미다(CANON-07 INV-HUMAN-DECISION-NORMALIZED);
  raw live 값은 normalize_human_decision을 거치지 않고 loop 판정에 쓰지 않는다
- lane-result escalation (SPEC_REPAIR 분류 → 다음 iteration 승급)은 구현됨(CANON-07) —
  high-risk 예산 1로 같은 loop 내 실행까지는 안 되는 것이 설계 한도이지 버그가 아님
- LITERAL_REFERENCE artifacts stay non-promoted (§13) — do not upgrade them without AST/manifest proof
- UX_POLISH lane의 UX_READY(진단만, patch 0)는 loop에서 NO_CHANGE로 집계되어 child가
  승격되지 않는 것이 설계 한도다 — report가 필요한 run은 execute_lane 직접 실행으로 남긴다
- UX patch는 data-ux-op marker block 주입만 — 기존 product 마크업/스크립트를 재작성하는
  operation을 추가하지 않는다 (자유 형식 수정 금지, CANON-06)
- viewport/keyboard의 정적 분석 PASS를 실기기 동작으로 간주하지 않는다 — media query는
  meta viewport 없이는 모바일에서 발화하지 않는다(§18 runtime smoke가 잡음). 정적
  검사와 브라우저 실조작 smoke는 서로를 대체하지 않는다
- 생성 콘솔 JS의 검증 결과 키는 {"valid": ...}를 유지한다 — {"ok": true} 문자열은
  mock-fallback 정적 검출기의 catch-window에 오탐된다(검출기 약화 금지 원칙 때문에
  코드 쪽에서 회피, 이슈 #13)

VERIFY:
- python -m repo_idea_miner architecture-check
- python -m repo_idea_miner architecture-build   # rerun twice → zero diff expected
- python -m pytest tests/test_architecture_atlas.py tests/test_architecture_scanner.py tests/test_architecture_context.py -q
- python -m pytest -q
