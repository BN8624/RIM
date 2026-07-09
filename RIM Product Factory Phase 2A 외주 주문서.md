# RIM Product Factory Phase 2A 외주 주문서

## Continuation Queue Routing + Safe Patch Lane

### — 자동 patch 대상과 spec repair 대상을 안전하게 분리하는 단계

## 0. 작업 배경

RIM Product Factory는 Phase 1.6 ~ 1.7b를 통해 다음 단계까지 완료했다.

```text
Phase 1.6
- Core-first Review-Repair Harness 구현
- core contract / runner / scenario / golden / product layer / gate 구조 도입

Phase 1.6b
- live challenge #47로 하네스 실전 검증
- Core Contract Gate, Product Layer Gate, Green/Continuation Base, Patch Review, factory-validate 보강

Phase 1.7
- #47 continuation_base를 이용해 첫 delta loop 실증
- failure classification / repair plan / patch / gate rerun / green promotion check 구현
- 자동 patch로 고치면 안 되는 문제는 SPEC_REPAIR_REQUIRED로 정직하게 분리

Phase 1.7b
- factory-validate가 continuation run을 별도 run type으로 인식하도록 보강
- continuation 산출물과 verdict consistency 검증
```

이제 Phase 2로 넘어갈 수 있다.

단, Phase 2를 한 번에 전부 구현하면 위험하다.
따라서 이번 작업은 **Phase 2A**로 제한한다.

---

# 1. Phase 2A의 정확한 정의

Phase 2A는 전체 성장 루프가 아니다.

Phase 2A의 목적은 다음이다.

```text
여러 Product Run / Continuation Run을 대상으로
무엇을 자동 patch로 고칠 수 있고,
무엇을 spec repair로 보내야 하며,
무엇은 제외해야 하는지 안정적으로 분류한다.
```

Phase 2A의 핵심:

```text
1. continuation queue dry-run
2. lane routing
3. safe patch lane
4. spec repair proposal/review only
5. dashboard에 recommended lane 표시
6. validate가 lane 정보를 검증
```

Phase 2A의 한 줄 정의:

```text
Phase 2A는 자동 실행 루프가 아니라,
안전한 라우팅 + 제한 patch + spec repair proposal-only 단계다.
```

---

# 2. 이번 작업에서 하지 말 것

금지:

```text
- Spec Repair Apply 자동화 금지
- golden/fixtures/contract 자동 수정 금지
- comparison_mode 자동 완화 금지
- invariant DSL 대개편 금지
- 여러 run 무제한 처리 금지
- factory 자동 배치를 Phase 2A로 전면 전환 금지
- Codex/Claude 자동 호출 금지
- N-candidate 경쟁 추가 금지
- hidden scenario 대형 시스템 구현 금지
- Dashboard 대개편 금지
- 기존 Challenge Mode 파괴 금지
- 새 DB schema migration 기본 금지
```

이번 작업은 다음에만 집중한다.

```text
run을 분류한다.
patch 가능한 것만 제한적으로 고친다.
spec repair가 필요한 것은 proposal/review까지만 만든다.
```

---

# 3. Lane 구분

Phase 2A는 run을 다음 lane으로 분류한다.

```text
PATCH_CONTINUATION
SPEC_REPAIR
EXCLUDED
REVIEW_ONLY
```

## 3.1 PATCH_CONTINUATION

코드 patch로 안전하게 고칠 수 있는 대상.

대상 verdict:

```text
NEEDS_MORE_GEMMA_LOOP
```

필수 조건:

```text
continuation_base 존재
core_contract 존재
runner 존재
allowed_touch_files 존재
frozen_files 존재
hardcode risk high 아님
oracle risk high 아님
next_goal 구체적
failure type이 patch-safe 범위에 있음
```

---

## 3.2 SPEC_REPAIR

코드 patch가 아니라 contract / fixture / golden / invariant / comparison 기준 쪽을 봐야 하는 대상.

대상 verdict:

```text
SPEC_REPAIR_REQUIRED
```

또는 다음 조건:

```text
golden_schema_mismatch가 patch로 해결 불가
runner가 contract에 더 일관적이고 golden이 뒤처진 경우
invariant DSL이 final_state 구조를 해석하지 못한 경우
comparison_mode가 잘못 지정된 경우
scenario/golden이 contract와 불일치하는 경우
```

Phase 2A에서는 Spec Repair를 **적용하지 않는다.**

Phase 2A에서 하는 것:

```text
Spec Repair Proposal 생성
Spec Repair Review 생성
Dashboard에 spec repair 필요 표시
```

Phase 2A에서 하지 않는 것:

```text
golden 수정
fixtures 수정
contract 수정
comparison_mode 변경
invariant DSL 대개편
green_base 억지 승격
```

