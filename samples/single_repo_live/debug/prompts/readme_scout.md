You are the README Scout of Repo Idea Miner.
From the README evidence, extract what the repo CLAIMS (not what is proven).
Separate self-promotion from verifiable substance. Answer in Korean.

Schema:
{"claimed_core_value": "...", "readme_attractions": ["..."], "overclaim_risks": ["..."], "unverifiable_points": ["..."]}

Return only valid JSON.
Do not wrap JSON in markdown fences.
Do not include explanations outside JSON.
Use the exact schema.
If evidence is insufficient, use "불확실" or "unknown" rather than inventing facts.

=== EVIDENCE PACKET ===
# Evidence Packet

## Repo Metadata
status: OK
- full_name: BN8624/RIM
- description: None
- stars: 0 / forks: 0 / watchers: 0
- topics: (없음)
- primary_language: Python / languages: Python
- created_at: 2026-07-08T06:03:53Z / updated_at: 2026-07-08T07:29:58Z / pushed_at: 2026-07-08T07:29:45Z
- archived: NO / disabled: NO / fork: NO
- open_issues_count: 0
- license: None / homepage: None
- default_branch: main / size: 113

## Input Mode
direct

## Preflight
status: LOW_SIGNAL_PROCEED
reason: 낮은 신호로 계속 진행: star 수 낮음, fork 수 낮음, issue 적음

## README Signal
status: OK
- length: 3624
- has_install: YES / has_usage_example: YES / has_features: NO
- has_demo_or_docs_link: YES / mentions_api: YES / mentions_docker: YES
- external_service_keywords: docker, worker

### README Excerpt
```
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

구조·JSON 스키마·secret 노출·필수 섹션을 검증합니다.

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

- LLM 출력은 Markd
```

## User Pain Signal
status: MISSING

### Recent Open Issues
(없음)

### High Comment Open Issues
(없음)

### Recent Closed Issues
(없음)

## PR Signal
status: MISSING

### Recent Human PRs
(없음)

### Excluded Bot / Dependency PRs
(없음)

## Structure Signal
status: OK

### File Tree Depth 2
```
.env.example
.gitignore
README.md
RIM_FANAL.md
RIM저장소재검수및보완요구서.md
SCOPE.md
checklist.md
pyproject.toml
repo_idea_miner/
repo_idea_miner/__init__.py
repo_idea_miner/__main__.py
repo_idea_miner/ceiling.py
repo_idea_miner/cli.py
repo_idea_miner/config.py
repo_idea_miner/errors.py
repo_idea_miner/evidence.py
repo_idea_miner/github_api.py
repo_idea_miner/jsonutil.py
repo_idea_miner/key_pool.py
repo_idea_miner/llm_client.py
repo_idea_miner/pipeline.py
repo_idea_miner/preflight.py
repo_idea_miner/redaction.py
repo_idea_miner/renderer.py
repo_idea_miner/sampler.py
repo_idea_miner/schemas.py
repo_idea_miner/search_pipeline.py
repo_idea_miner/signals.py
repo_idea_miner/truncation.py
repo_idea_miner/url_parser.py
repo_idea_miner/validate_run.py
repo_idea_miner/workers.py
samples/
samples/search_live/
samples/single_repo_live/
tests/
tests/conftest.py
tests/test_ceiling.py
tests/test_collector.py
tests/test_dependency.py
tests/test_followup.py
tests/test_json_repair.py
tests/test_key_pool.py
tests/test_llm_client.py
tests/test_pipeline_mock.py
tests/test_preflight.py
tests/test_redaction.py
tests/test_renderer.py
tests/test_sampler.py
tests/test_schema_validation.py
tests/test_signals.py
tests/test_truncation.py
tests/test_url_parser.py
```

### Docs / Examples / Demo Paths
(없음)

## Dependency / Runtime Evidence
status: OK
- files_found: pyproject.toml
- entries:
  - [RUNTIME] google-genai>=1.0.0 (pyproject.toml)
  - [RUNTIME] pydantic>=2.5 (pyproject.toml)
  - [RUNTIME] python-dotenv>=1.0 (pyproject.toml)
  - [RUNTIME] requests>=2.31 (pyproject.toml)
  - [DEV_TEST] pytest>=8 (pyproject.toml)
- risk_keyword_hits:
  - docker @ README (origin=README_ONLY)
  - worker @ README (origin=README_ONLY)

## Missing Data
(없음)

## Collector Notes
(없음)

