# RIM Product Factory 추가 개발 의뢰서 v3

## Challenge Mode 이후 자동 제품 생산 파이프라인

## 0. 작업 목적

현재 RIM에는 GitHub 레포를 분석해 다음 산출물을 생성하는 **Challenge Mode**가 있다.

```text
owner_brief.md
screen_story.md
challenge_card.md
implementation_prompt.md
```

Challenge Mode는 “만들 만한 후보”를 찾는 단계다.

이번 작업의 목표는 그 다음 단계다.

RIM에 **Product Factory**를 추가한다.

Product Factory는 Challenge Mode가 뽑은 좋은 후보를 사람 개입 없이 다음 단계까지 자동으로 밀어붙인다.

```text
Challenge 생성
→ 자동 승격 판단
→ 제품 기획
→ 화면/상태 설계
→ 기술 설계
→ 멀티파일 코드 생성
→ 구조 검사
→ 문법 검사
→ 기본 실행 검사
→ 디버깅
→ QA
→ 최종 작업물 생성
→ Dashboard에서 사람이 최종 검토
```

중요한 원칙:

```text
사람은 중간에 고르고 지시하지 않는다.
사람은 최종 작업물이 나온 뒤에만 확인한다.
```

이번 작업은 발굴 기능 추가가 아니다.
이번 작업은 RIM을 **자동 제품 생산 파이프라인**으로 확장하는 것이다.

---

## 1. 이번 작업의 핵심 정의

Product Factory는 단일파일 생성기가 아니다.

이번 작업에서 만들 것은 다음이다.

```text
검증 가능한 멀티파일 workspace를 자동으로 키우는 시스템
```

최종 작업물은 단일 `index.html`, 단일 `main.py`, 단일 CLI 파일 수준이면 안 된다.

최종 작업물은 최소한 다음 구조를 가져야 한다.

```text
final_artifact/
  README.md
  run_instructions.md
  manifest.json
  contract.json
  src/
    ...
  checks/ 또는 tests/
    ...
  reports/
    syntax_report.md
    contract_report.md
    smoke_report.md
    qa_report.md
  debug_history.jsonl
  product_verdict.md
```

중간 skeleton 단계에서는 단일 entrypoint에서 시작할 수 있다.
하지만 **Final Artifact** 또는 **Codex/Claude 승격 후보**가 단일파일이면 실패로 본다.

최종 후보는 최소한 다음을 만족해야 한다.

```text
- src 파일 2개 이상
- manifest.json 존재
- contract.json 존재
- checks/ 또는 tests/ 존재
- reports/ 존재
- 실행 방법 존재
- 검증 리포트 존재
```

---

## 2. 기존 RIM 기능 보존

기존 기능은 깨면 안 된다.

보존 대상:

```text
run
search
view
serve
validate
challenge
challenge-search
daemon
dashboard
status
pause
resume
validate-db
```

Product Factory는 기존 기능을 대체하지 않고, Challenge Mode 다음 단계로 추가한다.

기존 Challenge Mode 산출물 형식도 깨면 안 된다.

---

## 3. 용어 정의

### 3.1 Challenge

Challenge Mode가 생성한 구현 도전 과제다.

주요 파일:

```text
owner_brief.md
screen_story.md
challenge_card.md
implementation_prompt.md
```

---

### 3.2 Product Factory

Challenge를 받아 자동으로 제품 후보 workspace까지 키우는 파이프라인이다.

---

### 3.3 Workspace

Product Factory가 생성하고 계속 수정하는 작업물 디렉터리다.

예:

```text
workspace/
  README.md
  manifest.json
  contract.json
  src/
  checks/
  reports/
```

---

### 3.4 Desk

Desk는 작업 단계다.

예:

```text
Planning Desk
UX Spec Desk
Technical Spec Desk
Build Desk
Syntax Gate Desk
Debug Desk
QA Desk
Judge Desk
```

Desk는 다음을 가진다.

```text
입력 스키마
프롬프트
출력 스키마
검증 규칙
성공 시 다음 단계
실패 시 다음 단계
최대 재시도 횟수
```

---

### 3.5 Worker Slot

Gemma API key를 사용하는 실행 슬롯이다.