Spec Repair Apply는 Phase 2B로 미룬다.

---

## 3.3 EXCLUDED

루프에 넣으면 안 되는 대상.

제외 verdict:

```text
RUNS_BUT_WEAK
DROP
ERROR
```

제외 조건:

```text
hardcode risk high
oracle risk high
runner 없음
core_contract 없음
continuation_base 없음
failure type 불명확
viewer-only 산출물
next_goal 없음
```

---

## 3.4 REVIEW_ONLY

사용자가 검수해야 하는 대상.

대상 verdict:

```text
REVIEW_READY
PROMOTE_TO_CODEX
KEEP_CANDIDATE
```

이들은 continuation queue 대상이 아니다.

---

# 4. Phase 2A 안전 보강 규칙

이번 작업에서는 다음 안전 규칙을 반드시 구현한다.

## 4.1 Queue 실행 기본값은 dry-run

```text
factory-continue-queue는 기본적으로 절대 patch를 실행하지 않는다.
--execute가 없으면 run 분류와 queue 출력만 수행한다.
```

dry-run과 execute의 limit 정책은 분리한다.

```text
dry-run 기본 limit: 20
execute 기본 limit: 1
execute 최대 limit: 1
```

즉 dry-run은 queue 분류 품질을 볼 수 있도록 여러 후보를 보여준다.
실제 patch 실행은 반드시 1개만 허용한다.

실제 patch 실행은 다음처럼 명시 옵션이 있을 때만 허용한다.

```bash
python -m repo_idea_miner factory-continue-queue --lane patch --execute --limit 1
```

금지:

```bash
python -m repo_idea_miner factory-continue-queue --lane spec-repair --execute
python -m repo_idea_miner factory-continue-queue --lane spec-repair --apply
python -m repo_idea_miner factory-continue-queue --execute --limit 2
python -m repo_idea_miner factory-continue-queue --limit 999
```

Phase 2A에서 spec repair execute는 존재하면 안 된다.

---

## 4.2 Queue Manager는 기존 DB 구조 우선, filesystem fallback

Queue Manager는 run을 다음 순서로 찾는다.

```text
1. 현재 factory_db.py에 존재하는 run 조회 구조를 우선 재사용한다.
2. 새 DB schema migration은 기본 금지한다.
3. DB에서 run_dir를 찾을 수 있으면 해당 경로를 사용한다.
4. DB에서 찾지 못한 run만 runs/ filesystem fallback으로 찾는다.
5. runs/ 아래 continuation_run_summary.json 또는 harness_summary.json이 있으면 fallback 후보로 읽는다.
6. 중복 run은 run_id 기준으로 dedupe한다.
```

주의:

```text
product_runs / continuation runs라는 이름의 새 테이블을 임의로 만들지 않는다.
현재 DB schema에 맞춰 adapter/helper를 두는 방식으로 처리한다.
```

우선순위 정렬:

```text
1. live_validation 또는 continuation 이력이 있는 run
2. SPEC_REPAIR_REQUIRED / NEEDS_MORE_GEMMA_LOOP
3. 최근 run
4. hardcode/oracle risk 낮음
5. failure type 명확함
```

---

## 4.3 STATE_INVARIANT_NOT_EXPOSED는 무조건 patch-safe가 아니다

`STATE_INVARIANT_NOT_EXPOSED`는 다음 조건을 모두 만족할 때만 patch-safe다.

```text
1. contract invariant가 명확하고 checkable하다.
2. runner/core 내부에는 해당 값이 존재한다.
3. final_state snapshot에 노출만 빠졌다.
4. 필드 노출이 core 의미를 바꾸지 않는다.
```

위 조건을 만족하지 않으면 `SPEC_REPAIR`로 보낸다.

예:

```text
invariant 자체가 잘못됨
DSL이 final_state 구조를 해석하지 못함
contract가 과한 필드를 요구함
```

이 경우 patch가 아니라 spec repair 대상이다.

---

## 4.4 GOLDEN_SCHEMA_MISMATCH는 기본 SPEC_REPAIR

`GOLDEN_SCHEMA_MISMATCH`는 기본적으로 `SPEC_REPAIR`로 라우팅한다.

단, 다음 경우에만 `PATCH_CONTINUATION`으로 보낼 수 있다.

```text
runner output이 runner_contract의 required_output_fields 또는 output schema를 명백히 위반한 경우
```

이 판단 근거는 반드시 queue entry의 `reason`에 기록한다.

```text
runner가 contract를 어겨서 extra/missing field 발생
→ PATCH_CONTINUATION 가능

golden이 runner보다 뒤처짐
→ SPEC_REPAIR
```

---

## 4.5 Spec Repair Lane은 read-only mode로 실행한다

Spec Repair Proposal/Review는 read-only mode에서 실행한다.

