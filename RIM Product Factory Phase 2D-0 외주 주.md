# RIM Product Factory Phase 2D-0 외주 주문서

## Gemma Productization Autopilot

### — Evidence-based Judge + Gap + Lane + Auto Order + Repair Blueprint + Minimal Loop Proof

---

## 0. 작업 배경

RIM Product Factory는 #47 Mini-Comfy 사례에서 다음 과정을 거쳤다.

```text
1. Core artifact 생성
2. Spec repair
3. Anti-hardcode patch
4. Review package 생성
5. Viewer field mapping polish
6. 사용자 60초 검수
7. Minimal draft editor 추가
8. 제품성 재판정
```

이 과정에서 드러난 핵심 문제는 코드 생성 능력이 아니라 **제품화 판단 자동화의 부재**다.

현재까지는 사람이 계속 다음을 판단했다.

```text
- 이 결과물이 제품인지 아닌지
- 왜 제품 느낌이 부족한지
- 다음에 고칠 하나의 gap이 무엇인지
- 어떤 lane으로 수리해야 하는지
- 어떤 범위는 건드리면 안 되는지
- 다음 주문서를 어떻게 써야 하는지
- 어떤 수리 방향이 안전한지
```

원래 Product Factory라면 이 판단을 Gemma가 해야 한다.

따라서 Phase 2D-0의 목표는 다음이다.

```text
Gemma가 green artifact를 보고
제품성 stage를 판단하고,
제품이 아닌 이유를 evidence 기반 gap으로 분류하고,
다음 productization lane을 선택하고,
lane template 기반 scoped auto_order를 생성하고,
live artifact에 대해서는 repair blueprint까지 설계하되 apply는 하지 않고,
mock/safe lane에서는 judge → order → repair → smoke/validate → rejudge 흐름을 1회 증명하게 만든다.
```

---

## 1. Phase 2D-0의 정확한 정의

Phase 2D-0는 #47을 계속 수동 제품화하는 단계가 아니다.
Phase 2D-0는 Phase 2C-3 Runner-backed Draft Execution을 직접 구현하는 단계도 아니다.
Phase 2D-0는 여러 artifact를 무제한 제품화하는 단계도 아니다.

Phase 2D-0는 **Gemma Productization Autopilot의 판단 계층과 최소 루프 검증 단계**다.

```text
대상: green artifact 또는 reviewable artifact
기준 테스트: #47
핵심:
- Product Judge
- Gap Classifier
- Next Lane Planner
- Scoped Order Writer
- Repair Blueprint Writer
- Minimal Loop Proof

기본 정책:
- live artifact에는 repair apply 금지
- live #47에는 judge/gap/lane/order/blueprint 생성까지 허용
- mock/safe fixture에서만 실제 repair loop 1회 허용
```

핵심 한 줄:

```text
Phase 2D-0는 제품을 직접 완성하는 단계가 아니라,
Gemma가 “아직 제품이 아닌 이유”, “다음에 고칠 한 가지”, “어떻게 고칠지의 안전한 blueprint”를 evidence 기반으로 고르게 만드는 단계다.
```

---

## 2. 이번 작업에서 하지 말 것

금지:

```text
- #47 Phase 2C-3 Runner-backed Draft Execution 직접 구현 금지
- #47 product viewer/core/runner를 이번 단계에서 실제 수리 금지
- live artifact에 repair apply 금지
- 여러 run/challenge에 무제한 루프 실행 금지
- PRODUCT_CANDIDATE 라벨을 느슨하게 유지 금지
- #47 기대 정답을 Gemma 프롬프트에 넣는 것 금지
- 사람이 작성한 고정 주문서를 그대로 하드코딩 금지
- challenge_id/run_id/title 기반 stage/gap/lane 하드코딩 금지
- Gemma 판단 없이 next lane을 고정 금지
- core/golden/replay/contract 임의 수정 금지
- queue 전체 자동 수정 금지
- 대형 dashboard 개편 금지
- Codex/Claude 자동 호출 금지
- hidden scenario 대형 시스템 추가 금지
- strict JSON schema 없이 Gemma 자연어 응답을 통과시키는 것 금지
- evidence_refs 없는 판단을 통과시키는 것 금지
- live Gemma 실패를 mock 성공으로 덮는 것 금지
- mock/safe loop에서 generated auto_order와 무관한 hardcoded repair 실행 금지
```

이번 단계에서 #47에 대해 해야 하는 일은 다음이다.

```text
#47을 보고 Gemma가 스스로
“현재는 PRODUCT_CANDIDATE가 아니라 INTERACTION_CANDIDATE이고,
primary gap은 RUNNER_BACKED_EXECUTION_REQUIRED이며,
다음 주문서는 Runner-backed Draft Execution이어야 한다”
라고 evidence 기반으로 판단하게 만든다.

그리고 실제 apply 없이
repair_blueprint, expected_patch_plan, tests_to_run, rollback/failure conditions까지 생성한다.
```

단, 이 기대값은 **테스트 assertion에만 사용**하고, Gemma 프롬프트에는 제공하지 않는다.

---

## 3. Phase 2D-0 핵심 요구사항

반드시 구현할 핵심 요구사항:

```text
1. #47 기대 stage/gap/lane은 test assertion에만 둔다.
   Gemma Product Judge 프롬프트에는 정답을 넣지 않는다.

2. Product Judge 입력은 summary만 보지 않는다.
   실제 artifact evidence, user action evidence, product files snippet, smoke result를 함께 본다.

3. 모든 Gemma desk 출력은 strict JSON schema로 검증한다.
   JSON parse 실패, required field 누락, enum 외 값, evidence 없는 판단은 HOLD_FOR_HUMAN 처리한다.

4. schema validation 실패 시 1회 schema_repair_pass를 허용한다.
   단, 구조만 고치고 stage/gap/lane/evidence 판단의 의미 변경은 금지한다.

5. deterministic hard blocker rules를 코드로 둔다.
   예: runner-backed execution 없음 → PRODUCT_CANDIDATE 금지.

6. 모든 stage/gap/lane 판단은 evidence_refs를 가져야 한다.
   primary_gap은 최소 2개 이상의 evidence_refs를 가져야 한다.

7. lane별 risk / auto_execute_allowed / approval policy를 둔다.

8. auto_order는 free-form이 아니라 lane template + Gemma filled slots 방식으로 생성한다.

9. auto_order_quality_score와 order validation을 둔다.
   품질 미달이면 HOLD_FOR_HUMAN이다.

10. live Gemma judge/order generation은 #47에서 1회 실행한다.
    live repair apply는 하지 않는다.

11. live #47에 대해 repair_blueprint.json, expected_patch_plan.md, tests_to_run.json,
    rollback_or_failure_conditions.json을 생성한다.
    이 산출물은 적용하지 않고 Phase 2C-3 auto_order의 보조 자료로만 사용한다.

12. mock/safe fixture에서만 judge → order → repair → smoke/validate → rejudge E2E 루프 1회를 검증한다.

13. mock/safe loop의 repair는 generated auto_order와 scope_guard를 실제로 참조해야 한다.

14. 기존 Phase 2C-2 product_fitness_report를 수정하지 않는다.
    prior_fitness_label과 autopilot_stage를 별도로 기록한다.

15. live Gemma 실패 시 성공 처리 금지.
```

