# RIM Challenge Mode 정식 외주 주문서

## 기존 BN8624/RIM 구조 기준 구현 지시서

## 0. 작업 목표

기존 `BN8624/RIM` 저장소에 **Challenge Mode**를 정식 기능으로 추가한다.

이번 작업은 RIM을 새로 만드는 작업이 아니다.
기존 RIM의 `run`, `search`, `view`, `serve`, `validate` 기능과 기존 산출물 구조를 보존한 채, 별도의 Challenge Mode 계열 기능을 추가하는 작업이다.

이번 작업에서는 `RCM`, `Repo Challenge Miner`, `RIM RCM Mode` 같은 별도 명칭을 사용하지 않는다.

용어는 다음으로 통일한다.

```text
RIM
- 기존 저장소/프로젝트 이름

Challenge Mode
- RIM에 추가되는 새 기능 모드
- GitHub 레포를 구현 도전 과제로 변환하는 기능

Challenge Miner
- 로컬에서 계속 실행되며 repo 후보를 수집하고 Challenge를 생성하는 백그라운드 처리기

Challenge Dashboard
- 생성된 Challenge를 확인하고 SAVE / DROP / BUILD 판정하는 로컬 대시보드

Challenge Card
- 레포에서 추출한 구현 도전 과제 문서

Owner Brief
- 바이브코더 사용자가 이해할 수 있도록 쉽게 설명한 요약

Screen Story
- 실제 화면과 조작 흐름 설명

Implementation Prompt
- Claude/Codex/Gemma/외주 개발자에게 바로 넘기는 구현 지시문
```

금지 용어:

```text
RCM
Repo Challenge Miner
RIM RCM Mode
RCM Mode
```

한 줄 정의:

> RIM Challenge Mode는 GitHub 레포를 분석해 “제품 아이디어”가 아니라 “구현 도전 과제”로 변환하고, Gemma/Codex/Claude가 쉬운 구현으로 도망가지 못하도록 Difficulty Anchors와 Forbidden Simplifications를 포함한 Challenge Card를 생성하는 기능이다.

---

## 1. 현재 RIM 구조를 전제로 한 작업 원칙

현재 RIM에는 이미 다음 구조가 있다.

```text
repo_idea_miner/
  cli.py
  pipeline.py
  search_pipeline.py
  github_api.py
  key_pool.py
  llm_client.py
  schemas.py
  renderer.py
  viewer.py
  serve.py
  validate_run.py
  ...
```

기존 RIM 기능은 다음과 같다.

```text
run
- 단일 repo 분석
- idea_card.md 생성
- run_report.md 생성
- debug/evidence_packet.md 생성
- worker_outputs / judge_output 생성

search
- GitHub 검색 결과 기반 후보 분석
- top_ideas.md 생성
- search_report.md 생성
- candidates.json 생성
- cards/와 repos/ 생성

view
- run 디렉터리에서 모바일용 viewer.html 생성

serve
- run 디렉터리를 읽기 전용으로 serve

validate
- run 디렉터리 산출물, JSON, secret, viewer 등을 검증
```

이번 작업에서는 이 기존 기능을 깨면 안 된다.

---

## 2. 핵심 구현 방향

기존 RIM idea mode:

```text
repo → evidence packet → workers → critic/judge → idea_card → KEEP/MAYBE/DROP
```

추가할 Challenge Mode:

```text
repo/search result
→ repo snapshot/evidence 재사용
→ ChallengePackage JSON 생성
→ Owner Brief
→ Screen Story
→ Challenge Card
→ Implementation Prompt
→ Validation
→ SQLite 저장
→ Dashboard 표시
→ 사용자 SAVE / DROP / BUILD 판정
```

기존 RIM의 목적은 “이 레포에서 아이디어를 가져올 만한가?”를 판단하는 것이다.

Challenge Mode의 목적은 다르다.

```text
GitHub 레포의 핵심 상호작용과 어려운 구조를 뽑아
Gemma/Codex/Claude/외주 개발자가 쉽게 축소하지 못하는
구현 도전 과제로 바꾸는 것.
```

Challenge Mode에서 가장 중요한 필드는 다음 두 개다.

```text
1. Difficulty Anchors
2. Forbidden Simplifications
```

`Difficulty Anchors`는 작게 줄여도 절대 삭제하면 안 되는 원본 레포의 핵심 난이도다.

`Forbidden Simplifications`는 구현자가 쉬운 앱으로 축소하지 못하게 막는 금지 목록이다.

예:

```text
원본 레포:
Raycast류 command launcher

Difficulty Anchors:
- 키보드 중심 명령 검색
- 명령 실행
- 실행 결과 카드 표시
- 결과 카드에서 후속 액션 제공

Forbidden Simplifications:
- 단순 검색창으로 만들지 말 것
- 링크 모음으로 만들지 말 것
- 정적 메뉴판으로 만들지 말 것
- TODO 앱으로 바꾸지 말 것
```

---

## 3. 기존 파일을 어떻게 다룰지

### 3.1 유지할 파일 / 기능

다음은 기존 동작을 유지한다.

```text
cli.py
- 기존 run/search/view/serve/validate 명령 유지
- 새 challenge/challenge-search/daemon/dashboard/status/pause/resume/validate-db 명령 추가

pipeline.py
- 기존 단일 repo idea mode용으로 유지
- Challenge Mode 로직을 여기에 크게 섞지 말 것

search_pipeline.py
- 기존 search idea mode용으로 유지
- Challenge Search 로직을 여기에 크게 섞지 말 것

github_api.py
- 기존 GitHub collector 재사용

key_pool.py
- 기존 run/search live mode용 KeyPool 보존

llm_client.py
- 기존 GoogleGenAIGemmaClient / MockLLMClient / LLMCallLogger 보존

renderer.py
- 기존 idea_card / run_report / search_report renderer 보존

viewer.py
- 기존 run 디렉터리용 정적 viewer.html 생성 기능 보존

serve.py
- 기존 run 디렉터리 읽기 전용 serve 기능 보존

validate_run.py
- 기존 run artifact 검증 기능 보존
```