중요:

```text
Worker Slot은 고정 직책이 아니다.
```

잘못된 구조:

```text
KEY_1 = 기획자
KEY_2 = 코더
KEY_3 = QA
```

올바른 구조:

```text
KEY_1은 지금 Planning Desk에 배정될 수 있다.
다음 작업에서는 Debug Desk에 배정될 수 있다.
그다음 작업에서는 Build Desk에 배정될 수 있다.
```

역할은 key에 붙지 않고 Desk에 붙는다.

---

### 3.6 Task Packet

Desk 사이를 이동하는 작업 단위다.

Task Packet에는 다음이 들어간다.

```text
현재 workspace 상태
이전 리포트
다음 목표
수정 허용 파일
수정 금지 파일
실패 로그
검증 결과
다음 Desk 정보
```

---

## 4. 전체 자동 흐름

Product Factory의 기본 흐름은 다음이다.

```text
Challenge Card
→ Auto Promotion Gate
→ Product Planning Desk
→ UX/Spec Desk
→ Technical Spec Desk
→ Build Desk
→ Static Gate
→ Contract Gate
→ Syntax Gate
→ Smoke Gate
→ Debug Desk if failed
→ QA Desk
→ Judge Desk
→ Final Artifact
→ Dashboard Review
```

사람 개입은 Final Artifact 생성 전까지 없어야 한다.

---

## 5. 사람 개입 금지 원칙

Product Factory는 중간에 사용자에게 질문하지 않는다.

금지 예:

```text
이 후보로 진행할까요?
어떤 화면으로 만들까요?
이 오류를 어떻게 고칠까요?
이 파일을 추가할까요?
이제 빌드할까요?
```

허용되는 사람 개입:

```text
최종 작업물 생성 후 Dashboard에서 검토
KEEP / DROP / PRODUCTIZE / RETRY / ARCHIVE 판단
```

중간 판단은 자동 규칙으로 처리한다.

```text
기준 통과 → 다음 Desk
기준 미달 → retry 또는 drop
문법 실패 → Debug Desk
실행 실패 → Debug Desk
반복 실패 → TOO_WEAK 또는 DROP
```

Dashboard의 `RETRY`는 중간 개입이 아니다.
`RETRY`는 Final Artifact 생성 후 사용자가 해당 결과물을 다시 Factory에 넣는 후처리 버튼이다.

---

## 6. Auto Promotion Gate

Challenge가 조건을 만족하면 자동으로 Product Factory에 진입한다.

### 6.1 GOOD_CHALLENGE 승격 기준

`GOOD_CHALLENGE`는 일반 Product Factory 라인으로 진입한다.

조건:

```text
final_label == GOOD_CHALLENGE
owner_clarity_score >= 3
difficulty_anchor_alive >= 4
not_too_easy >= 4
immediate_demo_value >= 3
difficulty_anchors 길이 >= 2
forbidden_simplifications 길이 >= 2
```

---

### 6.2 STEAL_ONLY 승격 기준

`STEAL_ONLY`는 일반 Product Factory 라인이 아니라 **micro-workspace 라인**으로 진입한다.

목적:

```text
전체 제품을 만드는 것이 아니라,
훔칠 수 있는 핵심 루프/상호작용/구조 1개만 작게 구현한다.
```

조건:

```text
final_label == STEAL_ONLY
owner_clarity_score >= 3
difficulty_anchor_alive >= 3
immediate_demo_value >= 3
difficulty_anchors 길이 >= 1
forbidden_simplifications 길이 >= 1
```

STEAL_ONLY 결과물은 기본적으로 `PROMOTE_TO_CODEX`보다 `KEEP_CANDIDATE` 판정을 우선한다.
단, 결과물이 매우 좋고 구조가 명확하면 `PROMOTE_TO_CODEX`도 가능하다.

---

### 6.3 자동 제외 조건

다음 라벨은 자동으로 Product Factory에 진입하지 않는다.

```text
TOO_EASY
TOO_BIG
UNCLEAR_TO_OWNER
DROP
```

---

## 7. Desk 목록과 역할

### 7.1 Product Planning Desk

역할:

```text
Challenge Card를 제품 기획으로 바꾼다.
```