---

## 4. Product Stage Label 재정의

기존 `PRODUCT_CANDIDATE`는 너무 빨랐다.
Phase 2D-0 이후 제품성 단계는 다음으로 재정의한다.

```text
CORE_GREEN
REVIEWABLE_ARTIFACT
POLISHABLE_PROTOTYPE
INTERACTION_CANDIDATE
EXECUTION_CANDIDATE
PRODUCT_CANDIDATE
ARCHIVE
```

### 4.1 CORE_GREEN

```text
core/golden/gate는 통과했지만 제품 표면이나 사용 경험은 아직 약한 상태.
```

### 4.2 REVIEWABLE_ARTIFACT

```text
사람이 artifact를 열어보고 기본 동작을 확인할 수 있는 상태.
```

### 4.3 POLISHABLE_PROTOTYPE

```text
viewer/UI polish를 통해 제품 후보로 키울 가능성이 있는 상태.
```

### 4.4 INTERACTION_CANDIDATE

```text
조작 UI는 있지만 사용자가 만든 입력을 실제 runner/core로 실행하는 루프는 닫히지 않은 상태.
```

### 4.5 EXECUTION_CANDIDATE

```text
사용자가 만든 입력을 실제 runner/core로 실행할 수 있고 결과를 볼 수 있는 상태.
단, 실패 이해성, 재수정 루프, UX가 아직 약할 수 있다.
```

### 4.6 PRODUCT_CANDIDATE

```text
생성/편집/검증/실행/결과/수정/재실행 루프가 닫힌 상태.
사용자가 60초 안에 제품 가치를 이해할 수 있어야 한다.
```

### 4.7 ARCHIVE

```text
green이어도 제품화 가치가 낮아 후속 루프에서 제외하는 상태.
```

---

## 5. 기존 fitness label과 Autopilot stage 분리

#47은 Phase 2C-2에서 이미 다음처럼 기록되어 있다.

```text
prior_fitness_label: PRODUCT_CANDIDATE
prior_fitness_qualifier: draft_editor_candidate
```

Phase 2D-0는 기존 Phase 2C-2 산출물을 수정하지 않는다.
대신 새로운 autopilot 기준으로 별도 stage를 기록한다.

필수 기록:

```json
{
  "prior_fitness_label": "PRODUCT_CANDIDATE",
  "prior_fitness_qualifier": "draft_editor_candidate",
  "autopilot_stage": "INTERACTION_CANDIDATE",
  "autopilot_is_product_candidate": false,
  "reason": "runner-backed execution not included"
}
```

중요:

```text
Phase 2D-0는 review/phase2c2/product_fitness_report_after_editor.json을 수정하지 않는다.
review/phase2d0/product_stage_label.json에 새 기준의 판단을 기록한다.
```

---

## 6. Deterministic Hard Blocker Rules

Stage 판정은 Gemma 의견만으로 하지 않는다.
먼저 코드 기반 hard blocker를 적용하고, Gemma Judge는 그 결과를 넘을 수 없다.

필수 hard blockers:

```text
runner-backed execution 없음
→ PRODUCT_CANDIDATE 금지

사용자가 만든 입력을 실행할 수 없음
→ PRODUCT_CANDIDATE 금지

실행 결과를 볼 수 없음
→ PRODUCT_CANDIDATE 금지

수정 후 재실행할 수 없음
→ PRODUCT_CANDIDATE 금지

JS syntax FAIL
→ PRODUCT_CANDIDATE 금지

critical red flag 존재
→ PRODUCT_CANDIDATE 금지

viewer/product surface 없음
→ REVIEWABLE_ARTIFACT 이상 금지

조작 UI 없음
→ INTERACTION_CANDIDATE 이상 금지

조작 UI는 있으나 실행 없음
→ EXECUTION_CANDIDATE 이상 금지

60초 이해성 evidence 없음
→ PRODUCT_CANDIDATE 금지

first_screen_understandable=false
→ PRODUCT_CANDIDATE 금지

clear_next_action=false
→ PRODUCT_CANDIDATE 금지

failure_feedback_visible=false
→ PRODUCT_CANDIDATE 금지

user_can_understand_value_in_60s=false
→ PRODUCT_CANDIDATE 금지
```

#47에 적용되는 hard blocker:

```text
runner-backed execution not included
edited draft cannot be executed by runner
edit → run → result → revise loop not closed
```

따라서 #47은 현재 `PRODUCT_CANDIDATE`가 될 수 없다.

---

## 7. Product Loop Evidence Model

Gemma Product Judge는 반드시 “사용자가 실제로 무엇을 할 수 있는가”를 표로 판단한다.

필수 evidence fields:

```json
{
  "can_create_input": true,
  "can_validate_input": true,
  "can_execute_input": false,
  "can_see_result_from_created_input": false,
  "can_understand_failure": false,
  "can_revise_and_rerun": false,
  "product_loop_closed": false
}
```

Stage 판정은 이 evidence와 hard blocker를 기반으로 한다.

```text
create + validate + export만 가능
→ INTERACTION_CANDIDATE 이하

create + validate + execute + result 가능
→ EXECUTION_CANDIDATE 가능

create + validate + execute + result + revise + rerun 가능
→ PRODUCT_CANDIDATE 가능
```

---

## 8. User-Facing Product Quality Evidence

제품 느낌은 기능 루프만으로 판단하지 않는다.
Product Judge는 사용자-facing 품질도 evidence로 기록해야 한다.

필수 필드:

```json
{
  "first_screen_understandable": true,
  "clear_next_action": true,
  "has_example_or_seed_data": true,
  "success_feedback_visible": true,
  "failure_feedback_visible": false,
  "empty_screen_risk": false,
  "user_can_understand_value_in_60s": false
}
```

Stage 영향:

```text
first_screen_understandable=false
→ PRODUCT_CANDIDATE 금지

clear_next_action=false
→ PRODUCT_CANDIDATE 금지

has_example_or_seed_data=false
→ PRODUCT_CANDIDATE 금지 또는 UX_POLISH_REQUIRED

success_feedback_visible=false
→ EXECUTION_CANDIDATE 이상 제한

failure_feedback_visible=false
→ PRODUCT_CANDIDATE 금지

user_can_understand_value_in_60s=false
→ PRODUCT_CANDIDATE 금지
```

이 항목은 기능 루프가 닫혔는데도 제품 느낌이 약한 경우를 잡기 위한 것이다.

---

## 9. Evidence Reference 규칙

모든 stage/gap/lane 판단은 `evidence_refs`를 가져야 한다.

허용 evidence_refs 예:

```text
artifact_evidence.product_loop.can_execute_input=false
artifact_evidence.product_loop.can_see_result_from_created_input=false
phase2c2_editor_report.runner_backed_execution_included=false
product_fitness_report.limitations includes "runner-backed execution not included"
editor_smoke_review.draft_export_supported=true
viewer_js_syntax_check.status=PASS
viewer_handler_binding_check.status=PASS
user_facing_quality_evidence.user_can_understand_value_in_60s=false
```

필수 규칙:

```text
not_product_reason은 최소 1개 이상의 evidence_refs를 가져야 한다.
primary_gap은 최소 2개 이상의 evidence_refs를 가져야 한다.
recommended_next_lane은 primary_gap evidence_refs를 참조해야 한다.
evidence_refs 없는 판단은 무효다.
```

무효 처리:

```text
evidence_refs 없음
→ AUTOPILOT_INVALID_OUTPUT 또는 HOLD_FOR_HUMAN
```

---

## 10. Strict JSON Schema Validation

모든 Gemma desk 출력은 strict JSON schema로 검증한다.

필수 schema:

```text
product_stage_label.schema.json
product_gap_classification.schema.json
recommended_next_lane.schema.json
auto_order.schema.json
scope_guard.schema.json
auto_order_quality_report.schema.json
repair_blueprint.schema.json
tests_to_run.schema.json
```

검증 실패 처리:

```text
JSON parse 실패
required field 누락
enum 외 값
type 불일치
evidence_refs 누락
hard blocker 위반
→ AUTOPILOT_INVALID_OUTPUT 또는 HOLD_FOR_HUMAN
```

Gemma 자연어 응답만으로는 통과할 수 없다.

---

## 11. Schema Repair Pass 1회 허용

Gemma 출력이 내용상 유효하지만 JSON 포맷만 깨질 수 있다.
따라서 schema validation 실패 시 1회에 한해 `schema_repair_pass`를 허용한다.

허용:

```text
- JSON 괄호/쉼표/따옴표 수정
- required field 위치 보정
- 배열/객체 wrapping 수정
- enum 표기 대소문자 정규화
```

금지:

```text
- stage 의미 변경
- primary_gap 의미 변경
- recommended_next_lane 의미 변경
- evidence_refs 새로 날조
- not_product_reason 의미 변경
- hard blocker 결과 변경
```

규칙:

```text
schema_repair_pass는 구조만 고친다.
판단 내용은 바꾸지 않는다.
```

실패 처리:

```text
schema repair 후에도 검증 실패
→ AUTOPILOT_INVALID_OUTPUT

schema repair 중 의미 변경 감지
→ AUTOPILOT_INVALID_OUTPUT

evidence_refs 부족
→ AUTOPILOT_EVIDENCE_INSUFFICIENT 또는 HOLD_FOR_HUMAN
```

---

## 12. #47 Hardcode 금지

Phase 2D-0는 #47을 기준 테스트로 사용하지만, #47 전용 하드코딩은 금지한다.

금지:

```text
challenge_id == 47 기반 stage/gap/lane 고정
run_id == 072220 기반 stage/gap/lane 고정
title contains Mini-Comfy 기반 stage/gap/lane 고정
특정 파일명 조합만 보고 #47 정답 반환
```

#47 판정은 반드시 artifact evidence에서 도출되어야 한다.

필수 evidence:

```text
can_create_input=true
can_validate_input=true
can_execute_input=false
runner_backed_execution_included=false
product_loop_closed=false
```

추가 테스트:

```text
#47과 challenge_id/title이 다른 synthetic fixture라도
동일한 product loop evidence를 가지면
동일한 stage/gap/lane이 나와야 한다.
```

즉:

```text
판정 기준은 ID가 아니라 product loop evidence다.
```

---

## 13. Gap Classification

Gemma는 제품 후보가 아닌 이유를 gap으로 분류해야 한다.

필수 gap types:

```text
SPEC_REPAIR_REQUIRED
CORE_PATCH_REQUIRED
RUNNER_PATCH_REQUIRED
VIEWER_POLISH_REQUIRED
INTERACTION_UI_REQUIRED
RUNNER_BACKED_EXECUTION_REQUIRED
UX_POLISH_REQUIRED
EVIDENCE_INSUFFICIENT
SCOPE_CREEP_RISK
ARCHIVE_RECOMMENDED
```

### 13.1 primary_gap 원칙

여러 gap이 있어도 한 iteration에서는 하나만 primary gap으로 선택한다.

```text
한 루프에 하나의 주요 결함만 고친다.
```

우선순위 예시:

```text
spec/golden이 틀림
→ SPEC_REPAIR_REQUIRED

core 결과가 틀림
→ CORE_PATCH_REQUIRED

runner dispatch/output이 틀림
→ RUNNER_PATCH_REQUIRED

viewer가 결과를 잘못 표시함
→ VIEWER_POLISH_REQUIRED

viewer는 정상인데 조작 UI가 없음
→ INTERACTION_UI_REQUIRED

조작 UI는 있는데 사용자가 만든 입력을 실행할 수 없음
→ RUNNER_BACKED_EXECUTION_REQUIRED

실행은 되지만 60초 이해성이 낮음
→ UX_POLISH_REQUIRED
```

#47 현재 기대 primary gap은 다음이어야 한다.

```text
RUNNER_BACKED_EXECUTION_REQUIRED
```

단, 이 기대값은 테스트 assertion에만 사용하고 Gemma 프롬프트에는 제공하지 않는다.

---

## 14. Lane Selection

Gemma는 primary gap에 따라 다음 lane을 선택한다.

필수 lane types:

```text
SPEC_REPAIR
CORE_PATCH
RUNNER_PATCH
VIEWER_POLISH
INTERACTION_UI
RUNNER_BACKED_DRAFT_EXECUTION
UX_POLISH
ARCHIVE
HOLD_FOR_HUMAN
```

### 14.1 Lane Risk Policy

각 lane에는 risk와 실행 정책이 있어야 한다.

```json
{
  "lane": "RUNNER_BACKED_DRAFT_EXECUTION",
  "lane_risk": "medium",
  "dry_run_allowed": true,
  "auto_execute_allowed": false,
  "requires_human_approval_before_apply": true
}
```

필수 lane policy:

```text
SPEC_REPAIR
- risk: high
- dry_run_allowed: true
- auto_execute_allowed: false
- approval required: true

CORE_PATCH
- risk: high
- dry_run_allowed: true
- auto_execute_allowed: false
- approval required: true

RUNNER_PATCH
- risk: medium
- dry_run_allowed: true
- auto_execute_allowed: false by default
- approval required: true

VIEWER_POLISH
- risk: low
- dry_run_allowed: true
- auto_execute_allowed: true only in mock/safe lane
- approval required for live apply: true

INTERACTION_UI
- risk: low-medium
- dry_run_allowed: true
- auto_execute_allowed: true only in mock/safe lane
- approval required for live apply: true

RUNNER_BACKED_DRAFT_EXECUTION
- risk: medium
- dry_run_allowed: true
- auto_execute_allowed: false
- approval required: true

UX_POLISH
- risk: low
- dry_run_allowed: true
- auto_execute_allowed: true only in mock/safe lane
- approval required for live apply: true

ARCHIVE
- risk: low
- dry_run_allowed: true
- auto_execute_allowed: false
- approval required: false

HOLD_FOR_HUMAN
- risk: variable
- dry_run_allowed: false
- auto_execute_allowed: false
- approval required: true
```

