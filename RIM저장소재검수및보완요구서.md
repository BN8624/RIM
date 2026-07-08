# RIM 저장소 재검수 및 보완 요구서

대상 저장소: `https://github.com/BN8624/RIM.git`

## 1. 요청 목적

RIM 저장소가 최종 외주 스펙정본대로 실제 납품 가능한 상태인지 확인하고, 미흡한 부분을 보완해 주세요.

현재 저장소는 README와 파일 구성상 외주스펙정본의 기능을 상당 부분 반영한 것으로 보입니다.
다만 외부 검토 과정에서 GitHub 파일 화면과 Raw 파일 표시가 서로 충돌하는 현상이 확인되었습니다.

따라서 납품 완료 여부는 문서 주장이나 파일명 기준이 아니라, **fresh clone 후 실제 설치·컴파일·테스트·CLI 실행 결과**로 판단합니다.

---

## 2. 중요 전제

외부 검토 결과:

```text id="7m1ino"
GitHub 파일 화면:
- cli.py가 98 lines로 표시됨
- pyproject.toml이 27 lines로 표시됨

Raw 버튼 / raw.githubusercontent.com:
- cli.py가 2줄로 표시됨
- pyproject.toml이 1줄로 표시됨
- .env.example이 2줄로 표시됨
- .gitignore가 1줄로 표시됨
```

이것이 실제 파일 손상인지, GitHub raw 표시/캐시/검토 도구 문제인지는 단정하지 않습니다.

하지만 납품 검수에서는 반드시 fresh clone 기준 실행 로그로 증명해야 합니다.

```text id="8sx8ty"
파일이 깨졌다고 단정하지 않는다.
하지만 실행 가능한 상태인지 반드시 증명해야 한다.
실제 실행 로그가 없으면 납품 완료로 인정하지 않는다.
```

---

# 3. 최우선 증빙 요구

외주업체는 아래 명령을 **새 디렉터리에서 fresh clone 후** 실행하고, 터미널 전체 로그를 제출해야 합니다.

```bash id="dvy26k"
git clone https://github.com/BN8624/RIM.git
cd RIM

python --version

python -m py_compile repo_idea_miner/*.py

pip install -e ".[dev]"

pytest

python -m repo_idea_miner --help

python -m repo_idea_miner run \
  --repo https://github.com/BN8624/RIM \
  --mode mock \
  --input-mode direct

python -m repo_idea_miner search \
  --query "automation workflow python" \
  --limit 10 \
  --top 5 \
  --mode mock

python -m repo_idea_miner validate runs/<생성된_실행_경로>
```

성공 기준:

```text id="7986qh"
1. py_compile 통과
2. pip install -e ".[dev]" 통과
3. pytest 통과
4. python -m repo_idea_miner --help 정상 출력
5. run mock 실행 성공
6. search mock 실행 성공
7. validate 명령 성공
8. runs/<timestamp>/ 산출물 생성
9. secret 노출 없음
```

위 명령 중 하나라도 실패하면 납품 완료가 아닙니다.

---

# 4. 파일 정상성 확인 요구

다음 파일들은 실제 fresh clone 기준으로 줄바꿈과 문법이 정상이어야 합니다.

```text id="0hbyry"
pyproject.toml
.env.example
.gitignore
repo_idea_miner/__main__.py
repo_idea_miner/cli.py
repo_idea_miner/search_pipeline.py
repo_idea_miner/schemas.py
```

확인 명령:

```bash id="ou7nab"
python - <<'PY'
from pathlib import Path

for path in [
    "pyproject.toml",
    ".env.example",
    ".gitignore",
    "repo_idea_miner/__main__.py",
    "repo_idea_miner/cli.py",
    "repo_idea_miner/search_pipeline.py",
    "repo_idea_miner/schemas.py",
]:
    p = Path(path)
    print(f"\n--- {path} ---")
    print(f"exists={p.exists()} lines={len(p.read_text(encoding='utf-8').splitlines())}")
    print("\n".join(p.read_text(encoding='utf-8').splitlines()[:20]))
PY
```

