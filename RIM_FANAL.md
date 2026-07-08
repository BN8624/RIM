# Repo Idea Miner 최종 개발 요구서

## 1. 프로젝트명

Repo Idea Miner

---

## 2. 개발 목적

Repo Idea Miner는 GitHub 레포지토리 URL 또는 GitHub 검색어를 입력받아, 해당 레포의 README, Issues, PR, 파일 구조, dependency/runtime evidence를 수집·분석하고, 사용자가 5분 안에 **KEEP / MAYBE / DROP** 판단을 내릴 수 있는 아이디어 카드와 비교 리포트를 생성하는 Python CLI 도구다.

이 도구는 GitHub 레포를 긍정적으로 요약하는 도구가 아니다.

목적은 다음이다.

```text
GitHub 레포에서 가져올 만한 아이디어·패턴이 있는지 빠르게 판단한다.
별로인 아이디어는 빠르게 버린다.
README의 자기홍보와 실제 사용자 고통을 분리한다.
버그뿐 아니라 기능 요청, 자동화 요청, 워크플로우 불편도 함께 본다.
Dependency / Runtime / 유지보수 리스크를 과장하지도 축소하지도 않는다.
최종적으로 사용자가 KEEP / MAYBE / DROP을 빠르게 결정하게 한다.
```

---

## 3. 최종 납품 범위

최종 납품물은 다음 기능을 모두 포함해야 한다.

### 3.1 단일 레포 분석

GitHub repo URL 1개를 입력하면 해당 레포를 분석하고 다음 산출물을 생성한다.

```text
idea_card.md
run_report.md
debug/evidence_packet.md
debug/worker_outputs/*.json
debug/judge_output_raw.json
debug/judge_output_final.json
debug/llm_calls.jsonl
```

---

### 3.2 검색어 기반 레포 후보 분석

검색어를 입력하면 GitHub API로 후보 레포를 수집하고, 후보별 idea card를 생성한 뒤 최종 비교 리포트를 생성한다.

예:

```bash
python -m repo_idea_miner search \
  --query "automation workflow python" \
  --limit 30 \
  --top 10 \
  --mode live
```

출력:

```text
runs/<timestamp>/
- top_ideas.md
- search_report.md
- candidates.json

runs/<timestamp>/cards/
- OWNER_REPO_idea_card.md
- ...
```

---

### 3.3 Mock / Live 모드

다음 모드를 지원해야 한다.

```text
mock:
- 외부 LLM 호출 없음
- 전체 파이프라인 구조 검증용
- 테스트와 CI에서 사용

live:
- 실제 LLM 호출
- worker별 JSON output 생성
- JSON validation / repair / validator / renderer 전체 실행
```

---

### 3.4 Direct / Search input-mode

```text
direct:
- 사용자가 직접 지정한 레포
- star/fork/issue 수가 낮다는 이유만으로 hard drop 금지

search:
- GitHub 검색 결과 후보
- 낮은 activity, 빈 레포, archived 레포에 대해 더 공격적인 preflight drop 허용
```

---

## 4. 공식 API 사용 근거

### 4.1 사용 모델

사용 모델은 다음으로 고정한다.

```text
gemma-4-31b-it
```

Google 공식 문서 기준으로 Gemini API는 Gemma 4 모델 중 `gemma-4-31b-it`를 지원한다. 구현에서는 모델명을 코드에 직접 박지 말고 `.env`의 `RIM_GEMMA_MODEL` 값을 읽되, 기본값은 반드시 `gemma-4-31b-it`로 둔다.

```python
MODEL_NAME = os.getenv("RIM_GEMMA_MODEL", "gemma-4-31b-it")
```

---

### 4.2 Google GenAI SDK

Python SDK는 다음 패키지를 사용한다.

```bash
pip install -U google-genai
```

Python import 방식:

```python
from google import genai
```

Google GenAI SDK는 `genai.Client()`를 만들고 `client.models.generate_content(...)`로 모델을 호출하는 방식을 사용한다. SDK는 `GEMINI_API_KEY` 환경변수를 읽을 수 있고, 또는 `genai.Client(api_key=...)`처럼 명시적으로 API key를 전달할 수 있다. 본 프로젝트는 11개 key pool을 사용해야 하므로 전역 `GEMINI_API_KEY` 하나에 의존하지 말고, 선택된 key를 `genai.Client(api_key=selected_key)`로 명시 전달한다.

예시:

```python
from google import genai

def call_gemma_once(api_key: str, prompt: str, model: str = "gemma-4-31b-it") -> str:
    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=model,
        contents=prompt,
    )

    return response.text
```

실제 구현에서는 위 예시에 다음을 추가해야 한다.

```text
timeout
retry
key rotation
rate limit handling
JSON extraction
secret redaction
usage logging
worker name logging
```

---

## 5. 기술 요구사항

### 5.1 언어

Python 3.11 이상.

---

### 5.2 실행 환경

다음 환경에서 동작해야 한다.

```text
Linux
macOS
Windows
```

---

### 5.3 패키징

다음 방식으로 실행 가능해야 한다.

```bash
python -m repo_idea_miner ...
```

`pyproject.toml` 기반 패키징을 제공해야 한다.

---

### 5.4 설정

환경변수 또는 `.env`를 통해 설정한다.

사용자는 `.env` 파일에 다음 인증 정보를 직접 넣어준다.

```env
# GitHub API token
GITHUB_TOKEN=

# Google AI Studio / Gemini Developer API keys
GOOGLE_API_KEY_1=
GOOGLE_API_KEY_2=
GOOGLE_API_KEY_3=
GOOGLE_API_KEY_4=
GOOGLE_API_KEY_5=
GOOGLE_API_KEY_6=
GOOGLE_API_KEY_7=
GOOGLE_API_KEY_8=
GOOGLE_API_KEY_9=
GOOGLE_API_KEY_10=
GOOGLE_API_KEY_11=

# Gemma model
RIM_GEMMA_MODEL=gemma-4-31b-it

# LLM provider
RIM_LLM_PROVIDER=google_genai_gemma

# Key pool
RIM_KEY_POOL_STRATEGY=round_robin

# Retry policy
RIM_MAX_RETRIES_PER_CALL=3
RIM_RETRY_BACKOFF_STRATEGY=exponential_jitter
RIM_RETRY_INITIAL_DELAY_SECONDS=2
RIM_RETRY_MAX_DELAY_SECONDS=60
RIM_RESPECT_RETRY_AFTER=true
RIM_RETRY_AFTER_MAX_SECONDS=300

# Request timeout
RIM_REQUEST_TIMEOUT_SECONDS=180

# Generation behavior
RIM_TEMPERATURE=0.2
RIM_JSON_REPAIR_ATTEMPTS=1
```

중요:

```text
GOOGLE_API_KEY_1 ~ GOOGLE_API_KEY_11은 각각 다른 Google AI Studio 프로젝트에서 발급된 독립 API key다.
GITHUB_TOKEN은 사용자가 제공하는 인증된 GitHub token이다.
외주 개발자는 실제 key 값을 요구하거나 문서/로그/테스트에 노출하면 안 된다.
```

