# RIM Product Factory Phase 2B-1 외주 주문서

## #47 Spec Repair Apply Single Case

### — Phase 2A proposal을 기반으로 한 첫 사양 수리 적용 및 재검증

## 0. 작업 배경

RIM Product Factory는 Phase 2A에서 continuation queue routing과 lane 분리를 완료했다.

Phase 2A 결과 요약:

```text
- continuation queue dry-run 구현
- PATCH_CONTINUATION / SPEC_REPAIR / EXCLUDED / REVIEW_ONLY lane routing 구현
- #47은 SPEC_REPAIR lane으로 분류됨
- #47 spec_repair_proposal 생성됨
- #47 spec_repair_review 생성됨
- review 결과: APPROVE_FOR_PHASE2B
- apply_allowed_in_phase2a=false
- apply_performed=false
- frozen hash unchanged=true
- validate PASS
```

#47 현재 상태:

```text
base_run_id: 5
challenge_id: 47
challenge_title: Mini-Comfy: 시각적 노드 흐름 엔진
base_run_dir: runs/factory_20260709_072220
current lane: SPEC_REPAIR
current verdict: SPEC_REPAIR_REQUIRED
proposal status: generated
review status: APPROVE_FOR_PHASE2B
apply status: not applied
```

Phase 2A에서는 의도적으로 spec repair를 적용하지 않았다.

이번 Phase 2B-1의 목적은 다음이다.

```text
Phase 2A에서 생성·리뷰된 #47 spec repair proposal을 기준으로,
명시 apply 절차를 통해 golden/schema/invariant 관련 사양 수리를 1건만 적용하고,
모든 core gates와 factory-validate를 재실행하여 green_base 승격 가능 여부를 판단한다.
```

---

# 1. Phase 2B-1의 정확한 정의

Phase 2B-1은 Phase 2B 전체가 아니다.

이번 작업은 **단일 케이스 적용 검증**이다.

```text
대상: #47 한 건
작업: Spec Repair Apply
범위: proposal/review에서 승인된 변경만
목표: apply → gate rerun → validate → green promotion 재판정
```

이번 작업의 핵심 한 줄:

```text
#47의 spec repair proposal을 실제로 적용해도 하네스가 정답지를 느슨하게 만들지 않고,
gate를 다시 통과시키거나 정직하게 실패를 유지할 수 있는지 검증한다.
```

---

# 2. 이번 작업에서 하지 말 것

금지:

```text
- 여러 run/challenge spec repair apply 금지
- queue 전체 spec repair apply 금지
- patch lane live 일반화 금지
- factory 자동 배치 통합 금지
- Codex/Claude 자동 호출 금지
- N-candidate 경쟁 추가 금지
- hidden scenario 대형 시스템 추가 금지
- Dashboard 대개편 금지
- Challenge Mode 파괴 금지
- comparison_mode를 exact에서 partial/contains 등 느슨한 방식으로 자동 완화 금지
- golden을 실패 은폐용으로 완화 금지
- core 구현 결함을 golden 수정으로 덮기 금지
- invariant 실패를 warning/unchecked로 낮춰서 green 승격 금지
```

이번 작업은 오직 다음만 한다.

```text
#47 proposal/review 확인
→ dry-run apply plan 생성
→ pre-apply snapshot 생성
→ 명시 apply
→ spec diff 기록
→ gate rerun
→ validate
→ green promotion 재판정
```

---

# 3. 대상 식별 규칙

Phase 2B-1의 대상은 **challenge_id 47의 Phase 2A SPEC_REPAIR 산출물**이다.

다음 값을 구분해서 기록해야 한다.

```text
challenge_id: 47
base_run_id: 5
base_run_dir: runs/factory_20260709_072220
continuation/history run id: 존재하면 별도 기록
phase2a proposal/review path: base_run_dir 기준
```

주의:

```text
base_run_id와 continuation/history run id를 혼동하지 않는다.
최종 apply 대상 디렉터리를 명확히 출력한다.
```

권장 CLI는 `--run-dir` 기준이다.

```bash
python -m repo_idea_miner factory-spec-repair-apply \
  --run-dir runs/factory_20260709_072220 \
  --dry-run
```

apply도 `--run-dir` 기준을 우선 허용한다.

```bash
python -m repo_idea_miner factory-spec-repair-apply \
  --run-dir runs/factory_20260709_072220 \
  --apply
```

