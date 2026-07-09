# RIM Product Factory Phase 1.6 외주 주문서

## Core-first Review-Repair Harness

### — Phase 2 성장 루프에 넣을 첫 시제품의 바닥선 만들기

## 0. 작업 배경

현재 RIM Product Factory는 Challenge를 받아 멀티파일 workspace를 생성하고, 기본적인 구조/문법/실행 검사를 수행한다.

하지만 현재 결과물에는 다음 문제가 있다.

```text id="aoe4r5"
- 파일은 여러 개 생성된다.
- manifest/contract/report도 생성된다.
- 기본 실행도 되는 경우가 있다.
- 하지만 산출물이 얕다.
- 핵심 시스템보다 UI 껍데기나 샘플 앱에 가깝다.
- “제품화 후보”로 찍힌 결과도 실제 실행해보면 실망스러운 경우가 있다.
```

이번 Phase 1.6의 목적은 단순 평가 기준 보정이 아니다.

이번 작업의 목적은 Product Factory의 첫 시제품 생성 기준을 바꾸는 것이다.

기존 목표:

```text id="ov6lk8"
파일을 만들어라
문법을 통과해라
기본 실행되게 해라
보고서를 만들어라
```

새 목표:

```text id="vq56xf"
검증 가능한 core system을 먼저 만들고,
그 core를 실행·검증·조작·확인할 수 있는 첫 시제품을 만든다.
```

---

# 1. Phase 1.6의 정확한 정의

Phase 1.6은 최종 제품을 완성하는 단계가 아니다.

Phase 1.6은 **Phase 2 성장 루프에 넣어도 되는 첫 시제품의 바닥선을 만드는 단계**다.

```text id="md2a1l"
Phase 1.6 = 첫 시제품의 최소 합격선 재정의
Phase 2 = 그 시제품을 patch/delta/fixture/golden으로 계속 키우는 성장 루프
```

첫 시제품의 바닥선은 단순 실행이 아니다.

첫 시제품은 최소한 다음을 가져야 한다.

```text id="dt5gy7"
1. 검증 가능한 core system
2. core를 실행할 runner
3. scenario / fixture
4. golden expected output 또는 검증 가능한 oracle
5. replay / diff / validator
6. hardcode/stub 차단
7. core를 조작하거나 확인할 수 있는 product layer
8. Phase 2에서 이어받을 green base
```

중요:

```text id="ji1j7j"
검증 가능한 core system은 최종 한계가 아니라 시작점이다.
첫 시제품은 core에서 끝나면 안 된다.
core를 기반으로 사용자가 실행·조작·확인할 수 있는 product layer까지 포함해야 한다.
```

---

# 2. 핵심 원칙

## 2.1 Core-first

UI나 viewer부터 만들지 않는다.

금지:

```text id="jko1ve"
index.html 먼저 만들기
버튼/카드/목록부터 만들기
viewer 안에 핵심 로직을 묻기
샘플 데이터와 UI만 그럴듯하게 만들기
문법/실행 통과만 목표로 하기
```

올바른 순서:

```text id="b6lni3"
core model
→ state/action contract
→ runner
→ scenario/fixture
→ golden/replay
→ gate 검증
→ product layer
```

---

## 2.2 Review-Repair 중심

이번 작업은 후보 여러 개를 만들어 경쟁시키는 하네스가 아니다.

기본 흐름:

```text id="4wrb4i"
Draft
→ Review
→ Repair
→ Verify
→ Green Base
```

즉:

```text id="4m4krc"
하나의 기준 후보를 만들고,
리뷰와 게이트 실패를 바탕으로 제한된 수정 루프를 돌려,
Phase 2에 넣을 수 있는 첫 시제품 바닥선까지 끌어올린다.
```

---

## 2.3 Product Layer는 필수

Product Layer는 선택사항이 아니다.

Phase 1.6의 green base는 core-only artifact가 아니다.

```text id="ryz6fc"
green base =
검증된 core system
+
그 core를 사람이 실행·조작·확인할 수 있는 최소 product layer
```

단:

```text id="c59p60"
Product Layer는 core logic을 복제하거나 대체하면 안 된다.
Product Layer는 core runner output, state snapshot, replay result를 호출하거나 표시해야 한다.
```

---

## 2.4 후보 경쟁은 기본이 아니다

Phase 1.6에서는 경쟁 후보 생성이 핵심 요구가 아니다.

정책:

```text id="dtiypl"
live 기본 candidates = 1
mock candidates = 1~2 허용 가능
--candidates 옵션은 기존 호환 또는 실험 옵션으로만 둔다
Phase 1.6 성공 여부는 candidates 기능으로 판단하지 않는다
```

---

## 2.5 Desk와 Key의 개념 분리

```text id="tgmjy7"
Desk = 작업 단계 / 역할
Key = 회전 worker capacity
```

11개 키를 11명의 고정 역할로 배정하지 않는다.

