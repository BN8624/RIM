# RIM Product Factory Phase 1.5 외주 주문서 v4

## Product Result Dashboard 강화

## 0. 작업 목적

현재 RIM에는 Challenge Mode Dashboard와 Product Factory가 존재한다.

Product Factory는 Challenge를 받아 다음 산출물을 생성한다.

```text
product_run_dir/
final_artifact/
manifest.json
contract.json
syntax_report.md
contract_report.md
smoke_report.md
qa_report.md
product_verdict.md
codex_export/
```

하지만 현재 사용자는 Product Factory가 만든 결과물을 대시보드에서 충분히 한눈에 확인하기 어렵다.

이번 작업의 목적은 **Product Factory 결과를 사람이 검수할 수 있게 기존 대시보드에 명확히 보여주는 것**이다.

이번 작업은 Product Factory Phase 2가 아니다.
이번 작업은 Phase 2 전에 필요한 **Phase 1.5: Product Result Dashboard**다.

---

## 1. 핵심 방향

새 대시보드 서버를 만들지 않는다.

기존 Challenge Dashboard 안에 Product Factory 결과 화면을 추가/강화한다.

구조는 다음과 같다.

```text
기존 dashboard server 공유
기존 challenge.db 공유
기존 challenge_dashboard.py 확장

/
  Challenge Inbox

/challenge/<id>
  Challenge 상세

/products
  Product Factory 결과 목록

/product/<run_id>
  Product Run 상세 검수 화면
```

정리하면 다음과 같다.

```text
서버 / DB / 포트는 공유한다.
화면 / 라우트 / 목적은 분리한다.
```

Challenge 화면은 “무엇을 만들 만한가?”를 보는 곳이다.
Product 화면은 “무엇이 실제로 만들어졌고, 다음 판단은 무엇인가?”를 보는 곳이다.

---

## 2. 기존 기능 보존

기존 Challenge Dashboard 기능은 깨면 안 된다.

보존 대상:

```text
/
challenge 목록
challenge 상세
review action
challenge-search 결과
daemon/status 관련 기존 화면
기존 dashboard 실행 방식
기존 Product Factory CLI
기존 Product Factory 산출물
```

Product Result Dashboard는 기존 화면을 대체하지 않는다.

---

## 3. 이번 작업에서 하지 말 것

금지:

```text
별도 React/Vue/Svelte 앱 생성
새 dashboard 서버 생성
새 포트 사용
새 DB 생성
Product Factory 파이프라인 대규모 변경
Codex/Claude 자동 실행 버튼 추가
workspace 전체 파일 브라우저 공개
생성 앱 iframe 실행
생성 HTML/JS 직접 실행
실시간 로그 스트리밍
복잡한 차트/통계 대시보드
```

이번 작업은 결과 확인용 UI다.
예쁜 UI보다 **한눈에 판단 가능한 정보 구조**가 중요하다.

---

## 4. 중요한 개념 분리

Product Dashboard에서는 다음 개념을 반드시 분리한다.

```text
status  = Product Run 실행 상태
verdict = Factory의 자동 판정
review  = 사용자의 최종 검수 판단
```

예:

```text
status: completed
verdict: NEEDS_MORE_GEMMA_LOOP
review: RETRY
```

또는 실패 run:

```text
status: error
verdict: null
review: unreviewed
```

중요:

```text
ERROR는 verdict가 아니다.
ERROR는 run status다.
```

Product Verdict 라벨은 다음만 사용한다.

```text
PROMOTE_TO_CODEX
KEEP_CANDIDATE
NEEDS_MORE_GEMMA_LOOP
TOO_WEAK
DROP
```

`status=error`이고 `verdict=null`인 run도 `/products`에서 볼 수 있어야 한다.

---

## 5. Structured Summary 우선 원칙

대시보드는 markdown report를 regex로 억지 파싱하는 구조에 의존하면 안 된다.

가능하면 Product Factory 산출물에 다음 structured summary 파일을 추가 생성한다.

```text
product_summary.json
gate_summary.json
qa_summary.json
```

기존 산출물은 삭제하거나 변경하지 않는다.
summary json은 추가만 한다.

우선순위:

```text
1. structured summary json을 우선 사용
2. 없으면 기존 markdown report에서 fallback 파싱
3. fallback 파싱도 불확실하면 UNKNOWN / PARTIAL로 표시
4. 원문 report preview는 그대로 제공
```

이 작업을 위해 기존 CLI 동작을 깨면 안 된다.
단, Dashboard 표시를 위해 Product Factory 산출물에 summary json을 추가하는 것은 허용한다.

---

## 6. summary json 요구사항

### 6.1 product_summary.json

권장 구조:

```json
{
  "product_run_id": 1,
  "challenge_id": 14,
  "challenge_title": "사진 타임라인 스크러버",
  "status": "completed",
  "stage": "judge",
  "verdict": "NEEDS_MORE_GEMMA_LOOP",
  "recommended_action": "RETRY",
  "reason": "4개 Gate는 통과했지만 QA에서 scrubber onJump 미구현이 발견됨.",
  "issue_summary": "scrubber onJump 미구현",
  "next_goal": "Implement scrubber jump behavior",
  "workspace_dir": "...",
  "final_artifact_dir": "...",
  "codex_export_dir": null,
  "created_at": "...",
  "updated_at": "..."
}
```

---

### 6.2 gate_summary.json

권장 구조:

```json
{
  "static": {
    "status": "PASS",
    "summary": "required files and fake multi-file checks passed"
  },
  "contract": {
    "status": "PASS",
    "summary": "entrypoint and import graph reachable"
  },
  "syntax": {
    "status": "PASS",
    "summary": "node --check passed"
  },
  "smoke": {
    "status": "PASS",
    "summary": "npm test passed",
    "command": "npm test",
    "exit_code": 0,
    "stdout_preview": "...",
    "stderr_preview": "",
    "timeout": false
  }
}
```

Gate status는 다음 중 하나로 한다.

```text
PASS
FAIL
SKIP
UNKNOWN
```

---

### 6.3 qa_summary.json

권장 구조:

```json
{
  "anchor_status": "PARTIAL",
  "forbidden_status": "PASS",
  "core_interaction_status": "PARTIAL",
  "issue_summary": "scrubber onJump 미구현",
  "evidence": [
    "src/ui.js contains scrubber element",
    "src/app.js does not wire onJump handler"
  ],
  "next_goal": "Implement scrubber jump behavior",
  "recommended_action": "RETRY"
}
```

QA status는 다음 중 하나로 한다.

```text
PASS
PARTIAL
FAIL
UNKNOWN
```

---

## 7. 상단 네비게이션

기존 대시보드 상단에 최소한 다음 탭을 명확히 둔다.

```text
[Challenge Inbox] [Product Runs]
```

각 화면에서 서로 이동 가능해야 한다.

목적:

```text
Challenge Inbox = 발굴된 후보 확인
Product Runs = 실제 생성된 결과물 확인
```

모바일 화면에서도 버튼이 잘 보여야 한다.

---

## 8. /products 목록 화면 목표

`/products`는 단순 DB row 목록이 아니라 **검수 대기함**처럼 보여야 한다.

목록 화면은 많은 정보를 다 보여주는 곳이 아니다.

목록의 목적:

```text
1. 어떤 결과물이 나왔는지 빠르게 확인
2. 지금 판단이 필요한 run을 찾기
3. 상세 화면으로 들어갈지 결정
```

목록 카드 첫 화면에는 다음만 우선 노출한다.

```text
Product Verdict
Run Status
Review 상태
Challenge 제목
핵심 Issue 한 줄
Gate 요약
QA 요약
Next Goal 한 줄
추천 Action
상세 보기 링크
```

나머지 정보는 상세 화면으로 보낸다.

---

## 9. /products 목록 카드 예시

사용자가 모바일에서 이런 식으로 볼 수 있어야 한다.

```text
[NEEDS_MORE_GEMMA_LOOP] [completed] [미검수]

사진 타임라인 스크러버

Issue:
scrubber onJump 미구현

Gate:
4/4 PASS

QA:
PARTIAL

Next:
Implement scrubber jump behavior

추천:
RETRY

[상세 보기]
```

실패 run 예:

```text
[ERROR] [error] [미검수]

Challenge #47

Issue:
Smoke Gate timeout

Gate:
2/4 PASS

QA:
UNKNOWN

Next:
오류 로그 확인 필요

추천:
ARCHIVE 또는 DROP

[상세 보기]
```