`--run-id 5`는 보조로 허용할 수 있다.

```bash
python -m repo_idea_miner factory-spec-repair-apply \
  --run-id 5 \
  --dry-run
```

단, `--run-id`를 사용할 경우 resolved run_dir를 반드시 출력해야 한다.

---

# 4. 입력 산출물

Phase 2B-1은 Phase 2A 산출물을 입력으로 사용한다.

필수 입력:

```text
runs/factory_20260709_072220/spec_repair_proposal.json
runs/factory_20260709_072220/spec_repair_proposal.md
runs/factory_20260709_072220/spec_repair_review.json
runs/factory_20260709_072220/spec_repair_review.md
runs/factory_20260709_072220/frozen_hash_before.json
runs/factory_20260709_072220/frozen_hash_after.json
runs/factory_20260709_072220/frozen_hash_check.json
continuation_run_summary.json
failure_classification.json
repair_plan.json
green_base_promotion.json
gate_rerun_summary.json
```

필수 조건:

```text
review result = APPROVE_FOR_PHASE2B
apply_allowed_in_phase2a = false
apply_performed = false
current lane = SPEC_REPAIR
current verdict = SPEC_REPAIR_REQUIRED
```

위 조건이 충족되지 않으면 apply하지 않는다.

판정:

```text
CANNOT_APPLY_SPEC_REPAIR
```

---

# 5. 핵심 수리 대상

#47의 수리 대상은 Phase 2A proposal/review를 기준으로 한다.

현재 알려진 주요 문제:

```text
1. golden schema mismatch
   - runner/core가 표현하는 graph state와 golden expected schema가 맞지 않음

2. invariant DSL issue
   - invariant 검사기가 final_state의 top-level dict 또는 필요한 path/length 구조를 충분히 해석하지 못함
```

단, 이번 작업자는 임의로 해석해 수정하지 않는다.

원칙:

```text
spec_repair_proposal.json과 spec_repair_review.json의 근거를 먼저 읽고,
그 안에서 승인된 변경만 적용한다.
```

---

# 6. Pre-apply Snapshot / Rollback 요구사항

Spec Repair Apply는 frozen/spec 파일을 실제로 수정하는 단계다.
따라서 apply 전 반드시 되돌릴 수 있는 snapshot을 남긴다.

## 6.1 Snapshot 대상

apply 전 다음 파일/디렉터리의 snapshot manifest를 생성한다.

```text
golden/
fixtures/
core_contract.json
state_contract.json
action_contract.json
runner_contract.json
oracle_risk_report.json
invariant DSL 관련 파일
comparison/gate 관련 invariant evaluator 파일
```

## 6.2 필수 산출물

```text
pre_apply_snapshot_manifest.json
rollback_plan.json
```

apply 실패 또는 forbidden change 발견 시 추가 산출물:

```text
rollback_report.json
```

## 6.3 Rollback 정책

다음 상황에서는 rollback 가능 상태를 보장해야 한다.

```text
apply 중 예외 발생
proposal/review 범위 밖 파일 변경
forbidden change 발견
factory-validate 실패
gate rerun 결과와 green promotion 결과 모순
```

자동 rollback을 수행할지는 구현 판단에 맡긴다.
단, 최소한 **rollback_plan.json**은 반드시 남겨야 한다.

권장:

```text
apply 중 예외 또는 forbidden change 발견 시 자동 rollback
gate fail 자체는 자동 rollback 대상이 아님
```

gate fail은 spec repair가 잘못됐다는 뜻이 아닐 수 있으므로, 정직한 verdict로 남길 수 있다.

---

# 7. Spec Repair Apply 원칙

## 7.1 적용 가능한 변경

허용:

```text
golden expected schema 보정
state invariant 표현 보정
invariant DSL의 최소 path/length 해석 보강
runner/golden 비교 schema 정합 보정
oracle_risk_report 갱신
spec repair metadata 갱신
```

단, 모두 proposal/review에 근거가 있어야 한다.

---

## 7.2 적용 금지 변경

금지:

```text
challenge 핵심 변경
forbidden simplification 삭제 또는 완화
golden expected를 느슨하게 만들어 실패를 숨김
comparison_mode를 exact에서 partial/contains 등으로 완화
core 구현 오류를 golden 수정으로 덮음
runner/core를 spec repair 명목으로 임의 수정
product UI 수정
대상 외 challenge 수정
scenario 수 감소
golden expected field 삭제
invariant failure를 warning/unchecked로 낮춤
```