### 3.2 새로 추가할 파일 권장

Challenge Mode는 기존 pipeline에 억지로 우겨넣지 말고 병렬 모듈로 추가한다.

권장 파일:

```text
repo_idea_miner/
  challenge_schemas.py
  challenge_pipeline.py
  challenge_search_pipeline.py
  challenge_renderer.py
  challenge_db.py
  challenge_daemon.py
  challenge_dashboard.py
  challenge_key_scheduler.py
  challenge_validate.py
  challenge_prompts.py  또는 prompts/challenge_package.md
```

기존 `schemas.py`에 추가해도 되지만, 스키마가 커지면 `challenge_schemas.py`로 분리하는 것을 권장한다.

중요:

```text
기존 pipeline.py / search_pipeline.py를 Challenge Mode까지 담당하는 거대 파일로 만들지 말 것.
기존 idea mode와 Challenge Mode의 판정 라벨, schema, renderer가 섞이지 않게 할 것.
```

---

## 4. 추가할 CLI

기존 `cli.py`에 다음 명령을 추가한다.

### 4.1 단일 레포 Challenge 생성

```bash
python -m repo_idea_miner challenge \
  --repo https://github.com/OWNER/REPO \
  --mode mock
```

```bash
python -m repo_idea_miner challenge \
  --repo https://github.com/OWNER/REPO \
  --mode live
```

옵션:

```text
--repo      GitHub repo URL
--mode      mock 또는 live
--output-dir 기본 runs/
--max-issues 기존 run 옵션과 동일 기본값 사용
--max-prs 기존 run 옵션과 동일 기본값 사용
--tree-depth 기존 run 옵션과 동일 기본값 사용
```

구현 원칙:

```text
- 기존 run 명령을 대체하지 않는다.
- 기존 run 명령의 KEEP/MAYBE/DROP idea_card 산출물을 변경하지 않는다.
- challenge 명령은 Challenge Mode 전용 산출물을 생성한다.
```

---

### 4.2 GitHub 검색 기반 Challenge 생성

```bash
python -m repo_idea_miner challenge-search \
  --query "stars:>10000 language:TypeScript" \
  --limit 50 \
  --top 20 \
  --mode live
```

옵션 의미:

```text
--limit
GitHub Search API에서 가져올 최대 repo 후보 수

--top
중복 제거, 기본 필터, 우선순위 정렬 후 실제 Challenge 생성 대상으로 넘길 최대 repo 수
```

예:

```text
--limit 50 --top 20이면
GitHub에서 최대 50개 repo를 가져오고,
중복/필터/정렬 후 최대 20개 repo에 대해서만 Gemma Challenge 생성을 수행한다.
```

요구사항:

```text
- 기존 search 명령을 대체하지 않는다.
- 기존 search_pipeline.py를 크게 변경하지 말고 challenge_search_pipeline.py를 추가한다.
- 검색 결과를 candidates로 저장한다.
- 각 repo에 대해 ChallengePackage를 생성한다.
- GOOD_CHALLENGE / STEAL_ONLY를 상단에 둔다.
- TOO_EASY / DROP / UNCLEAR_TO_OWNER는 낮은 우선순위로 둔다.
- 결과는 run artifact와 SQLite DB에 모두 저장한다.
```

---

### 4.3 로컬 Challenge Miner 실행

```bash
python -m repo_idea_miner daemon
```

역할:

```text
- GitHub search seed를 주기적으로 수집한다.
- repo_queue에 저장한다.
- 중복 repo는 skip한다.
- 가능한 API key에 작업을 배정한다.
- ChallengePackage를 계속 생성한다.
- 결과를 challenge.db와 runs/에 저장한다.
- validation을 수행한다.
- Challenge Dashboard에서 볼 수 있게 한다.
```

---

### 4.4 Challenge Dashboard 실행

```bash
python -m repo_idea_miner dashboard \
  --host 127.0.0.1 \
  --port 8787
```

Tailscale에서 아이폰 Safari로 보려면 사용자가 명시적으로 다음처럼 실행할 수 있어야 한다.

```bash
python -m repo_idea_miner dashboard \
  --host 0.0.0.0 \
  --port 8787
```

주의:

```text
Dashboard는 기본 host가 반드시 127.0.0.1이어야 한다.
0.0.0.0 바인딩은 사용자가 명시적으로 실행한 경우에만 허용한다.
README에 “Tailscale 등 사설망에서만 사용할 것”을 명시한다.
```

---

### 4.5 상태 확인 / 제어

다음 명령을 추가한다.

```bash
python -m repo_idea_miner status
python -m repo_idea_miner pause
python -m repo_idea_miner resume
```

동작:

```text
status
- daemon 상태, queue 수, 완료 수, error 수, key 상태를 표시한다.

pause
- 새 작업 배정을 중단한다.
- 이미 진행 중인 작업은 안전하게 끝나게 한다.
- settings 테이블에 miner_paused=true를 저장한다.

resume
- 새 작업 배정을 재개한다.
- settings 테이블에 miner_paused=false를 저장한다.
```

---

### 4.6 검증 명령

기존 validate는 유지한다.

```bash
python -m repo_idea_miner validate runs/run-xxxx/
```