Phase 1.6에서는 키를 후보 경쟁보다 Review-Repair 흐름에 사용한다.

예:

```text id="jnmr8q"
Core Spec Draft: key 1개
Core Spec Review: 다른 key 1개
Core Spec Repair: 필요 시 다른 key 1개

Core Build: key 1개
Build Review: 다른 key 1개
Patch Repair: 필요 시 다른 key 1개
```

---

# 3. 이번 작업에서 하지 말 것

금지:

```text id="xowk4b"
- 새 대시보드 서버 만들기
- Product Factory 전체 재작성
- 기존 Challenge Mode 삭제
- 기존 Product Dashboard 파괴
- 단순 UI 개선 작업으로 축소
- 단순 “작은 앱 경험” 중심으로 축소
- 후보 경쟁 시스템을 핵심으로 구현
- Codex/Claude 자동 호출 추가
- viewer-only 결과물을 제품화 후보로 올리기
- runner/golden 없이 제품화 후보 판정하기
- Patch Repair를 Phase 2 수준의 기능 확장 루프로 키우기
```

---

# 4. 실제 구현 단위: 7개 Stage

Desk를 지나치게 잘게 나누면 문서와 JSON만 늘어날 위험이 있다.

따라서 실제 구현은 다음 7개 Stage 중심으로 한다.

```text id="sfs5es"
1. Core Spec Stage
2. Scenario Oracle Stage
3. Core Build Stage
4. Core Verification Stage
5. Repair Stage
6. Product Layer Stage
7. Verdict / Dashboard / Green Base Stage
```

각 Stage 안에서 필요한 Draft / Review / Repair를 수행한다.

---

# 5. Stage 1 — Core Spec Stage

## 5.1 역할

Challenge를 표준화하고, 어떤 core artifact를 만들지 정한 뒤, core contract를 작성하고 리뷰/수정한다.

---

## 5.2 포함 작업

```text id="ttf9p9"
Challenge Normalizer
Core Artifact Classifier
Core Contract Draft
Core Contract Review
Core Contract Repair
```

---

## 5.3 입력

```text id="r3tmt1"
challenge_card.md/json
implementation_prompt.md
owner_brief.md
screen_story.md if available
```

---

## 5.4 출력

```text id="x24sk2"
normalized_challenge.json
challenge_constraints.json
core_artifact_classification.json
core_contract.json
state_contract.json
action_contract.json
runner_contract.json
core_contract_review.json
core_contract_repair_report.md if repaired
```

---

## 5.5 normalized_challenge.json 필수 필드

```json id="iho3q3"
{
  "challenge_id": "",
  "title": "",
  "core_problem": "",
  "expected_artifact": "",
  "difficulty_anchors": [],
  "forbidden_simplifications": [],
  "success_conditions": [],
  "unknowns": [],
  "owner_clarity": 0
}
```

---

## 5.6 Artifact Class

바로 `static_web`, `python_cli`, `node_cli`로 보내면 안 된다.

먼저 core artifact class를 정한다.

```text id="j525s9"
RULE_ENGINE
SIMULATION_ENGINE
WORKFLOW_ENGINE
DATA_TRANSFORM_ENGINE
PLANNER_EVALUATOR
INTERACTIVE_TOOL
VIEWER_ONLY
```

`VIEWER_ONLY`는 최후의 선택이다.

정책:

```text id="v865lj"
VIEWER_ONLY로 분류된 Challenge는 Product Factory Build 대상에서 낮은 우선순위로 둔다.
VIEWER_ONLY라도 최소한 데이터 모델, interaction state, replayable input/output을 만들 수 있는지 재검토한다.
```

---

## 5.7 core_artifact_classification.json 예시

```json id="7yofsk"
{
  "artifact_class": "RULE_ENGINE",
  "reason": "The challenge requires deterministic state transitions and action outcomes.",
  "core_first": true,
  "runner_required": true,
  "golden_required": true,
  "product_layer_required": true
}
```

---

## 5.8 core_contract.json 필수 구조

```json id="s27xv7"
{
  "artifact_class": "RULE_ENGINE",
  "core_goal": "",
  "state_entities": [
    {
      "name": "",
      "fields": [],
      "invariants": []
    }
  ],
  "actions": [
    {
      "name": "",
      "input": [],
      "preconditions": [],
      "state_change": [],
      "output": []
    }
  ],
  "determinism": {
    "random_allowed": false,
    "seed_required": true
  },
  "forbidden_shortcuts": [
    "hardcoded output",
    "static UI only",
    "random behavior without seed",
    "no state transition",
    "scenario-id specific branching"
  ]
}
```

---

## 5.9 runner_contract.json 필수 구조

```json id="smp2ye"
{
  "runner_command": "node src/runner.js --scenario fixtures/scenario_001.json",
  "input_format": "scenario_json",
  "output_format": "json",
  "required_output_fields": [
    "ok",
    "final_state",
    "events",
    "summary",
    "errors"
  ]
}
```