---

# 8. Golden 수정 엄격 기준

Golden은 “통과시키기 위해” 수정하지 않는다.

Golden 수정은 다음 중 하나에 해당할 때만 허용한다.

```text
1. golden이 contract의 required output/state field를 누락했다.
2. scenario action 결과상 반드시 존재해야 하는 state가 golden에 없다.
3. runner output이 contract와 scenario에 일관되고, golden만 뒤처져 있다.
```

추가 조건:

```text
- golden 수정이 challenge 핵심을 약화하지 않아야 한다.
- 새 golden은 scenario action 결과를 더 정확히 표현해야 한다.
- 변경 diff는 spec_repair_diff_summary.json에 설명되어야 한다.
```

금지:

```text
- failing field를 삭제해서 PASS 만들기
- expected value를 null/empty로 바꿔 PASS 만들기
- exact comparison을 partial/contains로 완화
- scenario별로 다른 느슨한 expected를 만드는 것
- core 구현 결함을 golden expected 변경으로 덮기
```

## 8.1 #47 edges 처리 원칙

#47의 `edges` 문제는 다음 규칙으로 처리한다.

```text
edges가 contract와 scenario상 필수 graph state라면 golden에 추가 가능하다.
edges가 runner debug/output noise라면 golden을 고치지 말고 runner output schema 문제로 되돌린다.
```

판단 근거는 반드시 `spec_repair_diff_summary.json`에 기록한다.

---

# 9. Invariant DSL 최소 보강 기준

Phase 2B-1의 invariant DSL 보강은 **#47에서 필요한 최소 path/length 해석**만 허용한다.

허용:

```text
final_state.<field>
final_state.<field>.length
dict/list의 단순 length
missing path와 empty list/dict 구분
INVARIANT_NOT_EXPOSED와 INVARIANT_FAIL 구분 유지
```

금지:

```text
arbitrary expression evaluator
복잡한 predicate language
JavaScript/Python eval
nested query language 대개편
invariant 실패를 warning으로 낮추기
missing path를 자동 PASS 처리
check 불가능한 invariant를 성공 처리
```

원칙:

```text
이번 단계는 invariant DSL 대개편이 아니다.
#47 green 재검증에 필요한 최소 기능만 추가한다.
```

---

# 10. CLI 요구사항

Phase 2B-1은 queue apply가 아니다.

명시적 단일 run apply 명령을 추가한다.

권장 CLI:

```bash
python -m repo_idea_miner factory-spec-repair-apply \
  --run-dir runs/factory_20260709_072220 \
  --dry-run

python -m repo_idea_miner factory-spec-repair-apply \
  --run-dir runs/factory_20260709_072220 \
  --apply
```

보조 CLI:

```bash
python -m repo_idea_miner factory-spec-repair-apply \
  --run-id 5 \
  --dry-run

python -m repo_idea_miner factory-spec-repair-apply \
  --run-id 5 \
  --apply
```

단, 다음 조건을 반드시 지킨다.

```text
- run-dir 또는 run-id 명시 필수
- run-id 사용 시 resolved run_dir 출력 필수
- 기본은 dry-run
- --apply 없으면 파일 수정 금지
- --apply는 run 1개에만 허용
- queue 전체 apply 금지
- --all 금지
- --limit 2 이상 apply 금지
- review result가 APPROVE_FOR_PHASE2B가 아니면 apply 금지
```

금지 CLI:

```bash
python -m repo_idea_miner factory-continue-queue --lane spec-repair --apply
python -m repo_idea_miner factory-continue-queue --lane spec-repair --apply --limit 10
python -m repo_idea_miner factory-spec-repair-apply --all
```

---

# 11. Dry-run 요구사항

`--dry-run`은 실제 파일을 수정하지 않고 apply 계획만 출력한다.

출력:

```text
spec_repair_apply_plan.json
spec_repair_apply_plan.md
```

포함 항목:

```text
base_run_id
challenge_id
resolved_run_dir
proposal path
review path
review result
planned files to modify
planned changes
risk level
why safe to apply
blocked reasons if any
```

dry-run에서 실제 파일 hash가 바뀌면 실패다.

판정:

```text
DRY_RUN_PASS
DRY_RUN_BLOCKED
```

---

# 12. Apply 요구사항

`--apply`는 review 승인된 변경만 적용한다.

적용 전:

```text
1. proposal/review 재검증
2. resolved_run_dir 출력
3. pre_apply_snapshot_manifest 생성
4. rollback_plan 생성
5. frozen hash before apply 생성
6. target files 목록 확정
7. forbidden changes 사전 검사
8. apply plan 저장
```

적용 후:

```text
1. spec_repair_apply_report 생성
2. spec_repair_diff_summary 생성
3. frozen hash after apply 생성
4. frozen hash apply check 생성
5. forbidden changes 사후 검사
6. gate rerun
7. factory-validate
8. green promotion check
```

---

# 13. 산출물 요구사항

Phase 2B-1은 다음 산출물을 생성한다.

```text
spec_repair_apply_plan.json
spec_repair_apply_plan.md
spec_repair_apply_report.json
spec_repair_apply_report.md
spec_repair_diff_summary.json
pre_apply_snapshot_manifest.json
rollback_plan.json
rollback_report.json if rollback executed
frozen_hash_before_apply.json
frozen_hash_after_apply.json
frozen_hash_apply_check.json
gate_rerun_after_spec_repair.json
green_base_promotion_after_spec_repair.json
phase2b1_dashboard_summary.json
```

---

# 14. Gate Re-run 요구사항

Spec Repair Apply 후 반드시 다음을 재실행한다.

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

중요:

```text
Spec Repair Apply 후 gate를 재실행하지 않고 REVIEW_READY 또는 green_base를 만들면 안 된다.
```

---

# 15. Green Promotion 판정

## 15.1 승격 가능 조건

다음 조건을 모두 만족해야 green_base 승격 가능하다.

```text
Core Contract Gate PASS
Runner Gate PASS
Scenario Replay Gate PASS
Golden Output Gate PASS
State Invariant Gate PASS
Determinism Gate PASS
Anti-Hardcode risk high 아님
Product Layer Review PASS
factory-validate PASS
oracle risk high 아님
```

승격 시:

```text
promoted_to_green_base = true
new_verdict = REVIEW_READY
```

---

## 15.2 Green 승격 추가 금지 조건

다음 중 하나라도 있으면 green_base 승격 금지다.

```text
comparison_mode가 느슨해짐
forbidden_simplifications가 줄어듦
scenario 수가 줄어듦
golden expected field가 삭제됨
oracle_risk가 상승했는데 REVIEW_READY로 판정
spec_repair_review가 REQUIRES_HUMAN_REVIEW
proposal/review 범위 밖 파일 변경
invariant failure가 warning/unchecked로 낮아짐
factory-validate FAIL
gate fail 존재
```

이 경우 gate 일부가 PASS하더라도 green_base로 승격하지 않는다.

---

## 15.3 승격 실패 조건

승격 실패 시 다음 중 하나로 정직하게 남긴다.

```text
NEEDS_MORE_GEMMA_LOOP
SPEC_REPAIR_REQUIRED
RUNS_BUT_WEAK
DROP
REQUIRES_HUMAN_REVIEW
```

예:

```text
Spec Repair Apply 후 golden은 해결됐지만 invariant가 여전히 실패
→ NEEDS_MORE_GEMMA_LOOP 또는 SPEC_REPAIR_REQUIRED

Spec Repair Apply가 challenge 핵심을 약화할 위험 발견
→ REQUIRES_HUMAN_REVIEW 또는 SPEC_REPAIR_REQUIRED

Core 구현 결함으로 판명
→ NEEDS_MORE_GEMMA_LOOP
```

중요:

```text
green_base 승격 실패 자체는 작업 실패가 아니다.
정직한 verdict가 더 중요하다.
```

---

# 16. Dashboard 요구사항

Dashboard 대개편은 하지 않는다.

목록 카드 최소 표시:

```text
추천 경로: Spec Repair Apply
상태: 적용됨 / 적용 보류 / 재검증 실패 / Green 승격
이유: golden schema + invariant DSL 수리
```

상세 페이지 표시:

```text
spec repair proposal
spec repair review
apply plan
apply report
diff summary
snapshot/rollback 정보
gate rerun after apply
green promotion after apply
remaining failures
factory-validate result
```

---

# 17. Validate 요구사항

`factory-validate`는 Phase 2B-1 산출물을 인식해야 한다.

검증 항목:

```text
spec_repair_apply_plan 존재
spec_repair_apply_report 존재
spec_repair_diff_summary 존재
pre_apply_snapshot_manifest 존재
rollback_plan 존재
review result가 APPROVE_FOR_PHASE2B였는지 확인
apply가 단일 대상이었는지 확인
resolved_run_dir 정합성 확인
forbidden changes 없음
comparison_mode 완화 없음
scenario 수 감소 없음
golden expected field 삭제 없음
golden/contract 변경이 proposal/review 범위 안인지 확인
invariant failure warning화 없음
gate rerun 결과와 green promotion 결과 정합성 확인
```

중요 규칙:

```text
apply 후 gate fail + REVIEW_READY = validate FAIL
apply 후 gate fail + PROMOTE_TO_CODEX = validate FAIL
apply 후 validate fail + green_base = validate FAIL
comparison_mode 완화 + REVIEW_READY = validate FAIL
proposal/review 범위 밖 파일 변경 = validate FAIL
golden expected field 삭제 + REVIEW_READY = validate FAIL
scenario 수 감소 + REVIEW_READY = validate FAIL
invariant warning화 + REVIEW_READY = validate FAIL
```

---

# 18. 테스트 요구사항

최소 테스트:

```text
1. factory-spec-repair-apply --run-dir runs/factory_20260709_072220 --dry-run 동작
2. factory-spec-repair-apply --run-id 5 --dry-run 동작
3. run-id 사용 시 resolved_run_dir 출력
4. dry-run은 파일을 수정하지 않음
5. dry-run 후 frozen hash unchanged
6. review result가 APPROVE_FOR_PHASE2B가 아니면 apply 거부
7. --apply 없이 파일 수정 금지
8. --apply는 run-dir 또는 run-id 필수
9. --apply는 단일 run만 허용
10. --all apply 금지
11. queue 전체 spec apply 금지
12. spec_repair_apply_plan 생성
13. spec_repair_apply_report 생성
14. spec_repair_diff_summary 생성
15. pre_apply_snapshot_manifest 생성
16. rollback_plan 생성
17. apply 중 예외 시 rollback_report 생성 가능
18. proposal/review 범위 밖 변경 차단
19. comparison_mode 완화 차단
20. forbidden simplification 변경 차단
21. scenario 수 감소 차단
22. golden expected field 삭제 차단
23. golden schema 보정 허용
24. edges가 contract상 필수 graph state일 때만 golden 추가 허용
25. edges가 runner debug noise이면 golden 수정 금지
26. invariant DSL 최소 path 해석 보강 허용
27. final_state.<field> 해석
28. final_state.<field>.length 해석
29. dict/list 단순 length 해석
30. missing path를 PASS 처리하지 않음
31. INVARIANT_NOT_EXPOSED와 INVARIANT_FAIL 구분 유지
32. arbitrary eval 금지
33. 복잡한 predicate language 금지
34. apply 후 7개 core gates 재실행
35. apply 후 product layer review 재실행
36. apply 후 build review 재계산
37. apply 후 factory-validate 실행
38. gate fail + REVIEW_READY 차단
39. gate fail + PROMOTE_TO_CODEX 차단
40. validate fail + green_base 차단
41. comparison_mode 완화 + REVIEW_READY 차단
42. golden expected field 삭제 + REVIEW_READY 차단
43. invariant warning화 + REVIEW_READY 차단
44. green promotion 조건 충족 시 REVIEW_READY 가능
45. green promotion 조건 미달 시 정직한 verdict 유지
46. #47 apply plan 생성
47. #47 apply report 생성
48. #47 golden/invariant 문제 재검증
49. #47 green promotion 재판정
50. 기존 Phase 2A queue dry-run 유지
51. 기존 Phase 2A spec proposal-only 유지
52. 기존 factory-continue 단일 run 유지
53. 기존 factory-validate continuation 호환 유지
54. 기존 Product Dashboard 유지
55. 기존 Challenge Mode 유지
56. 전체 테스트 통과
57. secret scan 통과
```

---

# 19. 완료 기준

완료 기준:

```text
1. #47 spec repair proposal/review를 입력으로 읽는다.
2. base_run_id와 continuation/history run id를 구분해 기록한다.
3. --run-dir 기준 dry-run apply plan을 생성한다.
4. --run-id 사용 시 resolved_run_dir를 출력한다.
5. dry-run에서는 파일이 수정되지 않는다.
6. review가 APPROVE_FOR_PHASE2B일 때만 apply 가능하다.
7. --apply는 #47 단일 대상에만 명시적으로 수행된다.
8. pre-apply snapshot과 rollback_plan을 생성한다.
9. proposal/review 범위 밖 변경은 차단된다.
10. golden schema 보정이 엄격 기준 안에서 적용된다.
11. edges는 contract상 필수 graph state일 때만 golden에 추가된다.
12. invariant DSL은 #47에 필요한 최소 path/length 해석만 보강된다.
13. comparison_mode 완화는 발생하지 않는다.
14. forbidden simplification 약화는 발생하지 않는다.
15. scenario 수 감소는 발생하지 않는다.
16. golden expected field 삭제는 발생하지 않는다.
17. invariant failure warning화는 발생하지 않는다.
18. apply 후 모든 gates를 재실행한다.
19. apply 후 factory-validate를 실행한다.
20. green_base 승격 여부를 정직하게 판단한다.
21. 승격 실패 시에도 정확한 verdict를 남긴다.
22. Dashboard에 apply 결과와 gate rerun 결과가 표시된다.
23. 기존 Phase 2A 기능이 깨지지 않는다.
```

---

# 20. 작업 보고 형식

완료 후 아래 형식으로 보고한다.

```text
RIM Product Factory Phase 2B-1 #47 Spec Repair Apply 작업 보고

Base 상태
- 시작 HEAD:
- 종료 HEAD:
- origin ahead/behind:
- push 여부:

수정 파일
-

대상 식별
- challenge_id:
- base_run_id:
- base_run_dir:
- continuation/history run id:
- resolved_run_dir:
- proposal path:
- review path:
- review result:
- current verdict:

Dry-run
- command:
- apply plan:
- planned files:
- frozen hash unchanged:
- result:

Pre-apply Snapshot / Rollback
- snapshot manifest:
- rollback plan:
- rollback executed:
- rollback report:

Apply
- command:
- applied files:
- diff summary:
- forbidden change check:
- comparison_mode change:
- scenario count change:
- golden expected field deletion:
- invariant warning downgrade:
- apply report:

Spec Repair 내용
- golden schema repair:
- edges 판단:
- invariant DSL repair:
- oracle risk update:
- out-of-scope changes:

Gate Re-run
- Core Contract:
- Runner:
- Scenario Replay:
- Golden Output:
- State Invariant:
- Determinism:
- Anti-Hardcode:
- Product Layer Review:
- Build Review:
- factory-validate:

Green Promotion
- promoted_to_green_base:
- new verdict:
- remaining failures:
- next_goal:

Dashboard
- list card:
- detail page:
- report tabs:

테스트
- pytest:
- secret scan:

판정
- Phase 2B-1 완료 여부:
- #47 green 승격 여부:
- 아직 남은 항목:
- 후속 추천:
```

---

# 21. Phase 2B-1 성공의 의미

Phase 2B-1의 성공은 반드시 #47이 green으로 승격되는 것을 뜻하지 않는다.

성공 기준은 다음이다.

```text
- approved proposal만 적용한다.
- 정답지를 느슨하게 만들지 않는다.
- apply 전 snapshot/rollback 가능성을 확보한다.
- golden schema를 엄격 기준 안에서만 보정한다.
- invariant DSL을 필요한 만큼만 보강한다.
- 모든 gate를 다시 실행한다.
- green 승격 여부를 정직하게 판단한다.
```

따라서 가능한 성공 결과는 두 가지다.

```text
A. gate 통과 → #47 green_base 승격
B. 일부 실패 유지 → 정직한 NEEDS_MORE_GEMMA_LOOP 또는 SPEC_REPAIR_REQUIRED 유지
```

둘 다 Phase 2B-1의 정상 결과다.

---

# 22. 최종 정의

> RIM Product Factory Phase 2B-1은 Phase 2A에서 생성된 #47 Spec Repair Proposal/Review를 입력으로 받아, 승인된 사양 수리만 명시 apply하고, golden schema 및 invariant DSL 문제를 최소 범위로 보정한 뒤, 모든 core gates와 factory-validate를 재실행하여 #47의 green_base 승격 가능 여부를 정직하게 판단하는 단일 케이스 검증 단계다.
> 이 단계는 여러 run에 대한 spec repair 자동화가 아니며, Phase 2B 전체도 아니다. 목적은 “정답지를 느슨하게 고쳐 통과시키는 것”이 아니라, proposal/review 기반 사양 수리가 안전하게 적용되고 재검증되는지를 증명하는 것이다.