Challenge DB 검증은 별도 명령으로 추가한다.

```bash
python -m repo_idea_miner validate-db --db challenge.db
```

또는 다음도 허용한다.

```bash
python -m repo_idea_miner validate runs/run-xxxx/ --db challenge.db
```

원칙:

```text
validate
- run artifact 검증

validate-db
- SQLite DB integrity, 테이블 존재, artifact_dir 경로 정합성 검증
```

기존 validate 동작을 깨지 말 것.

---

## 5. 출력 폴더 구조

### 5.1 단일 repo challenge 실행 결과

```text
runs/<timestamp>/
  snapshot.json
  owner_brief.json
  owner_brief.md
  screen_story.json
  screen_story.md
  challenge_card.json
  challenge_card.md
  implementation_prompt.md
  validation_report.json
  viewer.html
```

### 5.2 challenge-search 실행 결과

```text
runs/<timestamp>/
  search_report.json
  challenge_index.json
  viewer.html

  repos/
    owner__repo1/
      snapshot.json
      owner_brief.json
      owner_brief.md
      screen_story.json
      screen_story.md
      challenge_card.json
      challenge_card.md
      implementation_prompt.md
      validation_report.json

    owner__repo2/
      ...
```

### 5.3 viewer.html과 Dashboard 역할 분리

`viewer.html`과 `Challenge Dashboard`는 다르다.

```text
viewer.html
- 특정 run 디렉터리 결과를 정적으로 보는 파일
- 기존 view/serve 흐름과 유사
- artifact 확인용

Challenge Dashboard
- challenge.db를 읽는 로컬 웹 UI
- 계속 쌓인 Challenge를 필터/검색/판정하는 확인함
- SAVE / MAYBE / DROP / BUILD NEXT 같은 쓰기 동작 있음
```

외주 구현자는 정적 viewer만 만들고 Dashboard를 생략하면 안 된다.

---

## 6. 사용자가 보는 핵심 파일

사용자가 먼저 볼 파일은 다음이다.

```text
owner_brief.md
screen_story.md
viewer.html
Challenge Dashboard
```

이 파일들은 바이브코더가 읽고 30초 안에 감이 와야 한다.

반드시 이해돼야 하는 것:

```text
- 이 레포가 쉽게 말해 뭔지
- 사람들이 왜 좋아하는지
- 우리가 훔칠 핵심이 뭔지
- 실제 화면은 어떻게 생길지
- 사용자는 무엇을 누를지
- 그냥 쉬운 앱과 무엇이 다른지
- Gemma/Codex/Claude에게 뭘 만들라고 시킬 수 있는지
```

---

## 7. 구현자에게 넘기는 파일

구현자에게 넘길 파일은 다음이다.

```text
implementation_prompt.md
```

이 파일은 그대로 복사해서 Claude Code, Codex, Gemma, 외주 개발자에게 줄 수 있어야 한다.

반드시 포함:

```text
- 구현 목표
- 산출 파일 목록
- 기술 제약
- Difficulty Anchors
- Forbidden Simplifications
- Allowed Simplifications
- Pass Criteria
- Failure Criteria
- 금지되는 쉬운 축소 버전
```

`challenge_card.json`에도 `implementation_prompt` 필드를 둘 수 있다.

정리:

```text
challenge_card.json의 implementation_prompt
- 원문 데이터

implementation_prompt.md
- 사람이 복사하기 좋게 렌더링한 파일

두 내용은 의미상 동일해야 하며 validate에서 누락/불일치 여부를 검사한다.
```

---

## 8. Challenge Mode Schema

Challenge Mode schema는 `challenge_schemas.py`에 두는 것을 권장한다.
기존 `schemas.py`에 추가해도 되지만, 기존 idea mode schema와 섞여 혼란이 생기지 않게 분리하는 것이 좋다.

### 8.1 OwnerBrief

```python
class OwnerBrief(BaseModel):
    source_repo: str
    what_is_this: str
    why_people_like_it: str
    what_we_steal: str
    what_screen_looks_like: str
    what_user_does: list[str]
    why_it_might_be_fun_or_useful: str
    how_it_differs_from_easy_version: str
    owner_clarity_score: int
    owner_clarity_risk: str
```

규칙:

```text
owner_clarity_score는 1~5 정수.
3 미만이면 GOOD_CHALLENGE가 될 수 없다.
```

---

### 8.2 ScreenStory

```python
class ScreenStory(BaseModel):
    first_screen: str
    user_actions: list[str]
    thirty_second_demo: str
    success_feeling: str
    failure_screen: str
```

목적:

```text
추상 설명이 아니라 실제 화면과 조작 흐름을 설명한다.
```

---

### 8.3 CoreInteraction

```python
class CoreInteraction(BaseModel):
    actor: str
    trigger: str
    loop: str
    reward: str
    state_change: str
    hard_part: str
```

---

### 8.4 ChallengeScores

```python
class ChallengeScores(BaseModel):
    difficulty_anchor_alive: int
    not_too_easy: int
    buildable_in_one_day: int
    visual_dependency_low: int
    immediate_demo_value: int
    owner_clarity: int
    user_taste_fit: int
    reuse_potential: int
```

각 항목은 1~5 정수다.

---

### 8.5 ChallengeCard