입력:

```text
owner_brief.md
screen_story.md
challenge_card.md
implementation_prompt.md
```

출력:

```text
product_brief.md
```

반드시 포함:

```text
제품 목표
사용자
핵심 사용 루프
첫 화면 목표
줄여도 되는 것
줄이면 안 되는 것
```

---

### 7.2 UX/Spec Desk

역할:

```text
화면 흐름과 사용자 행동, 상태 변화를 정의한다.
```

출력:

```text
ux_flow.md
screen_spec.json
state_transition_spec.json
```

반드시 포함:

```text
첫 화면
주요 화면 목록
사용자 행동
상태 변화
성공 화면
실패 화면
30초 데모 흐름
```

정적 설명만 있으면 실패다.

반드시 사용자가 무엇을 누르고, 그 결과가 어떻게 바뀌는지 설명해야 한다.

---

### 7.3 Technical Spec Desk

역할:

```text
멀티파일 workspace 구조와 구현 계약을 만든다.
```

출력:

```text
technical_plan.md
manifest.json
contract.json
build_task_packet.md
```

`manifest.json`에는 다음이 들어가야 한다.

```text
파일 목록
파일별 역할
entrypoint
실행 명령
검증 명령
생성 금지 파일
```

`contract.json`에는 다음이 들어가야 한다.

```text
모듈 관계
필수 entrypoint
필수 파일
필수 export/import 또는 연결 관계
상태 모델
핵심 상호작용 요구사항
Difficulty Anchors 반영 조건
Forbidden Simplifications 금지 조건
```

V1 Contract Gate는 언어별 최소 구조 검사부터 시작한다.

V1 필수 범위:

```text
파일 존재
entrypoint 연결
import/require graph reachability
manifest에 적힌 주요 모듈 존재
핵심 상호작용을 담당하는 파일 존재
```

선택 범위:

```text
필수 함수/클래스 단위 깊은 검증
세밀한 타입/인터페이스 검증
```

처음부터 모든 언어에 대해 깊은 함수/클래스 검증을 강제하지 않는다.

---

### 7.4 Build Desk

역할:

```text
contract와 build_task_packet에 맞춰 멀티파일 workspace를 생성하거나 수정한다.
```

출력:

```text
src/
README.md
run_instructions.md
build_report.md
```

중요 원칙:

```text
한 번에 전체 프로젝트를 계속 새로 쓰지 않는다.
현재 workspace를 기준으로 다음 층을 쌓는다.
가능하면 patch/delta 단위로 수정한다.
```

---

### 7.5 Static Gate Desk

역할:

```text
파일 구조와 기본 계약 위반을 검사한다.
```

검사 항목:

```text
필수 파일 존재
entrypoint 존재
README 존재
manifest와 실제 파일 일치
고아 파일 여부
src 파일 수 최소 기준
fake multi-file 여부
secret-like 문자열 여부
```

`fake multi-file` 예:

```text
파일은 여러 개지만 실제로는 entrypoint 하나만 쓰고 나머지는 연결되지 않음
```

---

### 7.6 Contract Gate Desk

역할:

```text
manifest/contract와 실제 코드 구조가 맞는지 검사한다.
```

V1 필수 검사 항목:

```text
파일 존재
entrypoint 연결 여부
import/require graph reachability
manifest 주요 모듈 존재
고아 모듈 없음
Difficulty Anchors 관련 코드 위치 존재
```

선택 검사 항목:

```text
필수 함수/클래스 존재 여부
세밀한 export/import 검증
타입/인터페이스 검증
```

필수 함수/클래스 검증은 가능한 언어와 구조에서만 수행한다.
V1에서는 파일/entrypoint/import graph/주요 모듈 존재 검사를 우선한다.

---

### 7.7 Syntax Gate Desk

역할:

```text
가장 싼 문법 검사부터 수행한다.
```

예:

```text
JavaScript: node --check
Python: python -m py_compile
JSON parse
HTML 기본 참조 검사
```

처음부터 복잡한 브라우저 테스트나 E2E를 강제하지 않는다.

---

### 7.8 Smoke Gate Desk

역할:

```text
기본 실행 가능 여부를 확인한다.
```

