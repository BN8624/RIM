# Repo Idea Miner

GitHub 레포지토리 URL 또는 검색어를 입력받아 README / Issues / PR / 파일 구조 / dependency evidence를 수집·분석하고, 5분 안에 **KEEP / MAYBE / DROP** 판단을 내릴 수 있는 아이디어 카드와 비교 리포트를 생성하는 Python CLI 도구입니다.

이 도구는 레포를 긍정적으로 요약하는 도구가 아닙니다. README의 자기홍보와 실제 사용자 고통을 분리하고, 별로인 아이디어는 빠르게 버리게 하는 것이 목적입니다.

## 설치

Python 3.11 이상이 필요합니다.

```bash
git clone https://github.com/BN8624/RIM.git
cd RIM
pip install -e ".[dev]"
```

## 설정

`.env.example`을 `.env`로 복사하고 인증 정보를 넣습니다.

```bash
cp .env.example .env
```

- `GITHUB_TOKEN` — GitHub API 토큰
- `GOOGLE_API_KEY_1` ~ `GOOGLE_API_KEY_11` — Google AI Studio 프로젝트별 독립 API key (일부만 넣어도 동작)
- `RIM_GEMMA_MODEL` — 기본값 `gemma-4-31b-it`
- 나머지 retry/backoff/timeout 설정은 `.env.example` 참고

`.env`는 `.gitignore`에 의해 커밋되지 않습니다. key 값은 어떤 산출물/로그에도 기록되지 않으며 key index(1~11)만 기록됩니다.

## 사용법

### 단일 레포 분석

```bash
python -m repo_idea_miner run \
  --repo https://github.com/OWNER/REPO \
  --mode live \
  --input-mode direct
```

- `--mode mock|live` (기본 mock): mock은 외부 LLM 호출 없이 파이프라인 구조를 검증
- `--input-mode direct|search` (기본 direct): direct는 낮은 star 수만으로 hard drop하지 않음
- `--output-dir` (기본 `runs/`), `--max-issues` (10), `--max-prs` (10), `--tree-depth` (2), `--no-llm` (mock alias)

출력 (`runs/<timestamp>/`):

```text
idea_card.md          ← 5분 판단용 카드
run_report.md         ← 실행/검증 리포트
debug/evidence_packet.md
debug/worker_outputs/*.json
debug/judge_output_raw.json / judge_output_final.json
debug/llm_calls.jsonl
debug/prompts/ , debug/raw/
```

### 검색어 기반 후보 분석

```bash
python -m repo_idea_miner search \
  --query "automation workflow python" \
  --limit 30 \
  --top 10 \
  --mode live
```

옵션:

- `--targeted` — 관심사 키워드(automation, workflow, developer productivity, CLI, Python, OCR/document extraction, test automation, code review, simulation/game tool, repo analysis, idea mining)와 후보의 topics(가중치 2)·이름·설명·언어(가중치 1)를 매칭해 `targeted_score`를 계산하고, 점수 내림차순(동점 시 star 수)으로 후보를 재정렬합니다. 점수와 매칭 근거는 `candidates.json`의 `targeted_score`/`targeted_matched`에, 정렬 사용 여부는 `search_report.md`의 `targeted_sort`에 기록됩니다.
- `--explore` — GitHub 검색을 updated 정렬로 전환해 넓게 탐색합니다.

출력 (`runs/<timestamp>/`): `top_ideas.md`, `search_report.md`, `candidates.json`, `cards/OWNER_REPO_idea_card.md`, `repos/OWNER_REPO/…`

### 산출물 검증

```bash
python -m repo_idea_miner validate runs/<timestamp>/
```

구조·JSON 스키마·secret 노출·필수 섹션을 검증합니다. `--require-viewer`를 주면 `viewer.html`의 존재·모바일 viewport·필터 버튼·카드·verdict label·secret scan까지 함께 검사합니다.

### 모바일 HTML 뷰어 (iPhone + Tailscale)

RIM 실행 결과를 아이폰 Safari에서 읽기 좋게 보기 위한 정적 뷰어와 읽기 전용 로컬 서버입니다. 서버형 대시보드가 아니라, 지정한 run 디렉터리만 읽기 전용으로 제공합니다.