---

## 5.10 Core Contract Review 기준

Review는 “좋아 보인다”가 아니라 계약 기반으로 한다.

검토 항목:

```text id="d0cq5d"
- Challenge의 핵심 난점을 보존했는가
- forbidden_simplifications를 차단하는가
- state/action 구조가 검증 가능한가
- runner로 실행 가능한가
- scenario/golden으로 검증 가능한가
- Phase 2에서 확장 가능한가
- UI 없이도 core가 독립적으로 검증 가능한가
```

Review 결과:

```json id="ha990x"
{
  "status": "PASS | NEEDS_REPAIR | FAIL",
  "blocking_issues": [],
  "repair_instructions": [],
  "risk_level": "low | medium | high"
}
```

Repair 제한:

```text id="4ybc3s"
max_core_contract_repair_attempts = 1
```

Repair 후 다시 Review한다.
두 번째 Review에서도 실패하면 Build로 넘기지 않는다.

상태:

```text id="9v8trs"
NEEDS_SPEC_REPAIR
```

---

# 6. Stage 2 — Scenario Oracle Stage

## 6.1 역할

Scenario fixture와 Golden expected를 만든다.

Scenario와 Golden은 서로 정합성이 중요하므로 Phase 1.6에서는 별도 후보 경쟁을 하지 않는다.

하나의 Stage에서 함께 만들고, 함께 리뷰/수정한다.

---

## 6.2 포함 작업

```text id="6g8d7u"
Scenario / Golden Draft
Scenario / Golden Review
Scenario / Golden Repair
Oracle Risk Assessment
```

---

## 6.3 출력

```text id="0akckg"
fixtures/scenario_001.json
fixtures/scenario_002.json
fixtures/scenario_003.json
golden/expected_001.json
golden/expected_002.json
golden/expected_003.json
oracle_risk_report.json
scenario_golden_review.json
scenario_golden_repair_report.md if repaired
```

---

## 6.4 최소 조건

```text id="il9w6l"
정상 케이스 1개 이상
경계 케이스 1개 이상
실패/무효 케이스 1개 이상
```

---

## 6.5 scenario 구조

```json id="ygb3sh"
{
  "id": "scenario_001",
  "title": "",
  "initial_state": {},
  "actions": [
    {
      "type": "",
      "payload": {}
    }
  ],
  "expected_behavior": [
    ""
  ],
  "must_check": [
    ""
  ]
}
```

---

## 6.6 expected 구조

```json id="97o4mq"
{
  "scenario_id": "scenario_001",
  "expected_final_state": {},
  "expected_events": [],
  "expected_summary": "",
  "comparison_mode": "exact | partial | invariant | review"
}
```

---

## 6.7 Golden 강도 정책

Golden은 항상 위험을 가진다.
모델이 만든 Golden을 절대 무조건 정답으로 취급하면 안 된다.

comparison mode 정책:

```text id="q2oopv"
comparison_mode = exact
- 강한 자동 gate로 사용 가능

comparison_mode = partial
- 부분 비교 gate로 사용 가능

comparison_mode = invariant
- 구조/불변조건 검증으로 사용 가능

comparison_mode = review
- 자동 제품화 판정 근거로 사용 금지
- Golden Output Gate PASS 근거로 사용 금지
- 참고 근거로만 사용
```

추가 판정 정책:

```text id="p208x7"
exact golden이 1개도 없으면 PROMOTE_TO_CODEX 금지
invariant/review 위주면 REVIEW_READY까지만 가능
oracle_risk_level이 medium 이상이면 product_verdict와 dashboard_summary에 표시
oracle_risk_level이 high이면 PROMOTE_TO_CODEX 금지
```

---

## 6.8 oracle_risk_report.json

```json id="7bmpvt"
{
  "golden_source": "model_generated | deterministic_oracle | human_seeded",
  "risk_level": "low | medium | high",
  "risk_reasons": [],
  "safe_for_auto_gate": true,
  "requires_human_review": false
}
```

---

## 6.9 Scenario / Golden Review 기준

검토 항목:

```text id="h3hhyx"
- happy path만 있지 않은가
- 경계 케이스가 있는가
- 실패/무효 케이스가 있는가
- Golden expected가 너무 모델 편의적이지 않은가
- comparison_mode가 적절한가
- forbidden_simplifications를 잡을 수 있는가
- 자동 gate로 사용 가능한가
```

Review 결과:

```json id="n39cic"
{
  "status": "PASS | NEEDS_REPAIR | FAIL",
  "blocking_issues": [],
  "repair_instructions": [],
  "golden_strength": "strong | medium | weak",
  "safe_for_auto_gate": true
}
```

Repair 제한:

```text id="7tal70"
max_scenario_golden_repair_attempts = 1
```

두 번째 Review에서도 실패하면 Build로 넘기지 않는다.

상태:

```text id="ndz6oh"
NEEDS_SPEC_REPAIR
```

---

# 7. Stage 3 — Core Build Stage

## 7.1 역할

Core Spec과 Scenario/Golden을 바탕으로 core-first 시제품을 구현한다.

---

## 7.2 포함 작업

```text id="i4z9xl"
Build Task Packet 생성
Core Build 실행
```

---

## 7.3 입력

```text id="9j6eb8"
normalized_challenge.json
challenge_constraints.json
core_artifact_classification.json
core_contract.json
state_contract.json
action_contract.json
runner_contract.json
fixtures/
golden/
oracle_risk_report.json
scenario_golden_review.json
```

---

## 7.4 출력

```text id="8784co"
build_task_packet.md
build_task_packet.json
final_artifact/
```

---

## 7.5 build_task_packet.md 필수 문구

```text id="ndt76s"
너의 목표는 파일을 채우는 것이 아니다.
너의 목표는 core contract와 scenario/golden을 만족하는 첫 시제품을 구현하는 것이다.

먼저 core system, runner, scenario replay를 구현하라.
그 다음 core를 조작하거나 확인할 수 있는 product layer를 붙여라.

viewer/product layer는 core logic을 대체하면 안 된다.
viewer는 core output, state snapshot, replay result를 보여주는 레이어여야 한다.
```

---

## 7.6 반드시 요구할 것

```text id="6fy0qx"
- src/core 또는 src/engine 구조
- runner command
- fixtures 실행 가능
- golden 비교 가능
- deterministic behavior
- anti-hardcode 회피
- product layer의 기반 준비
- README/run_instructions
```

---

## 7.7 기본 후보 수 정책

```text id="b0s4ya"
Phase 1.6 기본 build candidates = 1
live 기본 candidates = 1
mock candidates = 1~2 허용
--candidates는 기존 호환 또는 실험 옵션
Phase 1.6 성공 여부는 candidates 기능으로 판단하지 않음
```

---

## 7.8 final_artifact 기본 구조

```text id="8r70fv"
final_artifact/
  src/
    core/
    engine/
    runner.js or runner.py
  fixtures/
  golden/
  replay/
  validators/
  product/
  reports/
  README.md
  run_instructions.md
```

---

## 7.9 Builder 금지

```text id="qh0y5j"
- UI부터 만들기
- runner 생략
- core logic을 viewer 안에만 구현
- scenario fixture를 무시
- expected output을 코드에 박기
- scenario_001 같은 fixture id별 분기
- random/Date.now로 결과 흔들기
```

---

# 8. Stage 4 — Core Verification Stage

## 8.1 역할

Core Build 결과를 기계적으로 검증한다.

가능한 한 LLM 판단 없이 코드로 검증한다.

---

## 8.2 Gate 목록

```text id="fvrcs9"
Static Gate
Core Contract Gate
Syntax Gate
Runner Gate
Scenario Replay Gate
Golden Output Gate
State Invariant Gate
Determinism Gate
Anti-Hardcode Gate
```

Regression Gate는 Phase 1.6에서는 `green_base 저장` 중심으로 준비만 한다.
본격적인 Regression Gate는 Phase 2 범위다.

---

## 8.3 출력

```text id="4nz6h7"
gate_results.json
core_contract_summary.json
runner_summary.json
scenario_replay_summary.json
golden_diff_summary.json
state_invariant_summary.json
determinism_summary.json
anti_hardcode_summary.json
regression_summary.json
```

---

## 8.4 Runner 출력 필수 구조

Runner는 JSON을 출력해야 한다.

```json id="sa3jpj"
{
  "ok": true,
  "final_state": {},
  "events": [],
  "summary": "",
  "errors": []
}
```

JSON이 아니면 Runner Gate 실패.

---

## 8.5 Gate별 검사

### Static Gate

```text id="jr956m"
파일 구조
필수 파일 존재
멀티파일 여부
금지 dependency
기본 import/require graph
```

### Core Contract Gate

```text id="ofsrzf"
core_contract.json 존재
state_contract.json 존재
action_contract.json 존재
runner_contract.json 존재
contract에 정의된 state/action/runner가 실제 코드에 존재
```

### Syntax Gate

```text id="65yg93"
node --check
python compile
또는 프로젝트 타입별 문법 검사
```

### Runner Gate

```text id="it8wtf"
runner command 실행 가능
JSON output 생성
required_output_fields 존재
exit code 정상
timeout 없음
```

### Scenario Replay Gate

```text id="hd5e1b"
fixtures/scenario_*.json 전체 실행
actions 순서대로 재생
final_state/events/summary 수집
실패 scenario 기록
```

### Golden Output Gate

```text id="763sci"
runner output과 golden expected 비교
exact / partial / invariant comparison 지원
review comparison은 자동 PASS 근거로 사용 금지
diff report 생성
```

### State Invariant Gate