검사 예:

```text
npm install
npm run build
npm test
python main.py --help
node main.js
static server로 index.html 로드
```

가능하면 Docker 안에서 실행한다.

---

### 7.9 Debug Desk

역할:

```text
검증 실패 로그를 보고 patch 또는 수정 파일을 만든다.
```

입력:

```text
error_log.md
syntax_report.md
contract_report.md
smoke_report.md
현재 workspace
```

출력:

```text
patch proposal
debug_report.md
수정된 workspace
```

기본 debug 횟수:

```text
2~3회
```

무한 루프는 금지한다.

---

### 7.10 QA Desk

역할:

```text
결과물이 Challenge의 핵심을 지켰는지 검사한다.
```

검사 항목:

```text
Difficulty Anchors가 살아 있는가
Forbidden Simplifications를 위반하지 않았는가
단순 TODO/검색창/정적 대시보드로 퇴화하지 않았는가
사용자 행동과 상태 변화가 있는가
README만 있고 실행물이 없는 상태가 아닌가
```

출력:

```text
qa_report.md
anchor_check.md
forbidden_simplification_check.md
```

---

### 7.11 Judge Desk

역할:

```text
Gemma Factory 안에서 더 키울지, 버릴지, Codex/Claude로 승격할지 판정한다.
```

출력:

```text
product_verdict.md
```

라벨:

```text
PROMOTE_TO_CODEX
KEEP_CANDIDATE
NEEDS_MORE_GEMMA_LOOP
TOO_WEAK
DROP
```

---

## 8. Workspace 성장 방식

Product Factory는 한 번에 완성물을 만들려고 하지 않는다.

같은 workspace를 여러 단계로 성장시킨다.

권장 성장 단계:

```text
Level 1:
README + manifest + contract + src 2~4 files

Level 2:
src 4~8 files + checks 1~2 files

Level 3:
src 8~15 files + tests/checks + reports

Level 4:
필요하면 Dockerfile, fixtures, replay/golden check 추가
```

핵심은 파일 수가 아니다.

핵심은 다음이다.

```text
계약이 깨지지 않는 성장
검증 가능한 성장
이전 green base를 보존하는 성장
```

---

## 9. Snapshot / Rollback / Event Log

Product Factory는 각 단계마다 상태를 기록해야 한다.

필수:

```text
events.jsonl
snapshot/
debug_history.jsonl
```

각 loop 후 다음을 기록한다.

```text
현재 단계
사용한 Desk
사용한 worker_key_id
입력 파일
출력 파일
검증 결과
실패 로그
다음 상태
```

검증 통과 상태를 `green base`로 저장한다.

새 수정이 실패하면 green base로 rollback할 수 있어야 한다.

`worker_key_id`는 실제 API key 값이 아니다.

허용:

```text
KEY_01
KEY_02
KEY_03
```

금지:

```text
API key 원문
API key prefix
API key suffix
API key hash
```

DB, 로그, report, artifact에는 secret을 저장하지 않는다.

---

## 10. Context / Output 전략

Gemma 4 31B는 큰 컨텍스트와 제한된 출력을 전제로 사용한다.

전략:

```text
Context는 크게
Output은 제한적으로
작업물은 점진적으로
```

프롬프트에 넣을 컨텍스트:

```text
challenge_card
difficulty_anchors
forbidden_simplifications
product_brief
ux_flow
manifest
contract
현재 파일 트리
핵심 파일
최근 검증 리포트
최근 실패 로그
이번 loop 목표
수정 허용 파일
```

출력은 다음 중 하나로 제한한다.

```text
patch
single file replacement
small file set
debug report
next task packet
```

금지:

```text
매번 전체 프로젝트를 다시 쓰기
검증 없이 대규모 변경
이전 green base 무시
```

---

## 11. 11-key 사용 방식

11개 key는 고정 역할이 아니다.

11개 key는 다음 두 방식으로 사용한다.

### 11.1 여러 작업물 병렬 처리

여러 Challenge를 동시에 Factory에 흘려보낸다.

```text
Challenge A → Planning
Challenge B → Build
Challenge C → Debug
Challenge D → QA
```

---

