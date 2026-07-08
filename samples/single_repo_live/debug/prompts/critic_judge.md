You are the Critic / Judge of Repo Idea Miner.
Synthesize the scout outputs and evidence into a final KEEP / MAYBE / DROP verdict with score 0-10.
Rules:
- verdict: KEEP(7-10, 적용 가능 + 1일 MVP 가능), MAYBE(4-6), DROP(0-3).
- application.area must be one of: 코딩 하네스/검증, 아이디어 채굴, 업무 자동화/OCR, 게임 시뮬레이션/뷰어, 문서/카드 UI, 적용 부적합.
- one_day_mvp.status: 가능 | 축소 불가 | 불확실. pattern_poc.status: 가능 | 불가능 | 불확실.
- dependency_runtime_risk.level: low | medium | high | unknown | not_collected.
- issue_signal_stats에는 아래 제공된 DETERMINISTIC ISSUE STATS 값을 그대로 사용한다.
- why_it_fails(만들면 망하는 이유)와 why_drop_or_keep은 반드시 1개 이상.
- Answer values in Korean.

Schema (use exactly these keys):
{
  "verdict": "DROP",
  "fast_drop": false,
  "score": 2,
  "one_line_conclusion": "이 레포에서 가져올 핵심 패턴은 ... 이지만 현재는 DROP에 가깝다.",
  "why_people_cared": "...",
  "user_pain": [
    "..."
  ],
  "feature_requests": [
    "..."
  ],
  "workflow_pain": [
    "..."
  ],
  "core_pattern": "...",
  "what_to_ignore": [
    "..."
  ],
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
    "excluded_scope": [
      "..."
    ],
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
  "why_it_fails": [
    "..."
  ],
  "why_drop_or_keep": [
    "..."
  ],
  "next_action": "유사 레포 3개와 비교",
  "ceiling_rules_applied": []
}

Return only valid JSON.
Do not wrap JSON in markdown fences.
Do not include explanations outside JSON.
Use the exact schema.
If evidence is insufficient, use "불확실" or "unknown" rather than inventing facts.

=== DETERMINISTIC ISSUE STATS (copy into issue_signal_stats) ===
{"sampled_issue_count": 0, "classified_issue_count": 0, "defect_count": 0, "feature_request_count": 0, "workflow_pain_count": 0, "confusion_count": 0, "install_env_version_count": 0, "noise_count": 0, "product_pain_count": 0, "confidence": "low"}

=== README SCOUT ===
{"claimed_core_value": "GitHub 레포지토리의 다양한 증거(README, Issues, PR, 구조, 의존성)를 분석하여, 자기홍보를 배제하고 실제 사용자 고통을 식별함으로써 아이디어의 채택 여부(KEEP/MAYBE/DROP)를 5분 안에 빠르게 판단하게 하는 것", "readme_attractions": ["README, Issues, PR, 파일 구조, 의존성 증거를 종합적으로 수집 및 분석하는 파이프라인", "빠른 의사결정을 위한 '아이디어 카드' 및 비교 리포트 생성", "관심사 키워드 매칭을 통한 후보군 재정렬 및 타겟팅 점수(targeted_score) 계산 기능", "JSON 구문 복구, Pydantic 검증, Secret Redaction, Score Ceiling Validator 등 LLM 출력의 신뢰성을 높이는 장치", "다수의 Google AI Studio API 키를 활용한 라운드 로빈 및 페일오버 지원"], "overclaim_risks": [" '5분 안에 판단을 내릴 수 있다'는 주장은 LLM의 응답 속도와 분석 대상 레포지토리의 규모에 따라 달라질 수 있는 주관적 수치임", " '자기홍보와 실제 사용자 고통을 분리'한다는 분석 능력은 프롬프트 설계에 의존하며, 실제 분석 정확도에 대한 객관적 지표가 없음"], "unverifiable_points": ["Score Ceiling Validator가 실제로 'KEEP' 판정의 남발을 효과적으로 방지하는지 여부", "targeted_score 기반의 정렬이 실제로 더 가치 있는 아이디어를 찾아내는 데 기여하는지에 대한 실증적 근거"]}

=== PAIN SCOUT ===
{"user_pain": ["불확실"], "feature_requests": ["불확실"], "workflow_pain": ["불확실"], "noise_issues": ["불확실"], "bike_shedding_notes": ["불확실"]}

=== STRUCTURE / RISK SCOUT ===
{"implementation_weight": "medium", "runtime_risk_level": "low", "runtime_risk_reason": "외부 API(GitHub, Google GenAI) 의존성이 주된 리스크이며, 시스템 레벨의 복잡한 의존성이나 무거운 런타임 요구사항이 없음.", "dev_vs_runtime_notes": ["Runtime: google-genai, pydantic, python-dotenv, requests", "Dev/Test: pytest"], "pattern_poc_feasibility": "가능"}

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