```python
class ChallengeCard(BaseModel):
    source_repo: str
    repo_summary: str

    surface_features: list[str]
    core_interaction: CoreInteraction

    difficulty_anchors: list[str]
    forbidden_simplifications: list[str]
    allowed_simplifications: list[str]

    challenge_title: str
    one_line_challenge: str

    poc_30_min: str
    build_1_day: str
    expansion_3_day: str

    pass_criteria: list[str]
    failure_criteria: list[str]

    scores: ChallengeScores

    final_label: Literal[
        "GOOD_CHALLENGE",
        "TOO_EASY",
        "TOO_BIG",
        "NOT_MY_TASTE",
        "STEAL_ONLY",
        "UNCLEAR_TO_OWNER",
        "DROP",
    ]

    taste_risk: str
    implementation_prompt: str
```

---

### 8.6 ChallengePackage

Gemma live 호출은 가능하면 하나의 구조화된 JSON을 반환한다.

```python
class ChallengePackage(BaseModel):
    owner_brief: OwnerBrief
    screen_story: ScreenStory
    challenge_card: ChallengeCard
```

기본 실행은 repo 하나당 LLM 호출 1회를 목표로 한다.

---

### 8.7 ChallengeIndex

```python
class ChallengeIndexItem(BaseModel):
    source_repo: str
    repo_url: str
    challenge_title: str
    one_line_challenge: str
    final_label: str
    owner_clarity_score: int
    score_total: int
    difficulty_anchors: list[str]
    short_reason: str
    artifact_dir: str

class ChallengeIndex(BaseModel):
    query: str | None
    mode: str
    total_candidates: int
    generated_count: int
    items: list[ChallengeIndexItem]
```

---

## 9. 판정 라벨

Challenge Mode는 기존 KEEP/MAYBE/DROP을 쓰지 않는다.

라벨:

```text
GOOD_CHALLENGE
TOO_EASY
TOO_BIG
NOT_MY_TASTE
STEAL_ONLY
UNCLEAR_TO_OWNER
DROP
```

의미:

```text
GOOD_CHALLENGE
- 작게 만들 수 있지만 핵심 난이도가 살아 있음.

TOO_EASY
- Gemma가 쉽게 만들 수 있는 뻔한 과제.
- 핵심 앵커가 약함.

TOO_BIG
- 핵심을 살리려면 현재 범위로 너무 큼.

NOT_MY_TASTE
- 구조는 좋지만 사용자가 끌릴 가능성이 낮음.

STEAL_ONLY
- 전체 과제는 별로지만 UI/루프/구조 하나는 훔칠 만함.

UNCLEAR_TO_OWNER
- 바이브코더 사용자가 읽어도 뭘 만들라는 건지 감이 안 옴.

DROP
- 만들 이유가 약함.
```

자동 판정 규칙:

```text
owner_clarity_score < 3
→ UNCLEAR_TO_OWNER

difficulty_anchor_alive < 3
→ TOO_EASY 또는 DROP

not_too_easy < 3
→ TOO_EASY

buildable_in_one_day < 2
→ TOO_BIG

immediate_demo_value < 3
→ DROP

difficulty_anchors가 비어 있음
→ validation 실패

forbidden_simplifications가 비어 있음
→ validation 실패

pass_criteria가 비어 있음
→ validation 실패

failure_criteria가 비어 있음
→ validation 실패
```

---

## 10. Prompt 구성

기본 live 호출은 통합 prompt를 사용한다.

권장 파일:

```text
prompts/
  challenge_package.md              # 기본 live 호출용 통합 prompt
  challenge_owner_brief.md           # 선택/디버그용
  challenge_core_interaction.md      # 선택/디버그용
  challenge_anti_easy_critic.md      # 선택/디버그용
  challenge_designer.md              # 선택/디버그용
  challenge_implementation_prompt.md # 선택/디버그용
  challenge_indexer.md               # 선택/검색 요약용
```

정책:

```text
Challenge Mode는 기본적으로 repo 하나당 LLM 호출 1회를 목표로 한다.

역할별 prompt는 디버그/실험용으로 둘 수 있지만,
기본 live 실행은 challenge_package.md 통합 prompt를 사용한다.
```

---

## 11. Prompt 공통 원칙

모든 Challenge Mode prompt에 다음 원칙을 포함한다.

```text
너는 제품 아이디어를 추천하지 않는다.
너는 GitHub 레포에서 구현 도전 과제를 추출한다.

목표는 쉬운 앱을 만드는 것이 아니다.
목표는 원본 레포의 핵심 난이도와 상호작용을 작게 재현하는 것이다.

단순 TODO 앱, 단순 검색창, 정적 대시보드, 요약기, 링크 모음으로 축소하지 마라.

반드시 Difficulty Anchors와 Forbidden Simplifications를 명시하라.

출력은 개발자만 이해하는 추상어가 아니라,
바이브코더 사장이 이해할 수 있는 장면으로 설명하라.
```

주의할 표현:

```text
architecture
abstraction
framework
pipeline
graph-based
real-time sync
extensible system
```

이런 단어를 쓰려면 반드시 쉬운 설명을 붙여야 한다.

---

## 12. Owner Brief 요구사항

`owner_brief.md`는 다음 질문에 답해야 한다.

```text
1. 이게 쉽게 말해 뭐냐?
2. 사람들이 왜 좋아하냐?
3. 우리가 훔칠 핵심은 뭐냐?
4. 화면에서 어떻게 보이냐?
5. 사용자는 뭘 누르냐?
6. 이걸 만들면 뭐가 재밌거나 쓸모 있냐?
7. 그냥 쉬운 버전과 뭐가 다르냐?
8. 바이브코더가 이해하기 어려운 지점은 뭐냐?
```

나쁜 출력:

```text
이 레포는 extensible graph-based workflow automation framework입니다.
```

좋은 출력:

```text
쉽게 말하면, 사용자가 명령어를 검색해서 바로 실행하고,
실행 결과에서 다시 다음 행동으로 이어가는 작업 명령 센터다.
```