금지:

```text
patch writer 호출 금지
apply_patch 호출 금지
edit helper 호출 금지
contract/fixtures/golden 직접 쓰기 금지
oracle_risk_report 직접 수정 금지
comparison_mode 직접 변경 금지
```

Spec Repair Lane에서 허용되는 출력은 다음뿐이다.

```text
spec_repair_proposal.json
spec_repair_proposal.md
spec_repair_review.json
spec_repair_review.md
frozen_hash_before.json
frozen_hash_after.json
frozen_hash_check.json
phase2a_dashboard_summary.json
```

---

## 4.6 Spec Repair Lane은 frozen file hash를 보호한다

Spec Repair Proposal/Review 실행 전후 frozen 파일의 hash를 비교한다.

대상:

```text
golden/
fixtures/
core_contract.json
state_contract.json
action_contract.json
runner_contract.json
oracle_risk_report.json
```

Phase 2A에서 위 파일 hash가 바뀌면 validate FAIL이다.

```text
Spec Repair Proposal/Review는 만들 수 있다.
Spec Repair Apply는 할 수 없다.
```

---

## 4.7 Patch Lane도 frozen file hash를 보호한다

Patch Lane도 patch 전후 frozen file hash를 비교한다.

대상:

```text
golden/
fixtures/
core_contract.json
state_contract.json
action_contract.json
runner_contract.json
oracle_risk_report.json
```

규칙:

```text
hash unchanged → PASS
hash changed → patch reject + validate FAIL
```

즉 patch worker가 `src/`나 `product/`만 수정했다고 보고하더라도, frozen file hash가 바뀌면 실패다.

---

## 4.8 Patch Lane 중 spec 문제 발견 시 lane 전환

Patch Lane 도중 spec/golden/contract 문제로 판명되면 다음처럼 처리한다.

```text
1. patch를 중단한다.
2. new_verdict = SPEC_REPAIR_REQUIRED로 둔다.
3. recommended_lane = SPEC_REPAIR로 업데이트한다.
4. spec_repair_proposal을 생성할 수 있으면 생성하되 apply하지 않는다.
5. gate fail을 REVIEW_READY로 승격하지 않는다.
```

이 상태는 `PATCH_BLOCKED_SPEC`으로 기록한다.

---

## 4.9 APPROVE_FOR_PHASE2B여도 apply 금지

Spec Repair Review가 `APPROVE_FOR_PHASE2B`를 내도 Phase 2A에서는 적용하지 않는다.

```text
APPROVE_FOR_PHASE2B = 후속 Phase 2B에서 적용 가능하다는 뜻
APPROVE_FOR_PHASE2B ≠ 지금 적용
```

---

## 4.10 기존 Phase 1.7 / 1.7b continuation run 호환성

Phase 2A 이후 새로 생성되는 continuation run은 `lane` 필드가 필수다.

단, Phase 1.7 / 1.7b에서 이미 생성된 기존 continuation run은 `lane` 필드가 없을 수 있다.

규칙:

```text
기존 continuation run에 lane 필드가 없어도 validate FAIL로 보지 않는다.
이 경우 verdict와 failure_classification을 기반으로 inferred_lane을 계산해 표시한다.
```

예:

```text
verdict = SPEC_REPAIR_REQUIRED
→ inferred_lane = SPEC_REPAIR

verdict = NEEDS_MORE_GEMMA_LOOP
→ failure type을 보고 PATCH_CONTINUATION 또는 SPEC_REPAIR로 추론

verdict = REVIEW_READY
→ inferred_lane = REVIEW_ONLY
```

Phase 2A 이후 생성된 run에 lane이 없으면 validate FAIL이다.

---

## 4.11 #47은 patch execute 대상이 아니다

#47은 Phase 2A에서 반드시 `SPEC_REPAIR` lane으로 분류되어야 한다.

```text
run_id: 5
challenge_id: 47
current verdict: SPEC_REPAIR_REQUIRED
expected lane: SPEC_REPAIR
```

#47은 patch execute 대상이 아니다.

```text
--lane patch --execute --limit 1 실행 시 #47이 선택되면 안 된다.
patch-eligible run이 없으면 NO_PATCH_ELIGIBLE로 종료한다.
```

#47에서 허용되는 작업:

```text
Spec Repair Proposal 생성
Spec Repair Review 생성
Frozen Hash Guard 확인
Dashboard 표시
```

#47에서 금지되는 작업:

```text
golden 파일 수정
fixtures 수정
contract 수정
invariant DSL 대개편
green_base 억지 승격
patch execute
```

---

# 5. Queue Manager

## 5.1 CLI 추가

Queue dry-run 명령을 추가한다.

```bash
python -m repo_idea_miner factory-continue-queue --dry-run
```