---

### 5.5 `.env.example`

납품물에는 `.env.example`을 포함한다.

실제 `.env`는 포함하지 않는다.

`.gitignore`에는 반드시 다음이 포함되어야 한다.

```gitignore
.env
.env.*
!.env.example
runs/
```

단, 샘플 산출물을 제공해야 하는 경우에는 secret이 없는 `samples/` 디렉터리에 별도로 넣는다.

---

## 6. LLM Provider 요구사항

### 6.1 Provider 이름

Provider 이름은 다음으로 한다.

```text
google_genai_gemma
```

---

### 6.2 LLM Client 인터페이스

다음 인터페이스를 구현한다.

```python
class LLMClient:
    def generate_json(
        self,
        prompt: str,
        schema_name: str,
        model: str | None = None,
        temperature: float = 0.2,
        max_retries: int = 3,
    ) -> dict:
        ...
```

요구사항:

```text
- prompt를 입력받아 Gemma API를 호출한다.
- 응답은 반드시 JSON object로 파싱 가능한 문자열이어야 한다.
- JSON parse 실패 시 syntax repair를 1회 시도한다.
- 누락 필드 창작은 금지한다.
- 최종 dict를 반환한다.
- 실패 시 LLMCallError 계열 예외를 발생시킨다.
```

---

### 6.3 REST 호출

기본 구현은 Python SDK 기반이다.

REST 호출은 fallback 또는 디버그용으로만 허용한다.

REST endpoint 형식은 다음 구조를 따른다.

```text
https://generativelanguage.googleapis.com/v1beta/models/gemma-4-31b-it:generateContent
```

단, 필수 구현은 Python SDK 기반이다.

---

## 7. 11개 Google API Key Pool 요구사항

### 7.1 Key Pool 목적

사용자는 Google AI Studio 프로젝트별로 1개씩, 총 11개의 독립 API key를 제공한다.

Repo Idea Miner는 이 11개 key를 하나의 key pool로 관리해야 한다.

목적:

```text
한 key에 호출이 몰리지 않게 한다.
rate limit / quota / transient error 발생 시 다른 key로 회전한다.
실패한 key를 같은 retry cycle 안에서 즉시 재사용하지 않는다.
어떤 key가 사용됐는지 값은 숨기고 key index만 기록한다.
```

---

### 7.2 Key 로딩 규칙

`.env`에서 다음 패턴을 읽는다.

```text
GOOGLE_API_KEY_1
GOOGLE_API_KEY_2
...
GOOGLE_API_KEY_11
```

허용:

```text
11개 전체가 있으면 모두 사용
일부만 있으면 존재하는 key만 사용하되 run_report에 loaded_key_count 기록
```

금지:

```text
key 값 출력
key 값을 run_report에 기록
key 값을 debug artifact에 저장
key 값을 exception message에 포함
```

---

### 7.3 Key 상태

각 key는 다음 상태를 가진다.

```text
AVAILABLE
TEMP_FAILED
DISABLED
```

의미:

```text
AVAILABLE:
- 사용 가능

TEMP_FAILED:
- 현재 retry cycle에서 일시 실패
- 같은 worker 호출 안에서는 즉시 재사용하지 않음
- 다음 worker 또는 다음 run에서는 다시 사용 가능

DISABLED:
- invalid key, 401, 403 등 인증/권한 문제
- 현재 run에서 제외
```

기존처럼 고정 `RIM_KEY_COOLDOWN_SECONDS=3600` 방식은 사용하지 않는다.

이유:

```text
3600초 cooldown은 공식 고정값이 아니다.
429가 항상 1시간 제한을 의미하지 않는다.
고정 cooldown은 11개 key pool 사용률을 불필요하게 떨어뜨릴 수 있다.
Retry-After 또는 exponential backoff + jitter가 더 일반적이고 안전하다.
```

---

### 7.4 Key 선택 전략

기본 전략은 round robin이다.

```env
RIM_KEY_POOL_STRATEGY=round_robin
```

요구사항:

```text
worker 호출마다 다음 AVAILABLE key를 선택한다.
같은 run 안에서 특정 key에만 호출이 몰리면 안 된다.
key index는 1~11로 기록한다.
실제 key 값은 절대 기록하지 않는다.
```

예:

```text
Bouncer → key_index 1
README Scout → key_index 2
Pain Scout → key_index 3
Structure/Risk Scout → key_index 4
Critic/Judge → key_index 5
다음 repo → key_index 6부터 계속
```

---

## 8. Retry / Backoff / Timeout 정책

### 8.1 공식 방향

Google 문서는 429 `RESOURCE_EXHAUSTED`를 rate limit 초과로 설명하며, 기다렸다가 재시도하거나 요청 속도·크기를 줄이는 방식으로 대응하라고 안내한다. Google의 Gen AI retry 전략 문서는 408, 429, 5xx, timeout, 네트워크 오류 같은 transient error에는 exponential backoff와 jitter, 최대 재시도 횟수 제한을 사용하는 것을 권장한다.

따라서 본 프로젝트는 고정 1시간 cooldown을 사용하지 않는다.

---

### 8.2 재시도 가능한 오류

다음 오류는 재시도 가능하다.

```text
408 request timeout
429 RESOURCE_EXHAUSTED
500 INTERNAL
502 BAD_GATEWAY
503 UNAVAILABLE
504 DEADLINE_EXCEEDED / GATEWAY_TIMEOUT
network timeout
connection reset
temporary transport error
```

처리:

```text
1. 현재 key의 실패를 기록한다.
2. Retry-After 값이 있으면 그 시간을 우선 따른다.
3. Retry-After가 없으면 exponential backoff + jitter를 적용한다.
4. 같은 retry cycle 안에서는 실패한 key를 즉시 재사용하지 않는다.
5. 다음 available key로 재시도한다.
6. 최대 RIM_MAX_RETRIES_PER_CALL 횟수까지만 재시도한다.
```

---

### 8.3 재시도하면 안 되는 오류

다음 오류는 재시도하지 않는다.

```text
400 bad request
401 unauthorized
403 permission denied
invalid API key
model not found
invalid model name
invalid request payload
schema construction bug
prompt construction bug
```

처리:

```text
401 / 403 / invalid API key:
- 해당 key를 현재 run에서 DISABLED 처리
- 다른 key가 있으면 같은 요청을 다른 key로 재시도 가능
- 모든 key가 인증 실패하면 run 실패

model not found / invalid model name:
- 전체 설정 오류로 보고 즉시 실패
- 다른 key로 반복 재시도하지 않음

invalid payload / schema bug / prompt bug:
- 코드 버그로 보고 즉시 실패
```

---

### 8.4 Exponential Backoff + Jitter 기본값

