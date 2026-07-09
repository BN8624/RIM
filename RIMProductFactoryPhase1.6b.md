# RIM Product Factory Phase 1.6b 외주 주문서

## Live Challenge Validation + Gate Hardening

### — Core-first Review-Repair Harness 실전 검증 및 약한 게이트 보강

## 0. 작업 목적

RIM Product Factory Phase 1.6에서는 Core-first Review-Repair Harness가 구현되었다.

현재 상태:

```text id="b1x6qr"
- mock 기준 factory-build 완주
- Core Contract / Scenario / Golden / Runner / Product Layer 생성
- 7개 Core Gate 실행
- Review-Repair 제한 적용
- Dashboard Summary 생성
- Green Base 저장
```

하지만 아직 중요한 검증이 남아 있다.

```text id="lo1hgy"
mock 성공은 하네스 배관 성공일 뿐이다.
live Gemma 산출물을 실제로 끌어올리는지,
허접한 결과물을 냉정하게 낮추는지는 아직 검증되지 않았다.
```

이번 Phase 1.6b의 목적은 다음이다.

```text id="me0f1u"
1. live challenge 1건으로 Phase 1.6 harness를 실전 검증한다.
2. live 결과에서 gate가 약하게 통과하는 지점을 찾는다.
3. Core Contract Gate / Product Layer Gate / Green Base / Patch Review / Validate를 보강한다.
4. Phase 2 성장 루프에 들어가기 전, 첫 시제품 바닥선이 실제로 작동하는지 확인한다.
```

---

# 1. 이번 작업의 정확한 범위

이번 작업은 Phase 2가 아니다.

이번 작업에서 하지 말 것:

```text id="yz8rwk"
- Phase 2 continuation loop 구현 금지
- factory 자동 배치를 1.6 harness로 무리하게 통합 금지
- 새로운 대시보드 대개편 금지
- N-candidate 경쟁 시스템 추가 금지
- Contract/Scenario/Golden 후보 경쟁 추가 금지
- Codex/Claude 자동 호출 금지
- hidden scenario 대형 시스템 구현 금지
- Product Factory 전체 재작성 금지
```

이번 작업의 범위:

```text id="knpyw3"
- live challenge 1건 실행
- 결과물 실제 품질 검토
- 약한 gate 보강
- 관련 테스트 추가
- Dashboard 표시 최소 보강
- factory-validate 정합성 보강
- Phase 2 전제 조건 정리
```

---

# 2. 핵심 판단 기준

이번 작업의 성공 기준은 `REVIEW_READY`가 나오는 것이 아니다.

성공 기준은 **판정이 정직한가**다.

예:

```text id="p4nfw7"
좋은 결과 → REVIEW_READY
고칠 만한 결과 → NEEDS_MORE_GEMMA_LOOP
얕은 결과 → RUNS_BUT_WEAK
무너진 결과 → DROP
```

실패 사례:

```text id="ws4jk0"
runner가 약한데 REVIEW_READY
product layer가 replay를 실제로 안 쓰는데 REVIEW_READY
contract가 문자열로만 맞는데 REVIEW_READY
scenario/golden이 엉성한데 REVIEW_READY
hardcode/stub 의심인데 REVIEW_READY
```

즉 이번 1.6b는 “좋은 결과를 억지로 만들기”가 아니라:

```text id="ec3tgx"
하네스가 좋은 결과와 나쁜 결과를 제대로 구분하는지 검증하는 작업
```

이다.

---

# 3. Live Challenge Validation

## 3.1 대상 선택

live 검증은 1건만 수행한다.

대상 우선순위:

```text id="x0b5d1"
1. 이전에 실제 실행 결과가 실망스러웠던 challenge
2. 기존 Product Dashboard에서 REVIEW_READY 또는 PROMOTE 계열로 높게 나온 challenge
3. 최근 Challenge 중 core artifact로 분류 가능한 challenge
```

금지:

```text id="t0hwcl"
너무 쉬운 TODO/CRUD/list/dashboard 샘플 금지
VIEWER_ONLY로 끝나는 challenge 금지
mock sample을 live 검증으로 대체 금지
```

선택한 challenge는 보고서에 명시한다.

```text id="eaboye"
challenge_id:
challenge_title:
선택 이유:
기존 verdict if any:
```