옵션:

```bash
python -m repo_idea_miner factory-continue-queue --lane patch --dry-run
python -m repo_idea_miner factory-continue-queue --lane spec-repair --dry-run
python -m repo_idea_miner factory-continue-queue --lane patch --dry-run --limit 1
python -m repo_idea_miner factory-continue-queue --lane patch --execute --limit 1
python -m repo_idea_miner factory-continue-queue --lane spec-repair --proposal-only --limit 1
```

기본 정책:

```text
기본은 dry-run
dry-run 기본 limit = 20
execute 기본 limit = 1
execute 최대 limit = 1
무제한 queue 처리 금지
--execute가 없으면 patch 실행 금지
spec-repair lane은 proposal-only만 허용
```

---

## 5.2 Queue Entry 구조

출력 파일:

```text
continuation_queue.json
continuation_queue.md
```

Queue Entry 예시:

```json
{
  "run_id": 5,
  "challenge_id": 47,
  "current_verdict": "SPEC_REPAIR_REQUIRED",
  "recommended_lane": "SPEC_REPAIR",
  "can_continue": true,
  "can_patch": false,
  "reason": "golden schema mismatch and invariant DSL issue require spec repair",
  "blocking_reason": "",
  "risk_level": "medium",
  "priority": 1
}
```

Patch 대상 예시:

```json
{
  "run_id": 12,
  "challenge_id": 52,
  "current_verdict": "NEEDS_MORE_GEMMA_LOOP",
  "recommended_lane": "PATCH_CONTINUATION",
  "can_continue": true,
  "can_patch": true,
  "reason": "product layer does not consume replay output",
  "blocking_reason": "",
  "risk_level": "low",
  "priority": 1
}
```

Excluded 예시:

```json
{
  "run_id": 21,
  "challenge_id": 60,
  "current_verdict": "RUNS_BUT_WEAK",
  "recommended_lane": "EXCLUDED",
  "can_continue": false,
  "can_patch": false,
  "reason": "weak core system and low continuation value",
  "blocking_reason": "RUNS_BUT_WEAK is not eligible for continuation",
  "risk_level": "high",
  "priority": null
}
```

---

# 6. Patch Continuation Lane

## 6.1 역할

Patch Lane은 Phase 1.7의 continuation loop를 여러 run에 일반화한다.

단, Phase 2A에서는 안전한 failure type만 자동 patch한다.

입력:

```text
continuation_base
failure_classification
repair_plan
failed_scenarios
golden_diff
state_invariant_summary
product_layer_review
next_goal
allowed_touch_files
frozen_files
```

출력:

```text
continuation_run_summary.json
failure_classification.json
repair_plan.json
patch_task_packet.md
patch_diff_summary.json
gate_rerun_summary.json
green_base_promotion.json
phase2a_dashboard_summary.json
frozen_hash_before.json
frozen_hash_after.json
frozen_hash_check.json
```

---

## 6.2 Phase 2A에서 자동 patch 허용하는 failure type

자동 patch 1차 허용:

```text
RUNNER_OUTPUT_MISSING_FIELD
PRODUCT_LAYER_NOT_CONSUMING_REPLAY
```

조건부 허용:

```text
STATE_INVARIANT_NOT_EXPOSED
SCENARIO_REPLAY_FAILURE
DETERMINISM_FAILURE
ANTI_HARDCODE_FAILURE
RUNNER_OUTPUT_EXTRA_FIELD
```

조건부 허용 기준:

```text
STATE_INVARIANT_NOT_EXPOSED
- contract invariant가 명확하고 checkable함
- runner/core 내부에는 값이 있음
- final_state 노출만 빠짐
- 의미 변경 없이 snapshot에 추가 가능

SCENARIO_REPLAY_FAILURE
- missing handler
- invalid output schema
- runner command 연결 문제
같은 좁은 원인일 때만 patch

DETERMINISM_FAILURE
- Date.now
- Math.random
- random.random
- time.time
같은 명확한 비결정 패턴일 때만 patch

ANTI_HARDCODE_FAILURE
- fixture id 분기 제거
- expected literal 제거
같은 좁은 원인일 때만 patch

RUNNER_OUTPUT_EXTRA_FIELD
- runner output이 runner_contract를 명백히 위반한 경우만 patch
```

자동 patch 금지:

```text
GOLDEN_SCHEMA_MISMATCH
SPEC_REPAIR_REQUIRED
```

`GOLDEN_SCHEMA_MISMATCH`는 기본적으로 Spec Repair로 보낸다.

---

## 6.3 Patch Lane 금지

```text
contract 직접 수정 금지
fixtures 직접 수정 금지
golden 직접 수정 금지
oracle risk를 낮추기 위한 조작 금지
gate summary 직접 수정 금지
replay output 직접 수정 금지
```