---

## 15. Gemma Product Judge Desk

신규 Gemma desk를 추가한다.

역할:

```text
green artifact와 실제 evidence를 읽고 현재 product stage를 판정한다.
```

### 15.1 입력

Product Judge는 summary만 읽으면 안 된다.
다음 evidence를 함께 받아야 한다.

```text
- harness summary
- green_base info
- review package
- smoke review
- product fitness report
- dashboard summary
- final_artifact/product 주요 파일 snippet
- runner command 및 run result
- viewer JS 핵심 함수 목록
- known limitations
- available user actions
- product loop evidence
- user-facing product quality evidence
- hard blocker result
```

### 15.2 프롬프트 누수 금지

```text
#47의 기대 stage/gap/lane을 Product Judge 프롬프트에 넣지 않는다.
기대값은 test assertion에서만 사용한다.
```

### 15.3 출력

```json
{
  "stage": "INTERACTION_CANDIDATE",
  "is_product_candidate": false,
  "confidence": "high",
  "evidence_refs": [
    "artifact_evidence.product_loop.can_execute_input=false",
    "phase2c2_editor_report.runner_backed_execution_included=false"
  ],
  "not_product_reasons": [
    {
      "reason": "Edited draft cannot yet be executed by runner/core.",
      "evidence_refs": [
        "artifact_evidence.product_loop.can_execute_input=false",
        "phase2c2_editor_report.runner_backed_execution_included=false"
      ]
    }
  ],
  "product_loop_evidence": {
    "can_create_input": true,
    "can_validate_input": true,
    "can_execute_input": false,
    "can_see_result_from_created_input": false,
    "can_understand_failure": false,
    "can_revise_and_rerun": false,
    "product_loop_closed": false
  },
  "user_facing_quality_evidence": {
    "first_screen_understandable": true,
    "clear_next_action": true,
    "has_example_or_seed_data": true,
    "success_feedback_visible": true,
    "failure_feedback_visible": false,
    "empty_screen_risk": false,
    "user_can_understand_value_in_60s": false
  },
  "hard_blockers_applied": [
    "runner-backed execution 없음 → PRODUCT_CANDIDATE 금지"
  ],
  "missing_loop_parts": [
    "runner_backed_execution",
    "result_from_edited_input",
    "revise_and_rerun"
  ]
}
```

---

## 16. Gemma Gap Classifier Desk

역할:

```text
제품 후보가 아닌 이유를 gap으로 분류하고 primary_gap을 하나 고른다.
```

출력:

```json
{
  "gaps": [
    {
      "type": "RUNNER_BACKED_EXECUTION_REQUIRED",
      "severity": "blocking",
      "evidence_refs": [
        "artifact_evidence.product_loop.can_execute_input=false",
        "product_stage_label.missing_loop_parts includes runner_backed_execution"
      ],
      "explanation": "The product loop stops at draft export."
    }
  ],
  "primary_gap": "RUNNER_BACKED_EXECUTION_REQUIRED",
  "primary_gap_evidence_refs": [
    "artifact_evidence.product_loop.can_execute_input=false",
    "phase2c2_editor_report.runner_backed_execution_included=false"
  ],
  "primary_gap_reason": "The user can create and export a draft, but cannot execute it."
}
```

---

## 17. Gemma Next Lane Planner Desk

역할:

```text
primary_gap을 해결할 다음 lane을 선택한다.
```

출력:

```json
{
  "recommended_next_lane": "RUNNER_BACKED_DRAFT_EXECUTION",
  "reason": "Edited draft cannot yet be executed by runner/core.",
  "evidence_refs": [
    "product_gap_classification.primary_gap=RUNNER_BACKED_EXECUTION_REQUIRED",
    "artifact_evidence.product_loop.can_execute_input=false"
  ],
  "lane_risk": "medium",
  "dry_run_allowed": true,
  "auto_execute_allowed": false,
  "requires_human_approval_before_apply": true,
  "allowed_file_scopes": [],
  "protected_file_scopes": [],
  "human_decision_required": false
}
```

---

## 18. Gemma Scoped Order Writer Desk

역할:

```text
선택된 lane에 맞는 다음 scoped repair order를 자동 생성한다.
```

출력:

```text
auto_order.md
auto_order.json
scope_guard.json
```

### 18.1 lane template 기반 생성

auto_order는 free-form 생성이 아니다.

```text
Gemma는 주문서 전체 구조를 새로 발명하지 않는다.
정해진 lane template의 빈칸을 evidence 기반으로 채운다.
```

구조:

```text
lane_template: RUNNER_BACKED_DRAFT_EXECUTION

Gemma filled slots:
- background
- observed_gap
- evidence_refs
- allowed_scopes
- protected_scopes
- forbidden_actions
- concrete_acceptance_tests
- expected_outputs
- stop_conditions
- report_format
```

### 18.2 auto_order 필수 내용

auto_order에는 반드시 다음이 있어야 한다.

```text
- 작업 배경
- 정확한 정의
- 하지 말 것
- 수정 가능 범위
- 보호 대상 hash guard
- dry-run
- apply
- 산출물
- smoke/gate
- validate
- 테스트 요구사항
- 완료 기준
- 작업 보고 형식
- PRODUCT_CANDIDATE 과대평가 방지 조건
- stop condition
```

### 18.3 auto_order 품질 검증

auto_order는 생성 후 검증해야 한다.

필수 검증:

```text
- lane과 title이 일치하는가
- primary_gap을 직접 해결하는가
- allowed scope가 lane과 일치하는가
- protected scope가 충분한가
- forbidden actions가 있는가
- dry-run/apply가 분리되어 있는가
- hash guard가 있는가
- smoke/gate/validate가 있는가
- stop condition이 있는가
- 작업 보고 형식이 있는가
- PRODUCT_CANDIDATE 과대평가 방지 조건이 있는가
- evidence_refs가 auto_order에 반영되어 있는가
```

품질 점수:

```text
auto_order_quality_score >= 0.85
```

미달 시:

```text
recommended_next_lane = HOLD_FOR_HUMAN
repair_execute = false
```

---

## 19. Gemma Repair Blueprint Writer Desk

Phase 2D-0에서 live #47 artifact에 실제 repair apply는 금지한다.
하지만 Gemma가 단순히 판단과 주문서 작성만 하게 해서는 안 된다.

따라서 live #47에 대해서는 다음 산출물을 추가 생성한다.

```text
repair_blueprint.json
expected_patch_plan.md
tests_to_run.json
rollback_or_failure_conditions.json
```

목적:

```text
Gemma가 “다음에 무엇을 고쳐야 하는가”뿐 아니라
“어떻게 고칠 것인가”까지 설계하게 한다.
```

단, 이 산출물은 적용하지 않는다.

