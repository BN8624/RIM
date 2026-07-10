# RIM Product Factory Phase 2D-1

## Evidence-Driven Closed Productization Loop 구현 주문서

## 0. 목적

현재 Phase 2D-0은 다음 산출물을 생성한다.

* Product Stage Label
* Product Gap Classification
* Recommended Next Lane
* Auto Order
* Repair Blueprint

그러나 live product artifact에는 repair를 적용하지 않으며, 수정 후 재검증과 재판정이 연결되지 않았다.

이번 작업의 목적은 기존 Phase 2A~2C 실행 경로를 Phase 2D lane 뒤에 연결하여 다음 실제 폐쇄 루프를 만드는 것이다.

```text
Probe
→ Judge
→ Gap
→ Lane
→ Child Run
→ Apply
→ Gate
→ Fresh Probe
→ Progress Compare
→ Promote or Rollback
→ Rejudge
```

새로운 범용 코딩 에이전트를 만드는 작업이 아니다.

기존 repair·polish·editor·execution 경로를 재사용해야 한다.

---

## 1. 절대 원칙

1. 원본 base run을 직접 수정하지 않는다.
2. 매 iteration은 별도 child continuation run에서 실행한다.
3. Gemma가 자유 형식으로 임의 파일을 직접 수정하게 하지 않는다.
4. Gemma 출력은 strict schema를 통과한 patch/order packet이어야 한다.
5. lane executor가 allowed scope와 protected scope를 검증한 뒤 적용한다.
6. golden, fixture, contract의 의미를 약화해 gate를 통과시키지 않는다.
7. product layer 생성 후 anti-hardcode를 반드시 다시 실행한다.
8. demo/mock/fallback 데이터를 실제 실행 결과처럼 표시하면 실패다.
9. 수정 후에는 기존 report 값을 재사용하지 않고 fresh probe를 실행한다.
10. 사람은 중간 iteration에서 질문받지 않는다.
11. 자동 진행 불가능 시 HOLD_FOR_HUMAN 산출물을 만든 뒤 종료한다.
12. PRODUCT_CANDIDATE는 제품 루프뿐 아니라 원 주문서 핵심 요구사항까지 충족해야 한다.

---

## 2. 선행 수정

Closed Loop 구현 전에 다음을 먼저 고친다.

### 2.1 Anti-hardcode 스캔 시점 통일

최초 build와 continuation 모두 다음 순서로 실행한다.

```text
core build
→ product layer build
→ anti-hardcode including product/
→ product acceptance
→ final verdict
```

빌드 시 product/를 검사하지 않고 continuation에서만 검사하는 비대칭을 제거한다.

### 2.2 Mock fallback 금지

product layer 생성 prompt와 gate에 다음 규칙을 추가한다.

금지 예:

* scenario_1 고정 fallback
* runner 실패 시 성공 mock 표시
* fetch 실패 시 내장 demo result를 실제 결과처럼 표시
* Math.random 또는 Date.now 기반 가짜 실행 결과
* 사용자가 만든 입력과 무관한 고정 success payload

fallback이 필요하면 반드시 다음 상태로 표시한다.

```text
DEMO_ONLY
NOT_EXECUTED
RUNNER_UNAVAILABLE
```

이 상태에서는 PRODUCT_CANDIDATE가 될 수 없다.

### 2.3 Golden representation strict mode

기존 run은 `NOT_DECLARED` 호환을 유지한다.

새 harness schema version의 run은 다음을 강제한다.

* output_representation 필수
* event item type 필수
* event required keys 필수
* summary format 필수
* critical scenario의 expected event/result가 모두 비어 있으면 FAIL

---

## 3. 신규 주요 구성요소

권장 신규 파일:

```text
repo_idea_miner/factory_loop_executor.py
repo_idea_miner/factory_lane_executors.py
repo_idea_miner/factory_product_capabilities.py
repo_idea_miner/factory_product_progress.py
repo_idea_miner/factory_product_acceptance.py
```

기존 수정 파일:

```text
repo_idea_miner/factory_product_loop.py
repo_idea_miner/factory_autopilot_schemas.py
repo_idea_miner/factory_core_pipeline.py
repo_idea_miner/factory_validate.py
repo_idea_miner/factory_db.py
repo_idea_miner/challenge_dashboard.py
repo_idea_miner/cli.py
```

`factory_product_loop.py` 전체를 대규모로 재작성하지 않는다.

새 실행·progress·capability 책임만 신규 모듈로 추출한다.

---

## 4. Lane Executor Registry

다음 registry를 구현한다.

```text
SPEC_REPAIR
→ 기존 Phase 2B-1 spec repair apply 경로

CORE_PATCH
→ 기존 continuation core patch 경로

RUNNER_PATCH
→ 기존 continuation runner patch 경로

VIEWER_POLISH
→ factory_product_polish 경로

INTERACTION_UI
→ factory_product_editor 경로

RUNNER_BACKED_DRAFT_EXECUTION
→ factory_draft_execution 경로

UX_POLISH
→ 신규 generic product UX executor

ARCHIVE
→ apply 없음, archive report 생성

HOLD_FOR_HUMAN
→ apply 없음, human decision packet 생성
```