---

## 13. Screen Story 요구사항

`screen_story.md`는 실제 화면 흐름을 설명한다.

반드시 포함:

```text
- 첫 화면
- 사용자가 누르는 것
- 화면이 바뀌는 순서
- 30초 데모 장면
- 성공했을 때 느낌
- 실패한 화면
```

예:

```text
첫 화면:
중앙에 command palette가 있다.

사용자 행동:
1. Ctrl/Cmd+K를 누른다.
2. report를 입력한다.
3. Create weekly report 명령을 선택한다.
4. 결과 카드가 생성된다.
5. 카드에서 Copy, Save, Run follow-up을 누를 수 있다.

실패한 화면:
검색창만 있고 실행 결과 카드가 없으면 실패다.
```

---

## 14. Challenge Card 요구사항

`challenge_card.md`는 과제 정의 문서다.

반드시 포함:

```text
- Source Repo
- One-line Challenge
- What Makes The Original Interesting
- Surface Features
- Core Interaction
- Difficulty Anchors
- Forbidden Simplifications
- Allowed Simplifications
- 30-Minute PoC
- 1-Day Build
- 3-Day Expansion
- Pass Criteria
- Failure Criteria
- Taste Risk
- Final Label
```

---

## 15. Implementation Prompt 요구사항

`implementation_prompt.md`는 바로 구현자에게 넘기는 지시문이다.

반드시 포함:

```text
- 너는 아래 Challenge Card를 구현한다.
- 핵심 난이도를 삭제하지 마라.
- Forbidden Simplifications를 위반하지 마라.
- 산출물 파일 목록
- 기술 제약
- 완료 기준
- 실패 기준
```

기본 산출물:

```text
index.html
style.css
app.js
README.md
```

기본 제약:

```text
서버 없음
DB 없음
로그인 없음
외부 API 없음
localStorage 허용
모바일 브라우저에서 확인 가능
```

단, 원본 레포 성격상 CLI 과제가 더 적합하면 HTML 대신 CLI 산출물로 바꿀 수 있다.
그 경우 Owner Brief에서 왜 CLI가 더 적합한지 설명해야 한다.

---

## 16. Challenge DB 요구사항

계속 쌓는 구조이므로 run 폴더만으로는 부족하다.
SQLite DB를 추가한다.

기본 DB 파일:

```text
challenge.db
```

사용자-facing 문서와 내부 구현 모두 Challenge 용어로 통일한다.
`rcm.db` 명칭은 사용하지 않는다.

필수 테이블:

### 16.1 repos

```text
repo_url
owner
name
description
stars
forks
language
topics
archived
fork
first_seen_at
last_seen_at
last_processed_at
process_status
```

---

### 16.2 repo_queue

```text
id
repo_url
source_query
priority
status
attempts
next_retry_at
created_at
updated_at
last_error
```

status:

```text
queued
in_progress
done
error
skipped
```

---

### 16.3 challenges

```text
id
repo_url
challenge_title
one_line_challenge
final_label
score_total
owner_clarity_score
difficulty_anchor_alive
not_too_easy
buildable_in_one_day
visual_dependency_low
immediate_demo_value
user_taste_fit
reuse_potential
artifact_dir
created_at
updated_at
```

---

### 16.4 owner_reviews

```text
challenge_id
owner_status
note
updated_at
```

owner_status:

```text
unseen
saved
maybe
dropped
build_next
built
```

LLM 판정과 사용자 판정은 분리한다.

예:

```text
final_label = GOOD_CHALLENGE
owner_status = maybe
```

---

### 16.5 api_keys

```text
key_id
status
daily_used
consecutive_errors
last_error_type
next_available_at
last_success_at
last_used_at
```

status:

```text
available
in_flight
cooldown
exhausted
disabled
```

---

### 16.6 events

```text
id
timestamp
event_type
message
repo_url
challenge_id
key_id
metadata_json
```

---

### 16.7 settings

```text
key
value
updated_at
```

필수 key:

```text
miner_paused
```

`pause/resume`은 이 settings 테이블을 사용한다.

---

## 17. Local Challenge Miner 요구사항

Challenge Miner는 로컬 PC에서 계속 실행될 수 있어야 한다.

명령:

```bash
python -m repo_idea_miner daemon
```

역할:

```text
1. GitHub search seed 실행
2. repo 후보 수집
3. 중복 제거
4. repo_queue 적재
5. available key에 작업 배정
6. Gemma로 ChallengePackage 생성
7. JSON validation
8. markdown render
9. SQLite 저장
10. dashboard index 갱신
```

daemon은 다음 상태를 유지해야 한다.

```text
- 대기 중 repo 수
- 처리 중 repo 수
- 완료 challenge 수
- 에러 수
- key별 상태
- 최근 생성 challenge
```

queue refill 설정:

```env
RIM_SEED_INTERVAL_MINUTES=60
RIM_QUEUE_REFILL_THRESHOLD=100
RIM_QUEUE_REFILL_TARGET=500
```

정책:

```text
daemon은 queue가 RIM_QUEUE_REFILL_THRESHOLD 아래로 내려가거나,
RIM_SEED_INTERVAL_MINUTES가 지났을 때 seed query를 실행해 repo_queue를 보충한다.
```

---

## 18. 11-Key Controlled Parallel Pool 요구사항

Challenge Miner는 11개 Gemma API key를 전제로 한다.

이 시스템은 일부러 느리게 처리하지 않는다.
key별 RPD 여유가 있고 Gemma 처리 시간이 실제 병목이므로, 가능한 모든 key가 계속 작업하도록 설계한다.

기본 정책:

```text
- key 1개당 동시에 1개 작업만 처리한다.
- 최대 11개 key가 동시에 작업할 수 있다.
- 작업이 끝난 key는 cooldown 상태가 아니면 즉시 다음 repo를 처리한다.
- 전체 worker를 멈추지 않는다.
- 에러가 발생한 key만 잠깐 cooldown 처리한다.
- 429와 500은 둘 다 짧은 일시 오류로 취급한다.
- 같은 key에서 에러가 반복되면 해당 key의 cooldown만 점진적으로 늘린다.
- 다른 key들은 계속 작업한다.
```

기본 설정값:

```env
RIM_MAX_IN_FLIGHT_PER_KEY=1
RIM_MAX_CONCURRENT_KEYS=11
RIM_KEY_MIN_INTERVAL_SECONDS=1
RIM_KEY_DAILY_RPD_LIMIT=1500

RIM_TRANSIENT_ERROR_BACKOFF_SEQUENCE_SECONDS=30,60,120,300
RIM_TIMEOUT_BACKOFF_SEQUENCE_SECONDS=60,120,300
RIM_BACKOFF_RESET_AFTER_SUCCESS=3
RIM_RESPECT_RETRY_AFTER=false
```

기존 `key_pool.py`는 단일 run/search live mode용으로 보존한다.
Challenge Miner용으로는 DB-backed key scheduler를 별도 추가한다.

권장 파일:

```text
challenge_key_scheduler.py
```

---

## 19. 429 / 500 처리 정책

429와 500은 둘 다 transient error로 취급한다.

```text
429:
- 실제 quota exhausted로 단정하지 않는다.
- 500과 같은 transient error로 취급한다.
- 해당 key만 30초 cooldown 처리한다.
- 같은 key에서 반복되면 60초 → 120초 → 300초로 늘린다.
- 전체 miner는 계속 진행한다.

500:
- Google/model/server 쪽 일시 오류로 취급한다.
- 해당 key만 30초 cooldown 처리한다.
- 같은 key에서 반복되면 60초 → 120초 → 300초로 늘린다.
- 전체 miner는 계속 진행한다.

timeout:
- 해당 repo snapshot이 과도하게 큰지 기록한다.
- repo 단위 축약 재시도를 허용한다.
- 같은 key에서 timeout이 반복되면 60초 → 120초 → 300초로 늘린다.

daily quota exhausted:
- 명확하게 daily quota/RPD exhausted 메시지가 확인될 때만 exhausted 처리한다.
- 단순 429만으로 key를 장시간 정지시키지 않는다.
```

성공 처리:

```text
- 성공 시 daily_used를 증가시킨다.
- 성공이 3회 연속 발생하면 consecutive_errors를 reset한다.
- key를 available 상태로 되돌린다.
- queue에 대기 작업이 있으면 즉시 다음 작업을 배정한다.
```

daily_used reset:

```text
daily_used는 안전용 로컬 카운터다.
기본값은 로컬 날짜 기준 00:00에 reset한다.
명확한 quota exhausted 응답이 있을 때만 exhausted 처리한다.
```

설정:

```env
RIM_DAILY_USAGE_RESET_HOUR=0
RIM_DAILY_USAGE_TIMEZONE=local
```

절대 하지 말 것:

```text
- 429 하나로 전체 miner를 멈추지 말 것.
- 429 하나로 key를 15분~1시간씩 길게 쉬게 하지 말 것.
- 모든 key에 공통 cooldown을 걸지 말 것.
- 11개 key를 단일 worker처럼 순차 처리하지 말 것.
- 일부러 하루 처리량을 낮게 제한하지 말 것.
```

---

## 20. LLM 호출 구조

repo 하나당 LLM 호출 수를 과하게 늘리지 않는다.

권장 구조:

```text
1회 호출:
ChallengePackage JSON 생성

로컬 renderer:
owner_brief.md
screen_story.md
challenge_card.md
implementation_prompt.md 생성
```

가능하면 markdown 파일 4개를 각각 LLM에게 따로 쓰게 하지 않는다.

이유:

```text
- 호출 수 감소
- key 효율 증가
- JSON validation 쉬움
- markdown render 일관성 증가
```

기존 `llm_client.py`의 단일 호출 retry 정책은 보존한다.
Challenge Miner daemon의 key별 cooldown 정책은 `challenge_key_scheduler.py` 또는 동등한 DB-backed scheduler에서 관리한다.

---

## 21. GitHub 수집 / Seed 요구사항

처음에는 GitHub를 기본 seed로 사용한다.

seed query는 설정 파일로 관리한다.

예:

```yaml
queries:
  - "stars:>10000 language:TypeScript"
  - "stars:>5000 language:Python"
  - "topic:productivity stars:>1000"
  - "topic:developer-tools stars:>1000"
  - "topic:note-taking stars:>500"
  - "topic:automation stars:>1000"
  - "topic:visualization stars:>1000"
  - "topic:local-first stars:>500"
```

수집 단계에서 LLM 호출을 하지 않는다.

수집 단계 필터:

```text
- archived repo 낮은 우선순위 또는 skip
- fork-only repo skip 가능
- README 너무 짧으면 낮은 우선순위
- 이미 처리한 repo skip
- 최근 처리한 repo 재처리 금지
- stars/language/topics 저장
```

---

## 22. Challenge Dashboard 요구사항

Challenge Dashboard는 제어판이 아니라 **작업물 확인함**이다.

사용자는 아이폰에서 SSH 없이 dashboard만 본다.

기본 host:

```text
127.0.0.1
```

0.0.0.0 바인딩은 사용자가 명시한 경우만 허용한다.

---

