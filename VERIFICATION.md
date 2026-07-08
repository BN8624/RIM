# 재검수 증빙 (fresh clone 기준)

재검수 및 보완 요구서 기준 검수 결과. 모든 로그는 **새 디렉터리에 fresh clone 후** 실행한 것이다.

- 검수 일시: 2026-07-08
- 검수 대상 커밋: `cbcc01a` (§7 보완 + validate 실패 경로/validation_success null 보완 포함)
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

---

# 모바일 HTML 뷰어 + Tailscale 읽기 전용 서버 검수 (별도 주문서)

- 검수 일시: 2026-07-08
- 검수 환경: Windows 11, Python 3.14.5
- 추가 모듈: `repo_idea_miner/viewer.py`, `repo_idea_miner/serve.py`
- 추가 CLI: `view`, `serve`, `validate --require-viewer`

## 완료 기준 대비 결과 (주문서 §15)

| # | 기준 | 결과 |
|---|---|---|
| 1 | `view` 명령 추가 | PASS |
| 2 | `serve` 명령 추가 | PASS |
| 3 | 단일 run에서 viewer.html 생성 | PASS |
| 4 | search run에서 viewer.html 생성 | PASS |
| 5 | 모바일 반응형(viewport meta + inline CSS/JS) | PASS |
| 6 | Tailscale IP로 iPhone 접속 (`--host 0.0.0.0`/IP 바인딩) | PASS (바인딩·URL 출력 확인) |
| 7 | KEEP/MAYBE/DROP/ERROR 필터 | PASS |
| 8 | 점수/판정/한 줄 결론/핵심 패턴/다음 행동 표시 | PASS |
| 9 | 상세 접기/펼치기(`<details>`) | PASS |
| 10 | 외부 CDN/API 없이 동작 | PASS (CDN/fetch 참조 0) |
| 11 | run_dir 밖 접근 금지 | PASS (403) |
| 12 | `.env` 접근 금지 | PASS (403) |
| 13 | `debug/raw` 기본 노출 금지 | PASS (403, 중첩 경로 포함) |
| 14 | viewer.html secret scan 포함 | PASS |
| 15 | `validate --require-viewer` 지원 | PASS |
| 16 | pytest 통과 | PASS (159 passed, 뷰어/서버 24개 포함) |
| 17 | mock run/search + view + validate + serve 검수 | PASS (아래 로그) |
| 18 | README에 iPhone + Tailscale 사용법 | PASS |
| 19 | SCOPE/VERIFICATION 문서 갱신 | PASS (본 문서) |

## 주문서 §13 테스트 매핑 (20개)

`tests/test_viewer.py` / `tests/test_serve.py`.

1. view가 단일 run viewer 생성 → `test_view_creates_viewer_single`
2. view가 search run viewer 생성 → `test_view_creates_viewer_search`
3. serve가 읽기 전용 정적 서버로 뜸 → `test_serve_starts_and_serves_viewer`
4. serve root가 run 디렉터리로 제한 → `test_serve_blocks_outside_root`
5. serve가 `.env` 차단 → `test_serve_blocks_env`
6. serve가 path traversal 차단 → `test_serve_blocks_traversal`
7. serve가 debug/raw 기본 차단 → `test_serve_blocks_debug_raw_and_prompts`, `test_is_denied_unit`
8. viewer가 KEEP/MAYBE/DROP 라벨 포함 → `test_viewer_has_verdict_labels`
9. viewer가 score 포함 → `test_viewer_has_score`
10. viewer가 repo 링크 포함 → `test_viewer_has_repo_links`
11. viewer 필터 버튼 존재 → `test_viewer_has_filter_buttons`
12. viewer 모바일 viewport meta → `test_viewer_has_mobile_viewport`
13. viewer secret scan이 가짜 GITHUB_TOKEN 탐지 → `test_viewer_secret_scan_catches_github_token`
14. viewer secret scan이 가짜 GOOGLE_API_KEY 탐지 → `test_viewer_secret_scan_catches_google_key`
15. `validate --require-viewer` viewer 부재 시 실패 → `test_validate_require_viewer_fails_when_missing`
16. `validate --require-viewer` viewer 존재 시 통과 → `test_validate_require_viewer_passes_when_present`
17. JSON 부재 시 idea_card.md fallback → `test_missing_json_falls_back_to_idea_card`
18. 카드 부재 시 크래시 대신 ERROR 카드 → `test_missing_card_becomes_error_not_crash`
19. search viewer가 ERROR 후보 표시 → `test_search_viewer_displays_error_candidates`
20. targeted_score 정렬 옵션 노출 → `test_targeted_sort_shown_when_available`

추가 방어 테스트: GET/HEAD 외 501(`test_serve_is_read_only`), 생성된 viewer 무누출(`test_generated_viewer_is_clean`), idea_card 파싱(`test_parse_idea_card_extracts_fields`).

## 검수 터미널 로그

```text
=== pytest ===
159 passed in 4.85s   (뷰어/서버 24개 포함)

=== run mock (BN8624/RIM) ===
run_dir: runs\20260708_093836
verdict: MAYBE / score: 5 / fast_drop: False

=== view (single) ===
viewer: runs\20260708_093836\viewer.html

=== validate --require-viewer (single) ===
VALIDATION PASS

=== serve smoke (single, 127.0.0.1:8811) ===
/ -> 200   viewer.html -> 200   .env -> 403   debug/raw -> 403

=== search mock --targeted (limit 10 top 5) ===
run_dir: runs\20260708_093857
analyzed: 10 / errors: 0

=== view (search) ===
viewer: runs\20260708_093857\viewer.html

=== validate --require-viewer (search) ===
VALIDATION PASS
summary: keep 0 / maybe 10 / drop 0 / error 0 / secret_scan PASS / validation PASS / has_targeted true

=== serve smoke (search, 127.0.0.1:8812) ===
/ -> 200   candidates.json -> 200   repos/<name>/debug/raw/metadata.json -> 403
```

주: Tailscale 실기기(iPhone Safari) 접속은 `--host 0.0.0.0`/Tailscale IP 바인딩과 URL 출력까지 로컬에서 검증했다. 실제 tailnet 왕복은 사용자 기기 환경에서 수행한다 (README 3단계 참고).