```text id="epcpab"
state invariant 위반 여부
invalid action 후 상태 오염 여부
필수 필드 누락 여부
음수 불가 필드 등 기본 불변조건
```

### Determinism Gate

```text id="ffcosv"
같은 scenario를 2회 이상 실행
같은 seed에서 같은 output인지 비교
random 사용 시 seed 필수
Math.random 직접 사용 금지
Date.now 기반 결과 변화 금지
```

### Anti-Hardcode Gate

Phase 1.6에서는 Level 1 + 간단한 Level 2까지만 구현한다.

Level 1:

```text id="mvlbit"
scenario_001 등 fixture id 직접 분기 탐지
expected output 문자열 직접 포함 탐지
hardcoded success 탐지
입력과 무관한 고정 출력 탐지
TODO / placeholder / coming soon 탐지
```

Level 2:

```text id="5e23eg"
scenario id/title 변경 후 실행
fixture 순서 변경 후 실행
동일 구조의 간단 변형 fixture 실행
```

Hidden scenario test는 Phase 1.6 범위에 넣지 않는다.

---

# 9. Stage 5 — Repair Stage

## 9.1 역할

Gate 결과를 검토하고, 첫 시제품 바닥선을 맞추기 위한 제한적 수리를 수행한다.

이 Stage는 Phase 2 continuation이 아니다.

---

## 9.2 포함 작업

```text id="94s5ys"
Build Review
Patch Repair
Re-run Core Gates
```

---

## 9.3 Build Review 출력

```text id="rhxdgs"
build_review.json
build_review.md
```

---

## 9.4 Build Review 기준

```text id="jcprya"
- runner가 실제 core를 실행하는가
- scenario를 제대로 replay하는가
- golden을 하드코딩하지 않았는가
- state transition이 실제로 있는가
- core logic이 UI에 묻히지 않았는가
- 실패가 patch로 고칠 수 있는가
```

Review 결과:

```json id="d83bzl"
{
  "status": "PASS | NEEDS_PATCH | FAIL",
  "blocking_issues": [],
  "patch_instructions": [],
  "failed_scenarios": [],
  "hardcode_risk": "low | medium | high",
  "patchable": true
}
```

---

## 9.5 Patch Repair 제한

Patch Repair는 새 기능 추가 루프가 아니다.

```text id="glcw8c"
Patch Repair는 기존 Contract/Scenario/Golden을 통과시키기 위한 제한적 수리만 수행한다.
새 기능, 새 시스템, 새 product layer 확장은 Phase 2 범위다.
```

제한:

```text id="kbijq8"
max_patch_attempts = 2
```

원칙:

```text id="t7wku7"
처음부터 재생성 금지
실패한 scenario/gate 중심으로 수정
green 부분 보존
core contract를 임의로 바꾸지 않음
runner/golden을 우회하지 않음
```

Patch 후 Core Gates를 다시 실행한다.

Patch 2회 후에도 실패하면 다음 중 하나로 판정한다.

```text id="r5mspu"
NEEDS_MORE_GEMMA_LOOP
RUNS_BUT_WEAK
DROP
```

---

# 10. Stage 6 — Product Layer Stage

## 10.1 역할

검증된 core를 기반으로 사용자가 실행·조작·확인할 수 있는 product layer를 만든다.

Product Layer는 필수다.

---

## 10.2 포함 작업

```text id="vtp3kn"
Product Layer Build
Product Layer Review
Product Layer Repair if needed
```

---

## 10.3 출력

```text id="7qrsuc"
product/
  viewer/
  editor/ optional
  dashboard/ optional
product_layer_review.json
product_layer_review.md
```

---

## 10.4 원칙

```text id="a223pj"
Product Layer는 core logic을 대체하지 않는다.
Product Layer는 core runner output, state snapshot, replay result를 보여준다.
Product Layer에서만 동작하고 runner에서는 검증 불가한 구조는 실패다.
```

---

## 10.5 Product Layer Review 기준

```text id="j7hccy"
- viewer/product layer가 core output을 보여주는가
- core logic을 복제하지 않았는가
- 사용자가 결과를 확인할 수 있는가
- 실행 방법이 명확한가
- product layer가 core 검증 결과와 불일치하지 않는가
```

Review 결과:

```json id="qgj17w"
{
  "status": "PASS | NEEDS_REPAIR | FAIL",
  "blocking_issues": [],
  "repair_instructions": []
}
```

Repair 제한:

```text id="p8k8oa"
max_product_layer_repair_attempts = 1
```

원칙:

```text id="tzyw6u"
core logic 수정 금지
product layer와 실행 안내만 수정
```

---

# 11. Stage 7 — Verdict / Dashboard / Green Base Stage

## 11.1 역할

최종 verdict를 판정하고, 사용자 검수용 summary를 만들고, Phase 2 continuation을 위한 green base를 저장한다.

---

## 11.2 입력