**1. viewer.html 생성**

```bash
python -m repo_idea_miner view runs/<timestamp>/
```

`runs/<timestamp>/viewer.html`을 만듭니다. 단일 레포 run과 검색 run 모두 지원하며, 모바일 우선 반응형·다크모드 대응·inline CSS/JS(외부 CDN/API 0회)로 동작합니다. 검색 결과는 KEEP/MAYBE/DROP/ERROR 카드, 필터(전체/KEEP/MAYBE/DROP/ERROR/DROP 숨기기), 정렬(점수순/판정순/원래 순서/targeted_score순), 상세 접기/펼치기를 제공합니다.

**2. 읽기 전용 서버 실행**

```bash
# 로컬 확인 (기본 host 127.0.0.1)
python -m repo_idea_miner serve runs/<timestamp>/ --host 127.0.0.1 --port 8787

# iPhone에서 Tailscale로 보려면 외부 바인딩
python -m repo_idea_miner serve runs/<timestamp>/ --host 0.0.0.0 --port 8787
```

이 서버는 읽기 전용입니다. 지정한 run 디렉터리 밖의 파일에 접근할 수 없고, path traversal·`.env`·`debug/raw`·`debug/prompts`·`llm_calls.jsonl`은 차단하며, GET/HEAD 이외 메서드는 501로 거부합니다. RIM 실행 버튼·key 입력 화면 같은 것은 존재하지 않습니다.

**3. iPhone Safari에서 열기 (Tailscale)**

1. PC/VM과 iPhone이 같은 Tailscale tailnet에 연결돼 있어야 합니다.
2. PC/VM에서 `search`(또는 `run`)로 분석을 실행합니다.
3. `python -m repo_idea_miner view runs/<timestamp>/`로 viewer.html을 생성합니다.
4. `python -m repo_idea_miner serve runs/<timestamp>/ --host 0.0.0.0 --port 8787`로 서버를 띄웁니다.
5. iPhone Safari에서 `http://<PC_or_VM_Tailscale_IP>:8787/`로 접속합니다. Tailscale MagicDNS를 쓰면 `http://<machine-name>:8787/`도 가능합니다.

`serve` 실행 시 로컬/Tailscale(100.x.x.x 추정)/LAN 후보 URL을 출력합니다. Tailscale IP 자동 탐지에 실패하면 `http://<your-tailscale-ip>:8787/` 안내 문구만 출력합니다 (`tailscale ip -4`로 직접 확인 가능).

전체 예시:

```bash
python -m repo_idea_miner search \
  --query "automation workflow python" \
  --limit 10 --top 5 --mode live --targeted
python -m repo_idea_miner view runs/<timestamp>/
python -m repo_idea_miner serve runs/<timestamp>/ --host 0.0.0.0 --port 8787
# → iPhone Safari: http://<TAILSCALE_IP>:8787/
```

## Challenge Mode

Challenge Mode는 GitHub 레포를 "제품 아이디어"가 아니라 **구현 도전 과제**로 변환하는 기능입니다. 기존 idea mode(run/search)의 KEEP/MAYBE/DROP 판정과는 목적이 다릅니다.

- idea mode — 이 레포에서 아이디어를 가져올 만한가?
- Challenge Mode — 이 레포의 핵심 상호작용과 어려운 구조를, Gemma/Codex/Claude가 쉬운 앱으로 축소하지 못하는 과제로 바꿀 수 있는가?

핵심 필드는 두 개입니다.

- **Difficulty Anchors** — 작게 줄여도 절대 삭제하면 안 되는 원본 레포의 핵심 난이도
- **Forbidden Simplifications** — 구현자가 단순 검색창/링크 모음/TODO 앱으로 도망가지 못하게 막는 금지 목록

판정 라벨은 `GOOD_CHALLENGE / TOO_EASY / TOO_BIG / NOT_MY_TASTE / STEAL_ONLY / UNCLEAR_TO_OWNER / DROP`입니다.