```text
live #47에서는 repair apply 금지
코드/제품/runner/core/replay 실제 수정 금지
repair_blueprint는 Phase 2C-3 auto_order의 보조 자료로만 사용
```

필수 내용:

```text
- target lane
- observed gap
- evidence_refs
- proposed implementation approach
- expected changed file scopes
- protected file scopes
- expected patch shape
- tests_to_run
- rollback conditions
- failure conditions
- PRODUCT_CANDIDATE 과대평가 방지 조건
```

#47 기대 예시:

```json
{
  "target_lane": "RUNNER_BACKED_DRAFT_EXECUTION",
  "observed_gap": "Edited draft cannot yet be executed by runner/core.",
  "apply_allowed": false,
  "purpose": "Blueprint only for Phase 2C-3.",
  "expected_patch_shape": [
    "draft_to_runner_input_adapter",
    "runner execution command wiring",
    "result capture",
    "viewer result display",
    "edit_validate_execute_result_revise smoke"
  ]
}
```

---

## 20. Sequential Desk Mode와 Unified Decision Packet Mode

Phase 2D-0는 기본적으로 다음 sequential desk 흐름을 사용한다.

```text
Product Judge
→ Gap Classifier
→ Next Lane Planner
→ Scoped Order Writer
→ Repair Blueprint Writer
```

하지만 Gemma가 충분히 안정적으로 구조화 출력을 낼 수 있으므로, 다음 모드도 허용한다.

```text
unified_decision_packet mode
```

Unified mode는 Gemma가 한 번에 다음을 생성한다.

```text
product_stage_label
product_gap_classification
recommended_next_lane
repair_blueprint
auto_order_slots
scope_guard_draft
```

단, 검증 기준은 sequential mode와 동일하다.

```text
strict JSON schema validation
evidence_refs validation
hard blocker validation
lane risk policy validation
auto_order quality validation
scope_guard validation
```

중요:

```text
호출 방식은 유연하게 하되,
검증 기준은 절대 낮추지 않는다.
```

---

## 21. Productization Autopilot Loop CLI

신규 CLI를 추가한다.

권장 CLI:

```bash
python -m repo_idea_miner factory-product-loop \
  --run-dir runs/factory_20260709_072220 \
  --mode live \
  --max-iterations 1
```

기본값:

```text
max_iterations = 1
repair_execute = false
live_repair_apply = false
```

### 21.1 Loop 흐름

```text
1. run 상태 읽기
2. review/product artifacts 읽기
3. artifact evidence 추출
4. user-facing quality evidence 추출
5. hard blocker rules 적용
6. Gemma Product Judge 실행
7. strict JSON schema 검증
8. evidence_refs 검증
9. Gemma Gap Classifier 실행
10. strict JSON schema 검증
11. evidence_refs 검증
12. Gemma Next Lane Planner 실행
13. strict JSON schema 검증
14. lane risk policy 검증
15. Gemma Scoped Order Writer 실행
16. lane template 기반 auto_order 생성
17. auto_order quality validation 실행
18. Gemma Repair Blueprint Writer 실행
19. repair_blueprint/tests_to_run/rollback conditions 검증
20. product_loop_iteration_summary 생성
21. dashboard summary 생성
```

### 21.2 Live와 Mock 정책

Phase 2D-0에서 live로 반드시 할 것:

```text
#47에 대해 live Gemma judge/gap/lane/order/blueprint generation 1회 실행
```

Phase 2D-0에서 live로 하지 말 것:

```text
#47에 auto_order를 apply하지 않는다.
#47을 2C-3로 직접 구현하지 않는다.
```

Mock/safe fixture에서 허용:

```text
judge → order → scoped repair → smoke/validate → rejudge E2E 1회
```

이 mock/safe loop는 Autopilot이 단순 주문서 작성기가 아니라 루프 구조를 가진다는 것을 증명하기 위한 것이다.

---

## 22. Mock/Safe Loop Proof 요구사항

mock/safe loop는 가짜 성공이면 안 된다.
반드시 실제 파일 변경과 smoke/validate/rejudge를 포함한다.

필수 흐름:

```text
1. fixture artifact 생성
2. 제품성 결함 1개 주입
3. Gemma 또는 mock judge가 stage/gap/lane 선택
4. lane template 기반 auto_order 생성
5. generated auto_order와 scope_guard를 읽는다
6. generated order 기반으로 제한된 repair 적용
7. 실제 파일 변경 발생
8. smoke 실행
9. validate 실행
10. rejudge 실행
11. stage가 개선되거나, 개선 없음으로 정직하게 멈춤
```

허용되는 mock/safe lane:

```text
VIEWER_POLISH
INTERACTION_UI
UX_POLISH
```

금지:

```text
mock/safe loop에서 core/golden/contract/replay 의미 변경 금지
mock/safe loop 결과를 #47 live artifact에 적용 금지
generated auto_order와 무관한 hardcoded repair 실행 금지
scope_guard를 읽지 않는 repair 실행 금지
lane_template을 무시한 repair 실행 금지
smoke/validate 없이 rejudge만 수행 금지
```

검증 산출물:

```text
mock_loop_order_following_report.json
```

필수 필드:

```json
{
  "auto_order_read": true,
  "scope_guard_read": true,
  "repair_followed_order": true,
  "changed_files_within_allowed_scope": true,
  "protected_files_unchanged": true,
  "smoke_ran": true,
  "validate_ran": true,
  "rejudge_ran": true,
  "stage_improved_or_honest_stop": true
}
```

---

## 23. Live Gemma 실패 처리

Phase 2D-0는 live Gemma judge/order/blueprint generation이 핵심이다.
mock test가 통과해도 live #47 판단이 실패하면 Phase 2D-0 완료가 아니다.

실패 분류:

```text
AUTOPILOT_INFRA_FAIL
AUTOPILOT_INVALID_OUTPUT
AUTOPILOT_EVIDENCE_INSUFFICIENT
AUTOPILOT_HOLD_FOR_HUMAN
```

처리 규칙:

```text
API 오류 / timeout / model unavailable
→ AUTOPILOT_INFRA_FAIL

JSON parse 실패 / schema 검증 실패 / enum 외 값
→ AUTOPILOT_INVALID_OUTPUT

evidence_refs 부족 / artifact evidence 부족
→ AUTOPILOT_EVIDENCE_INSUFFICIENT

판단 불확실 / lane 선택 불가능 / 품질 점수 미달
→ AUTOPILOT_HOLD_FOR_HUMAN
```

완료 조건:

```text
live Gemma #47 judge/gap/lane/order/blueprint generation PASS가 아니면 Phase 2D-0 완료 아님.
```

---

## 24. Loop Stop Conditions

필수 정지 조건:

```text
PRODUCT_CANDIDATE 도달
ARCHIVE 판정
same primary_gap 2회 반복
product fitness score 개선 없음
protected file scope 위험
scope creep 감지
max_iterations 도달
human_decision_required = true
auto_order_quality_score < 0.85
lane policy상 auto_execute_allowed = false
strict JSON schema 검증 실패
evidence_refs 검증 실패
live Gemma failure
repair_blueprint가 protected scope 수정을 제안
mock_loop_order_following_report 실패
```