`replay/`는 runner 재실행 결과로 재생성될 수 있지만, patch worker가 직접 작성하면 안 된다.

---

## 6.4 Patch 제한

```text
max_patch_attempts = 2
transient retry/backoff 유지
frozen file 수정 시 patch reject
allowed_touch_files 밖 수정 시 patch reject
```

Patch 후 반드시 실행:

```text
Core Contract Gate
Runner Gate
Scenario Replay Gate
Golden Output Gate
State Invariant Gate
Determinism Gate
Anti-Hardcode Gate
Product Layer Review
Build Review Recompute
factory-validate
```

---

## 6.5 Patch Lane 결과 상태

Patch 결과는 다음 중 하나여야 한다.

```text
PATCH_GREEN
PATCH_PROGRESS
PATCH_BLOCKED_SPEC
PATCH_FAILED
NO_PATCH_ELIGIBLE
```

### PATCH_GREEN

```text
gate 통과
green_base 승격
new_verdict = REVIEW_READY 가능
```

### PATCH_PROGRESS

```text
일부 failure 해결
remaining failure 있음
NEEDS_MORE_GEMMA_LOOP 유지
```

### PATCH_BLOCKED_SPEC

```text
patch 중 spec/golden 문제로 판명
patch 중단
SPEC_REPAIR_REQUIRED로 lane 전환
spec_repair_proposal 생성 가능
apply는 하지 않음
```

### PATCH_FAILED

```text
patch 시도했으나 개선 없음
NEEDS_MORE_GEMMA_LOOP 유지 또는 RUNS_BUT_WEAK
```

### NO_PATCH_ELIGIBLE

```text
patch lane에 안전하게 실행할 대상이 없음
아무 파일도 수정하지 않음
```

---

# 7. Spec Repair Lane — Phase 2A 범위

## 7.1 역할

Spec Repair Lane은 코드 patch로 고치면 안 되는 문제를 분리한다.

Phase 2A에서는 **proposal/review까지만 구현한다.**

Phase 2A에서 금지:

```text
spec repair apply
golden 직접 수정
fixture 직접 수정
contract 직접 수정
comparison_mode 직접 변경
invariant DSL 대개편
```

---

## 7.2 대상

```text
SPEC_REPAIR_REQUIRED verdict
golden_schema_mismatch가 patch로 해결 불가
invariant DSL 문제
scenario/golden이 contract와 불일치
comparison_mode 오류
```

#47은 대표 사례다.

```text
#47 → SPEC_REPAIR lane
reason: golden schema mismatch + invariant DSL issue
```

---

## 7.3 Frozen Hash Guard

Spec Repair Proposal/Review 실행 전후로 frozen file hash를 저장하고 비교한다.

출력:

```text
frozen_hash_before.json
frozen_hash_after.json
frozen_hash_check.json
```

검사 대상:

```text
golden/
fixtures/
core_contract.json
state_contract.json
action_contract.json
runner_contract.json
oracle_risk_report.json
```

결과 규칙:

```text
hash unchanged → PASS
hash changed → FAIL
```

Phase 2A에서 hash가 바뀌면 반드시 validate FAIL이다.

---

## 7.4 Spec Repair Proposal

출력:

```text
spec_repair_proposal.json
spec_repair_proposal.md
```

필수 구조:

```json
{
  "base_run_id": 5,
  "challenge_id": 47,
  "repair_type": "golden_schema | invariant_dsl | comparison_mode | scenario_expected",
  "problem": "",
  "proposed_change": "",
  "why_this_is_spec_problem": "",
  "why_this_is_not_code_patch": "",
  "risk_level": "low | medium | high",
  "requires_human_review": false,
  "apply_allowed_in_phase2a": false
}
```

중요:

```text
apply_allowed_in_phase2a는 항상 false여야 한다.
```

---

## 7.5 Spec Repair Review

출력:

```text
spec_repair_review.json
spec_repair_review.md
```

Review 항목:

```text
수정이 challenge 핵심을 보존하는가
forbidden simplification을 약화하지 않는가
golden을 너무 느슨하게 만들지 않는가
runner/core 결함을 spec 수정으로 덮지 않는가
자동 gate 근거로 사용 가능한가
oracle risk가 높아지는가
```

결과:

```text
APPROVE_FOR_PHASE2B
NEEDS_REVISION
REJECT
REQUIRES_HUMAN_REVIEW
```

Phase 2A에서는 `APPROVE_FOR_PHASE2B`가 나와도 적용하지 않는다.

---

## 7.6 Spec Repair Apply 금지

Phase 2A에서는 다음 파일을 수정하면 안 된다.

```text
golden/
fixtures/
core_contract.json
state_contract.json
action_contract.json
runner_contract.json
oracle_risk_report.json
```

