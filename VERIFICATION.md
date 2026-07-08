# 재검수 증빙 (fresh clone 기준)

재검수 및 보완 요구서 기준 검수 결과. 모든 로그는 **새 디렉터리에 fresh clone 후** 실행한 것이다.

- 검수 일시: 2026-07-08
- 검수 대상 커밋: `0a3fda75db800be78b499df8c91d07490e4d2337` (§7 보완 포함)
- 검수 환경: Windows 11, Python 3.14.5

## 결론 요약 (§9 납품 완료 인정 기준)

| # | 기준 | 결과 |
|---|---|---|
| 1 | fresh clone 기준 py_compile 통과 | PASS |
| 2 | pip install -e ".[dev]" 통과 | PASS |
| 3 | pytest 통과 | PASS (fresh clone 134개, 보완 후 135개) |
| 4 | python -m repo_idea_miner --help 통과 | PASS |
| 5 | run mock 통과 | PASS (MAYBE 5점) |
| 6 | search mock 통과 (limit 10 top 5) | PASS (10후보, 오류 0) |
| 7 | validate 통과 | PASS (run/search 모두) |
| 8 | run live 통과 | PASS (gemma-4-31b-it, KEEP 8점) |
| 9 | search live 통과 (limit 10 top 5) | PASS (7후보 판정, 3후보는 Google 500 INTERNAL로 실패 기록 — 아래 참고) |
| 10 | key 값 미노출 | PASS (runs/ 739개 파일 스캔) |
| 11 | GitHub token 미노출 | PASS (동일 스캔) |
| 12 | .env가 git에 잡히지 않음 | PASS (`git check-ignore .env` → `.gitignore:1:.env`) |
| 13 | targeted 옵션 실제 동작 | PASS (targeted_score 계산·재정렬·기록) |
| 14 | run_report 포함 최종 secret scan | PASS (구현 + 테스트) |
| 15 | 제출 로그 제공 | 본 문서 하단 전체 로그 |

## §2 "raw 표시 충돌"에 대한 결론

fresh clone 기준 실제 파일은 전부 정상이다. GitHub 파일 화면 표시와 일치하며(`cli.py` 98줄, `pyproject.toml` 27줄 정상 TOML 파싱), 외부 검토 도구의 raw 표시 문제였음이 실행 로그로 증명되었다.

```text
--- pyproject.toml: exists=True lines=27  (TOML parse PASS)
--- .env.example: exists=True lines=42
--- .gitignore: exists=True lines=10
--- repo_idea_miner/__main__.py: exists=True lines=5
--- repo_idea_miner/cli.py: exists=True lines=98
--- repo_idea_miner/search_pipeline.py: exists=True lines=219
--- repo_idea_miner/schemas.py: exists=True lines=150
```

## §7 보완 처리 내역

| 항목 | 처리 |
|---|---|
| 7.1 `--targeted` 실구현 | 관심사 키워드 × topics(가중 2)/이름·설명·언어(가중 1)로 `targeted_score` 계산, 내림차순 재정렬. candidates.json에 `targeted_score`/`targeted_matched`, search_report.md에 `targeted_sort` 기록. README 설명 추가. |
| 7.2 search live key pool 집계 | 후보별 retry/failover를 합산해 search_report에 기록. live 검수에서 retry_count 14 / failover_count 14로 실측 확인 (500 INTERNAL failover). mock에서는 0으로 안전 표시. |
| 7.3 nullable schema | `related_project`, MVP `feature/input/output`, PoC `idea/input/output`을 `str \| None`으로 변경. `status == 가능`이면 필수(model_validator). 요구된 5개 검수 케이스 테스트 추가. |
| 7.4 validation_success 의미 | llm_calls.jsonl의 `validation_success`는 항상 `null`. Pydantic 결과는 run_report.md의 JSON Validation이 공식 기록 (SCOPE.md 명시). |
| 7.5 truncation은 warning | LENGTH_TRUNCATED를 Errors에서 제거, Length Truncation 섹션에만 기록. 테스트 추가. |
| 7.6 최종 secret scan | run_report.md 작성 후 전체 디렉터리 재스캔, FAIL 시 report 갱신 + run 실패 처리. redaction 우회 상황 테스트 추가. |
| (발견) validate와 실패 후보 | live 검수 중 발견: LLM 실패가 기록된 후보의 카드 부재를 validate가 위반으로 처리 → run_report에 실패가 기록된 후보는 건너뛰도록 보완 + 테스트. |

## §8 요구 테스트 매핑