- `GOOD_CHALLENGE` — 작게 만들 수 있지만 핵심 난이도가 살아 있음 (최우선)
- `TOO_EASY` — 핵심 앵커가 약한 뻔한 과제 (낮은 우선순위)
- `UNCLEAR_TO_OWNER` — 바이브코더가 읽어도 뭘 만들라는 건지 감이 안 옴 (owner_clarity_score < 3이면 자동 적용)

### 단일 레포 Challenge 생성

```bash
python -m repo_idea_miner challenge --repo https://github.com/OWNER/REPO --mode live
```

출력 (`runs/<timestamp>/`):

```text
snapshot.json                 ← 수집 스냅샷
owner_brief.{json,md}         ← 바이브코더용 쉬운 설명 (뭔지/왜 좋은지/뭘 훔칠지)
screen_story.{json,md}        ← 실제 화면·조작 흐름 (첫 화면/누르는 것/30초 데모/실패 화면)
challenge_card.{json,md}      ← 과제 정의 (Anchors/Forbidden/PoC~3일 확장/Pass·Fail 기준)
implementation_prompt.md      ← 구현자(Claude/Codex/Gemma/외주)에게 그대로 복사해 넘기는 지시문
validation_report.json        ← 스키마/산출물/secret 검증 결과
viewer.html                   ← 모바일 정적 뷰어
```

**Owner Brief 읽는 법** — "이게 쉽게 말해 뭐냐"부터 "쉬운 버전과 뭐가 다르냐"까지 8개 질문에 답합니다. 30초 안에 감이 안 오면 그 과제는 UNCLEAR_TO_OWNER입니다. **Screen Story**는 추상 설명 없이 첫 화면과 누르는 순서, 실패한 화면(이렇게 되면 실패)을 설명합니다.

**Implementation Prompt 넘기는 법** — `implementation_prompt.md`(또는 Dashboard의 COPY IMPLEMENTATION PROMPT 버튼)를 그대로 복사해 구현자에게 붙여넣으면 됩니다. 구현 목표/산출 파일/기술 제약/Difficulty Anchors/Forbidden Simplifications/Pass·Failure Criteria가 모두 포함돼 있습니다.

repo 하나당 LLM 호출은 기본 1회(통합 ChallengePackage JSON)이고, markdown 4종은 로컬 renderer가 생성합니다.

### 검색 기반 Challenge 생성

```bash
python -m repo_idea_miner challenge-search \
  --query "stars:>10000 language:TypeScript" \
  --limit 50 --top 20 --mode live
```

- `--limit` — GitHub Search에서 가져올 최대 repo 후보 수
- `--top` — 중복 제거/필터(fork skip, archived 후순위)/정렬 후 실제 Challenge 생성 대상 수

출력: `challenge_index.json`, `search_report.json`, `viewer.html`, `repos/OWNER__REPO/…`. 목록은 GOOD_CHALLENGE → STEAL_ONLY → … → TOO_EASY → DROP 순으로 정렬됩니다.

### Challenge Miner (daemon)

```bash
python -m repo_idea_miner daemon              # 계속 실행
python -m repo_idea_miner daemon --once       # 한 사이클만 (검증용)
python -m repo_idea_miner status              # queue/완료/에러/key 상태
python -m repo_idea_miner pause               # 새 작업 배정 중단 (진행 중 작업은 완료)
python -m repo_idea_miner resume              # 재개
```

daemon은 seed query(기본 내장, `--seeds seeds.yaml`로 교체 가능)를 주기적으로 실행해 `repo_queue`를 보충하고, 가능한 key마다 작업을 배정해 ChallengePackage를 계속 생성합니다. 결과는 `challenge.db`와 `runs/`에 쌓입니다.

**11-key controlled parallel pool** — key 1개당 동시 1작업, 최대 11개 key가 동시에 일합니다. 일부러 느리게 처리하지 않으며 전체 worker를 멈추지 않습니다.