---

## 10. /products 목록에 너무 많은 정보 금지

목록 카드에 다음 정보를 모두 길게 펼치지 않는다.

```text
전체 파일 경로
긴 report 원문
전체 events log
전체 manifest
전체 contract
긴 QA 근거
전체 stdout/stderr
```

목록은 검수 대기함이다.
파일 뷰어가 아니다.

---

## 11. /products 필터

최소한 다음 필터를 제공한다.

```text
전체
PROMOTE_TO_CODEX
KEEP_CANDIDATE
NEEDS_MORE_GEMMA_LOOP
TOO_WEAK
DROP
status=error
미검수
검수완료
RETRY
PRODUCTIZE
```

필터는 query parameter 방식이면 충분하다.

예:

```text
/products?verdict=NEEDS_MORE_GEMMA_LOOP
/products?status=error
/products?review=unreviewed
/products?review=RETRY
/products?review=PRODUCTIZE
```

Phase 2에서 continuation 대상을 찾기 위해 `/products?review=RETRY`가 반드시 동작해야 한다.

---

## 12. Challenge 제목 fallback 규칙

Product Run의 원본 Challenge 정보가 일부 없을 수 있다.

Challenge 제목은 다음 우선순위로 표시한다.

```text
1. challenge DB title
2. challenge_card.md title
3. owner_brief.md 첫 heading
4. product_summary.json challenge_title
5. product_run_id
```

challenge_id가 없는 sample mock run도 목록과 상세 화면에서 깨지면 안 된다.

---

## 13. /product/<run_id> 상세 화면 목표

상세 화면은 report 파일 탭부터 보여주면 안 된다.

가장 위에는 **판정 요약 박스**가 있어야 한다.

상세 화면 순서:

```text
1. Verdict Hero
2. 추천 Action
3. 원본 Challenge 요약
4. Gate Summary
5. QA Summary
6. Known Issues / Next Goal
7. Smoke Output Preview
8. Artifact Paths
9. Final Artifact File Tree
10. 허용된 Source Preview
11. Report Preview Tabs
12. Action Buttons
```

---

## 14. Verdict Hero

상세 화면 최상단에 다음을 표시한다.

```text
Product Verdict
Run Status
Review 상태
추천 Action
한 줄 이유
현재 stage
생성 시간
```

예:

```text
[NEEDS_MORE_GEMMA_LOOP]

Status: completed
Review: 미검수
추천 Action: RETRY

이유:
4개 Gate는 통과했지만 QA에서 scrubber onJump 미구현이 발견됨.
다음 루프에서 scrubber jump behavior 구현 필요.
```

---

## 15. 원본 Challenge 요약

Product Run은 원본 Challenge에서 출발했으므로 상세 화면에서 원본 Challenge 정보를 보여줘야 한다.

표시 항목:

```text
Challenge ID
Challenge 제목
Owner Brief 요약
Difficulty Anchors
Forbidden Simplifications
원본 Challenge 상세 링크
```

원본 Challenge 상세 링크를 누르면 기존 `/challenge/<id>`로 이동한다.

원본 Challenge가 없거나 삭제되었으면 화면이 깨지지 않고 다음처럼 표시한다.

```text
원본 Challenge 정보 없음
```

---

## 16. Gate Summary

상세 화면에서 Gate 결과를 요약한다.

필수 표시:

```text
Static Gate
Contract Gate
Syntax Gate
Smoke Gate
```

각 Gate는 다음 상태 중 하나로 표시한다.

```text
PASS
FAIL
SKIP
UNKNOWN
```

표시 예:

```text
Static: PASS
Contract: PASS
Syntax: PASS
Smoke: PASS
```

Gate Summary는 `gate_summary.json`을 우선 사용한다.
없으면 report 파일에서 fallback 파싱한다.
fallback 파싱 결과는 확실하지 않으면 `UNKNOWN`으로 표시한다.

---

## 17. QA Summary

상세 화면에서 QA 결과를 요약한다.

표시 항목:

```text
Anchor 결과
Forbidden 결과
Core Interaction 결과
핵심 결함
QA 판단 이유
근거 코드/파일 요약
```

예:

```text
Anchor: PARTIAL
Forbidden: PASS
Core Interaction: PARTIAL
Issue: scrubber onJump 미구현
Evidence:
- src/ui.js contains scrubber element
- src/app.js does not wire onJump handler
```

QA Summary는 `qa_summary.json`을 우선 사용한다.
없으면 `qa_report.md`, `anchor_check.md`, `forbidden_simplification_check.md`, `product_verdict.md`에서 fallback 파싱한다.
파싱 실패 시 report preview에서 원문을 읽을 수 있어야 한다.

---

## 18. Known Issues / Next Goal

다음 정보를 별도 박스로 보여준다.

```text
known_issues.md 내용
next_goal.md 내용
product_summary.json next_goal
qa_summary.json next_goal
product_verdict.md 안의 next action
```

우선순위:

```text
1. product_summary.json next_goal
2. qa_summary.json next_goal
3. next_goal.md
4. product_verdict.md fallback
```

파일이 없으면 다음처럼 표시한다.

```text
Known Issues: 없음 또는 파일 없음
Next Goal: 없음 또는 파일 없음
```

NEEDS_MORE_GEMMA_LOOP인 경우 이 영역이 특히 중요하다.

---

## 19. Smoke Output Preview

생성 앱을 iframe으로 실행하지 않는다.
하지만 실행 결과를 판단할 수 있도록 Smoke Output Preview를 제공한다.

표시 항목:

```text
command
exit_code
timeout 여부
stdout 첫 30줄
stderr 첫 30줄
```

source of truth:

```text
1. gate_summary.json smoke
2. smoke_report.md fallback
```

주의:

```text
stdout/stderr는 길이 제한을 둔다.
secret-like 문자열이 있으면 마스킹하거나 표시하지 않는다.
HTML/JS를 실행하지 않는다.
```

---

## 20. Artifact Paths

다음 경로를 표시한다.

```text
workspace_dir
final_artifact_dir
codex_export_dir
```

경로는 복사하기 쉽게 보여준다.

단, 브라우저에서 임의 파일을 열 수 있게 만들 필요는 없다.

---

## 21. Final Artifact File Tree

Final Artifact 안의 파일 목록을 보여준다.

표시 예:

```text
final_artifact/
  README.md
  run_instructions.md
  manifest.json
  contract.json
  src/
    app.js
    state.js
    ui.js
    styles.css
  reports/
    syntax_report.md
    contract_report.md
    smoke_report.md
    qa_report.md
  product_verdict.md
```

주의:

```text
workspace 전체 파일 브라우저를 만들지 않는다.
허용된 final_artifact / reports / codex_export 요약만 보여준다.
```

---

## 22. 허용된 Source Preview

보안상 workspace 전체 파일 브라우저는 금지한다.

다만 사용자가 “실제로 무엇이 만들어졌는지” 확인할 수 있도록, 제한된 범위에서 source preview를 허용한다.

허용 범위:

```text
final_artifact/src/ 아래 파일
final_artifact/README.md
final_artifact/run_instructions.md
final_artifact/manifest.json
final_artifact/contract.json
reports 안의 허용된 report 파일
```

제한:

```text
파일 크기 제한
표시 줄 수 제한
텍스트 파일만 표시
secret-like 문자열 마스킹 또는 차단
HTML은 text로 escape
JS는 실행하지 않고 text로 표시
상대경로 ../ 차단
절대경로 차단
```

권장 기본 preview:

```text
entrypoint 파일
state/model 파일
UI 파일
핵심 interaction 파일
```

---

## 23. Report Preview Tabs

상세 화면 하단에 report preview tabs를 둔다.

최소 탭:

```text
README.md
run_instructions.md
product_verdict.md
qa_report.md
contract_report.md
syntax_report.md
smoke_report.md
manifest.json
contract.json
events.jsonl
debug_history.jsonl
product_summary.json
gate_summary.json
qa_summary.json
```

보안 원칙:

```text
화이트리스트 파일만 읽는다.
경로 traversal을 차단한다.
workspace 임의 파일 읽기를 허용하지 않는다.
secret-like 문자열이 있으면 표시하지 않거나 경고 처리한다.
HTML report를 그대로 렌더링하지 말고 text로 escape 처리한다.
```

---

## 24. Action Buttons

상세 화면에 다음 버튼을 둔다.