```env
RIM_MAX_RETRIES_PER_CALL=3
RIM_RETRY_BACKOFF_STRATEGY=exponential_jitter
RIM_RETRY_INITIAL_DELAY_SECONDS=2
RIM_RETRY_MAX_DELAY_SECONDS=60
RIM_RESPECT_RETRY_AFTER=true
RIM_RETRY_AFTER_MAX_SECONDS=300
```

계산 예시:

```python
import random

def compute_retry_delay(attempt: int, initial: float = 2.0, max_delay: float = 60.0) -> float:
    base = min(max_delay, initial * (2 ** attempt))
    jitter = random.uniform(0, base * 0.25)
    return base + jitter
```

예상 대기:

```text
attempt 0 → 약 2초 + jitter
attempt 1 → 약 4초 + jitter
attempt 2 → 약 8초 + jitter
최대값은 RIM_RETRY_MAX_DELAY_SECONDS를 넘지 않음
```

주의:

```text
위 숫자는 운영 기본값이다.
Google 공식 고정값이 아니다.
.env로 조정 가능해야 한다.
```

---

### 8.5 Retry-After 우선 정책

429 응답에 `Retry-After` 또는 유사 retry delay 정보가 포함되어 있으면 이를 우선한다.

```env
RIM_RESPECT_RETRY_AFTER=true
RIM_RETRY_AFTER_MAX_SECONDS=300
```

정책:

```text
1. API 응답에서 retry delay를 읽을 수 있으면 해당 값을 사용한다.
2. retry delay가 없으면 exponential backoff + jitter를 사용한다.
3. retry delay가 과도하게 길면 RIM_RETRY_AFTER_MAX_SECONDS를 상한으로 둔다.
```

---

### 8.6 Request Timeout

기본값:

```env
RIM_REQUEST_TIMEOUT_SECONDS=180
```

의미:

```text
Gemma API 1회 호출을 최대 180초까지 기다린다.
180초는 공식 고정값이 아니라 운영 기본값이다.
.env에서 조정 가능해야 한다.
```

설정 이유:

```text
레포 분석 prompt는 일반 짧은 채팅보다 길 수 있다.
Gemma 4 31B 모델 응답은 짧은 모델보다 느릴 수 있다.
120초는 긴 repo evidence + JSON 생성에는 빡빡할 수 있다.
그러나 무한 대기는 안 되므로 180초를 기본값으로 둔다.
```

---

## 9. CLI 요구사항

### 9.1 단일 레포 분석 명령

```bash
python -m repo_idea_miner run \
  --repo https://github.com/OWNER/REPO \
  --mode live \
  --input-mode direct
```

옵션:

```text
--repo
- 필수
- GitHub repository URL

--mode
- mock
- live
- 기본값: mock

--input-mode
- direct
- search
- 기본값: direct

--output-dir
- 기본값: runs/

--max-issues
- 기본값: 10

--max-prs
- 기본값: 10

--tree-depth
- 기본값: 2

--no-llm
- mock alias
```

---

### 9.2 검색 명령

```bash
python -m repo_idea_miner search \
  --query "ai agent workflow automation" \
  --limit 30 \
  --top 10 \
  --mode live
```

옵션:

```text
--query
- 필수
- GitHub 검색어

--limit
- 검색 후보 수
- 기본값: 30

--top
- top_ideas.md에 포함할 최종 카드 수
- 기본값: 10

--mode
- mock
- live

--targeted
- 사용자의 관심사와 가까운 레포 우선

--explore
- 넓은 탐색 모드
```

---

### 9.3 검증 명령

```bash
python -m repo_idea_miner validate runs/<timestamp>/
```

기능:

```text
산출물 구조 검증
JSON schema 검증
secret 노출 여부 검증
idea_card.md 필수 섹션 검증
run_report.md 필수 섹션 검증
```

---

## 10. 전체 처리 흐름

### 10.1 단일 레포 분석 흐름

```text
1. repo URL 파싱
2. input-mode 확인
3. preflight 실행
4. GitHub metadata 수집
5. README 수집
6. Issues 수집
7. Issue body sampler 실행
8. Issue signal tag 생성
9. PR 수집 및 bot/dependency PR 필터링
10. File tree depth 2 수집
11. Docs / examples / demo path 수집
12. Dependency / Runtime Evidence 수집
13. evidence_packet.md 생성
14. Bouncer 실행
15. FAST DROP이면 fast_drop_card 또는 idea_card.md 생성 후 종료
16. README Scout 실행
17. Pain Scout 실행
18. Structure / Risk Scout 실행
19. Critic / Judge 실행
20. JSON validation
21. JSON syntax repair 1회
22. Score Ceiling Validator 실행
23. Length truncation 실행
24. judge_output_final.json 생성
25. idea_card.md 렌더링
26. run_report.md 생성
27. secret redaction 검증
```

---

### 10.2 검색어 분석 흐름

```text
1. GitHub search query 실행
2. 후보 repo 최대 N개 수집
3. search-mode preflight 적용
4. FAST_DROP_PREFLIGHT 후보 제외 또는 fast_drop 기록
5. 후보별 단일 레포 분석 실행
6. 각 repo별 idea_card.md 생성
7. 후보 전체 결과를 모아 top_ideas.md 생성
8. search_report.md 생성
```

---

## 11. 출력 구조

### 11.1 단일 레포 실행 결과

```text
runs/<timestamp>/
- idea_card.md
- run_report.md

runs/<timestamp>/debug/
- evidence_packet.md
- llm_calls.jsonl
- worker_outputs/
  - bouncer.json
  - readme_scout.json
  - pain_scout.json
  - structure_risk_scout.json
  - critic_judge_raw.json
  - critic_judge_final.json
- prompts/
  - bouncer.md
  - readme_scout.md
  - pain_scout.md
  - structure_risk_scout.md
  - critic_judge.md
- raw/
  - metadata.json
  - readme.md
  - issues.json
  - prs.json
  - file_tree.json
  - dependency_evidence.json
```

---

### 11.2 검색어 실행 결과

```text
runs/<timestamp>/
- top_ideas.md
- search_report.md
- candidates.json

runs/<timestamp>/cards/
- OWNER_REPO_idea_card.md
- ...

runs/<timestamp>/repos/
- OWNER_REPO/
  - idea_card.md
  - run_report.md
  - debug/
```

---

## 12. GitHub Collector 요구사항

### 12.1 Repo Metadata

다음 항목을 수집한다.

```text
owner
repo name
description
stars
forks
watchers
topics
primary language
languages
updated_at
created_at
pushed_at
archived 여부
disabled 여부
fork 여부
open issues count
license
homepage
default branch
repo size
```

---

### 12.2 README

README를 수집한다.

README가 없으면 실패 처리하지 않고 `MISSING`으로 기록한다.

README에서 다음 신호를 추출한다.

```text
설치 방법
사용 예시
주요 기능
demo / screenshot / docs link
API 사용 여부
Docker 사용 여부
외부 서비스 사용 여부
```

---

### 12.3 Issues

다음 issue bucket을 수집한다.

```text
최근 업데이트된 open issue 최대 5개
comments 많은 open issue 최대 3개
최근 closed issue 최대 3개
```