Spec Repair Lane은 proposal/review만 생성한다.

Spec Repair Apply는 Phase 2B에서 별도 주문서로 다룬다.

---

# 8. #47 처리 요구사항

#47은 Phase 2A에서 Spec Repair Lane으로 분류되어야 한다.

기대 결과:

```text
run_id: 5
challenge_id: 47
current verdict: SPEC_REPAIR_REQUIRED
recommended_lane: SPEC_REPAIR
can_patch: false
proposal generated: true
review generated: true
apply performed: false
frozen hash unchanged: true
```

#47에서 다룰 문제:

```text
golden schema mismatch
invariant DSL issue
```

#47에서 하지 말 것:

```text
golden 파일 직접 수정
contract 직접 수정
invariant DSL 즉시 대개편
green_base 억지 승격
patch execute
```

---

# 9. Dashboard 요구사항

Dashboard 대개편은 하지 않는다.

목록 카드에는 기술 세부 로그를 보여주지 않는다.

목록 카드 표시:

```text
추천 경로
이유 한 줄
상태
```

예시 — Spec Repair:

```text
[사양 수리 필요]

추천 경로: Spec Repair
이유: golden schema mismatch / invariant DSL issue
상태: 제안서 생성됨, 적용은 보류
```

예시 — Patch:

```text
[더 돌려야 함]

추천 경로: Patch Continuation
이유: product layer replay 소비 실패
상태: 자동 patch 가능
```

예시 — Excluded:

```text
[제외]

추천 경로: 제외
이유: RUNS_BUT_WEAK / continuation 가치 낮음
상태: 루프 대상 아님
```

상세 페이지에만 다음을 표시한다.

```text
failure types
risk level
blocking reason
proposal/review
patch history
validate result
green promotion status
remaining failures
```

---

# 10. Validate 요구사항

Phase 2A에서는 새 run type을 늘리지 않는다.

기존 continuation validate 구조를 유지하고, lane 필드를 추가한다.

```text
run_type = CONTINUATION_RUN
lane = PATCH_CONTINUATION | SPEC_REPAIR | EXCLUDED | REVIEW_ONLY
```

검증 항목:

```text
lane 존재
기존 run의 inferred_lane 호환성
queue entry 존재 또는 단일 run continuation metadata 존재
recommended lane과 verdict 정합성
patch/spec repair proposal 정합성
gate rerun 정합성
green promotion 정합성
verdict consistency
frozen hash guard 정합성
```

중요 규칙:

```text
SPEC_REPAIR lane은 apply가 없어도 validate PASS 가능하다.
Phase 2A에서 spec 파일이 실제 수정되면 validate FAIL이어야 한다.
APPROVE_FOR_PHASE2B가 있어도 apply가 수행되면 FAIL이다.
Phase 1.7/1.7b 기존 continuation run은 lane이 없어도 inferred_lane으로 PASS 가능하다.
```

Verdict consistency 유지:

```text
gate fail + REVIEW_READY = FAIL
gate fail + PROMOTE_TO_CODEX = FAIL
requires_spec_repair true + REVIEW_READY = FAIL
requires_spec_repair true + SPEC_REPAIR_REQUIRED = PASS 가능
patch transient final failure + NEEDS_MORE_GEMMA_LOOP = PASS 가능
```

---

# 11. CLI 요약

필수 CLI:

```bash
python -m repo_idea_miner factory-continue-queue --dry-run
python -m repo_idea_miner factory-continue-queue --lane patch --dry-run
python -m repo_idea_miner factory-continue-queue --lane spec-repair --dry-run
python -m repo_idea_miner factory-continue-queue --lane patch --dry-run --limit 1
python -m repo_idea_miner factory-continue-queue --lane patch --execute --limit 1
python -m repo_idea_miner factory-continue-queue --lane spec-repair --proposal-only --limit 1
```

기존 유지:

```bash
python -m repo_idea_miner factory-continue --run-id <id>
python -m repo_idea_miner factory-continue --run-dir <path>
python -m repo_idea_miner factory-validate <run_dir>
```

금지:

```bash
python -m repo_idea_miner factory-continue-queue --limit 999
python -m repo_idea_miner factory-continue-queue --execute --limit 2
python -m repo_idea_miner factory-continue-queue --lane spec-repair --execute
python -m repo_idea_miner factory-continue-queue --lane spec-repair --apply
```

---

# 12. 테스트 요구사항

최소 테스트:

```text
1. factory-continue-queue --dry-run 생성
2. dry-run 기본 limit이 20
3. execute 기본/최대 limit이 1
4. --execute 없으면 patch가 실행되지 않음
5. --lane patch --execute --limit 1일 때만 patch 실행
6. --execute --limit 2 이상은 거부
7. spec-repair lane에는 --execute가 허용되지 않음
8. queue entry에 recommended_lane 포함
9. 기존 factory_db.py 조회 구조 재사용
10. DB 우선 run discovery
11. filesystem fallback run discovery
12. 새 DB schema migration 없음
13. run_id 기준 dedupe
14. NEEDS_MORE_GEMMA_LOOP run은 PATCH_CONTINUATION으로 분류
15. SPEC_REPAIR_REQUIRED run은 SPEC_REPAIR로 분류
16. REVIEW_READY는 REVIEW_ONLY 또는 queue 제외
17. RUNS_BUT_WEAK는 EXCLUDED
18. DROP은 EXCLUDED
19. hardcode risk high는 EXCLUDED
20. oracle risk high는 EXCLUDED
21. continuation_base 없으면 EXCLUDED 또는 CANNOT_CONTINUE
22. Patch Lane이 frozen contract/fixtures/golden 수정을 거부
23. Patch Lane이 allowed_touch_files 안에서만 수정
24. Patch Lane도 frozen hash before/after/check 생성
25. Patch Lane에서 frozen hash가 바뀌면 patch reject + validate FAIL
26. Patch Lane 자동 허용 failure type만 patch
27. GOLDEN_SCHEMA_MISMATCH는 기본 SPEC_REPAIR로 분류
28. runner_contract 위반이 명확한 RUNNER_OUTPUT_EXTRA_FIELD만 patch 가능
29. STATE_INVARIANT_NOT_EXPOSED는 checkable + value exists + exposure-only일 때만 patch
30. DSL/contract 자체 문제인 invariant failure는 SPEC_REPAIR
31. PRODUCT_LAYER_NOT_CONSUMING_REPLAY는 Patch Lane 가능
32. Patch 후 gate rerun 수행
33. Patch 결과 PATCH_GREEN 기록 가능
34. Patch 결과 PATCH_PROGRESS 기록 가능
35. Patch 결과 PATCH_BLOCKED_SPEC 기록 가능
36. PATCH_BLOCKED_SPEC이면 recommended_lane이 SPEC_REPAIR로 전환
37. NO_PATCH_ELIGIBLE이면 파일 수정 없음
38. Spec Repair Proposal/Review가 read-only mode로 실행
39. Spec Repair Lane에서 patch writer/apply_patch/edit helper 호출 금지
40. Spec Repair Proposal 생성
41. Spec Repair Review 생성
42. Spec Repair Proposal의 apply_allowed_in_phase2a=false
43. APPROVE_FOR_PHASE2B여도 apply하지 않음
44. Frozen Hash Guard가 before/after/check 파일 생성
45. Phase 2A에서 golden 파일 수정 시 validate FAIL
46. Phase 2A에서 fixtures 수정 시 validate FAIL
47. Phase 2A에서 contract 수정 시 validate FAIL
48. 기존 Phase 1.7/1.7b continuation run은 lane 없어도 inferred_lane으로 validate PASS 가능
49. Phase 2A 이후 생성 run은 lane 없으면 validate FAIL
50. #47이 SPEC_REPAIR lane으로 분류
51. #47 proposal/review 생성
52. #47 apply 미수행
53. #47 frozen hash unchanged 확인
54. #47은 patch execute 대상에서 제외
55. patch-eligible run이 없으면 NO_PATCH_ELIGIBLE
56. Dashboard에 recommended lane 표시
57. Dashboard에 reason 한 줄 표시
58. factory-validate가 lane 필드 검증
59. factory-validate가 inferred_lane 호환성 검증
60. factory-validate가 frozen hash guard 검증
61. SPEC_REPAIR lane proposal-only는 validate PASS 가능
62. gate fail + REVIEW_READY 차단 유지
63. gate fail + PROMOTE_TO_CODEX 차단 유지
64. existing factory-build mock 통과
65. existing factory-continue 단일 run 통과
66. existing continuation validate 통과
67. 기존 Challenge Mode 유지
68. 기존 Dashboard 유지
69. 전체 테스트 통과
70. secret scan 통과
```

---

# 13. 완료 기준

완료 기준:

```text
1. continuation queue dry-run이 동작한다.
2. dry-run 기본 limit은 20이다.
3. execute 기본/최대 limit은 1이다.
4. --execute가 없으면 patch가 실행되지 않는다.
5. run discovery가 기존 DB 구조 우선 + filesystem fallback으로 동작한다.
6. 새 DB schema migration 없이 구현된다.
7. run이 PATCH_CONTINUATION / SPEC_REPAIR / EXCLUDED / REVIEW_ONLY로 분류된다.
8. NEEDS_MORE_GEMMA_LOOP는 patch lane으로 간다.
9. SPEC_REPAIR_REQUIRED는 spec repair lane으로 간다.
10. RUNS_BUT_WEAK / DROP / high risk run은 제외된다.
11. Patch Lane은 safe failure type만 자동 patch한다.
12. Patch Lane은 frozen files를 hash guard로 보호한다.
13. Patch Lane은 gate rerun과 validate를 수행한다.
14. Patch 중 spec 문제 발견 시 PATCH_BLOCKED_SPEC으로 멈추고 SPEC_REPAIR로 전환한다.
15. Spec Repair Lane은 read-only proposal/review까지만 수행한다.
16. Spec Repair Apply는 Phase 2A에서 수행되지 않는다.
17. Frozen Hash Guard가 spec files 불변을 검증한다.
18. 기존 1.7/1.7b continuation run은 lane이 없어도 inferred_lane으로 호환된다.
19. Phase 2A 이후 생성된 continuation run은 lane 필드가 필수다.
20. #47은 spec repair lane으로 분류되고 proposal/review가 생성된다.
21. #47에서 frozen hash가 변하지 않는다.
22. #47은 patch execute 대상이 아니다.
23. patch-eligible run이 없으면 NO_PATCH_ELIGIBLE로 종료한다.
24. Dashboard가 recommended lane과 이유를 보여준다.
25. factory-validate가 lane 정합성, inferred_lane, frozen hash guard를 검증한다.
26. 기존 1.6~1.7b 기능이 깨지지 않는다.
```

---

# 14. 작업 보고 형식

완료 후 아래 형식으로 보고한다.

```text
RIM Product Factory Phase 2A Continuation Queue Routing 작업 보고

Base 상태
- 시작 HEAD:
- 종료 HEAD:
- origin ahead/behind:
- push 여부:

수정 파일
-

Queue Manager
- factory-continue-queue:
- dry-run 기본:
- dry-run limit:
- --execute 동작:
- execute limit:
- DB 우선 discovery:
- filesystem fallback:
- dedupe:
- lane 분류:
- 제외 조건:
- priority:

Lane Routing
- PATCH_CONTINUATION:
- SPEC_REPAIR:
- EXCLUDED:
- REVIEW_ONLY:

Patch Lane
- 대상 run:
- 허용 failure type:
- conditional patch-safe 판정:
- patch attempts:
- frozen hash guard:
- frozen 보호:
- gate rerun:
- result:

Spec Repair Lane
- 대상 run:
- read-only mode:
- proposal:
- review:
- APPROVE_FOR_PHASE2B 여부:
- apply 미수행 확인:
- frozen hash before/after/check:

#47 처리
- before verdict:
- lane:
- patch execute 대상 제외:
- spec repair proposal:
- spec repair review:
- apply performed:
- frozen hash unchanged:
- result:

Backward Compatibility
- 기존 1.7/1.7b continuation lane 없는 run validate:
- inferred_lane:
- Phase 2A 이후 lane 필수화:

Dashboard
- recommended lane 표시:
- reason 표시:
- status 표시:

Validate
- lane field:
- inferred_lane:
- proposal-only SPEC_REPAIR PASS:
- Phase 2A spec file 수정 차단:
- frozen hash guard:
- verdict consistency:

실행 검증
- queue dry-run:
- patch lane dry-run:
- patch lane execute limit 1:
- no patch eligible:
- spec repair proposal-only:
- factory-validate:
- pytest:
- secret scan:

판정
- Phase 2A 완료 여부:
- Phase 2B 착수 가능 여부:
- 아직 남은 항목:
- 후속 추천:
```

---

# 15. Phase 2B로 넘길 항목

Phase 2A에서 하지 않고 Phase 2B로 넘긴다.

```text
Spec Repair Apply
golden 갱신 자동화
invariant DSL 본격 보강
comparison_mode 변경 적용
여러 run limit=3 이상 처리
hidden scenario
full regression expansion
factory 자동 배치 통합
```

---

# 16. 최종 정의

Phase 2A는 continuation을 무작정 많이 돌리는 단계가 아니다.

> RIM Product Factory Phase 2A는 여러 Product Run / Continuation Run을 대상으로 continuation queue를 만들고, NEEDS_MORE_GEMMA_LOOP는 Patch Continuation으로, SPEC_REPAIR_REQUIRED는 Spec Repair Proposal/Review로, RUNS_BUT_WEAK/DROP/high-risk run은 제외로 분류하는 단계다.
> 이 단계에서는 안전한 failure type만 명시적 `--execute` 아래에서 자동 patch하고, contract/fixtures/golden을 수정하는 Spec Repair Apply는 수행하지 않는다.
> 목적은 “계속 고치기”가 아니라, 무엇을 자동 patch로 고치고 무엇을 spec repair로 보낼지 하네스가 안정적으로 판단하게 만드는 것이다.