```text id="x4phmn"
core_artifact_classification.json
core_contract_review.json
scenario_golden_review.json
core_contract_summary.json
runner_summary.json
scenario_replay_summary.json
golden_diff_summary.json
state_invariant_summary.json
determinism_summary.json
anti_hardcode_summary.json
build_review.json
product_layer_review.json
oracle_risk_report.json
user review history if available
```

---

## 11.3 출력

```text id="4sphhm"
product_verdict.md
product_eval_summary.json
dashboard_summary.json
core_system_summary.json
harness_summary.json
green_base.json
```

---

## 11.4 Verdict 라벨

```text id="p76jx2"
REVIEW_READY
NEEDS_MORE_GEMMA_LOOP
RUNS_BUT_WEAK
KEEP_CANDIDATE
DROP
PROMOTE_TO_CODEX
```

---

## 11.5 REVIEW_READY

조건:

```text id="ybgcmu"
core system 검증 가능
runner 실행 가능
scenario replay 통과
golden diff 허용 범위
determinism 통과
hardcode risk 낮음
product layer가 core를 기반으로 동작
사용자가 검수할 가치 있음
```

---

## 11.6 NEEDS_MORE_GEMMA_LOOP

조건:

```text id="2x9lkr"
core 구조는 맞음
일부 scenario/golden 실패
next_goal이 구체적
patch/delta로 개선 가능
```

---

## 11.7 RUNS_BUT_WEAK

조건:

```text id="1lbe52"
기본 실행은 되지만 core system이 약함
scenario가 빈약함
state transition이 거의 없음
viewer/UI 중심으로만 동작
Phase 2에 넣어도 성장 가치가 낮음
```

---

## 11.8 DROP

조건:

```text id="z0zkoy"
runner 없음
core contract 붕괴
scenario replay 불가
hardcode/stub 심각
state transition 없음
Challenge 핵심과 불일치
```

---

## 11.9 PROMOTE_TO_CODEX

매우 보수적으로 사용한다.

조건:

```text id="3q6qak"
REVIEW_READY 조건 모두 만족
core system 구조 명확
scenario/golden/replay 충분
product layer가 core를 잘 보여줌
Codex/Claude가 정리/확장할 가치 있음
```

금지:

```text id="v55dkq"
runner 없음
golden 없음
scenario replay 실패
determinism 실패
hardcode risk high
viewer-only 산출물
core logic이 UI에 묻힘
oracle risk high
comparison_mode = review에 의존
exact golden 0개
```

---

## 11.10 Dashboard Summary

기술 결과를 사용자 검수용 한국어 요약으로 바꾼다.

목록 카드에는 과한 기술 로그를 노출하지 않는다.

목록 카드 표시:

```text id="fc9ryg"
[검수 가능 / 더 돌려야 함 / 약함]

산출물 유형: 룰 엔진
코어: 있음
검증: 3/4 통과
결정성: 통과
위험: 낮음
추천: 실행해보고 판단
```

상세 페이지 표시:

```text id="v59xnz"
runner_summary
scenario_replay_summary
golden_diff_summary
anti_hardcode_summary
failed_scenarios
file paths
run instructions
```

---

## 11.11 Green Base 저장

green base는 Phase 2 continuation의 시작점이다.

저장 조건:

```text id="wcj64q"
Core Gates 통과 또는 patch 가능한 PARTIAL
Product Layer Review PASS
hardcode risk low 또는 medium
next_goal 존재
```

저장 산출물:

```text id="ngaj9t"
green_base.json
green_base_path
failed_scenarios
golden_diff
next_goal
allowed_touch_files
frozen_files
regression_suite
```

원칙:

```text id="jiut9c"
Phase 2는 처음부터 다시 만들지 않는다.
Phase 2는 green base를 이어받아 patch/delta로 성장시킨다.
```

---

# 12. Phase 2 연결 조건

Phase 1.6 결과 중 아무거나 Phase 2로 넘기면 안 된다.

Phase 2 대상:

```text id="tur48q"
review = RETRY
또는
verdict = NEEDS_MORE_GEMMA_LOOP

그리고:
core_contract 존재
runner 존재
failed_scenarios 존재
next_goal 구체적
hardcode risk high 아님
green_base_path 존재
```

Phase 2 제외:

```text id="j6hvut"
RUNS_BUT_WEAK
DROP
runner 없음
core contract 없음
hardcode risk high
viewer-only 산출물
oracle risk high
green_base 없음
```

---

# 13. CLI 요구사항

기존 CLI는 유지한다.

필수:

```bash id="nchz67"
python -m repo_idea_miner factory-build --sample mock --mode mock
python -m repo_idea_miner factory-build --challenge-id <id> --mode live
```

선택:

```bash id="pztc2b"
python -m repo_idea_miner factory-build --sample mock --mode mock --candidates 2
```

정책:

```text id="k06i3y"
live 기본 candidates = 1
mock candidates = 1~2
--candidates는 기존 호환 또는 실험 옵션
Phase 1.6 성공 여부는 candidates 기능으로 판단하지 않음
```