### 11.2 같은 작업물의 여러 다음 수 생성

한 workspace가 특정 단계에 도달하면, 여러 worker가 서로 다른 다음 수를 제안할 수 있다.

예:

```text
Worker A: 핵심 루프 개선 patch
Worker B: UI 흐름 개선 patch
Worker C: 상태 모델 개선 patch
Worker D: 테스트 추가 patch
Worker E: Forbidden 위반 검사
```

여러 patch 후보가 있을 경우 선택 기준은 다음 순서다.

```text
1. 적용 가능 여부
2. 문법 검사 통과
3. contract gate 통과
4. smoke check 통과
5. 수정 범위가 작은 것
6. Difficulty Anchor 반영 점수가 높은 것
7. Forbidden Simplification 위반이 없는 것
```

하네스가 검증 결과를 보고 적용할 후보를 고른다.

---

## 12. Key 상태 공유 원칙

Challenge daemon과 Product Factory는 같은 key 상태 저장소를 공유해야 한다.

이유:

```text
Challenge daemon과 Product Factory가 동시에 실행될 수 있기 때문이다.
```

규칙:

```text
한 key는 동시에 하나의 작업만 수행한다.
Challenge 작업이든 Factory 작업이든 key status는 공통으로 관리한다.
```

공통 status:

```text
available
in_flight
cooldown
exhausted
disabled
```

429/500 처리 정책도 기존 Challenge Mode와 동일하게 따른다.

```text
429/500은 해당 key만 짧게 cooldown
전체 daemon/factory 중단 금지
명확한 daily quota exhausted 메시지가 있을 때만 exhausted 처리
```

---

## 13. Docker 사용 원칙

Docker는 허용한다.

Docker의 목적:

```text
생성 코드 격리
의존성 설치 테스트
문법 검사
간단 실행 검사
smoke test
로컬 환경 오염 방지
```

Docker는 검증 샌드박스다.
배포 인프라가 아니다.

금지:

```text
Docker를 배포 시스템으로 확대
Kubernetes
복잡한 compose 운영
CI/CD 대형화
처음부터 상용 운영 환경 흉내
```

Docker 실행은 두 단계로 나눈다.

### 13.1 Dependency Install 단계

의존성 설치가 필요한 경우 제한적으로 network를 허용할 수 있다.

예:

```text
npm install
pip install -r requirements.txt
```

조건:

```text
timeout 필수
secret/env/home mount 금지
workspace만 mount
CPU/memory 제한
실패 로그 저장
```

---

### 13.2 Execution/Test 단계

실행/테스트 단계는 기본적으로 network disabled 또는 제한 모드로 실행한다.

조건:

```text
.env 파일을 mount하지 않는다.
API key 파일을 mount하지 않는다.
사용자 홈 디렉터리를 mount하지 않는다.
repo 루트 전체를 mount하지 않는다.
workspace 디렉터리만 필요한 범위로 mount한다.
CPU 제한을 둔다.
memory 제한을 둔다.
timeout을 둔다.
컨테이너 실행 로그에 secret-like 문자열이 포함되면 실패 처리한다.
```

금지 예:

```text
docker run -v $HOME:/host ...
docker run -v .:/repo ...
docker run --network host ...
```

---

## 14. 검증 단계

검증은 싼 것부터 시작한다.

### Level 0 — 파일 존재 검사

```text
필수 파일 존재
README 존재
manifest 존재
contract 존재
entrypoint 존재
```

### Level 1 — 구조 검사

```text
manifest와 실제 파일 일치
contract와 실제 코드 일치
고아 모듈 없음
fake multi-file 없음
```

### Level 2 — 문법 검사

```text
node --check
python -m py_compile
json parse
html reference check
```

### Level 3 — 의존성 설치 검사

```text
npm install
pip install -r requirements.txt
```

timeout 필수.

### Level 4 — 기본 실행 검사

```text
npm run build
npm test
python main.py --help
node main.js
static server로 index.html 열기
```

### Level 5 — 간단 smoke check

```text
앱이 시작되는가
콘솔 에러가 없는가
핵심 파일이 로드되는가
입력/버튼/상태 변화가 최소한 존재하는가
```

### Level 6 — 고급 QA