```text
KEEP
DROP
PRODUCTIZE
RETRY
ARCHIVE
```

버튼은 Product Factory를 바로 실행하지 않는다.

이번 범위에서 버튼은 **사용자 검수 상태를 DB에 기록**하는 것까지 한다.

예:

```text
KEEP 클릭
→ product_review 상태를 KEEP으로 저장

DROP 클릭
→ product_review 상태를 DROP으로 저장

PRODUCTIZE 클릭
→ product_review 상태를 PRODUCTIZE로 저장

RETRY 클릭
→ product_review 상태를 RETRY로 저장

ARCHIVE 클릭
→ product_review 상태를 ARCHIVE로 저장
```

RETRY는 이번 단계에서 실제 continuation loop를 실행하지 않는다.
RETRY는 Phase 2에서 continuation 대상으로 사용할 수 있도록 상태만 기록한다.

---

## 25. Verdict와 추천 버튼 매핑

Product Verdict에 따라 추천 버튼을 강조한다.

```text
PROMOTE_TO_CODEX        → PRODUCTIZE 추천
KEEP_CANDIDATE          → KEEP 추천
NEEDS_MORE_GEMMA_LOOP   → RETRY 추천
TOO_WEAK                → ARCHIVE 또는 DROP 추천
DROP                    → DROP 추천
status=error            → ARCHIVE 또는 DROP 추천
```

추천 버튼은 시각적으로 강조한다.

다른 버튼도 누를 수 있어야 한다.

---

## 26. Product Review DB 요구사항

기존 DB에 이미 Product review 저장 구조가 있으면 그것을 사용한다.

없다면 최소 테이블을 추가한다.

```text
product_reviews
  id
  product_run_id
  action
  note
  selected_next_goal
  reviewer_source
  created_at
```

규칙:

```text
product_reviews는 append-only로 저장한다.
목록과 상세 화면에는 product_run_id별 최신 review만 표시한다.
이전 review 기록은 삭제하지 않는다.
```

`note`와 `selected_next_goal`은 UI에서 처음부터 필수 입력으로 만들 필요는 없다.
하지만 DB 필드는 준비한다.

Phase 2에서 RETRY/PRODUCTIZE 대상 입력으로 사용될 수 있어야 한다.

권장 값:

```text
reviewer_source = dashboard
```

---

## 27. 목록 화면에서 review 상태 표시

`/products` 목록에서 사용자의 최신 검수 상태를 보여준다.

예:

```text
미검수
KEEP
DROP
PRODUCTIZE
RETRY
ARCHIVE
```

Product Verdict와 사용자 Review는 구분해야 한다.

```text
Product Verdict = Factory의 자동 판정
Review Action = 사용자의 최종 판단
```

---

## 28. RETRY / PRODUCTIZE 후속 연결

이번 단계에서 RETRY나 PRODUCTIZE를 실행하지 않는다.

하지만 Phase 2에서 후속 작업 큐로 사용할 수 있게 표시/필터링되어야 한다.

필수:

```text
/products?review=RETRY 동작
/products?review=PRODUCTIZE 동작
상세 화면에서 selected_next_goal 표시
RETRY 저장 시 현재 next_goal을 selected_next_goal 기본값으로 저장 가능
```

V1 UI에서는 note 입력이 없어도 된다.
다만 내부적으로 selected_next_goal을 저장할 수 있는 구조를 준비한다.

---

## 29. 모바일 가독성

사용자는 작은 화면에서 볼 수 있다.

따라서 다음을 지킨다.

```text
카드형 목록
테이블 중심 UI 금지
목록 카드 폭 100%
가로 스크롤 최소화
긴 report는 기본 접힘
상세 화면 상단 요약 먼저 표시
Action Buttons는 상세 상단과 하단에 모두 배치
버튼은 손가락으로 누르기 충분한 크기
목록 카드 첫 화면에는 verdict/title/issue/gate count/recommended action만 우선 표시
```

멋진 디자인은 필요 없다.
폰에서 읽고 판단 가능하면 된다.

---

## 30. 보안 요구사항

대시보드는 생성물 파일을 읽는다.
따라서 최소 보안 규칙을 지킨다.