Phase 2D-0에서는 `max_iterations=1`이 기본이다.

---

## 25. #47 Acceptance Test

Phase 2D-0의 핵심 acceptance test는 #47이다.

입력:

```text
runs/factory_20260709_072220
```

현재 사실:

```text
REVIEW_READY
green_base true
Phase 2C-2 draft editor candidate
runner-backed execution not included
edited draft cannot be executed by runner
```

중요:

```text
아래 기대값은 test assertion에만 둔다.
Gemma 프롬프트에는 제공하지 않는다.
```

기대 출력:

```json
{
  "prior_fitness_label": "PRODUCT_CANDIDATE",
  "prior_fitness_qualifier": "draft_editor_candidate",
  "autopilot_stage": "INTERACTION_CANDIDATE",
  "autopilot_is_product_candidate": false,
  "primary_gap": "RUNNER_BACKED_EXECUTION_REQUIRED",
  "recommended_next_lane": "RUNNER_BACKED_DRAFT_EXECUTION",
  "next_order_title": "RIM Product Factory Phase 2C-3 Runner-backed Draft Execution"
}
```

auto_order는 다음 내용을 포함해야 한다.

```text
Phase 2C-3 Runner-backed Draft Execution
- draft JSON을 runner input으로 변환
- runner 실행
- result capture
- viewer에 result 표시
- edit → validate → execute → result → revise loop 검증
```

repair_blueprint는 다음을 포함해야 한다.

```text
- draft_to_runner_input_adapter
- runner execution command wiring
- result capture
- viewer result display
- edit_validate_execute_result_revise smoke
- apply_allowed=false
```

---

## 26. Fixture Acceptance Tests

#47 하나만으로는 과적합 위험이 있다.
따라서 stage별 fixture를 추가한다.

필수 fixture:

```text
1. viewer만 있고 조작 UI 없음
   → POLISHABLE_PROTOTYPE 또는 REVIEWABLE_ARTIFACT

2. 조작 UI는 있지만 실행 없음
   → INTERACTION_CANDIDATE

3. 실행은 되지만 재수정/재실행 루프 없음
   → EXECUTION_CANDIDATE

4. 생성/편집/검증/실행/결과/수정/재실행 루프 있음
   → PRODUCT_CANDIDATE

5. green이지만 제품 가치 낮음
   → ARCHIVE

6. evidence 부족
   → EVIDENCE_INSUFFICIENT 또는 HOLD_FOR_HUMAN

7. #47과 다른 ID/title을 가진 동일 evidence fixture
   → #47과 동일 stage/gap/lane
```

각 fixture는 hard blocker와 Gemma judge 결과가 일치해야 한다.

---

## 27. Product Candidate 엄격 조건

Phase 2D-0 이후 `PRODUCT_CANDIDATE`는 다음 조건을 모두 만족해야 한다.

```text
1. 사용자가 입력을 만들 수 있음
2. 입력을 검증할 수 있음
3. 입력을 실제 runner/core로 실행할 수 있음
4. 실행 결과를 볼 수 있음
5. 실패 원인을 이해할 수 있음
6. 수정 후 다시 실행할 수 있음
7. 60초 안에 제품 가치가 이해됨
8. first screen이 이해 가능함
9. 다음 행동이 명확함
10. 성공/실패 피드백이 보임
11. no critical red flags
12. hard blockers 없음
```

하나라도 빠지면 `PRODUCT_CANDIDATE` 금지다.

#47 현재 상태는 `PRODUCT_CANDIDATE`가 아니어야 한다.

---

## 28. 산출물 요구사항

권장 저장 위치:

```text
runs/factory_20260709_072220/review/phase2d0/
```

필수 산출물:

```text
artifact_evidence.json
user_facing_quality_evidence.json
hard_blocker_result.json
product_stage_label.json
product_stage_label.md
product_gap_classification.json
product_gap_classification.md
recommended_next_lane.json
recommended_next_lane.md
auto_order.md
auto_order.json
auto_order_quality_report.json
scope_guard.json
repair_blueprint.json
expected_patch_plan.md
tests_to_run.json
rollback_or_failure_conditions.json
product_loop_iteration_summary.json
product_loop_iteration_summary.md
product_loop_dashboard_summary.json
mock_loop_order_following_report.json
```

필수 schema 파일 또는 schema 정의 위치:

```text
product_stage_label.schema.json
product_gap_classification.schema.json
recommended_next_lane.schema.json
auto_order.schema.json
scope_guard.schema.json
auto_order_quality_report.schema.json
repair_blueprint.schema.json
tests_to_run.schema.json
```

조건부 산출물:

```text
schema_repair_report.json
- schema_repair_pass가 실행된 경우 필수
```

선택 산출물:

```text
judge_prompt_trace.json
order_writer_prompt_trace.json
```

주의:

```text
prompt trace에는 API key, secret, env 값이 절대 들어가면 안 된다.
```

---

## 29. Dashboard 요구사항

Dashboard 대개편은 하지 않는다.

목록 카드에 추가:

```text
prior fitness label
autopilot stage
next lane
autopilot status
auto_order status
repair blueprint status
```

예시:

```text
prior fitness: PRODUCT_CANDIDATE / draft_editor_candidate
autopilot stage: INTERACTION_CANDIDATE
next lane: RUNNER_BACKED_DRAFT_EXECUTION
autopilot: auto_order generated
auto_order quality: PASS
repair blueprint: generated / apply_allowed=false
```

상세 페이지 표시:

```text
Artifact Evidence
User-Facing Quality Evidence
Hard Blockers
Product Judge
Gap Classification
Next Lane
Auto Order
Auto Order Quality
Scope Guard
Repair Blueprint
Mock Loop Order Following
Loop Summary
```

---

## 30. Validate 요구사항

`factory-validate`는 Phase 2D-0 marker가 있는 run에만 Phase 2D-0 산출물을 필수 요구한다.

Phase 2D-0 marker:

```text
product_loop_dashboard_summary.json 존재
또는 product_stage_label.json 존재
또는 auto_order.json 존재
```

기존 Phase 2A / 2B / 2C run은 기존 validate 경로 유지.

### 30.1 검증 항목

```text
artifact_evidence 존재
user_facing_quality_evidence 존재
hard_blocker_result 존재
product_stage_label 존재
product_gap_classification 존재
recommended_next_lane 존재
auto_order 존재
auto_order_quality_report 존재
scope_guard 존재
repair_blueprint 존재
expected_patch_plan 존재
tests_to_run 존재
rollback_or_failure_conditions 존재
product_loop_iteration_summary 존재
product_loop_dashboard_summary 존재
strict JSON schema 검증 PASS
evidence_refs 검증 PASS
stage / gap / lane 정합성
hard blocker와 stage 정합성
prior_fitness_label과 autopilot_stage 분리 기록
auto_order와 lane 정합성
scope_guard와 auto_order 정합성
repair_blueprint와 lane 정합성
PRODUCT_CANDIDATE 엄격 조건 위반 없음
```