초기 필수 아님.

```text
Playwright
브라우저 자동 클릭
시각적 비교
복잡한 E2E
```

초기 Product Factory는 Level 0~4를 필수로 하고, 가능하면 Level 5까지 간다.

---

## 15. Product Verdict 라벨

최종 라벨:

```text
PROMOTE_TO_CODEX
KEEP_CANDIDATE
NEEDS_MORE_GEMMA_LOOP
TOO_WEAK
DROP
```

의미:

```text
PROMOTE_TO_CODEX
- Codex/Claude에게 넘겨 제품화/정리/확장할 가치가 있음.

KEEP_CANDIDATE
- 지금 당장 승격은 아니지만 보관할 가치 있음.

NEEDS_MORE_GEMMA_LOOP
- 가능성은 있으나 아직 문법/구조/실행/상호작용 중 하나가 부족함.

TOO_WEAK
- 실행은 되지만 제품 느낌이 약함.

DROP
- 버림.
```

Dashboard 버튼과 매핑:

```text
PROMOTE_TO_CODEX → PRODUCTIZE 추천
KEEP_CANDIDATE → KEEP 추천
NEEDS_MORE_GEMMA_LOOP → RETRY 추천
TOO_WEAK → ARCHIVE 또는 DROP 추천
DROP → DROP 추천
```

---

## 16. Codex/Claude 승격 기준

Codex/Claude는 초기 구현자가 아니다.

Codex/Claude는 살아남은 후보를 제품화/정리/확장하는 고급 작업자다.

중요:

```text
PROMOTE_TO_CODEX는 Codex/Claude 자동 호출이 아니다.
이번 범위는 Codex/Claude에 넘길 수 있는 export bundle 생성까지다.
Codex/Claude 실제 실행, API 연동, 자동 PR 생성은 이번 범위에 포함하지 않는다.
```

Codex/Claude로 넘길 최소 조건:

```text
1. 멀티파일 workspace가 있다.
2. manifest/contract가 있다.
3. 필수 파일 존재 검사를 통과했다.
4. 문법 검사를 통과했다.
5. import/export 또는 파일 연결 계약을 통과했다.
6. 기본 실행 또는 smoke check를 통과했다.
7. 핵심 상호작용/룰/상태 변화가 최소 1개 이상 실제 코드에 있다.
8. Difficulty Anchors가 qa_report에서 확인됐다.
9. Forbidden Simplifications 위반이 없다.
10. debug loop 기록이 있다.
```

Codex/Claude export bundle:

```text
codex_export/
  source_workspace/
  manifest.json
  contract.json
  challenge_card.md
  product_brief.md
  ux_flow.md
  technical_plan.md
  syntax_report.md
  smoke_report.md
  qa_report.md
  debug_history.jsonl
  known_issues.md
  next_goal.md
```

Codex/Claude 역할:

```text
구조 정리
버그 수정
리팩토링
테스트 강화
핵심 상호작용 강화
제품화 가능 수준으로 확장
```

Codex/Claude가 하면 안 되는 것:

```text
처음부터 새로 만들기
Challenge를 무시하고 다른 앱으로 바꾸기
검증 리포트를 무시하기
Difficulty Anchors 제거하기
```

---

## 17. Dashboard 역할

Dashboard는 중간 지시판이 아니다.

Dashboard는 최종 검수함이다.

Dashboard가 보여줄 것:

```text
최종 작업물
Product Verdict
검증 통과/실패
QA 결과
Difficulty Anchor 반영 여부
Forbidden 위반 여부
Codex/Claude 승격 여부
Codex/Claude export bundle 경로
실패 원인
```

사람 버튼:

```text
KEEP
DROP
PRODUCTIZE
RETRY
ARCHIVE
```

수동 시작 버튼은 있어도 되지만 기본 흐름은 자동이다.

---

## 18. DB 추가 요구사항

기존 `challenge.db`에 Product Factory 관련 테이블을 추가한다.

### 18.1 product_runs

```text
id
challenge_id
status
current_stage
workspace_dir
final_artifact_dir
verdict
created_at
updated_at
```

### 18.2 product_tasks