```text
허용된 파일명만 preview
상대경로 ../ 차단
절대경로 입력 차단
workspace 전체 탐색 금지
secret-like 문자열 표시 금지 또는 경고
.env / key / token / credential 파일 표시 금지
HTML report를 그대로 렌더링하지 말고 text로 escape 처리
```

특히 생성된 HTML/JS를 대시보드 안에서 실행하지 않는다.

```text
iframe 실행 금지
script 실행 금지
raw HTML 렌더링 금지
```

---

## 31. 불완전 Run 대응

정상 완료된 Product Run만 가정하면 안 된다.

다음 경우에도 `/products`와 `/product/<run_id>` 화면이 깨지면 안 된다.

```text
product_verdict.md 없음
qa_report.md 없음
gate_summary.json 없음
product_summary.json 없음
final_artifact_dir 없음
codex_export 없음
challenge_id 없음
challenge_id는 있지만 원본 challenge 삭제됨
status=error
verdict=null
report 파일이 너무 큼
report에 secret-like 문자열 포함
invalid run_id 접근
```

표시 규칙:

```text
없는 정보는 없음 / UNKNOWN / 파일 없음으로 표시한다.
페이지 전체가 500 에러로 깨지면 안 된다.
invalid run_id는 404 또는 안전한 error page를 반환한다.
```

---

## 32. CLI 변경 금지 원칙

이번 작업의 중심은 Dashboard다.

가능하면 다음 CLI는 변경하지 않는다.

```text
factory
factory-build
factory-status
factory-validate
challenge
challenge-search
daemon
```

필요한 경우에도 backward compatible하게만 수정한다.

단, Dashboard 표시 품질을 위해 다음 summary json을 Product Factory 산출물에 추가하는 것은 허용한다.

```text
product_summary.json
gate_summary.json
qa_summary.json
```

기존 산출물은 삭제하거나 호환성 깨지게 변경하지 않는다.

---

## 33. 테스트 요구사항

최소 테스트:

```text
1. /products 접근 가능
2. /products에 product_runs 목록 표시
3. verdict 배지 표시
4. status와 verdict 분리 표시
5. review 상태 표시
6. verdict 필터 동작
7. status=error 필터 동작
8. review 필터 동작
9. /products?review=RETRY 동작
10. /products?review=PRODUCTIZE 동작
11. /product/<run_id> 접근 가능
12. 원본 Challenge 요약 표시
13. challenge_id 없는 sample run 표시
14. 원본 challenge 삭제된 run 표시
15. Gate Summary 표시
16. gate_summary.json 우선 사용
17. gate_summary.json 없을 때 fallback 동작
18. QA Summary 표시
19. qa_summary.json 우선 사용
20. qa_summary.json 없을 때 fallback 동작
21. Known Issues / Next Goal 표시
22. Smoke Output Preview 표시
23. Artifact Paths 표시
24. Final Artifact File Tree 표시
25. 허용된 Source Preview 표시
26. Report Preview Tabs 표시
27. 화이트리스트 파일만 preview 가능
28. ../ path traversal 차단
29. 절대경로 차단
30. raw HTML/script 실행 금지
31. HTML/JS는 text escape 표시
32. KEEP 버튼 review 상태 저장
33. DROP 버튼 review 상태 저장
34. PRODUCTIZE 버튼 review 상태 저장
35. RETRY 버튼 review 상태 저장
36. ARCHIVE 버튼 review 상태 저장
37. product_reviews append-only 저장
38. 목록에는 최신 review만 표시
39. RETRY 저장 시 selected_next_goal 저장 가능
40. Product Verdict와 Review Action을 구분해서 표시
41. PROMOTE_TO_CODEX → PRODUCTIZE 추천 버튼 강조
42. NEEDS_MORE_GEMMA_LOOP → RETRY 추천 버튼 강조
43. status=error, verdict=null run 표시
44. product_verdict.md 없음에도 상세 페이지가 깨지지 않음
45. qa_report.md 없음에도 상세 페이지가 깨지지 않음
46. final_artifact_dir 없음에도 상세 페이지가 깨지지 않음
47. codex_export 없음에도 상세 페이지가 깨지지 않음
48. report에 secret-like 문자열 포함 시 마스킹/차단
49. report 파일이 너무 클 때 truncate 또는 preview 제한
50. invalid run_id 접근 시 안전한 404/에러 처리
51. 기존 Challenge Dashboard 테스트 통과
52. 기존 Product Factory 테스트 통과
53. secret scan 통과
```

