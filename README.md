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

- LLM 출력은 Markdown이 아니라 JSON으로 받고 Pydantic으로 검증한다.
- Judge를 믿되 Validator(ceiling rules)로 막는다. raw와 final을 분리 기록한다.
- 11개 Google AI Studio key를 round-robin pool로 관리한다. 429/503/timeout은 Retry-After 우선 + exponential backoff/jitter로 failover하고, 401/403/invalid key는 해당 key만 DISABLED 처리한다. 고정 1시간 cooldown은 사용하지 않는다.
- Issue는 앞부분만 보지 않는다(head+tail+키워드 문맥 샘플링). 댓글 수 착시는 unique commenter / maintainer ratio로 걸러낸다.
- Dockerfile/docker-compose 존재만으로 risk를 과장하지 않는다 (evidence origin 기록, 판단은 Judge).
- API key와 GitHub token은 어떤 산출물에도 노출하지 않는다 (redaction + 최종 스캔).

## 구현 범위 / 미구현 범위

샘플 산출물은 `samples/`에 있습니다. 구현/제외 범위는 [SCOPE.md](SCOPE.md)를 참고하세요.