```text
id
product_run_id
desk_name
status
input_artifact
output_artifact
attempt_count
worker_key_id
created_at
updated_at
last_error
```

`worker_key_id`는 실제 API key가 아니라 내부 ID만 저장한다.

### 18.3 product_events

```text
id
product_run_id
timestamp
event_type
message
metadata_json
```

### 18.4 product_artifacts

```text
id
product_run_id
artifact_type
path
created_at
```

---

## 19. CLI 추가 요구사항

### 19.1 자동 Product Factory 실행

기본 실행은 안전 모드여야 한다.

```bash
python -m repo_idea_miner factory --mode mock --once
python -m repo_idea_miner factory --mode live --max-runs 3
```

대량 자동 처리는 사용자가 명시적으로 요청한 경우에만 허용한다.

```bash
python -m repo_idea_miner factory --mode live --continuous
```

원칙:

```text
factory 명령은 기본적으로 무제한으로 돌면 안 된다.
--once 또는 --max-runs N 같은 제한이 있어야 한다.
--continuous를 명시한 경우에만 계속 실행한다.
```

---

### 19.2 단일 Challenge에서 Product Factory 실행

```bash
python -m repo_idea_miner factory-build --challenge-id <id> --mode mock
python -m repo_idea_miner factory-build --challenge-dir <path> --mode live
python -m repo_idea_miner factory-build --sample mock --mode mock
```

source of truth 규칙:

```text
--challenge-id는 challenge.db에 저장된 challenge를 source of truth로 사용한다.
--challenge-dir은 DB 없이 run artifact만으로 Product Factory를 실행하는 fallback 경로다.
--sample mock은 실제 challenge_id 없이 고정 sample challenge로 mock Product Factory를 실행한다.
여러 입력이 동시에 주어지면 --challenge-id를 우선한다.
```

---

### 19.3 상태 확인

```bash
python -m repo_idea_miner factory-status
```

---

### 19.4 검증

```bash
python -m repo_idea_miner factory-validate <product_run_dir>
```

---

## 20. Mock Mode 요구사항

mock mode에서도 전체 Product Factory 흐름이 돌아야 한다.

```bash
python -m repo_idea_miner factory-build --sample mock --mode mock
```

mock mode는 placeholder만 만들면 안 된다.

테스트 가능한 고정 workspace를 생성해야 한다.

---

## 21. Live Mode 요구사항

live mode는 기존 11-key controlled pool을 사용한다.

주의:

```text
기존 key 정책을 깨지 말 것
Challenge daemon과 Factory가 같은 key 상태 저장소를 공유할 것
429/500은 해당 key만 짧게 cooldown
전체 factory 중단 금지
실패한 Desk만 retry 또는 fallback
API key를 산출물에 출력 금지
```

---

## 22. 테스트 요구사항

최소 테스트:

```text
1. factory CLI help
2. factory-build CLI help
3. factory-status CLI help
4. factory-validate CLI help
5. factory --mode mock --once 실행
6. factory --mode live --max-runs 제한 확인
7. factory --mode live --continuous 명시 옵션 확인
8. factory-build --sample mock --mode mock 실행
9. factory-build mock 실행
10. product_brief.md 생성
11. ux_flow.md 생성
12. technical_plan.md 생성
13. manifest.json 생성
14. contract.json 생성
15. 멀티파일 src 생성
16. Final Artifact가 단일파일이면 실패
17. manifest와 실제 파일 불일치 시 실패
18. contract와 실제 코드 불일치 시 실패
19. V1 Contract Gate가 파일/entrypoint/import graph/주요 모듈을 검사
20. 문법 검사 실패 시 Debug Desk로 이동
21. Debug Desk 최대 횟수 제한
22. smoke_report.md 생성
23. qa_report.md 생성
24. product_verdict.md 생성
25. PROMOTE_TO_CODEX일 때 codex_export/ bundle 생성
26. Codex/Claude 자동 호출이 발생하지 않음
27. product_runs/product_tasks/product_events row 생성
28. worker_key_id가 실제 secret을 포함하지 않음
29. Challenge daemon과 Factory가 key 상태 저장소를 공유
30. Docker dependency install 단계와 execution/test 단계 분리
31. Docker sandbox가 .env/API key/home directory를 mount하지 않음
32. patch 후보 선택 기준 테스트
33. Dashboard에서 Product Verdict 표시
34. Dashboard 버튼과 Product Verdict 매핑 확인
35. 기존 RIM run/search/view/serve/validate 동작 유지
36. 기존 Challenge Mode 동작 유지
37. secret scan 통과
```