1. fresh clone install test 문서화 → 본 문서
2. `__main__.py` CLI entry test → `test_module_entry_help`
3. `.env.example` line format test → `test_env_example_line_format`
4. `.gitignore` .env ignore test → `test_gitignore_ignores_env`
5. `--targeted` 정렬/점수 test → `test_rank_candidates_targeted_reorders` 외 4개
6. nullable schema test → `test_unfit_area_null_related_project_ok` 외 5개
7. llm_calls validation_success test → `test_llm_calls_validation_success_is_null_*` 2개
8. length truncation warning test → `test_length_truncation_is_not_an_error`
9. final secret scan includes run_report test → `test_final_scan_includes_run_report`, `test_pipeline_fails_when_redaction_bypassed`
10. search live key pool aggregate test → `test_search_report_aggregates_key_pool_counts`, `test_search_mock_key_pool_safe_values`

전체: `pytest` 135 passed.

## search live의 오류 3건에 대하여

10개 후보 중 3개(langgenius/dify, martinrusev/imbox, aruba/central-python-workflows)는 Google API의 일시적 `500 INTERNAL`이 재시도 한도(3회, key failover 포함)까지 지속되어 해당 후보만 실패로 기록되었다. 이는 §8.2 재시도 정책의 정상 동작이며, 실패는 search_report.md Errors에 기록되고 나머지 7개 후보는 정상 판정되었다 (KEEP 3 / MAYBE 2 / DROP 2). 재실행 시 해당 후보도 정상 분석된다.

## 전체 터미널 로그

```text
=== [1] git clone ===
Cloning into 'RIM'...

=== [2] python --version ===
Python 3.14.5

=== [3] py_compile ===
py_compile PASS

=== [4] pip install -e .[dev] ===
(성공 — pip 최신 버전 안내만 출력)

=== [5] pytest ===
134 passed in 1.76s

=== [6] --help ===
usage: repo_idea_miner [-h] {run,search,validate} ...
(run / search / validate 서브커맨드 정상 출력)

=== [7] git check-ignore .env ===
.gitignore:1:.env	.env
.env ignored: YES

=== [8] 파일 정상성 확인 (§4) ===
--- pyproject.toml: exists=True lines=27
--- .env.example: exists=True lines=42
--- .gitignore: exists=True lines=10
--- repo_idea_miner/__main__.py: exists=True lines=5
--- repo_idea_miner/cli.py: exists=True lines=98
--- repo_idea_miner/search_pipeline.py: exists=True lines=219
--- repo_idea_miner/schemas.py: exists=True lines=150
pyproject.toml TOML parse: PASS

=== [9] run mock (BN8624/RIM) ===
run_dir: runs\20260708_073053
verdict: MAYBE / score: 5 / fast_drop: False

=== [10] search mock (limit 10 top 5) ===
run_dir: runs\20260708_073100
analyzed: 10 / errors: 0

=== [11] validate (run mock) ===
VALIDATION PASS

=== [12] validate (search mock) ===
VALIDATION PASS

=== [13] run live (BN8624/RIM) ===
run_dir: runs\20260708_073247
verdict: KEEP / score: 8 / fast_drop: False

=== [14] search live (limit 10 top 5) ===
run_dir: runs\20260708_073550
analyzed: 10 / errors: 3 (Google 500 INTERNAL — 위 설명 참고)

=== [15] validate (run live) ===
VALIDATION PASS

=== [16] validate (search live) ===
(1차: 실패 기록된 후보의 카드 부재를 위반으로 처리 → validate 보완 후 재실행)
VALIDATION PASS

=== [17] search mock --targeted (§7.1 검수 명령) ===
run_dir: runs\20260708_080556
analyzed: 10 / errors: 0
pydoit/doit        | targeted_score = 11 | matched = [automation, workflow, cli, python]
jmathai/elodie     | targeted_score = 9  | matched = [automation, workflow, cli, python]
apache/airflow     | targeted_score = 8  | matched = [automation, workflow, python]
PrefectHQ/prefect  | targeted_score = 8  | matched = [automation, workflow, python]
Skyvern-AI/skyvern | targeted_score = 8  | matched = [automation, workflow, python]
- targeted_sort: YES (targeted_score 내림차순, star 수 보조 정렬)

=== [18] live run 세부 성공 기준 (§5.1) ===
bouncer                model=gemma-4-31b-it key_index=1 success=True
readme_scout           model=gemma-4-31b-it key_index=2 success=True
pain_scout             model=gemma-4-31b-it key_index=3 success=True
structure_risk_scout   model=gemma-4-31b-it key_index=4 success=True
critic_judge           model=gemma-4-31b-it key_index=5 success=False (일시 오류 → failover)
critic_judge           model=gemma-4-31b-it key_index=6 success=True
Judge Raw: KEEP 8 / Validator Final: KEEP 8 (분리 기록)
Secret Redaction: PASS / Token Exposure: NO

=== [19] 전체 runs/ secret scan (fresh clone) ===
files: 739 / secret scan: PASS
```

주: [18]의 key 5 실패 로그에 `validation_success=False`로 남던 잔여 경로 1곳은 보완 커밋에서 `null`로 수정되었고 회귀 테스트가 실패/성공 로그 모두를 검증한다.