성공 기준:

```text id="awjvbs"
- pyproject.toml이 정상 TOML 형식이어야 함
- .env.example이 줄 단위 환경변수 예시여야 함
- .gitignore가 .env를 실제로 ignore해야 함
- __main__.py가 python -m repo_idea_miner 진입점으로 동작해야 함
- Python 파일들이 py_compile을 통과해야 함
```

`.gitignore` 확인:

```bash id="kh3y54"
git check-ignore .env
```

`.env`가 ignore되어야 합니다.

---

# 5. Live 검수 요구

사용자가 `.env`에 다음 값을 직접 넣습니다.

```env id="fpt9yl"
GITHUB_TOKEN=

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

RIM_GEMMA_MODEL=gemma-4-31b-it
RIM_LLM_PROVIDER=google_genai_gemma
RIM_KEY_POOL_STRATEGY=round_robin

RIM_MAX_RETRIES_PER_CALL=3
RIM_RETRY_BACKOFF_STRATEGY=exponential_jitter
RIM_RETRY_INITIAL_DELAY_SECONDS=2
RIM_RETRY_MAX_DELAY_SECONDS=60
RIM_RESPECT_RETRY_AFTER=true
RIM_RETRY_AFTER_MAX_SECONDS=300
RIM_REQUEST_TIMEOUT_SECONDS=180

RIM_TEMPERATURE=0.2
RIM_JSON_REPAIR_ATTEMPTS=1
```

외주업체는 실제 key 값을 요구하면 안 됩니다.
key 값은 사용자만 넣습니다.

---

## 5.1 단일 레포 live 검수

다음 명령이 성공해야 합니다.

```bash id="ltpw7d"
python -m repo_idea_miner run \
  --repo https://github.com/BN8624/RIM \
  --mode live \
  --input-mode direct
```

성공 기준:

```text id="c67z0q"
- GITHUB_TOKEN 사용
- GOOGLE_API_KEY_1~11 중 하나 이상 사용
- model = gemma-4-31b-it
- Bouncer / README Scout / Pain Scout / Structure Risk Scout / Critic Judge 실행
- worker output JSON 생성
- Pydantic validation 통과
- idea_card.md 생성
- run_report.md 생성
- debug/llm_calls.jsonl 생성
- key 값은 노출되지 않고 key_index만 기록
- Judge raw와 Validator final 분리 기록
```

---

## 5.2 검색어 live 검수

다음 명령이 성공해야 합니다.

```bash id="mfs6c6"
python -m repo_idea_miner search \
  --query "automation workflow python" \
  --limit 10 \
  --top 5 \
  --mode live
```

성공 기준:

```text id="drihix"
- 후보 repo 수집
- search-mode preflight 적용
- 후보별 live analysis 실행
- key pool round robin 사용
- 후보별 idea_card.md 생성
- top_ideas.md 생성
- search_report.md 생성
- validator correction rate 기록
- key 값 미노출
```

---

# 6. 반드시 확인할 산출물

단일 레포 실행 후 다음 파일이 있어야 합니다.

```text id="xbt68w"
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
- raw/
```

검색어 실행 후 다음 파일이 있어야 합니다.

```text id="lqj6c4"
runs/<timestamp>/
- top_ideas.md
- search_report.md
- candidates.json

runs/<timestamp>/cards/
- OWNER_REPO_idea_card.md

runs/<timestamp>/repos/
- OWNER_REPO/
  - idea_card.md
  - run_report.md
  - debug/
```

---

# 7. 보완 요구사항

아래 항목은 현재 구현 여부를 다시 확인하고, 미흡하면 수정해야 합니다.

---

## 7.1 `--targeted` 옵션 실제 구현

현재 외부 검토상 `search_pipeline.py`에서 `targeted` 인자를 받지만, 실제 검색 호출에는 `targeted`가 반영되지 않는 것으로 보입니다.

요구사항:

```text id="9d5g3l"
--targeted 사용 시 사용자의 관심사와 가까운 레포를 우선 정렬해야 한다.
```

관심사 기준 예시:

```text id="yvbr5e"
automation
workflow
developer productivity
CLI
Python
OCR/document extraction
test automation
code review/helper
simulation/game tool
repo analysis
idea mining
```

구현 허용 방식:

```text id="v1ni8l"
1. GitHub search query를 topic/language 키워드로 보강하거나
2. 후보 수집 후 topics / description / README summary 기준으로 targeted_score를 계산하거나
3. candidates.json과 search_report.md에 targeted_score와 정렬 기준을 기록한다.
```

검수 명령:

```bash id="bphefm"
python -m repo_idea_miner search \
  --query "automation workflow python" \
  --limit 10 \
  --top 5 \
  --mode mock \
  --targeted
```

검수 기준:

```text id="e35pqt"
- --targeted가 결과 정렬에 영향을 줘야 함
- candidates.json에 targeted 관련 점수 또는 이유가 기록되어야 함
- README에 --targeted의 실제 동작이 설명되어야 함
```

`--targeted`를 구현하지 않을 경우, CLI와 README에서 제거하고 미지원 범위로 명시해야 합니다.

---

## 7.2 Search live 모드 key pool 집계

검색어 live 실행에서는 여러 repo를 연속 분석합니다.

요구사항:

```text id="aw4awi"
search_report.md의 key pool summary는 전체 후보 분석에 사용된 key_index, retry_count, failover_count를 정확히 합산해야 한다.
```

검수 기준:

```text id="ybrqv9"
- search_report.md의 used_key_indexes가 각 repo의 debug/llm_calls.jsonl과 일치해야 함
- retry_count / failover_count가 후보별 run_report와 합산되어야 함
- mock mode에서는 key pool 값이 mock 기준으로 안전하게 표시되어야 함
```

---

## 7.3 Pydantic schema nullable 필드

외부 검토상 다음 필드가 `str` 필수값으로 보입니다.

```text id="jk8t4k"
Application.related_project
OneDayMvp.feature
OneDayMvp.input
OneDayMvp.output
PatternPoc.idea
PatternPoc.input
PatternPoc.output
```

하지만 다음 상황에서는 `null`이 자연스럽습니다.

```text id="ubckvk"
application.area == 적용 부적합 → related_project = null 가능
one_day_mvp.status == 축소 불가 → feature/input/output = null 가능
pattern_poc.status == 불가능 또는 불확실 → idea/input/output = null 가능
```

요구사항:

```text id="7jl9my"
위 필드는 str | None 허용으로 수정한다.
단, status == 가능인 경우에는 해당 필드가 비어 있으면 안 된다.
```

검수 테스트:

```text id="aqu1az"
- 적용 부적합 + related_project null → validation 통과
- one_day_mvp 축소 불가 + feature/input/output null → validation 통과
- pattern_poc 불가능 + idea/input/output null → validation 통과
- one_day_mvp 가능인데 feature/input/output null → validation 실패
- pattern_poc 가능인데 idea/input/output null → validation 실패
```

---

## 7.4 `llm_calls.jsonl`의 validation_success 의미 정리

LLM client 단계에서는 JSON parse 성공 여부만 알 수 있고, Pydantic validation 결과는 pipeline 단계에서 확정됩니다.

요구사항:

```text id="o7h7gy"
llm_calls.jsonl에서 validation_success가 실제 Pydantic validation 성공을 의미하지 않는다면 제거하거나 null로 기록한다.
```

권장 방식:

```text id="u2qee2"
- llm_calls.jsonl: json_parse_success, repair_used까지만 기록
- Pydantic validation 결과는 worker output validation log 또는 run_report.md에 기록
```

잘못된 기록 예:

```json id="jjvj23"
{"json_parse_success": true, "validation_success": true}
```

단순 JSON parse 성공을 validation 성공처럼 기록하면 안 됩니다.

---

## 7.5 Length truncation은 Error가 아니라 Warning

길이 초과는 실패가 아니라 안전한 축약입니다.

요구사항:

```text id="jvg58i"
LENGTH_TRUNCATED는 Errors가 아니라 Warnings 또는 Length Truncation 섹션에만 기록한다.
```