---

## 3.2 실행 명령

기본 명령:

```bash id="0knca6"
python -m repo_idea_miner factory-build --challenge-id <id> --mode live
```

또는 기존 CLI 인자 구조에 맞게 동일 의미로 실행한다.

정책:

```text id="azshz7"
live 기본 candidates = 1
mock candidates로 대체 금지
API key 출력 금지
secret 로그 출력 금지
실패해도 key 내용 출력 금지
```

---

## 3.3 Live 검증 산출물

live run 후 다음을 확인한다.

```text id="gzybcz"
core_artifact_classification.json
core_contract.json
state_contract.json
action_contract.json
runner_contract.json
fixtures/scenario_*.json
golden/expected_*.json
oracle_risk_report.json
runner_summary.json
scenario_replay_summary.json
golden_diff_summary.json
state_invariant_summary.json
determinism_summary.json
anti_hardcode_summary.json
product_layer_review.json
product_eval_summary.json
dashboard_summary.json
green_base 또는 continuation_base 관련 파일
```

---

## 3.4 Live 결과 수동 검토

실행 결과를 사람이 확인할 수 있게 다음을 보고한다.

```text id="xe7k1o"
- run directory
- final_artifact path
- 실행 명령
- runner 실행 결과 요약
- product layer 실행 방법
- dashboard에서 표시되는 한국어 요약
- 최종 verdict
- verdict가 정직한지에 대한 작업자 판단
```

중요:

```text id="4j6x14"
작업자는 “좋아 보인다”만 쓰면 안 된다.
어떤 gate가 무엇을 근거로 통과했는지,
실행 결과가 verdict와 맞는지 구체적으로 적는다.
```

---

# 4. Gate Hardening 1 — Core Contract Gate 보강

## 4.1 현재 문제

현재 Core Contract Gate가 단순 문자열 포함 검사에 가까우면 약하다.

문제:

```text id="8qkqhf"
action name이 주석에만 있어도 통과 가능
state entity가 unused string으로 있어도 통과 가능
runner가 실제 action/state를 쓰지 않아도 통과 가능
dead code로 contract를 만족하는 척할 수 있음
```

---

## 4.2 보강 목표

Core Contract Gate는 최소한 다음을 확인해야 한다.

```text id="q13wy6"
1. contract의 action이 실제 callable function/handler로 존재한다.
2. runner가 scenario action을 해당 action handler로 dispatch한다.
3. action 실행 후 final_state 또는 events가 변한다.
4. state entity가 runner output final_state에 반영된다.
5. contract의 required output fields가 실제 runner output에 존재한다.
```

---

## 4.3 구현 방향

프로젝트 타입별로 가능한 범위에서 구현한다.

Node/JS의 경우:

```text id="xov5kz"
- src/core 또는 src/engine 파일에서 export/module.exports 검사
- runner가 core/engine module을 import/require하는지 검사
- scenario action type이 dispatch table 또는 handler 호출로 연결되는지 검사
- runner output final_state/events에 contract entity/action 흔적이 있는지 검사
```

Python의 경우:

```text id="p6z2sz"
- ast로 function/class 정의 검사
- runner가 core module을 import하는지 검사
- action name과 function/dispatch 연결 검사
- runner output final_state/events 반영 검사
```

단순 문자열 scan은 보조 검사로만 사용한다.

---

## 4.4 실패 조건

다음은 Core Contract Gate 실패 또는 PARTIAL이어야 한다.

```text id="8wsi5g"
action name이 주석/문자열에만 있음
runner가 core module을 import하지 않음
runner가 scenario action을 실제 handler로 넘기지 않음
final_state가 항상 고정값
events가 항상 고정값
state entity가 output에 반영되지 않음
```

---

# 5. Gate Hardening 2 — Product Layer Gate 보강

## 5.1 현재 문제

Product Layer가 `"replay"` 또는 `"runner"`라는 문자열만 포함해도 통과하면 약하다.

문제:

```text id="tb3hmt"
주석에 replay라고 써도 통과
README에 runner라고 써도 통과
실제로 replay/index.json을 읽지 않아도 통과
core output을 렌더링하지 않아도 통과
viewer 안에 별도 fake data를 넣어도 통과
```