`factory-rejudge`는 Phase 1.6 필수 요구에서 제외한다.
필요하면 후속 Phase 1.6b 또는 1.7에서 구현한다.

---

# 14. DB / Artifact 요구사항

기존 DB를 파괴하지 않는다.

DB 변경은 최소화한다.

권장 최소 필드:

```text id="9xu9bx"
artifact_class
harness_summary_path
core_system_summary_path
green_base_path
```

그 외 정보는 JSON artifact로 저장한다.

```text id="1na9jz"
oracle_risk_level
hardcode_risk
failed_scenarios
golden_diff
allowed_touch_files
frozen_files
next_goal
```

---

# 15. 완료 샘플 기준

Phase 1.6 완료 기준에는 mock challenge 1개 전체 완주가 반드시 포함되어야 한다.

명령:

```bash id="0a3um0"
python -m repo_idea_miner factory-build --sample mock --mode mock
```

완주 결과는 다음을 포함해야 한다.

```text id="8cr5ej"
- normalized_challenge.json
- core_artifact_classification.json
- core_contract.json
- state_contract.json
- action_contract.json
- runner_contract.json
- fixtures/scenario_001.json
- fixtures/scenario_002.json
- fixtures/scenario_003.json
- golden/expected_001.json
- golden/expected_002.json
- golden/expected_003.json
- oracle_risk_report.json
- runner
- runner_summary.json
- scenario_replay_summary.json
- golden_diff_summary.json
- determinism_summary.json
- anti_hardcode_summary.json
- product layer
- product_layer_review.json
- dashboard_summary.json
- green_base.json
```

허용 결과:

```text id="wel2ih"
REVIEW_READY
또는
NEEDS_MORE_GEMMA_LOOP with concrete next_goal
```

허용하지 않는 완료:

```text id="yo5k3h"
runner 없음
scenario 없음
golden 없음
product layer 없음
green_base 없음
PROMOTE_TO_CODEX 남발
```

---

# 16. 테스트 요구사항

최소 테스트:

```text id="28kcbr"
1. Challenge Normalizer output 생성
2. Core Artifact Classifier output 생성
3. VIEWER_ONLY가 기본값이 아님
4. core_contract.json 생성
5. state_contract.json 생성
6. action_contract.json 생성
7. runner_contract.json 생성
8. Core Contract Review 생성
9. Core Contract Repair max 1회 제한
10. 정상/경계/실패 scenario 생성
11. golden expected 생성
12. oracle_risk_report.json 생성
13. Scenario/Golden Review 생성
14. comparison_mode = review는 Golden Output Gate PASS 근거로 사용 금지
15. comparison_mode = review는 PROMOTE_TO_CODEX 근거로 사용 금지
16. exact golden 0개면 PROMOTE_TO_CODEX 금지
17. oracle_risk_level high면 PROMOTE_TO_CODEX 금지
18. Scenario/Golden Repair max 1회 제한
19. build_task_packet.md 생성
20. build_task_packet에 core-first 지시 포함
21. live 기본 candidates = 1
22. mock candidates = 1~2 허용
23. Core Build 결과에 runner 존재
24. Core Contract Gate 통과/실패 테스트
25. Runner Gate 통과/실패 테스트
26. Scenario Replay Gate 통과/실패 테스트
27. Golden Output Gate 통과/실패 테스트
28. State Invariant Gate 통과/실패 테스트
29. Determinism Gate 통과/실패 테스트
30. Anti-Hardcode Level 1 테스트
31. Anti-Hardcode Level 2 간단 변형 테스트
32. Build Review 생성
33. Patch Repair max 2회 제한
34. Patch Repair가 새 기능 추가를 하지 않음
35. patch 후 Core Gates 재실행
36. Product Layer가 필수
37. Product Layer가 core output 기반인지 검사
38. Product Layer Review 생성
39. Product Layer Repair max 1회 제한
40. runner 없는 산출물은 PROMOTE_TO_CODEX 금지
41. golden 없는 산출물은 PROMOTE_TO_CODEX 금지
42. viewer-only 산출물은 PROMOTE_TO_CODEX 금지
43. hardcode risk high는 PROMOTE_TO_CODEX 금지
44. REVIEW_READY 라벨 생성 가능
45. NEEDS_MORE_GEMMA_LOOP 라벨 생성 가능
46. RUNS_BUT_WEAK 라벨 생성 가능
47. dashboard_summary.json 생성
48. Dashboard 목록 카드가 과도한 기술 로그를 노출하지 않음
49. Dashboard 상세에서 runner/golden/determinism 표시
50. green_base.json 생성
51. green_base_path 저장
52. failed_scenarios 저장
53. golden_diff 저장
54. next_goal 저장
55. mock challenge 1개 전체 완주
56. existing Product Factory mock 동작 유지
57. existing Product Dashboard 동작 유지
58. existing Challenge Mode 동작 유지
59. 기존 테스트 전체 통과
60. secret scan 통과
```