**429/500 처리** — 둘 다 짧은 일시 오류로 취급해 해당 key만 30초 cooldown하고, 같은 key에서 반복되면 60→120→300초로 늘립니다 (timeout은 60→120→300초). 다른 key들은 계속 작업합니다. 명확한 daily quota/RPD exhausted 메시지가 확인될 때만 exhausted 처리하며, 단순 429로 key를 장시간 정지시키지 않습니다. `daily_used`는 안전용 로컬 카운터로 로컬 날짜 00:00에 reset됩니다. 관련 설정은 `RIM_TRANSIENT_ERROR_BACKOFF_SEQUENCE_SECONDS` 등 환경변수로 조정합니다.

### Challenge Dashboard

```bash
python -m repo_idea_miner dashboard --host 127.0.0.1 --port 8787
```

`challenge.db`를 읽는 로컬 웹 확인함입니다. Today 요약(오늘 생성/라벨별/에러/queue/key 상태), 필터(final_label/owner_status/language/날짜/score), 상세 탭(Owner Brief/Screen Story/Challenge Card/Implementation Prompt/Validation Report), 판정 버튼(SAVE/MAYBE/DROP/BUILD NEXT/MARK BUILT)과 COPY 버튼을 제공합니다. LLM 판정(final_label)과 사용자 판정(owner_status)은 분리 저장됩니다.

특정 run의 `viewer.html`은 정적 artifact 확인용이고, Dashboard는 계속 쌓인 Challenge를 판정하는 확인함입니다 — 역할이 다릅니다.

**보안 주의** — Dashboard에는 인증이 없습니다. 기본 host는 반드시 `127.0.0.1`이며, 아이폰 Safari 등에서 보려면 **Tailscale 등 사설망에서만** 명시적으로 `--host 0.0.0.0`을 사용하세요.

### challenge.db

Challenge Mode의 누적 저장소(SQLite)입니다. 기본 위치는 저장소 루트의 `challenge.db`(`--db`로 변경 가능, 커밋되지 않음)이고 `repos / repo_queue / challenges / owner_reviews / api_keys / events / settings` 테이블을 가집니다. `pause/resume`은 `settings.miner_paused`를 사용합니다.

### Challenge 산출물 검증

```bash
python -m repo_idea_miner validate runs/<timestamp>/          # challenge run이면 자동으로 challenge 검증
python -m repo_idea_miner validate-db --db challenge.db       # DB integrity/테이블/artifact_dir 정합성
python -m repo_idea_miner validate runs/<timestamp>/ --db challenge.db  # 둘 다
```

스키마 통과, difficulty_anchors/forbidden_simplifications/pass·failure_criteria 비어 있지 않음, implementation_prompt.md에 Anchors/Forbidden 반영, viewer.html 존재·secret 미노출 등을 검사합니다.

## Product Factory

Challenge Mode가 뽑은 좋은 후보를 사람 개입 없이 **멀티파일 제품 후보 workspace**까지 자동으로 키우는 파이프라인입니다 (요구서: `RIMProductFactory.md`).

```text
Challenge Card → Auto Promotion Gate → Planning → UX/Spec → Technical Spec
  → Build → Static/Contract/Syntax/Smoke Gate → (실패 시 Debug Desk, 최대 횟수 제한)
  → QA → Judge → Final Artifact (+ PROMOTE_TO_CODEX면 codex_export bundle)
  → Dashboard에서 사람이 최종 검토 (KEEP/DROP/PRODUCTIZE/RETRY/ARCHIVE)
```

```bash
# 승격 대상 challenge 자동 처리 (기본은 안전 모드 — 1건)
python -m repo_idea_miner factory --mode mock --once
python -m repo_idea_miner factory --mode live --max-runs 3
python -m repo_idea_miner factory --mode live --continuous   # 명시했을 때만 계속 실행

# 단일 challenge 실행 (--challenge-id 우선, --challenge-dir는 DB 없는 fallback)
python -m repo_idea_miner factory-build --challenge-id 12 --mode live
python -m repo_idea_miner factory-build --challenge-dir runs/<ts> --mode mock
python -m repo_idea_miner factory-build --sample mock --mode mock

# 상태/검증
python -m repo_idea_miner factory-status
python -m repo_idea_miner factory-validate runs/factory_<ts>
```