검수 기준:

```text id="5sjtru"
긴 문자열이 들어와도 run은 성공해야 함
run_report.md의 Errors에는 LENGTH_TRUNCATED가 없어야 함
Length Truncation 섹션에는 truncated_fields가 기록되어야 함
```

---

## 7.6 run_report.md 포함 최종 secret scan

secret scan은 `run_report.md` 작성 전 산출물만 검사하면 안 됩니다.

요구사항:

```text id="ergp7o"
run_report.md 작성 후 전체 runs/<timestamp>/ 디렉터리를 다시 secret scan한다.
최종 Secret Redaction PASS/FAIL은 run_report.md 포함 전체 산출물 기준이어야 한다.
```

검수 테스트:

```text id="oq4e02"
fake secret을 run_report에 들어가게 하는 테스트를 추가하고, secret scan이 FAIL 처리하는지 확인한다.
```

---

# 8. 필수 테스트 추가/확인

기존 테스트 외에 아래 테스트가 반드시 있어야 합니다.

```text id="ot58gl"
1. fresh clone install test 문서화
2. __main__.py CLI entry test
3. .env.example line format test
4. .gitignore .env ignore test
5. --targeted 실제 정렬/점수 반영 test
6. nullable schema test
7. llm_calls validation_success 의미 test
8. length truncation warning test
9. final secret scan includes run_report test
10. search live key pool aggregate test
```

---

# 9. 납품 완료 인정 기준

다음 조건을 모두 만족해야 납품 완료로 인정합니다.

```text id="pg2dza"
1. fresh clone 기준 py_compile 통과
2. pip install -e ".[dev]" 통과
3. pytest 통과
4. python -m repo_idea_miner --help 통과
5. run mock 통과
6. search mock 통과
7. validate 통과
8. run live 통과
9. search live 통과
10. key 값 미노출
11. GitHub token 미노출
12. .env가 git에 잡히지 않음
13. targeted 옵션이 실제 동작하거나 제거됨
14. run_report 포함 최종 secret scan 통과
15. 모든 제출 로그 제공
```

---

# 10. 제출해야 할 증빙

외주업체는 다음을 제출해야 합니다.

```text id="y16bmp"
1. 수정 커밋 해시
2. fresh clone 검수 전체 터미널 로그
3. pytest 전체 결과
4. run mock 산출물
5. search mock 산출물
6. run live 산출물
7. search live 산출물
8. secret redaction 테스트 결과
9. key pool 테스트 결과
10. targeted 옵션 동작 설명
11. 미구현/제외 범위 설명
```

---

# 11. 최종 요청 문구

아래 요구를 처리한 뒤 보고해 주세요.

```text id="bhlhtl"
RIM 저장소가 외주스펙정본을 충족하는지 fresh clone 기준으로 검수해 주세요.

외부 검토에서 GitHub 파일 화면과 raw 표시가 서로 충돌하는 현상이 있었습니다. 실제 파일 손상인지 도구 표시 문제인지는 단정하지 않겠습니다. 따라서 판단 기준은 fresh clone 후 py_compile, pip install, pytest, CLI smoke test, mock run/search, live run/search, validate 실행 로그입니다.

특히 다음 항목을 반드시 확인·수정해 주세요.

1. pyproject.toml / Python 소스 / .env.example / .gitignore가 실제 파일 기준 정상인지 증명
2. python -m repo_idea_miner 진입점 정상 동작
3. pytest 전체 통과
4. mock run/search/validate 통과
5. live run/search 통과
6. 11개 Google AI Studio key pool round robin / retry / failover 정상 동작
7. gemma-4-31b-it 모델 사용 확인
8. key 값과 GitHub token이 어떤 산출물에도 노출되지 않음
9. --targeted 옵션이 실제 정렬/점수에 반영되거나 제거됨
10. nullable schema, length truncation warning, final secret scan, search key pool aggregate 문제 점검

위 항목을 처리하고 커밋 해시, 테스트 로그, 실행 산출물 경로를 제출해 주세요.
```