각 issue에서 수집:

```text
title
number
url
state
labels
comments_count
unique_commenters_count
maintainer_comment_ratio
bot_comment_count
updated_at
created_at
closed_at
body_sample
signal_tags
bike_shedding_possible
```

PR이 issue 목록에 섞이면 제외한다.

```text
pull_request key가 있으면 Pain 분석 대상에서 제외
```

---

### 12.4 PRs

최근 PR 최대 10개를 수집한다.

단, bot/dependency PR은 필터링한다.

제외 대상:

```text
dependabot[bot]
renovate[bot]
github-actions[bot]
pre-commit-ci[bot]
dependabot-preview[bot]
```

제외 제목 패턴:

```text
Bump
Update dependency
chore(deps)
chore(deps-dev)
deps:
build(deps)
build(deps-dev)
```

사람이 작성한 dependency migration PR은 완전히 버리지 않고 보조 신호로 남길 수 있다.

---

### 12.5 File Tree

depth 2 수준의 file tree를 수집한다.

필수 확인 경로:

```text
root files
src/
app/
lib/
docs/
examples/
demo/
tests/
scripts/
config files
```

---

### 12.6 Dependency / Runtime Evidence

다음 파일을 확인한다.

```text
package.json
pyproject.toml
requirements.txt
Cargo.toml
go.mod
Dockerfile
docker-compose.yml
Makefile
```

수집 원칙:

```text
Collector는 risk 판단을 하지 않는다.
Collector는 evidence origin만 기록한다.
Judge가 risk를 판단한다.
```

origin 값:

```text
README_ONLY
DOCS_ONLY
DEV_TEST
OPTIONAL
RUNTIME
SCRIPT_ENTRYPOINT
DOCKER_LOCAL
CONFIG_ONLY
UNKNOWN
```

---

## 13. Preflight 요구사항

### 13.1 Preflight 결과값

```text
PROCEED
LOW_SIGNAL_PROCEED
FAST_DROP_PREFLIGHT
ERROR_STOP
```

---

### 13.2 direct 모드 규칙

direct 모드에서는 다음 이유만으로 hard drop하면 안 된다.

```text
star 수 낮음
fork 수 낮음
issue 적음
README 짧음
최근 활동 약함
```

이 경우 `LOW_SIGNAL_PROCEED`로 계속 진행한다.

---

### 13.3 search 모드 규칙

search 모드에서는 다음 조건일 때 `FAST_DROP_PREFLIGHT`를 허용한다.

```text
archived + 장기 미활동
README 없음 + issue 없음
사실상 빈 레포
template / mirror / fork-only 레포
metadata 외 분석 가능한 evidence 없음
```

---

### 13.4 ERROR_STOP 조건

```text
repo not found
private repo 접근 불가
GitHub API 인증 실패
metadata도 수집 불가한 rate limit
```

---

## 14. Issue Body Sampler 요구사항

### 14.1 목적

Issue 본문 앞부분만 사용하지 않는다.

GitHub issue의 앞부분은 템플릿, 환경 정보, 인사말일 수 있으므로 다음을 조합해 `body_sample`을 만든다.

```text
앞부분
끝부분
키워드 주변 문맥
```

---

### 14.2 출력 제한

각 issue의 `body_sample`은 최대 1,500자다.

구성 기준:

```text
앞부분 최대 500자
끝부분 최대 500자
키워드 주변 문맥 최대 500자
중복 제거
긴 로그는 일부만 보존
```

---

### 14.3 결함/버그 키워드

```text
error
bug
fail
failed
failure
expected
actual
reproduce
steps
regression
workaround
cannot
can't
crash
slow
performance
오류
버그
실패
재현
기대
실제
회귀
느림
성능
안됨
깨짐
```

---

### 14.4 기능 요청 키워드

```text
feature
request
feature request
would be great
would be nice
support
support for
add support
integrate
integration
plugin
extension
API
custom
customize
option
config
setting
template
기능 요청
지원
추가
연동
통합
플러그인
확장
API
커스텀
사용자 설정
옵션
설정
템플릿
```

---

### 14.5 워크플로우/자동화 키워드

```text
automate
automation
workflow
batch
bulk
export
import
sync
schedule
report
dashboard
pipeline
repeat
manual
copy paste
no-code
low-code
자동화
워크플로우
일괄 처리
대량 처리
내보내기
가져오기
동기화
예약
리포트
보고서
대시보드
파이프라인
반복
수동
복붙
노코드
로우코드
```

---

### 14.6 문서/혼란 키워드

```text
confusing
confused
docs
documentation
example
tutorial
how to
setup
install
dependency
version
헷갈림
문서
예제
튜토리얼
사용법
설치
의존성
버전
설정
```

---

### 14.7 템플릿성 섹션 압축

다음 섹션은 너무 길면 압축한다.

```text
Environment
System Info
OS
Python version
Node version
Package version
Logs
Checklist
```

환경 정보 자체가 신호일 수 있으므로 완전히 삭제하지 않는다.
다만 `body_sample` 전체를 환경 정보가 덮지 않게 한다.

---

## 15. Issue Signal Tag 요구사항

각 issue에 다음 tag를 붙인다.

```text
defect_signal
feature_signal
workflow_signal
confusion_signal
noise_signal
uncertain_signal
```

한 issue에 여러 tag가 붙을 수 있다.

의미:

```text
defect_signal:
- 오류, 버그, 실패, 성능 저하, 회귀

feature_signal:
- 기능 요청, 지원 요청, 확장 요청

workflow_signal:
- 자동화, 반복 작업, 배치, 연동, export/import, 수동 작업 불편

confusion_signal:
- 문서, 설정, 사용법, 예제 부족

noise_signal:
- 설치/환경/버전 충돌, 중복, stale, bot성, 논쟁성

uncertain_signal:
- 신호가 불명확함
```

---

## 16. Comments / Bike-shedding 요구사항

comments count가 높은 issue는 반드시 다음을 함께 기록한다.

```text
comments_count
unique_commenters_count
maintainer_comment_ratio
bot_comment_count
bike_shedding_possible
```

판정 원칙:

```text
댓글 수가 많아도 unique commenters가 적으면 pain signal로 과대평가하지 않는다.
댓글 수가 많고 unique commenters가 많으면 반복 pain 가능성을 높게 본다.
maintainer_comment_ratio가 높고 user 참여가 낮으면 내부 설계 논쟁 가능성을 표시한다.
```

bike-shedding 가능성 신호:

```text
comments_count는 높지만 unique_commenters_count가 낮음
동일 참여자들이 긴 논쟁 반복
maintainer_comment_ratio가 높음
명확한 user pain보다 철학/방향성 논쟁이 중심
labels에 discussion, design, proposal 등이 있음
결론 없이 오래 지속됨
```

---

## 17. Dependency / Runtime Evidence 요구사항

위험 키워드 예시:

```text
docker
kubernetes
redis
postgres
mysql
mongodb
playwright
selenium
torch
tensorflow
cuda
openai
anthropic
stripe
auth
oauth
s3
aws
gcp
azure
queue
worker
browser
native
binding
```

판정 원칙:

```text
키워드 발견만으로 위험을 확정하지 않는다.
어디에서 발견되었는지 기록한다.
runtime 필수로 보이는지는 Judge가 판단한다.
```

Docker 판정:

```text
docker-compose.yml만 존재하고 runtime entrypoint와 연결되지 않음
→ origin = DOCKER_LOCAL
→ high risk 금지

Dockerfile이 존재하지만 README에서 필수 실행 경로로 설명되지 않음
→ origin = CONFIG_ONLY 또는 DOCKER_LOCAL
→ high risk 금지

README의 설치/실행 방법이 Docker 중심이고 Docker 없이는 실행 경로가 불명확함
→ origin = SCRIPT_ENTRYPOINT 또는 RUNTIME
→ risk 상승 가능

Kubernetes, cloud deploy, docker swarm, compose multi-service DB/queue가 핵심 실행 경로임
→ infrastructure risk 상승 가능
```

---

## 18. Evidence Packet 요구사항

`debug/evidence_packet.md`를 반드시 생성한다.

형식:

```md
# Evidence Packet

## Repo Metadata
status: OK / MISSING / SKIPPED / ERROR

## Input Mode
direct / search

## Preflight
status:
reason:

## README Signal
status:

## User Pain Signal
status:

### Recent Open Issues

### High Comment Open Issues

### Recent Closed Issues

For each issue:
- title:
- labels:
- comments_count:
- unique_commenters_count:
- maintainer_comment_ratio:
- bot_comment_count:
- bike_shedding_possible:
- updated_at:
- signal_tags:
- body_sample:

## PR Signal
status:

### Recent Human PRs

### Excluded Bot / Dependency PRs

## Structure Signal
status:

### File Tree Depth 2

### Docs / Examples / Demo Paths

## Dependency / Runtime Evidence
status:

## Missing Data

## Collector Notes
```

---

## 19. Worker 요구사항

최종 제품은 다음 worker를 포함해야 한다.

```text
Bouncer
README Scout
Pain Scout
Structure / Risk Scout
Critic / Judge
```

---

### 19.1 Bouncer

역할:

```text
evidence packet을 보고 full worker 실행 여부 판단
명백한 FAST DROP이면 full worker 생략
```

출력:

```json
{
  "bouncer_decision": "PROCEED",
  "fast_drop": false,
  "reason": "..."
}
```

허용값:

```text
PROCEED
FAST_DROP
UNCERTAIN_PROCEED
```

원칙:

```text
좋은 레포를 너무 빨리 버리면 안 된다.
불확실하면 PROCEED 또는 UNCERTAIN_PROCEED.
```

---

### 19.2 README Scout

역할:

```text
README가 주장하는 핵심 가치 추출
README 기준 매력 추출
README 과장 가능성 표시
README만으로는 확정할 수 없는 부분 표시
```

---

### 19.3 Pain Scout

역할:

```text
issue에서 실제 사용자 고통 추출
feature request 추출
workflow/automation pain 추출
noise issue 분리
bike-shedding issue 과대평가 방지
```

---

### 19.4 Structure / Risk Scout

역할:

```text
file tree와 dependency evidence 기반으로 구현 무게 추정
runtime risk 판단
dev/test dependency와 runtime dependency 구분
Docker 오탐 방지
Pattern PoC 가능성 추정
```

---

### 19.5 Critic / Judge

역할:

```text
README / Pain / Structure 결과를 종합
KEEP / MAYBE / DROP 판정
점수 0~10 부여
적용 가능 영역 판단
1일 MVP 가능성 판단
1일 Pattern PoC 가능성 판단
만들면 망하는 이유 제시
왜 버려야 하는지 제시
```

---

## 20. Worker JSON 출력 원칙

모든 worker output은 Markdown이 아니라 JSON이어야 한다.

LLM 출력 흐름:

```text
LLM JSON
→ JSON parse
→ syntax repair 1회
→ Pydantic validation
→ validator
→ Markdown renderer
```

Markdown은 최종 사용자용 산출물에만 사용한다.

프롬프트에는 반드시 다음을 포함한다.

```text
Return only valid JSON.
Do not wrap JSON in markdown fences.
Do not include explanations outside JSON.
Use the exact schema.
If evidence is insufficient, use "불확실" or "unknown" rather than inventing facts.
```

---

## 21. Critic / Judge JSON Schema

최종 Judge output schema는 다음을 따른다.

```json
{
  "verdict": "DROP",
  "fast_drop": true,
  "score": 2,
  "one_line_conclusion": "이 레포에서 가져올 핵심 패턴은 ... 이지만 현재는 DROP에 가깝다.",
  "why_people_cared": "...",
  "user_pain": ["..."],
  "feature_requests": ["..."],
  "workflow_pain": ["..."],
  "core_pattern": "...",
  "what_to_ignore": ["..."],
  "dependency_runtime_risk": {
    "level": "medium",
    "reason": "..."
  },
  "application": {
    "area": "아이디어 채굴",
    "related_project": "Repo Idea Miner",
    "reason": "..."
  },
  "one_day_mvp": {
    "status": "가능",
    "feature": "...",
    "input": "...",
    "output": "...",
    "excluded_scope": ["..."],
    "reason": "..."
  },
  "pattern_poc": {
    "status": "가능",
    "idea": "...",
    "input": "...",
    "output": "...",
    "reason": "..."
  },
  "issue_signal_stats": {
    "sampled_issue_count": 0,
    "classified_issue_count": 0,
    "defect_count": 0,
    "feature_request_count": 0,
    "workflow_pain_count": 0,
    "confusion_count": 0,
    "install_env_version_count": 0,
    "noise_count": 0,
    "product_pain_count": 0,
    "confidence": "medium"
  },
  "why_it_fails": ["..."],
  "why_drop_or_keep": ["..."],
  "next_action": "유사 레포 3개와 비교",
  "ceiling_rules_applied": []
}
```

---

## 22. JSON 허용 값

### 22.1 verdict

```text
KEEP
MAYBE
DROP
```

### 22.2 dependency_runtime_risk.level

```text
low
medium
high
unknown
not_collected
```

### 22.3 application.area

```text
코딩 하네스/검증
아이디어 채굴
업무 자동화/OCR
게임 시뮬레이션/뷰어
문서/카드 UI
적용 부적합
```

### 22.4 one_day_mvp.status

```text
가능
축소 불가
불확실
```

### 22.5 pattern_poc.status

```text
가능
불가능
불확실
```

### 22.6 issue_signal_stats.confidence

```text
low
medium
high
```

---

## 23. Pydantic Validation 요구사항

Pydantic validation은 필수다.

실패 처리:

```text
JSON parse 불가
필수 필드 없음
enum 값 이상함
score가 0~10 범위 밖
list가 와야 하는데 string이 옴
object가 와야 하는데 string이 옴
why_it_fails가 비어 있음
next_action이 비어 있음
```