---

## 34. 완료 기준

완료 기준:

```text
1. 기존 dashboard 서버에서 /products와 /product/<run_id>를 볼 수 있다.
2. 새 서버/새 포트/새 프론트엔드 앱을 만들지 않는다.
3. /products가 Product Run 검수 대기함처럼 보인다.
4. 목록 카드는 verdict/title/issue/gate count/QA/recommended action 중심으로 간결하다.
5. status, verdict, review가 명확히 분리되어 보인다.
6. ERROR는 verdict가 아니라 status로 표시된다.
7. structured summary json을 우선 사용하고 markdown은 fallback preview로 둔다.
8. 상세 화면에서 verdict hero, challenge 요약, gate summary, QA summary, next goal, smoke output, artifact paths, file tree, source preview, report tabs를 볼 수 있다.
9. KEEP / DROP / PRODUCTIZE / RETRY / ARCHIVE 버튼이 있다.
10. 버튼은 DB에 사용자 review 상태를 append-only로 저장한다.
11. 목록과 상세에는 최신 review만 표시한다.
12. RETRY는 continuation을 실행하지 않고 상태와 selected_next_goal만 기록한다.
13. /products?review=RETRY로 Phase 2 후보를 볼 수 있다.
14. report preview는 화이트리스트 파일만 읽는다.
15. 생성 HTML/JS를 대시보드에서 실행하지 않는다.
16. final_artifact/src의 허용된 파일은 size limit 안에서 text preview 가능하다.
17. smoke output preview를 볼 수 있다.
18. 불완전 run에서도 페이지가 깨지지 않는다.
19. 기존 Challenge Dashboard 기능이 깨지지 않는다.
20. 기존 Product Factory 기능이 깨지지 않는다.
```

---

## 35. 작업 보고 형식

완료 후 아래 형식으로 보고한다.

```text
RIM Product Result Dashboard 작업 보고

Base 상태
- 시작 HEAD:
- 종료 HEAD:
- origin ahead/behind:
- push 여부:

수정 파일
-

기존 기능 보존 확인
- Challenge Dashboard:
- Challenge 상세:
- Product Factory CLI:
- Product Factory tests:

추가/개선 화면
- /products:
- /product/<run_id>:
- 상단 navigation:
- verdict badge:
- status/verdict/review 분리:
- review state:
- filters:
- gate summary:
- QA summary:
- next goal:
- smoke output preview:
- source preview:
- report tabs:
- action buttons:

Structured summary
- product_summary.json:
- gate_summary.json:
- qa_summary.json:
- markdown fallback:

DB 변경
- product_reviews:
- append-only:
- latest review 조회:
- selected_next_goal:
- 기존 product_* 테이블 영향:

보안 확인
- whitelist preview:
- path traversal 차단:
- absolute path 차단:
- raw HTML/script escape:
- secret-like 문자열 처리:
- large file truncate:

불완전 run 대응
- missing verdict:
- missing qa report:
- missing final artifact:
- missing challenge:
- status=error/verdict=null:
- invalid run_id:

실행 검증
- dashboard 실행:
- /products 확인:
- /product/<run_id> 확인:
- KEEP/DROP/PRODUCTIZE/RETRY/ARCHIVE 저장 확인:
- /products?review=RETRY 확인:
- /products?status=error 확인:

테스트
- pytest:
- secret scan:

주의사항
- 남은 한계:
- 후속 추천:
```

---

## 36. 최종 정의

이번 작업은 Product Factory Phase 2가 아니다.

이번 작업은 Product Factory Phase 1 결과를 사람이 볼 수 있게 만드는 **Product Result Dashboard 강화 작업**이다.

> 기존 Challenge Dashboard 안에 Product Runs 전용 화면을 분리해, Product Factory가 생성한 멀티파일 결과물의 status, verdict, review, gate, QA, issue, next goal, smoke output, report, artifact 경로를 한눈에 보여주고, 사용자가 KEEP / DROP / PRODUCTIZE / RETRY / ARCHIVE 판단을 DB에 append-only로 기록할 수 있게 만든다. 이때 structured summary json을 우선 사용하고 markdown은 fallback preview로만 사용한다.