---

## 5.2 보강 목표

Product Layer는 실제로 core output을 소비해야 한다.

최소 조건:

```text id="zjmbat"
1. product layer가 replay/index.json 또는 runner output artifact를 실제로 읽는다.
2. final_state / events / summary 중 최소 2개 이상을 표시한다.
3. product layer 내부에 별도 fake state를 만들지 않는다.
4. core logic을 product layer 안에 복제하지 않는다.
5. product layer와 runner/core가 분리되어 있다.
```

---

## 5.3 검사 방법

정적 검사:

```text id="8p8zr2"
- product/viewer 파일에서 replay/index.json 또는 equivalent artifact path 접근 검사
- final_state/events/summary field 사용 검사
- hardcoded demo data 검사
- core logic function 복제 의심 검사
```

가능하면 간단 실행 검사:

```text id="f10lmw"
- replay/index.json에 unique marker를 넣은 테스트 fixture 생성
- product layer source 또는 rendered output이 해당 marker를 참조/표시하는지 확인
```

Phase 1.6b에서는 브라우저 자동화까지 요구하지 않는다.
다만 HTML/JS 정적 구조상 replay output을 소비하는지 확인해야 한다.

---

## 5.4 실패 조건

다음은 Product Layer Review 실패 또는 NEEDS_REPAIR이어야 한다.

```text id="nsjzf9"
replay/runner 문자열만 있고 실제 파일 접근 없음
final_state/events/summary를 표시하지 않음
product layer에 fake sample state만 있음
core logic을 viewer 안에 다시 구현
runner output과 product layer 표시가 불일치
```

---

# 6. Gate Hardening 3 — Green Base 명칭/조건 보강

## 6.1 현재 문제

모든 gate가 PASS가 아니어도 patchable이면 `green_base`가 저장될 수 있다면 명칭이 위험하다.

문제:

```text id="e9b5ny"
gate 일부 실패 상태인데 green_base라고 부르면 Phase 2에서 품질 기준이 흐려질 수 있음
```

---

## 6.2 변경 정책

base를 두 종류로 구분한다.

```text id="bjtuxm"
green_base
- 모든 필수 core gate 통과
- product layer review PASS
- hardcode risk low 또는 medium
- Phase 2에서 regression 기준으로 삼을 수 있음

repair_base 또는 continuation_base
- core_contract와 runner는 있으나 일부 gate 실패
- NEEDS_MORE_GEMMA_LOOP 대상
- Phase 2에서 수정 시작점으로는 쓸 수 있지만 green이라고 부르면 안 됨
```

---

## 6.3 저장 조건

green_base 저장 조건:

```text id="o277mf"
Core Contract Gate PASS
Runner Gate PASS
Scenario Replay Gate PASS
Golden Output Gate PASS 또는 허용 가능한 PARTIAL
State Invariant Gate PASS
Determinism Gate PASS
Anti-Hardcode risk high 아님
Product Layer Review PASS
```

continuation_base 저장 조건:

```text id="9q5wf0"
Core Contract Gate PASS
Runner Gate PASS
next_goal 구체적
patchable true
hardcode risk high 아님
```

---

## 6.4 Dashboard 표시

Dashboard에는 구분해서 표시한다.

```text id="rfs7l7"
Green Base: 있음 / 없음
Continuation Base: 있음 / 없음
```

한국어 예시:

```text id="lxmtor"
성장 루프 기준점: 준비됨
수정 시작점: 준비됨
```

또는:

```text id="r1d5we"
성장 루프 기준점: 아직 아님
수정 시작점: 있음
```

---

# 7. Gate Hardening 4 — Patch 후 Build Review 재계산

## 7.1 현재 문제

Patch 후 gate 결과가 바뀌는데 Build Review가 최초 결과에 묶여 있으면 판단이 낡을 수 있다.

문제:

```text id="dqg3e0"
1차 patch 후 실패 항목이 달라짐
하지만 patch_instructions는 이전 review 기준
2차 patch가 엉뚱한 문제를 고칠 수 있음
```

---

## 7.2 보강 목표

Patch 후에는 gate 재실행뿐 아니라 Build Review도 다시 계산한다.

흐름:

```text id="r8hpcg"
Core Build
→ Gates
→ Build Review
→ Patch
→ Gates 재실행
→ Build Review 재계산
→ 필요 시 Patch 2
→ Gates 재실행
→ Build Review 최종
```

---

## 7.3 테스트 조건

테스트는 다음을 포함한다.

```text id="adsrzo"
1. 첫 gate 실패 A 발생
2. patch 후 A는 해결되고 B가 남음
3. 두 번째 Build Review가 B를 기준으로 patch instruction을 생성
```

---

# 8. Gate Hardening 5 — factory-validate 경로 정합성 보강

## 8.1 현재 문제

core run 검증에서 `workspace`와 `final_artifact`가 어긋날 경우 검증이 약해질 수 있다.

---

## 8.2 보강 목표

`factory-validate`는 core run에서 다음을 모두 확인해야 한다.

```text id="h4qqkp"
workspace artifact 존재
final_artifact artifact 존재
둘의 핵심 파일 정합성
final_artifact 기준으로 사용자 실행 가능
dashboard_summary가 final_artifact path를 가리킴
run_instructions가 final_artifact 기준으로 맞음
```

---

## 8.3 실패 조건

다음은 validate 실패여야 한다.

```text id="u9qn3x"
workspace에는 있는데 final_artifact에는 없음
final_artifact에는 있는데 dashboard_summary가 workspace만 가리킴
run_instructions가 존재하지 않는 경로를 가리킴
core summaries가 workspace 기준인데 final_artifact와 불일치
```

---

# 9. Live 결과 기반 Verdict 검증

Live challenge 1건 실행 후, 다음 판정 검증표를 작성한다.

```text id="pdbsoi"
항목:
- core contract가 실제 runner 동작과 연결되는가
- scenario replay가 의미 있는가
- golden이 너무 쉬운가
- product layer가 core output을 실제로 보여주는가
- hardcode/stub 위험이 있는가
- verdict가 결과 품질과 맞는가
```

결과 형식:

```json id="voavwc"
{
  "live_validation": {
    "challenge_id": "",
    "run_id": "",
    "verdict": "",
    "verdict_is_honest": true,
    "overrated": false,
    "underrated": false,
    "issues_found": [],
    "gate_hardening_applied": []
  }
}
```

---

# 10. Dashboard 최소 보강

Dashboard 대개편은 하지 않는다.

필수 보강:

```text id="rz8i58"
- Core Contract Gate 세부 결과 표시
- Product Layer가 replay/runner output을 실제 소비했는지 표시
- Green Base와 Continuation Base 구분 표시
- Live validation run임을 표시
```

목록 카드에는 너무 많은 기술 로그를 노출하지 않는다.

목록 카드 예시:

```text id="qkrnuz"
[검수 가능] [미검수]

산출물 유형: 룰 엔진

검증:
Runner 통과 · Scenario 통과 · Golden 3/3 · 결정성 통과

제품 레이어:
Replay 출력 사용 확인

기준점:
Green Base 준비됨

위험:
하드코딩 위험 낮음
```

상세 페이지에만 세부 리포트를 노출한다.

---

# 11. CLI / 실행 정책

이번 작업에서 필수 CLI는 다음이다.

```bash id="o29mpp"
python -m repo_idea_miner factory-build --challenge-id <id> --mode live
python -m repo_idea_miner factory-build --sample mock --mode mock
python -m repo_idea_miner factory-validate
```

선택:

```bash id="dummvj"
python -m repo_idea_miner factory-build --sample mock --mode mock --candidates 2
```

정책:

```text id="wtd9h2"
live candidates 기본 1 유지
mock candidates 최대 2 유지
factory 자동 배치 통합은 이번 범위 아님
```

단, 보고서에는 다음을 명시한다.

```text id="bhlgpm"
factory-build는 Phase 1.6b hardened harness 사용
factory 자동 배치는 기존 파이프라인 유지 여부
```

---

# 12. 테스트 요구사항

최소 테스트:

```text id="w699rx"
1. Core Contract Gate가 단순 문자열만으로 PASS하지 않음
2. action name이 주석에만 있으면 FAIL 또는 PARTIAL
3. runner가 core module을 import/require하지 않으면 FAIL
4. scenario action이 handler로 dispatch되지 않으면 FAIL
5. final_state가 항상 고정값이면 FAIL 또는 hardcode risk 상승
6. product layer에 replay 문자열만 있으면 FAIL
7. product layer가 replay/index.json을 실제 참조해야 PASS
8. product layer가 final_state/events/summary 중 최소 2개 이상 사용해야 PASS
9. product layer에 fake state만 있으면 FAIL
10. green_base는 필수 gate 통과 시에만 생성
11. 일부 gate 실패지만 patchable이면 continuation_base 생성
12. green_base와 continuation_base가 dashboard에서 구분됨
13. patch 후 Build Review가 재계산됨
14. 두 번째 patch instruction이 최신 gate 결과를 반영함
15. factory-validate가 final_artifact 기준 파일 존재를 검사
16. workspace와 final_artifact 불일치 시 validate 실패
17. run_instructions가 없는 경로를 가리키면 validate 실패
18. live validation summary json 생성
19. verdict_is_honest 필드 생성
20. runner 없는 결과는 PROMOTE_TO_CODEX 금지 유지
21. golden 없는 결과는 PROMOTE_TO_CODEX 금지 유지
22. hardcode risk high는 PROMOTE_TO_CODEX 금지 유지
23. viewer-only 산출물은 PROMOTE_TO_CODEX 금지 유지
24. mock factory-build 여전히 PASS
25. 기존 Product Dashboard 동작 유지
26. 기존 Challenge Mode 동작 유지
27. 기존 테스트 전체 통과
28. secret scan 통과
```

---

# 13. 완료 기준

완료 기준:

```text id="wwol53"
1. live challenge 1건을 Phase 1.6 harness로 실행했다.
2. live result의 verdict가 정직한지 검토했다.
3. Core Contract Gate가 문자열 검색 수준을 넘어 runner/action/state 연결을 검사한다.
4. Product Layer Gate가 replay/runner output 실제 소비를 검사한다.
5. green_base와 continuation_base가 구분된다.
6. patch 후 Build Review가 재계산된다.
7. factory-validate가 final_artifact 기준 정합성을 검사한다.
8. Dashboard가 green/continuation base와 product layer output 소비 여부를 표시한다.
9. mock run이 계속 통과한다.
10. 기존 기능과 테스트가 깨지지 않는다.
```

---

# 14. 작업 보고 형식

완료 후 아래 형식으로 보고한다.

```text id="phyp4l"
RIM Product Factory Phase 1.6b Live Validation + Gate Hardening 작업 보고

Base 상태
- 시작 HEAD:
- 종료 HEAD:
- origin ahead/behind:
- push 여부:

수정 파일
-

Live Challenge Validation
- challenge_id:
- challenge_title:
- 선택 이유:
- run_id:
- final_artifact path:
- 실행 명령:
- verdict:
- verdict_is_honest:
- overrated/underrated:
- 주요 발견:

Gate Hardening
- Core Contract Gate 보강:
- Product Layer Gate 보강:
- Green Base / Continuation Base 분리:
- Patch 후 Build Review 재계산:
- factory-validate final_artifact 정합성:

Dashboard
- live validation 표시:
- product layer output 소비 표시:
- green/continuation base 표시:

CLI
- factory-build live:
- factory-build mock:
- factory-validate:

Live 결과 산출물
- core_contract_summary:
- runner_summary:
- scenario_replay_summary:
- golden_diff_summary:
- determinism_summary:
- anti_hardcode_summary:
- product_layer_review:
- live_validation_summary:

테스트
- pytest:
- secret scan:

판정
- Phase 2 착수 가능 여부:
- 아직 보강 필요한 항목:
- 후속 추천:
```

---

# 15. 최종 정의

Phase 1.6b는 Phase 2가 아니다.

> RIM Product Factory Phase 1.6b는 Core-first Review-Repair Harness를 실제 live challenge 1건에 적용하여, mock에서만 통과하는 하네스인지 실제 Gemma 산출물도 제대로 검증·판정하는 하네스인지 확인하는 단계다.
> 이 과정에서 Core Contract Gate, Product Layer Gate, Green Base 조건, Patch Review 재계산, factory-validate 정합성을 보강하여, Phase 2 성장 루프에 들어가기 전 첫 시제품의 바닥선이 실제로 작동하는지 검증한다.