실패 시:

```text
VALIDATION_FAIL 기록
idea_card.md 생성하지 않음
exit code 실패
```

---

## 24. JSON Repair 요구사항

Live Judge가 JSON을 잘못 출력할 수 있다.

허용 repair:

```text
깨진 따옴표 수정
trailing comma 제거
markdown fence 제거
JSON object만 추출
앞뒤 설명 문장 제거
```

금지 repair:

```text
새 판단 추가
score 변경
verdict 변경
누락 필드 창작
why_drop_or_keep 새로 작성
one_day_mvp 새로 판단
pattern_poc 새로 판단
application area 새로 판단
```

누락 필드가 있으면 repair하지 말고 validation fail 처리한다.

---

## 25. Length Truncation 요구사항

문자열 길이 초과는 validation fail로 처리하지 않는다.

정책:

```text
구조 오류 = 실패
길이 초과 = 자동 축약
```

제한:

```text
one_line_conclusion: 최대 160자
why_people_cared: 최대 400자
user_pain: 최대 5개, 각 180자
feature_requests: 최대 5개, 각 180자
workflow_pain: 최대 5개, 각 180자
core_pattern: 최대 300자
what_to_ignore: 최대 5개, 각 180자
dependency_runtime_risk.reason: 최대 240자
application.reason: 최대 240자
one_day_mvp.reason: 최대 240자
pattern_poc.reason: 최대 240자
why_it_fails: 최대 5개, 각 180자
why_drop_or_keep: 최대 5개, 각 180자
next_action: 최대 120자
ceiling_rules_applied: 최대 8개
```

길이 초과 시:

```text
문자열은 truncate 후 ... 추가
list는 앞 N개만 유지
run_report.md에 LENGTH_TRUNCATED 기록
```

---

## 26. Score Ceiling Validator 요구사항

Judge가 KEEP 또는 높은 점수를 주더라도 Validator가 최종 안전장치 역할을 한다.

### 26.1 not_collected / unknown 구분

```text
not_collected = 아직 수집하지 않음
unknown = 수집했지만 판단 불가
```

규칙:

```text
not_collected에는 dependency ceiling 적용 금지
unknown에는 KEEP 금지 또는 최대 MAYBE 적용 가능
```

---

### 26.2 적용 부적합 상한

```text
application.area == 적용 부적합
→ score 최대 5
→ KEEP 금지
```

---

### 26.3 1일 MVP 축소 불가 상한

```text
one_day_mvp.status == 축소 불가
and pattern_poc.status != 가능
→ score 최대 4
→ KEEP 금지
```

---

### 26.4 Pattern PoC 가능 예외

```text
one_day_mvp.status == 축소 불가
and pattern_poc.status == 가능
→ KEEP 금지
→ MAYBE 가능
→ score 최대 6
```

---

### 26.5 Issue pain 약함 상한

```text
product_pain_count == 0
and feature_request_count == 0
and workflow_pain_count == 0
and classified_issue_count >= 3
and confidence >= medium
→ score 최대 5
→ KEEP 금지
```

---

### 26.6 설치/환경/버전 충돌 편중 상한

```text
classified_issue_count >= 5
and install_env_version_count / classified_issue_count >= 0.7
and confidence >= medium
→ score 최대 4
```

---

### 26.7 Runtime risk 높음 상한

```text
dependency_runtime_risk.level == high
→ score 최대 5
→ KEEP 금지
```

---

### 26.8 Dependency unknown 상한

```text
dependency_runtime_risk.level == unknown
→ KEEP 금지
→ 최대 MAYBE
```

---

### 26.9 Validator correction 기록

Validator가 score 또는 verdict를 수정하면 반드시 기록한다.

```text
judge_raw_verdict
judge_raw_score
validator_final_verdict
validator_final_score
correction_applied
correction_reason
```

---

## 27. Verdict 규칙

```text
KEEP:
- score 7~10
- 적용 가능
- 1일 MVP 가능
- 치명적 ceiling rule 없음

MAYBE:
- score 4~6
- 신호는 있으나 비교 필요
- 적용 가능성이 있지만 확실하지 않음
- 제품 MVP는 어렵지만 Pattern PoC 가능

DROP:
- score 0~3
- 또는 ceiling rule으로 KEEP 불가
- 또는 1일 MVP도 Pattern PoC도 불가능
```

주의:

```text
Pattern PoC 가능은 KEEP 근거가 아니라 MAYBE 보존 근거다.
```

---

## 28. idea_card.md 요구사항

검증된 JSON을 Markdown으로 렌더링한다.

형식:

```md
# Repo Idea Card

## 판정
KEEP / MAYBE / DROP

## FAST DROP에 가까운가
YES / NO

## 점수
0~10

## 한 줄 결론

## 왜 사람들이 관심 가졌나

## 실제 사용자 고통

## 기능 요청 신호

## 워크플로우/자동화 신호

## 가져올 패턴

## 버릴 것

## Dependency / Runtime Risk

## 내 현재 병목에 적용

## 1일 MVP

## 1일 Pattern PoC

## 만들면 망하는 이유

## 왜 이 판정인가

## 다음 행동
```

카드는 5분 안에 읽을 수 있어야 한다.

---

## 29. top_ideas.md 요구사항

검색어 기반 분석 결과로 `top_ideas.md`를 생성한다.

형식:

```md
# Top Ideas

## 검색어

## 전체 요약
- 분석 후보 수:
- FAST DROP 수:
- KEEP 수:
- MAYBE 수:
- DROP 수:

## Top KEEP

## Top MAYBE

## 빠르게 버린 후보

## 비교해볼 만한 패턴

## 다음 행동
```

KEEP이 없으면 “KEEP 없음”이라고 명확히 표시한다.

---

## 30. run_report.md 요구사항

`run_report.md`에는 다음을 기록한다.

```md
# Run Report

## Input
- repo:
- mode:
- input_mode:
- timestamp:

## Preflight
- status:
- reason:

## Collector Status
- metadata:
- readme:
- issues:
- prs:
- file_tree:
- dependency:

## Issue Sampler
- sampled_issue_count:
- sample_max_chars:
- template_sections_compressed:
- defect_count:
- feature_request_count:
- workflow_pain_count:
- confusion_count:
- noise_count:
- uncertain_count:

## Comments Signal
- high_comment_issue_count:
- unique_commenters_available:
- bike_shedding_possible_count:

## LLM Key Pool
- provider: google_genai_gemma
- model: gemma-4-31b-it
- configured_key_count:
- loaded_key_count:
- strategy: round_robin
- used_key_indexes:
- disabled_key_indexes:
- temp_failed_key_indexes:
- retry_count:
- failover_count:
- retry_backoff_strategy:
- retry_initial_delay_seconds:
- retry_max_delay_seconds:
- request_timeout_seconds:
- respect_retry_after:

## Missing Data

## Errors

## JSON Validation
PASS / FAIL

## Content Gate
PASS / FAIL

## Length Truncation
- length_truncated:
- truncated_field_count:
- truncated_fields:

## Judge Raw
- raw_verdict:
- raw_score:

## Validator Final
- final_verdict:
- final_score:

## Ceiling Rules
- applied:
- corrected:
- correction_reason:
- before_score:
- after_score:
- before_verdict:
- after_verdict:

## Secret Redaction
PASS / FAIL

## Token/API Key Exposure
YES / NO

## Output Files
- idea_card.md
- debug/evidence_packet.md
- debug/worker_outputs/
- debug/llm_calls.jsonl
```