---

# 17. 완료 기준

완료 기준:

```text id="cqebd6"
1. Phase 1.6 workflow가 7개 Stage로 정리됨
2. Build 전에 Core Contract / Scenario / Golden이 생성되고 리뷰됨
3. Contract/Scenario/Golden은 후보 경쟁이 아니라 Draft→Review→Repair 구조로 동작함
4. Gemma Builder가 core-first build task packet을 받음
5. live 기본 build 후보는 1개로 제한됨
6. Core Build 결과는 runner를 반드시 포함함
7. Core Gates가 실행됨
8. Gate 실패를 Build Review가 구조화함
9. Patch Repair가 실패 중심으로 제한 실행됨
10. Product Layer가 필수로 생성됨
11. Product Layer가 core output 기반인지 검토됨
12. Product Judge가 core-system harness 결과로 verdict를 판정함
13. PROMOTE_TO_CODEX가 보수적으로 제한됨
14. Dashboard 목록은 한국어 검수함처럼 보이고, 상세에서 기술 요약을 볼 수 있음
15. Phase 2 continuation을 위한 green_base_path / failed_scenarios / golden_diff / next_goal이 저장됨
16. mock challenge 1개가 전체 1.6 workflow를 완주함
17. 기존 기능이 깨지지 않음
```

---

# 18. 작업 보고 형식

완료 후 아래 형식으로 보고한다.

```text id="vpbdnb"
RIM Product Factory Phase 1.6 Core-first Review-Repair Harness 작업 보고

Base 상태
- 시작 HEAD:
- 종료 HEAD:
- origin ahead/behind:
- push 여부:

수정 파일
-

7개 Stage 구현
- Core Spec Stage:
- Scenario Oracle Stage:
- Core Build Stage:
- Core Verification Stage:
- Repair Stage:
- Product Layer Stage:
- Verdict / Dashboard / Green Base Stage:

Core Artifacts
- normalized_challenge.json:
- core_artifact_classification.json:
- core_contract.json:
- state_contract.json:
- action_contract.json:
- runner_contract.json:

Scenario / Golden
- fixtures:
- golden:
- comparison modes:
- oracle risk:

Review-Repair 제한
- Core contract repair max:
- Scenario/Golden repair max:
- Patch repair max:
- Product layer repair max:

Core Gates
- Core Contract Gate:
- Runner Gate:
- Scenario Replay Gate:
- Golden Output Gate:
- State Invariant Gate:
- Determinism Gate:
- Anti-Hardcode Level 1:
- Anti-Hardcode Level 2:

Patch 결과
- failed scenarios:
- patch attempts:
- re-run gates:

Product Layer
- 생성 위치:
- core output 기반 여부:
- runner와 분리 여부:

Judge
- REVIEW_READY:
- NEEDS_MORE_GEMMA_LOOP:
- RUNS_BUT_WEAK:
- PROMOTE_TO_CODEX 제한:
- exact golden 0개 금지:
- oracle risk high 금지:

Dashboard
- 목록 카드:
- 상세 기술 요약:
- artifact class 표시:
- runner/golden/determinism 표시:
- hardcode risk 표시:
- 실행 경로 표시:

Green Base / Phase 2 준비
- green_base.json:
- green_base_path:
- failed_scenarios:
- golden_diff:
- next_goal:
- allowed_touch_files:
- frozen_files:

CLI
- factory-build live default candidates:
- factory-build mock candidates:

완료 샘플
- command: python -m repo_idea_miner factory-build --sample mock --mode mock
- result:
- verdict:
- green_base:
- product layer:

테스트
- pytest:
- secret scan:

주의사항
- 남은 한계:
- 후속 추천:
```

---

# 19. 최종 정의

이번 작업은 “더 예쁜 앱”을 만들게 하는 작업이 아니다.

이번 작업은 RIM Product Factory의 첫 시제품 기준을 바꾸는 작업이다.

> RIM Product Factory Phase 1.6은 Phase 2 성장 루프에 넣을 수 있는 첫 시제품의 바닥선을 재정의한다.
> 첫 시제품은 UI 껍데기가 아니라, core contract, state/action model, runner, scenario fixture, golden expected, replay/golden/determinism/anti-hardcode 검증을 통과한 core system과, 그 core를 사용자가 실행·조작·확인할 수 있는 product layer를 함께 가져야 한다.
> 이를 위해 Product Factory를 7개 Stage로 정리한다: Core Spec, Scenario Oracle, Core Build, Core Verification, Repair, Product Layer, Verdict/Dashboard/Green Base.
> Phase 1.6의 목적은 여러 후보 중 하나를 고르는 것이 아니라, 하나의 기준 후보를 Draft → Review → Repair → Verify 흐름으로 Phase 2에 넣을 수 있는 green base까지 끌어올리는 것이다.