---

## 23. 완료 기준

완료 기준:

```text
1. Challenge에서 Final Artifact까지 사람 개입 없이 진행된다.
2. 최종 작업물은 단일파일이 아니라 멀티파일 workspace다.
3. manifest/contract가 생성된다.
4. manifest/contract와 실제 workspace를 검증한다.
5. V1 Contract Gate는 파일 존재, entrypoint, import/require graph, 주요 모듈 존재를 검사한다.
6. 문법 검사를 수행한다.
7. 기본 실행 또는 smoke check를 수행한다.
8. 실패 시 Debug Desk로 자동 이동한다.
9. 반복 실패 시 자동으로 DROP/TOO_WEAK/NEEDS_MORE_GEMMA_LOOP 판정한다.
10. QA가 Difficulty Anchors와 Forbidden Simplifications를 검사한다.
11. Product Verdict가 생성된다.
12. PROMOTE_TO_CODEX는 Codex/Claude 자동 호출이 아니라 export bundle 생성을 의미한다.
13. Dashboard에서 최종 작업물과 판정을 볼 수 있다.
14. Codex/Claude 승격 가능한 후보를 구분할 수 있다.
15. factory 기본 실행은 --once 또는 --max-runs 안전장치를 가진다.
16. Docker sandbox는 secret과 사용자 환경을 노출하지 않는다.
17. Challenge daemon과 Product Factory는 같은 key 상태 저장소를 공유한다.
18. 기존 RIM 기능과 Challenge Mode 기능이 깨지지 않는다.
```

---

## 24. 작업 보고 형식

완료 후 아래 형식으로 보고한다.

```text
RIM Product Factory 작업 보고

Base 상태
- 시작 HEAD:
- 종료 HEAD:
- origin ahead/behind:
- push 여부:

수정 파일
-

기존 기능 보존 확인
- run:
- search:
- view:
- serve:
- validate:
- challenge:
- challenge-search:
- daemon:
- dashboard:

추가 기능
- factory:
- factory-build:
- factory-status:
- factory-validate:
- Product Planning Desk:
- UX/Spec Desk:
- Technical Spec Desk:
- Build Desk:
- Static Gate:
- Contract Gate:
- Syntax Gate:
- Smoke Gate:
- Debug Desk:
- QA Desk:
- Judge Desk:
- Codex/Claude export bundle:

실행 검증
- factory --mode mock --once:
- factory --mode live --max-runs 1:
- factory-build --sample mock --mode mock:
- factory-build --challenge-id <id> --mode mock:
- factory-validate <product_run_dir>:

DB 확인
- product_runs:
- product_tasks:
- product_events:
- product_artifacts:
- key state shared with challenge daemon:

Docker 확인
- dependency install 단계:
- execution/test 단계:
- network 정책:
- mount 정책:
- timeout/CPU/memory 제한:

테스트
- pytest:
- secret scan:

생성 산출물 예시
- product_run_dir:
- final_artifact:
- manifest.json:
- contract.json:
- syntax_report.md:
- contract_report.md:
- smoke_report.md:
- qa_report.md:
- product_verdict.md:
- codex_export:

주의사항
- 남은 한계:
- 후속 추천:
```

---

## 25. 최종 정의

이번 작업은 발굴 기능 추가가 아니다.

이번 작업은 RIM을 다음 단계로 확장하는 것이다.

> RIM Product Factory는 Challenge Mode가 발굴한 후보를 받아, 11개 Gemma worker capacity와 검증 하네스를 이용해 사람 개입 없이 멀티파일 workspace를 기획, 설계, 구현, 검증, 디버깅, QA까지 진행하고, 최종적으로 Codex/Claude로 넘길 수 있는 export bundle을 만들 만한 제품 후보 또는 버릴 후보를 자동 판정하는 생산 파이프라인이다.