---

## 31. Search Report 요구사항

검색어 기반 분석에서는 `search_report.md`를 생성한다.

필수 항목:

```md
# Search Report

## Query

## Candidate Collection
- requested_limit:
- collected_count:
- after_preflight_count:
- analyzed_count:

## Preflight Summary
- proceed:
- low_signal_proceed:
- fast_drop_preflight:
- error_stop:

## Verdict Summary
- keep:
- maybe:
- drop:

## LLM Key Pool Summary
- configured_key_count:
- loaded_key_count:
- used_key_indexes:
- disabled_key_indexes:
- retry_count:
- failover_count:

## Validator Correction Summary
- correction_count:
- correction_rate:

## Errors

## Output Files
```

판정 기준:

```text
validator correction rate > 40% → 경고
validator correction rate > 60% → search_report에 FAIL 표시
```

---

## 32. llm_calls.jsonl 요구사항

각 LLM 호출마다 다음 정보를 기록한다.

```json
{
  "worker": "pain_scout",
  "model": "gemma-4-31b-it",
  "key_index": 2,
  "attempt": 1,
  "success": true,
  "latency_ms": 18420,
  "error_type": null,
  "retry_after_seconds": null,
  "backoff_delay_seconds": 0,
  "input_chars": 12000,
  "output_chars": 3000,
  "json_parse_success": true,
  "validation_success": true,
  "repair_used": false
}
```

실패 후 재시도 예:

```json
{
  "worker": "pain_scout",
  "model": "gemma-4-31b-it",
  "key_index": 2,
  "attempt": 1,
  "success": false,
  "latency_ms": 3012,
  "error_type": "RESOURCE_EXHAUSTED",
  "retry_after_seconds": null,
  "backoff_delay_seconds": 2.4,
  "json_parse_success": false,
  "validation_success": false,
  "repair_used": false
}
```

금지:

```text
API key 값 저장 금지
GitHub token 저장 금지
prompt 안에 secret이 포함된 경우 prompt 전체 저장 금지
```

---

## 33. Secret Redaction 요구사항

다음 secret은 산출물에 노출되면 안 된다.

```text
GITHUB_TOKEN 값
GOOGLE_API_KEY_1 ~ GOOGLE_API_KEY_11 값
GEMINI_API_KEY 값
GOOGLE_API_KEY 값
ghp_
github_pat_
AIza
sk-
.env 내용
```

규칙:

```text
환경변수 값은 report/log/artifact에 쓰지 않는다.
token 존재 여부만 YES/NO로 기록한다.
산출물 저장 전 secret-like string redaction을 적용한다.
redaction 후에도 원문 secret이 남아 있으면 실패 처리한다.
exception traceback에도 secret이 없어야 한다.
```

---

## 34. 필수 테스트

다음 테스트를 포함해야 한다.

### 34.1 URL parser test

```text
https://github.com/OWNER/REPO 파싱 성공
잘못된 URL 실패
```

### 34.2 Preflight test

```text
direct 모드에서 star 낮음만으로 FAST_DROP 금지
search 모드에서 빈 archived repo는 FAST_DROP 가능
repo not found는 ERROR_STOP
```

### 34.3 GitHub collector test

```text
metadata 수집 성공
README 없음은 MISSING 처리
PR이 issue 목록에 섞이면 제외
```

### 34.4 Issue sampler test

```text
앞부분만 환경 정보인 issue에서도 끝부분/키워드 주변 문맥 포함
feature request 키워드 감지
workflow/automation 키워드 감지
긴 로그는 압축
body_sample 1500자 이하
```

### 34.5 Issue signal tag test

```text
bug issue → defect_signal
feature request issue → feature_signal
automation/export issue → workflow_signal
docs/setup issue → confusion_signal
install/version issue → noise_signal
```

### 34.6 Comments / bike-shedding test

```text
comments_count 높고 unique_commenters 낮음 → bike_shedding_possible 가능
unique_commenters 많으면 repeated pain 가능성 기록
maintainer_comment_ratio 높으면 내부 논쟁 가능성 기록
```

### 34.7 PR filter test

```text
dependabot PR 제외
renovate PR 제외
chore(deps) PR 제외
human PR 유지
```

### 34.8 Dependency evidence test

```text
package.json dependencies/devDependencies 구분
pyproject dependencies optional/dev group 구분
requirements.txt 수집
Dockerfile만으로 high risk 금지
docker-compose만으로 high risk 금지
```

### 34.9 JSON validation test

```text
정상 mock JSON 통과
verdict 이상값 실패
score 11 실패
필수 필드 누락 실패
list/object 타입 오류 실패
```

### 34.10 JSON repair test

```text
markdown fence 제거 가능
trailing comma 제거 가능
누락 필드 창작 금지
verdict/score 변경 금지
```

### 34.11 Length truncation test

```text
긴 문자열은 실패하지 않고 truncate
긴 list는 앞 N개만 유지
run_report에 LENGTH_TRUNCATED 기록
```

### 34.12 Score ceiling test

```text
적용 부적합 + KEEP → KEEP 금지, score 최대 5
MVP 축소 불가 + Pattern PoC 불가능 → score 최대 4
MVP 축소 불가 + Pattern PoC 가능 → MAYBE 가능, score 최대 6
dependency not_collected → dependency ceiling 미적용
dependency unknown → KEEP 금지
runtime high → KEEP 금지
```

### 34.13 Renderer test

```text
idea_card.md 필수 섹션 포함
KEEP/MAYBE/DROP 표시
Pattern PoC 섹션 포함
top_ideas.md 생성
```

### 34.14 Secret redaction test

```text
GITHUB_TOKEN fake value redaction
GOOGLE_API_KEY_1 fake value redaction
GOOGLE_API_KEY_11 fake value redaction
ghp_ 토큰 redaction
github_pat_ redaction
AIza redaction
sk- redaction
환경변수 값이 산출물에 남으면 실패
```

### 34.15 .env key loading test

```text
GOOGLE_API_KEY_1 ~ GOOGLE_API_KEY_11 로딩
일부 key만 있어도 loaded_key_count 정확히 기록
key 값은 로그에 남지 않음
```

### 34.16 Key pool round robin test

```text
5개 worker 호출 시 key_index가 순서대로 회전
같은 key에만 호출이 몰리지 않음
```

### 34.17 Key failover test

```text
429 발생 시 다음 key로 재시도
503 발생 시 다음 key로 재시도
timeout 발생 시 다음 key로 재시도
```