- **승격 기준(§6)** — GOOD_CHALLENGE는 일반 라인, STEAL_ONLY는 micro-workspace 라인으로 진입. TOO_EASY/TOO_BIG/UNCLEAR_TO_OWNER/DROP은 진입하지 않습니다.
- **검증 게이트** — Static(파일/manifest/고아 파일/fake multi-file/secret), Contract(entrypoint·import graph reachability·주요 모듈·anchor 마커), Syntax(py_compile/node --check/json/html 참조), Smoke(의존성 설치→실행/검증 명령). 실패하면 Debug Desk가 patch를 만들고 최대 횟수(기본 2회) 안에서 재검증합니다.
- **Docker 샌드박스(§13)** — 의존성 설치 단계만 제한적 network 허용, 실행/테스트 단계는 `--network none`. workspace 디렉터리만 mount하고 `.env`/API key/home은 절대 mount하지 않습니다. CPU/memory/timeout 제한이 걸립니다 (docker가 없으면 최소 환경변수 로컬 실행으로 fallback, `RIM_FACTORY_USE_DOCKER=auto|on|off`).
- **판정** — `PROMOTE_TO_CODEX / KEEP_CANDIDATE / NEEDS_MORE_GEMMA_LOOP / TOO_WEAK / DROP`. PROMOTE_TO_CODEX는 Codex/Claude 자동 호출이 아니라 `codex_export/` bundle 생성까지입니다.
- **key 공유(§12)** — Challenge daemon과 같은 `challenge.db`의 `api_keys` 테이블을 key 상태 저장소로 공유합니다. 429/500은 해당 key만 cooldown.
- **DB** — `product_runs / product_tasks / product_events / product_artifacts` 테이블이 `challenge.db`에 추가됩니다. `worker_key_id`는 `KEY_01` 형식 내부 ID만 저장합니다.
- **Dashboard** — 목록 상단 `제품 공장` 링크(`/products`)에서 verdict/리포트를 확인하고 KEEP/DROP/PRODUCTIZE/RETRY/ARCHIVE를 판정합니다. verdict별 추천 버튼이 강조됩니다.

## 테스트

```bash
pytest
```

URL 파싱, preflight, collector 필터, issue sampler/signal tag, bike-shedding, dependency origin, JSON validation/repair, length truncation, score ceiling, renderer, secret redaction, key pool round-robin/failover, retry-after/backoff, timeout 설정을 모두 커버합니다.

## 아키텍처 요약

```text
수집 (github_api) → preflight → evidence_packet
  → Bouncer → README Scout / Pain Scout / Structure·Risk Scout → Critic/Judge
  → JSON parse (+syntax repair 1회) → Pydantic validation
  → Score Ceiling Validator (KEEP 남발 방지, raw/final 분리 기록)
  → Length truncation (실패가 아니라 축약)
  → idea_card.md / run_report.md 렌더링 → secret redaction 검증
```

핵심 원칙:

- LLM 출력은 Markdown이 아니라 JSON으로 받고 Pydantic으로 검증한다.
- Judge를 믿되 Validator(ceiling rules)로 막는다. raw와 final을 분리 기록한다.
- 11개 Google AI Studio key를 round-robin pool로 관리한다. 429/503/timeout은 Retry-After 우선 + exponential backoff/jitter로 failover하고, 401/403/invalid key는 해당 key만 DISABLED 처리한다. 고정 1시간 cooldown은 사용하지 않는다.
- Issue는 앞부분만 보지 않는다(head+tail+키워드 문맥 샘플링). 댓글 수 착시는 unique commenter / maintainer ratio로 걸러낸다.
- Dockerfile/docker-compose 존재만으로 risk를 과장하지 않는다 (evidence origin 기록, 판단은 Judge).
- API key와 GitHub token은 어떤 산출물에도 노출하지 않는다 (redaction + 최종 스캔).

## 구현 범위 / 미구현 범위

샘플 산출물은 `samples/`에 있습니다. 구현/제외 범위는 [SCOPE.md](SCOPE.md)를 참고하세요.