조건부 검증:

```text
schema_repair_pass 실행됨
→ schema_repair_report 존재 필수

mock/safe loop 실행됨
→ mock_loop_order_following_report 존재 필수
```

### 30.2 중요 규칙

```text
runner-backed execution 없음 + autopilot_stage=PRODUCT_CANDIDATE
→ validate FAIL

hard blocker 존재 + autopilot_stage=PRODUCT_CANDIDATE
→ validate FAIL

prior_fitness_label=PRODUCT_CANDIDATE/draft_editor_candidate는 허용
단 autopilot_stage=PRODUCT_CANDIDATE이면 hard blocker 없어야 함

stage=INTERACTION_CANDIDATE인데 실행 루프가 닫혔다고 표시
→ validate FAIL

recommended_next_lane과 primary_gap 불일치
→ validate FAIL

auto_order가 recommended_next_lane과 불일치
→ validate FAIL

auto_order_quality_score < 0.85
→ validate FAIL 또는 HOLD_FOR_HUMAN

auto_order에 금지 범위가 누락됨
→ validate FAIL

scope_guard가 비어 있음
→ validate FAIL

evidence_refs 누락
→ validate FAIL

schema 검증 실패
→ validate FAIL

challenge_id/title 기반 hardcode 감지
→ validate FAIL

repair_blueprint.apply_allowed=true on live #47
→ validate FAIL

expected_patch_plan이 protected scope 수정을 제안
→ validate FAIL

mock_loop_order_following_report.repair_followed_order=false
→ validate FAIL

user_facing_quality_evidence.user_can_understand_value_in_60s=false
+ autopilot_stage=PRODUCT_CANDIDATE
→ validate FAIL
```

---

## 31. 테스트 요구사항

최소 테스트:

```text
1. factory-product-loop dry-run 동작
2. max_iterations 기본값 1
3. live repair apply 기본 false
4. Phase 2D-0에서 #47 repair apply 금지
5. artifact_evidence 추출
6. user_facing_quality_evidence 추출
7. hard blocker rules 적용
8. runner-backed execution 없음 → PRODUCT_CANDIDATE 차단
9. prior_fitness_label과 autopilot_stage 분리
10. #47 input을 INTERACTION_CANDIDATE로 판정
11. #47을 PRODUCT_CANDIDATE로 판정하지 않음
12. #47 primary_gap = RUNNER_BACKED_EXECUTION_REQUIRED
13. #47 next_lane = RUNNER_BACKED_DRAFT_EXECUTION
14. #47 auto_order title = Phase 2C-3 Runner-backed Draft Execution
15. #47 기대값은 프롬프트가 아니라 test assertion에만 존재
16. strict JSON schema 검증
17. schema parse fail → schema_repair_pass 1회
18. schema_repair_pass는 의미 변경 금지
19. schema repair 후에도 실패하면 AUTOPILOT_INVALID_OUTPUT
20. required field missing → AUTOPILOT_INVALID_OUTPUT
21. enum 외 값 → AUTOPILOT_INVALID_OUTPUT
22. evidence_refs 없는 판단 차단
23. primary_gap evidence_refs 2개 미만 차단
24. auto_order.md 생성
25. auto_order.json 생성
26. scope_guard.json 생성
27. auto_order_quality_report 생성
28. auto_order_quality_score >= 0.85
29. repair_blueprint.json 생성
30. expected_patch_plan.md 생성
31. tests_to_run.json 생성
32. rollback_or_failure_conditions.json 생성
33. repair_blueprint.apply_allowed=false on live #47
34. expected_patch_plan이 protected scope 수정을 제안하면 validate FAIL
35. stage/gap/lane 정합성 검사
36. lane risk policy 검사
37. lane auto_execute_allowed 검사
38. PRODUCT_CANDIDATE 엄격 조건 검사
39. CORE_GREEN fixture
40. REVIEWABLE/POLISHABLE fixture
41. INTERACTION_CANDIDATE fixture
42. EXECUTION_CANDIDATE fixture
43. PRODUCT_CANDIDATE fixture
44. ARCHIVE fixture
45. EVIDENCE_INSUFFICIENT fixture
46. same primary_gap 2회 반복 stop condition
47. max_iterations stop condition
48. human_decision_required stop condition
49. auto_order_quality_score 미달 stop condition
50. live Gemma invalid output 실패 분류
51. live Gemma infra fail 실패 분류
52. auto_order에 하지 말 것 포함
53. auto_order에 보호 대상 hash guard 포함
54. auto_order에 validate/test/report 형식 포함
55. auto_order가 lane template 기반인지 검사
56. recommended_next_lane과 auto_order 일치
57. challenge_id == 47 hardcode 금지
58. title contains Mini-Comfy hardcode 금지
59. #47과 다른 ID/title을 가진 동일 evidence fixture에서 같은 stage/gap/lane
60. unified_decision_packet mode schema 검증
61. sequential mode와 unified mode validator 공유
62. mock/safe fixture에서 judge → order → repair → smoke/validate → rejudge E2E 1회
63. mock/safe loop가 auto_order를 실제로 읽음
64. mock/safe loop가 scope_guard를 실제로 읽음
65. mock/safe repair가 allowed scope 안에서만 변경
66. mock/safe repair가 protected scope를 변경하지 않음
67. mock/safe loop에서 실제 파일 변경 발생
68. mock/safe loop에서 smoke/validate 실행
69. mock_loop_order_following_report 생성
70. user_facing_quality_evidence 생성
71. first_screen_understandable=false + PRODUCT_CANDIDATE 차단
72. clear_next_action=false + PRODUCT_CANDIDATE 차단
73. has_example_or_seed_data=false + PRODUCT_CANDIDATE 차단 또는 UX_POLISH_REQUIRED
74. failure_feedback_visible=false + PRODUCT_CANDIDATE 차단
75. user_can_understand_value_in_60s=false + PRODUCT_CANDIDATE 차단
76. live Gemma judge/order/blueprint generation #47 1회
77. live repair apply는 실행하지 않음
78. live Gemma #47 실패 시 Phase 2D-0 완료 처리 금지
79. Phase 2D-0 marker validate
80. 기존 Phase 2C-2 validate 유지
81. 기존 Phase 2C-1 validate 유지
82. 기존 Phase 2C-0 validate 유지
83. 기존 Phase 2B validate 유지
84. 기존 Challenge Mode 유지
85. 전체 테스트 통과
86. secret scan 통과
```

---

## 32. 완료 기준

완료 기준:

```text
1. Product Judge Desk가 추가된다.
2. Gap Classifier Desk가 추가된다.
3. Next Lane Planner Desk가 추가된다.
4. Scoped Order Writer Desk가 추가된다.
5. Repair Blueprint Writer Desk가 추가된다.
6. strict JSON schema validation이 추가된다.
7. schema_repair_pass 1회 규칙이 추가된다.
8. evidence_refs validation이 추가된다.
9. hard blocker rules가 코드로 추가된다.
10. artifact evidence extractor가 추가된다.
11. user-facing quality evidence extractor가 추가된다.
12. lane risk policy가 추가된다.
13. lane template 기반 auto_order generator가 추가된다.
14. auto_order quality validator가 추가된다.
15. sequential mode와 unified_decision_packet mode를 지원하거나, 최소한 validator가 unified output을 받을 준비를 한다.
16. factory-product-loop CLI가 추가된다.
17. #47의 prior_fitness_label과 autopilot_stage를 분리 기록한다.
18. #47을 INTERACTION_CANDIDATE로 판정한다.
19. #47을 PRODUCT_CANDIDATE로 오판하지 않는다.
20. #47 primary_gap을 RUNNER_BACKED_EXECUTION_REQUIRED로 판정한다.
21. #47 next_lane을 RUNNER_BACKED_DRAFT_EXECUTION으로 고른다.
22. #47에 대한 Phase 2C-3 auto_order.md를 생성한다.
23. #47에 대한 repair_blueprint / expected_patch_plan / tests_to_run / rollback conditions를 생성한다.
24. live #47에서는 repair apply를 하지 않는다.
25. auto_order에 scope guard와 금지 범위가 포함된다.
26. mock/safe fixture에서 judge → order → repair → smoke/validate → rejudge 루프 1회를 검증한다.
27. mock/safe loop가 generated auto_order와 scope_guard를 실제로 따른다.
28. live Gemma #47 judgment/order/blueprint generation이 PASS한다.
29. Phase 2D-0 validate가 동작한다.
30. Dashboard에 prior fitness / autopilot stage / next lane / autopilot status / auto_order status / repair blueprint status가 표시된다.
31. 기존 Phase 2A / 2B / 2C 기능이 깨지지 않는다.
```

---

## 33. 작업 보고 형식

완료 후 아래 형식으로 보고한다.

```text
RIM Product Factory Phase 2D-0 Gemma Productization Autopilot 작업 보고

Base 상태
- 시작 HEAD:
- 종료 HEAD:
- origin ahead/behind:
- push 여부:

수정 파일
-

대상
- run_dir:
- challenge_id:
- current verdict:
- green_base:
- prior_fitness_label:
- prior_fitness_qualifier:
- autopilot_stage:

Artifact Evidence
- can_create_input:
- can_validate_input:
- can_execute_input:
- can_see_result_from_created_input:
- can_understand_failure:
- can_revise_and_rerun:
- product_loop_closed:
- evidence_refs:

User-Facing Quality
- first_screen_understandable:
- clear_next_action:
- has_example_or_seed_data:
- success_feedback_visible:
- failure_feedback_visible:
- empty_screen_risk:
- user_can_understand_value_in_60s:

Hard Blockers
- blockers:
- applied:
- PRODUCT_CANDIDATE blocked:

Product Judge
- stage:
- is_product_candidate:
- confidence:
- evidence_refs:
- not_product_reasons:
- missing_loop_parts:
- schema validation:

Gap Classification
- gaps:
- primary_gap:
- severity:
- evidence_refs:
- schema validation:

Next Lane
- recommended_next_lane:
- reason:
- evidence_refs:
- lane_risk:
- dry_run_allowed:
- auto_execute_allowed:
- requires_human_approval_before_apply:
- allowed scopes:
- protected scopes:
- schema validation:

Auto Order
- auto_order.md:
- auto_order.json:
- scope_guard.json:
- lane_template:
- title:
- lane:
- auto_order_quality_score:
- order validation:

Repair Blueprint
- repair_blueprint:
- expected_patch_plan:
- tests_to_run:
- rollback_or_failure_conditions:
- apply_allowed:
- protected scope proposal:

Gemma Mode
- sequential mode:
- unified_decision_packet mode:
- selected mode:
- shared validator:

Schema Repair
- schema_repair_pass used:
- schema_repair_report:
- meaning changed:
- final schema validation:

Hardcode Guard
- challenge_id/title hardcode check:
- synthetic same-evidence fixture:
- result:

Minimal Loop Proof
- mock/safe fixture:
- judge:
- order:
- repair:
- actual file changed:
- smoke:
- validate:
- rejudge:
- result:

Mock Loop Order Following
- auto_order read:
- scope_guard read:
- repair followed order:
- actual file changed:
- protected files unchanged:
- smoke/validate/rejudge:
- report:

Live Run Policy
- #47 live judge/order/blueprint generation:
- #47 live repair apply:
- live failure type:
- stop condition:

Dashboard
- card:
- detail:
- tabs:

Validate
- Phase 2D-0 marker:
- schema validation:
- evidence_refs validation:
- hard blocker consistency:
- stage/gap/lane consistency:
- auto_order consistency:
- repair_blueprint consistency:
- factory-validate:

테스트
- pytest:
- secret scan:

판정
- Phase 2D-0 완료 여부:
- #47 판정이 근거 기반으로 사람 판단과 일치하는지:
- 다음 추천:
```

---

## 34. Phase 2D-0 성공의 의미

Phase 2D-0 성공은 #47을 제품으로 완성하는 것이 아니다.

성공은 다음이다.

```text
Gemma가 #47을 보고
“아직 제품이 아니다.
현재는 INTERACTION_CANDIDATE다.
부족한 핵심은 RUNNER_BACKED_EXECUTION이다.
다음 lane은 RUNNER_BACKED_DRAFT_EXECUTION이다.
다음 주문서는 Phase 2C-3 Runner-backed Draft Execution이다.”
라고 evidence 기반 JSON으로 판단하는 것.
```

그리고 여기서 끝나면 부족하다.
Gemma는 live #47에 대해 다음까지 설계해야 한다.

```text
repair_blueprint
expected_patch_plan
tests_to_run
rollback_or_failure_conditions
```

단, live #47에는 apply하지 않는다.

또한 mock/safe fixture에서는 실제로 다음 루프를 검증해야 한다.

```text
judge → order → repair → smoke/validate → rejudge
```

즉 Phase 2D-0는 사람이 하던 제품성 판단과 주문서 생성 루프를 Gemma에게 넘기는 첫 단계다.

---

## 35. 최종 정의

> RIM Product Factory Phase 2D-0는 green artifact를 제품 후보로 끌어올리기 위한 Gemma Productization Autopilot의 첫 단계다.
> 이 단계는 제품을 직접 완성하는 것이 아니라, Gemma가 artifact의 현재 제품성 stage를 strict JSON schema와 evidence_refs 기반으로 판단하고, 제품 느낌이 부족한 primary gap을 분류하고, 다음 productization lane을 선택하고, lane template 기반 scoped auto_order를 생성하게 만든다.
> 또한 live #47에는 apply하지 않지만, repair_blueprint, expected_patch_plan, tests_to_run, rollback_or_failure_conditions까지 생성하게 하여 Gemma를 단순 주문서 작성기가 아니라 제품화 엔지니어로 사용한다.
> Phase 2D-0는 mock/safe fixture에서 judge → order → repair → smoke/validate → rejudge 최소 루프를 1회 검증해, Productization Autopilot이 실제 루프 구조를 갖췄음을 증명한다.