각 executor는 공통 결과를 반환한다.

```json
{
  "status": "APPLIED | BLOCKED | FAILED | NO_CHANGE",
  "child_run_dir": "...",
  "changed_files": [],
  "allowed_scope_check": "PASS",
  "protected_hash_check": "PASS",
  "targeted_tests": [],
  "targeted_test_status": "PASS",
  "failure_signature": null
}
```

---

## 5. Child Run과 Lineage

iteration마다 다음 lineage를 기록한다.

```json
{
  "loop_id": "...",
  "iteration": 2,
  "base_run_id": 13,
  "parent_run_id": 21,
  "child_run_id": 22,
  "selected_lane": "RUNNER_PATCH",
  "primary_gap_before": "RUNNER_PATCH_REQUIRED",
  "stage_before": "REVIEWABLE_ARTIFACT"
}
```

base run은 항상 불변이어야 한다.

성공한 child만 다음 iteration의 parent가 된다.

실패한 child는 기록은 남기되 active candidate로 승격하지 않는다.

---

## 6. Product Capability Profile

challenge ID, title, 노드·엣지 이름으로 분기하지 않는다.

artifact와 contract에서 다음 profile을 생성한다.

```json
{
  "input_kind": "graph | file_operation | scenario | document | generic",
  "editable_entities": [],
  "validation_command": "",
  "execution_command": "",
  "viewer_entrypoint": "",
  "result_required_fields": [],
  "failure_required_fields": [],
  "primary_user_actions": [],
  "critical_user_flows": []
}
```

공통 evidence 이름은 다음으로 바꾼다.

```text
can_create_or_modify_input
can_validate_input
can_execute_primary_action
can_observe_state_change
can_understand_success
can_understand_failure
can_revise_and_retry
product_loop_closed
```

도메인별 node/edge/file/path 등의 상세 evidence는 adapter evidence에만 둔다.

---

## 7. Fresh Probe

각 iteration 전후에 실제 artifact를 다시 검사한다.

보고서 boolean만 읽어 판정하지 않는다.

필수 probe:

1. runner 실제 실행
2. 정상 입력 success scenario
3. 다른 정상 입력 success scenario
4. 잘못된 입력 failure scenario
5. 입력 수정 후 재실행
6. 수정 전후 결과 차이 확인
7. viewer가 실제 result artifact를 표시하는지 확인
8. mock/fallback 검사
9. core output과 product surface 필드 정합성 검사
10. critical user flow handler 연결 확인

probe 결과에는 실행 명령, exit code, 입력 hash, 출력 hash, artifact path를 기록한다.

---

## 8. Product Acceptance Gate

PRODUCT_CANDIDATE에는 다음을 모두 요구한다.

```text
core gates 전부 PASS
factory-validate PASS
post-product anti-hardcode PASS
mock_fallback_count == 0
protected hash PASS
critical_requirement_coverage == 1.0
difficulty_anchor_coverage == 1.0
forbidden_simplification_violation_count == 0
product_loop_closed == true
success scenario 최소 2개 PASS
failure scenario 최소 1개 PASS
revise-and-rerun 결과 변화 확인
first screen CTA와 설명 존재
success/failure feedback 실제 표시
```

원 주문서의 critical requirement가 하나라도 미구현이면 PRODUCT_CANDIDATE가 아니다.

이 경우 stage 최대치는 `EXECUTION_CANDIDATE` 또는 `POLISHABLE_PROTOTYPE`으로 제한한다.

---

## 9. Progress Comparison

각 iteration 전후 다음 metric vector를 생성한다.

```json
{
  "stage_rank": 0,
  "core_gates_passed": 0,
  "product_acceptance_passed": 0,
  "hard_blocker_count": 0,
  "critical_requirement_coverage": 0.0,
  "difficulty_anchor_coverage": 0.0,
  "product_loop_parts_passed": 0,
  "success_scenarios_passed": 0,
  "failure_scenarios_passed": 0,
  "mock_fallback_count": 0,
  "regression_count": 0
}
```

의미 있는 개선은 다음 중 하나 이상이어야 한다.

* stage rank 상승
* hard blocker 감소
* product acceptance 통과 수 증가
* critical requirement coverage 증가
* difficulty anchor coverage 증가
* product loop parts 증가
* 실패 scenario가 PASS로 전환

동시에 다음을 만족해야 한다.

```text
regression_count == 0
protected hash PASS
mock fallback 증가 없음
기존 PASS gate의 FAIL 전환 없음
```

조건 미충족 시 `NO_MEANINGFUL_PROGRESS`로 기록하고 child를 승격하지 않는다.

---

## 10. 전략 변경과 중단

기본 예산:

```text
max_iterations = 4
max_attempts_per_lane = 2
max_high_risk_lane_attempts = 1
max_consecutive_no_progress = 2
max_infra_retries = 2
```

중단 조건:

* 엄격한 PRODUCT_CANDIDATE 도달
* ARCHIVE 판정
* protected scope 변경
* golden/fixture/contract 의미 약화 시도
* 연속 무개선 2회
* 같은 failure signature 2회
* 예산 초과
* evidence 부족
* 요구사항 자체가 모순돼 자동 결정 불가

같은 primary gap이 반복되더라도 failure signature가 달라지고 metric이 개선되면 계속할 수 있다.

단순히 primary gap 문자열이 같다는 이유만으로 중단하지 않는다.

---

## 11. HOLD_FOR_HUMAN

중간 질문을 보내지 않는다.

다음 최종 packet을 생성한다.

```text
현재 최고 candidate
현재 stage
남은 blocking gap
시도한 lane과 횟수
각 시도의 diff
실패 signature
보호 장치 결과
자동으로 결정하지 못한 이유
사람이 결정할 단 하나의 질문
추천 선택지
```

Dashboard에서 최종 검수 대상으로 표시한다.

---

## 12. Dashboard

제품 카드에 다음을 표시한다.

```text
현재 iteration / 최대 iteration
현재 stage
이전 stage
primary gap
선택 lane
metric delta
회귀 여부
mock fallback 수
critical requirement coverage
anchor coverage
stop reason
active child run
```

기술 로그 전체를 첫 화면에 노출하지 않는다.

상세 탭에서 lineage와 iteration별 evidence를 볼 수 있게 한다.

---

## 13. CLI

기존 `factory-product-loop`를 확장한다.

예:

```bash
python -m repo_idea_miner factory-product-loop \
  --run-id 13 \
  --mode live \
  --execute \
  --max-iterations 4
```

안전 기본값:

```text
--execute 미지정
→ judge/order/blueprint only

--execute 지정
→ child run closed loop 실행
```

`--apply-original` 같은 원본 직접 수정 옵션은 만들지 않는다.

---

## 14. 필수 검증 순서

각 apply 후 다음 순서로 실행한다.

```text
targeted lane test
→ syntax
→ core contract
→ runner
→ scenario replay
→ golden output
→ state invariant
→ determinism
→ product layer build/check
→ post-product anti-hardcode
→ product acceptance
→ factory-validate
→ fresh probe
→ rejudge
```

한 단계라도 실패하면 green 또는 PRODUCT_CANDIDATE를 기록하지 않는다.

---

## 15. 필수 테스트

1. 실제 child run이 생성되고 base run hash가 불변이다.
2. lane별 올바른 기존 executor가 호출된다.
3. protected scope 수정 제안이 apply 전에 차단된다.
4. product layer 생성 후 anti-hardcode가 실행된다.
5. 최초 build와 continuation이 같은 mock fallback을 같은 결과로 판정한다.
6. 수정 후 fresh evidence가 바뀐다.
7. report boolean을 조작해도 실제 probe 실패가 우선한다.
8. 의미 없는 UI 문구 변경은 progress로 인정하지 않는다.
9. 기존 PASS gate가 FAIL이면 rollback된다.
10. 두 success scenario와 한 failure scenario가 실행된다.
11. revise 후 출력 hash가 달라져야 revise-and-rerun PASS다.
12. critical requirement 미충족 상태에서 PRODUCT_CANDIDATE가 차단된다.
13. #47 특례 ID 없이 Mini-Comfy capability를 추출한다.
14. #54 특례 ID 없이 Virtual File Explorer capability를 추출한다.
15. 같은 loop 코드가 #47과 #54에 사용된다.
16. 연속 무개선 2회 후 HOLD_FOR_HUMAN으로 정직하게 종료한다.
17. flaky 없이 전체 테스트를 반복 3회 통과한다.
18. secret이 prompt, log, lineage, dashboard에 노출되지 않는다.

---

## 16. 완료 기준

다음 두 live 검증이 모두 필요하다.

### Case A — #47 Mini-Comfy

* 기존 green base 무손상
* 실제 편집·검증·실행·결과·수정·재실행 PASS
* 원 주문서 critical requirement coverage가 정확히 기록됨
* 드래그 선 연결이 미구현이면 PRODUCT_CANDIDATE 과대평가 금지
* mock fallback 0
* post-product anti-hardcode PASS

### Case B — #54 Virtual File Explorer

* graph 전용 분기 없이 capability profile 생성
* 현재 golden/value/exposure 문제를 올바른 lane으로 분류
* child run에서 repair
* 전체 gate 재실행
* fresh probe로 실제 개선 확인
* mock fallback 0
* base run 무손상

두 도메인이 같은 closed-loop orchestrator를 통과하기 전에는 다수 run batch 자동화를 시작하지 않는다.

---

## 17. 작업 보고 형식

작업 완료 보고에는 다음만 명확히 적는다.

```text
시작/종료 HEAD
수정 파일
신규 파일
P0 비대칭 수정 결과
lane executor 연결표
#47 live 결과
#54 live 결과
iteration별 stage/gap/lane/delta
base hash 불변 여부
post-product anti-hardcode 결과
PRODUCT_CANDIDATE 과대평가 차단 여부
pytest 결과와 flaky 여부
커밋/푸시 여부
남은 실제 한계
```