### 22.1 Today

```text
오늘 생성된 challenge 수
GOOD_CHALLENGE 수
STEAL_ONLY 수
TOO_EASY 수
DROP 수
에러 수
처리 중 repo 수
대기 중 repo 수
key별 상태 요약
```

---

### 22.2 Challenge List

필터:

```text
final_label
owner_status
source_query
language
created_at
score range
```

정렬:

```text
GOOD_CHALLENGE 우선
STEAL_ONLY 다음
owner_clarity_score 높은 순
score_total 높은 순
created_at 최신순
```

목록 카드 표시:

```text
repo
challenge_title
one_line_challenge
final_label
owner_clarity_score
score_total
short_reason
owner_status
```

---

### 22.3 Challenge Detail

탭:

```text
Owner Brief
Screen Story
Challenge Card
Implementation Prompt
Validation Report
```

---

### 22.4 Action Buttons

```text
SAVE
MAYBE
DROP
BUILD NEXT
MARK BUILT
COPY IMPLEMENTATION PROMPT
COPY CHALLENGE CARD
```

버튼 동작:

```text
- owner_reviews 테이블에 owner_status 저장
- note 입력 가능
- BUILD NEXT는 구현 후보로 따로 필터 가능해야 함
```

---

### 22.5 Dashboard 보안

```text
- 인증 기능은 만들지 않는다.
- 따라서 기본 host는 반드시 127.0.0.1이다.
- 0.0.0.0 바인딩은 사용자가 명시적으로 실행한 경우에만 허용한다.
- 0.0.0.0 사용 시 README에 “Tailscale 등 사설망에서만 사용할 것”을 명시한다.
- .env 노출 금지
- API key 노출 금지
- raw LLM prompt/response 기본 노출 금지
- dashboard HTML도 secret scan 대상
```

---

## 23. Search 기반 Challenge 요구사항

`challenge-search`는 단순히 검색 결과를 나열하면 안 된다.

검색 결과 repo들을 Challenge 후보로 바꾼 뒤, 사용자가 볼 수 있게 정렬해야 한다.

정렬 우선순위:

```text
1. GOOD_CHALLENGE
2. STEAL_ONLY
3. NOT_MY_TASTE
4. TOO_BIG
5. UNCLEAR_TO_OWNER
6. TOO_EASY
7. DROP
```

동일 라벨 안에서는 다음 점수로 정렬한다.

```text
difficulty_anchor_alive
not_too_easy
immediate_demo_value
owner_clarity
user_taste_fit
reuse_potential
```

`TOO_EASY`는 낮게 둔다.
이 도구의 목적은 쉬운 앱 후보를 찾는 게 아니기 때문이다.

---

## 24. Mock 모드 요구사항

mock 모드는 실제 Gemma 호출 없이도 전체 파일을 생성해야 한다.

```bash
python -m repo_idea_miner challenge --repo https://github.com/example/example --mode mock
```

```bash
python -m repo_idea_miner challenge-search --query "demo" --limit 5 --top 3 --mode mock
```

mock 결과는 placeholder만 있으면 안 된다.
테스트 가능한 고정 샘플이어야 한다.

---

## 25. Live 모드 요구사항

live 모드는 기존 Gemini/Gemma 설정을 재사용한다.

요구사항:

```text
- 기존 .env 구조를 깨지 말 것
- API key를 로그/산출물에 출력하지 말 것
- 실패 시 에러를 run artifact와 DB events에 남길 것
- JSON validation 실패 시 repair 또는 fail-safe 처리할 것
- raw LLM 응답이 저장된다면 secret scan 대상에 포함할 것
- 일부 repo 실패가 전체 challenge-search 또는 daemon을 중단시키지 않게 할 것
```

---

## 26. Validate 요구사항

기존 validate 동작은 유지한다.

```bash
python -m repo_idea_miner validate runs/<timestamp>/
```

Challenge artifact 검증은 기존 validate에 추가하거나 `challenge_validate.py`로 분리해도 된다.

DB 검증은 별도 명령으로 제공한다.

```bash
python -m repo_idea_miner validate-db --db challenge.db
```

검증 대상:

```text
owner_brief.json
screen_story.json
challenge_card.json
challenge_index.json
implementation_prompt.md
viewer.html
challenge.db
artifact_dir 경로 정합성
```

검증 규칙:

```text
- JSON schema 통과
- required field 누락 없음
- difficulty_anchors 길이 >= 1
- forbidden_simplifications 길이 >= 1
- pass_criteria 길이 >= 1
- failure_criteria 길이 >= 1
- owner_clarity_score 1~5
- scores의 모든 항목 1~5
- implementation_prompt.md 존재
- implementation_prompt.md 안에 Difficulty Anchors 반영
- implementation_prompt.md 안에 Forbidden Simplifications 반영
- viewer.html 존재
- viewer.html에 secret-like 문자열 없음
- DB 기본 테이블 존재
- DB row와 artifact_dir 경로 정합성 확인
```

---

## 27. 테스트 요구사항

최소 테스트:

```text
1. 기존 run CLI help 동작
2. 기존 search CLI help 동작
3. 기존 view/serve/validate 동작 유지
4. challenge CLI help 동작
5. challenge-search CLI help 동작
6. daemon CLI help 동작
7. dashboard CLI help 동작
8. validate-db CLI help 동작
9. challenge --mode mock 정상 종료
10. challenge-search --mode mock 정상 종료
11. 단일 challenge 실행 후 required output 생성
12. search challenge 실행 후 challenge_index.json 생성
13. challenge_card.json schema validation 통과
14. owner_brief.json schema validation 통과
15. screen_story.json schema validation 통과
16. forbidden_simplifications 비어 있으면 validation 실패
17. difficulty_anchors 비어 있으면 validation 실패
18. owner_clarity_score 범위 밖이면 validation 실패
19. implementation_prompt.md 생성
20. implementation_prompt.md에 금지 축소 목록 반영
21. viewer.html 생성
22. viewer.html secret scan 통과
23. SQLite 기본 테이블 생성
24. settings.miner_paused 저장/변경 가능
25. owner_status 저장/변경 가능
26. key별 cooldown이 전체 miner를 멈추지 않음
27. 429/500 mock error에서 해당 key만 cooldown 처리
28. 기존 RIM run/search/validate 테스트가 깨지지 않음
29. live 실패 repo가 전체 search run을 중단시키지 않음
```

가능하면 `pytest` 기준으로 작성한다.

---

## 28. 문서 요구사항

README 또는 별도 문서에 다음을 추가한다.

```text
- Challenge Mode가 무엇인지
- 기존 RIM idea mode와의 차이
- challenge 명령 사용법
- challenge-search 명령 사용법
- daemon 사용법
- dashboard 사용법
- validate-db 사용법
- challenge.db 위치와 역할
- 산출물 설명
- GOOD_CHALLENGE / TOO_EASY / UNCLEAR_TO_OWNER 라벨 의미
- Owner Brief와 Screen Story를 어떻게 읽는지
- Implementation Prompt를 어떻게 외주/Codex/Claude/Gemma에게 넘기는지
- 11-key controlled parallel pool 동작 방식
- 429/500 transient error 처리 방식
- Dashboard를 Tailscale 등 사설망에서만 0.0.0.0으로 열라는 주의사항
```

---

## 29. 완료 기준

작업 완료 기준:

```text
1. 기존 RIM 기능이 깨지지 않는다.
2. 기존 run/search/view/serve/validate가 계속 동작한다.
3. challenge 명령이 mock/live에서 동작한다.
4. challenge-search 명령이 mock/live에서 동작한다.
5. daemon 명령이 동작한다.
6. dashboard 명령이 동작한다.
7. validate-db 명령이 동작한다.
8. 단일 repo 실행 시 다음 산출물이 생성된다.
   - owner_brief.md
   - screen_story.md
   - challenge_card.md
   - implementation_prompt.md
   - viewer.html
   - validation_report.json

9. search 실행 시 여러 repo challenge가 생성되고 challenge_index.json이 생성된다.
10. challenge.db에 repos/repo_queue/challenges/owner_reviews/api_keys/events/settings 테이블이 생성된다.
11. dashboard에서 challenge 목록과 상세 내용을 볼 수 있다.
12. dashboard에서 SAVE / MAYBE / DROP / BUILD NEXT / MARK BUILT 판정 가능하다.
13. implementation_prompt.md를 바로 구현자에게 넘길 수 있다.
14. Difficulty Anchors가 schema 필수값이다.
15. Forbidden Simplifications가 schema 필수값이다.
16. Owner Brief가 바이브코더도 이해 가능한 문장으로 작성된다.
17. Screen Story가 실제 화면/조작 흐름을 설명한다.
18. validate가 Challenge Mode 산출물을 검사한다.
19. validate-db가 DB와 artifact_dir 정합성을 검사한다.
20. 11-key controlled parallel pool이 동작한다.
21. 429/500 발생 시 해당 key만 짧게 cooldown되고 전체 miner는 계속 진행한다.
22. 테스트 통과.
23. secret scan 통과.
24. README 또는 문서 업데이트 완료.
```

---

## 30. 작업 보고 형식

완료 후 아래 형식으로 보고한다.

```text
RIM Challenge Mode 작업 보고

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

추가 기능
- challenge 서브커맨드:
- challenge-search 서브커맨드:
- daemon:
- dashboard:
- validate-db:
- Owner Brief 출력:
- Screen Story 출력:
- Challenge Card 출력:
- Implementation Prompt 출력:
- Challenge DB:
- 11-key controlled parallel pool:

실행 검증
- python -m repo_idea_miner challenge --repo <sample> --mode mock:
- python -m repo_idea_miner challenge --repo <sample> --mode live:
- python -m repo_idea_miner challenge-search --query <sample> --limit <n> --top <n> --mode mock:
- python -m repo_idea_miner challenge-search --query <sample> --limit <n> --top <n> --mode live:
- python -m repo_idea_miner daemon:
- python -m repo_idea_miner dashboard:
- python -m repo_idea_miner validate <run_dir>:
- python -m repo_idea_miner validate-db --db challenge.db:

테스트
- pytest 결과:
- secret scan 결과:

DB 확인
- repos row count:
- repo_queue row count:
- challenges row count:
- owner_reviews update:
- api_keys state:
- settings.miner_paused:
- events row count:

생성 산출물 예시
- run dir:
- owner_brief.md:
- screen_story.md:
- challenge_card.md:
- implementation_prompt.md:
- viewer.html:
- dashboard URL:

주의사항
- 남은 한계:
- 후속 추천:
```

---

## 31. 최종 한 줄 정의

이번 작업은 RIM을 새로 만드는 작업이 아니다.

> 기존 BN8624/RIM의 run/search/view/serve/validate 구조를 보존한 채, Challenge Mode를 병렬 추가해 GitHub 레포를 바이브코더가 이해 가능한 화면/조작 스토리와 Gemma가 쉬운 구현으로 도망가지 못하는 구현 도전 과제로 변환하고, challenge.db와 Challenge Dashboard에 계속 쌓아 사용자가 좋은 후보만 SAVE/BUILD할 수 있게 만드는 작업이다.