### 34.18 Invalid key handling test

```text
401 발생 시 해당 key DISABLED
403 발생 시 해당 key DISABLED
invalid API key 발생 시 해당 key DISABLED
```

### 34.19 Model config test

```text
기본 모델이 gemma-4-31b-it인지 확인
RIM_GEMMA_MODEL로 override 가능한지 확인
model not found 발생 시 전체 설정 오류로 실패 처리
```

### 34.20 Retry-After test

```text
429 응답에 Retry-After가 있으면 해당 값을 우선 사용
Retry-After가 없으면 exponential backoff + jitter 사용
```

### 34.21 Exponential backoff test

```text
attempt 0,1,2에서 delay가 증가한다.
delay는 RIM_RETRY_MAX_DELAY_SECONDS를 넘지 않는다.
jitter가 적용된다.
```

### 34.22 Same retry cycle key reuse 방지 test

```text
key_index 1이 429를 내면 같은 worker 호출 retry cycle에서 key_index 1을 즉시 재사용하지 않는다.
다음 available key를 사용한다.
```

### 34.23 Request timeout 설정 test

```text
RIM_REQUEST_TIMEOUT_SECONDS 값이 provider 호출 timeout에 적용된다.
기본값은 180초다.
값은 .env로 override 가능하다.
```

---

## 35. 검수 기준

최종 납품 검수는 다음 기준으로 진행한다.

### 35.1 단일 레포 mock 검수

```bash
python -m repo_idea_miner run \
  --repo https://github.com/OWNER/REPO \
  --mode mock \
  --input-mode direct
```

성공 조건:

```text
idea_card.md 생성
run_report.md 생성
evidence_packet.md 생성
worker output JSON 생성
필수 섹션 존재
secret 노출 없음
```

---

### 35.2 단일 레포 live 검수

```bash
python -m repo_idea_miner run \
  --repo https://github.com/OWNER/REPO \
  --mode live \
  --input-mode direct
```

성공 조건:

```text
GITHUB_TOKEN 사용
GOOGLE_API_KEY_1~11 중 하나 이상 사용
model = gemma-4-31b-it
Bouncer / Scouts / Judge live JSON 생성
Pydantic validation 통과
idea_card.md 생성
run_report.md 생성
key index 기록
key 값 미노출
Judge raw와 Validator final 분리 기록
```

---

### 35.3 검색어 mock 검수

```bash
python -m repo_idea_miner search \
  --query "automation workflow python" \
  --limit 10 \
  --top 5 \
  --mode mock
```

성공 조건:

```text
candidates.json 생성
top_ideas.md 생성
search_report.md 생성
각 후보 카드 생성
```

---

### 35.4 검색어 live 검수

```bash
python -m repo_idea_miner search \
  --query "automation workflow python" \
  --limit 10 \
  --top 5 \
  --mode live
```

성공 조건:

```text
후보 repo 수집
search-mode preflight 적용
후보별 live analysis 실행
key pool round robin 사용
후보별 idea_card.md 생성
top_ideas.md 생성
search_report.md 생성
validator correction rate 기록
LLM output JSON schema 준수
key 값 미노출
```

---

### 35.5 테스트 검수

```bash
pytest
```

성공 조건:

```text
필수 테스트 전체 통과
key pool 테스트 통과
failover 테스트 통과
retry/backoff 테스트 통과
secret redaction 테스트 통과
Gemma model config 테스트 통과
```

---

## 36. 구현 금지 사항

최종 납품에서도 다음은 구현하지 않는다.

```text
웹 대시보드
브라우저 UI
유튜브 콘텐츠 자동 생성
블로그 콘텐츠 자동 생성
자동 프로젝트 생성
사용자 feedback 학습 시스템
장기 DB 구축
전체 코드 clone 후 정밀 코드리뷰
PR 생성 / GitHub write action
고정 1시간 key cooldown 정책
API key 또는 GitHub token 로그 출력
```

---

## 37. 최종 납품물

납품 시 다음을 제공해야 한다.

```text
1. 전체 소스코드
2. README.md
3. 설치 방법
4. 실행 예시
5. 환경변수 설정 예시
6. .env.example
7. 테스트 실행 방법
8. 테스트 코드
9. 샘플 실행 결과
10. 샘플 산출물:
   - idea_card.md
   - run_report.md
   - top_ideas.md
   - search_report.md
   - evidence_packet.md
   - worker output JSON
   - llm_calls.jsonl
11. Google GenAI Gemma provider 구현
12. key pool 구현 코드
13. key rotation / retry / failover 구현
14. secret redaction 테스트
15. 구현 범위 설명서
16. 미구현/제외 범위 명시
```

---

## 38. 품질 기준

최종 제품은 다음 기준을 만족해야 한다.

```text
단일 레포 분석이 안정적으로 동작한다.
검색어 기반 후보 분석이 동작한다.
README / Issue / PR / File Tree / Dependency evidence가 분리된다.
Issue 앞부분만 보지 않는다.
버그뿐 아니라 기능 요청과 워크플로우 불편도 본다.
comments count 착시를 줄인다.
bot/dependency PR을 제거한다.
Docker / dependency keyword만으로 risk를 과장하지 않는다.
LLM output은 JSON으로 받고 Markdown으로 직접 파싱하지 않는다.
Pydantic validation을 통과한다.
길이 초과는 실패가 아니라 안전하게 축약한다.
Score Ceiling Validator가 KEEP 남발을 막는다.
Judge raw 결과와 Validator final 결과를 분리 기록한다.
11개 Google AI Studio key를 pool로 관리한다.
429/503/timeout은 retry/backoff/failover로 처리한다.
401/403/invalid key는 해당 key를 DISABLED 처리한다.
Secret이 산출물에 노출되지 않는다.
테스트가 포함되어 있고 pytest로 검증 가능하다.
```

---

## 39. 최종 원칙

```text
Collector는 단순하게.
증거는 분리해서 저장한다.
Issue는 앞부분만 보지 않는다.
버그뿐 아니라 기능 요청과 워크플로우 불편도 본다.
댓글 수만 믿지 않는다.
Dependency keyword만으로 risk를 확정하지 않는다.
LLM 출력은 Markdown이 아니라 JSON으로 받는다.
Pydantic으로 구조를 검증한다.
길이 초과는 실패가 아니라 안전하게 축약한다.
Judge를 믿되 Validator로 막는다.
Validator가 자주 뒤집으면 Judge 품질 문제로 본다.
not_collected와 unknown을 구분한다.
직접 입력 레포는 star 수만으로 버리지 않는다.
검색 후보는 더 강하게 걸러도 된다.
Google AI Studio key 11개는 독립 key pool로 관리한다.
고정 1시간 cooldown은 사용하지 않는다.
일시 오류는 Retry-After 또는 exponential backoff + jitter로 처리한다.
API key와 GitHub token은 어떤 산출물에도 노출하지 않는다.
최종 산출물은 보고서가 아니라 5분 판단용 카드다.
```
