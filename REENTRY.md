# REENTRY — 다음 세션 재진입 요약

작성: 2026-07-10 (직전 커밋 5c6d849 기준). 이 문서는 최신 세션 종료 시점의 스냅샷이다.
이전 내용과 충돌하면 이 문서가 우선한다. 상세 이력은 git log와 `checklist.md` 참조.

## 1. 현재 상태

- pytest **893 passed** (알려진 부하성 flaky: `test_patch_repair_fixes_broken_build`, `test_build_review_recomputed_after_patch` — 격리 실행 시 통과).
- 워킹트리 clean, 전부 push됨 (main).
- **#47 (Mini-Comfy 노드 엔진, runs/factory_20260709_072220)**: green + REVIEW_READY + **PRODUCT_CANDIDATE**.
  Phase 2C-3까지 완료 — draft editor에서 만든 초안을 실제 runner로 실행/재실행하는 루프가 닫힘(product_loop_closed=true).
  검수 서버: `python product/draft_server.py --port 8799` (Tailscale 100.89.73.83:8799/product/viewer/index.html — 실행 기능은 이 브리지 서버로만 동작, 정적 8788로는 안 됨).
- **#54 (가상 파일 탐색기, run_id 13, runs/factory_20260710_021635)**: NEEDS_MORE_GEMMA_LOOP, continuation_base 살아있음.
  표현 계약 도입 후 runner↔golden 이벤트/summary **완전 일치**. 남은 실패는 값/노출 수준
  (golden에 root_node 키 부재, invariant 필드 미노출, scenario_003 error target 값).
  continuation 시도(runs/factory_20260710_023719)는 **DROP** — patch 실패 + anti_hardcode가
  viewer의 demo mock fallback(scenario_1)을 감지. base run은 무손상.

## 2. 이번 세션에서 완료한 것 (커밋 4개)

1. `b44931a` Phase 2C-3 Runner-backed Draft Execution — factory_draft_execution.py,
   `factory-draft-execution --run-dir|--run-id --dry-run|--apply`, 어댑터/브리지/실행 패널/실행 스모크.
2. `faecca1` factory-continue --run-dir 식별자 backfill 버그 수정
   (find_product_run_id_by_run_dir + validate 완화: base_run_dir도 식별자로 인정).
3. `5c6d849` **정답지 품질 개선** — core_contract에 `output_representation`(이벤트/summary 표현 계약) 필수화,
   `lint_golden_representation`(factory_core_gates)로 구현 전 기계 검사, 실패 시 NEEDS_SPEC_REPAIR 정직 중단.
   live #54 3차 빌드로 효과 실증.
4. 두 번째 도메인(#54) live 검증 — 하네스는 코드 수정 없이 전부 동작함을 확인.

## 3. 다음 권장 액션 (우선순위 순)

1. **anti-hardcode 검사 시점 비대칭 + viewer mock fallback 금지** (task chip 생성됨):
   빌드 게이트는 product/ 생성 전에 돌아 viewer를 스캔 안 하고, continuation 재실행은 스캔함 → 같은 산출물이
   빌드 PASS/continuation FAIL. 개선: product layer 생성 후 anti_hardcode 재실행(스캔 범위 정렬) +
   product layer 프롬프트에 mock/fallback 데이터 금지 규칙.
2. 그 후 **#54 재빌드 → green 시도**: 남은 실패가 spec repair 가능 부류라 2A queue → 2B-1 spec-repair-apply 경로 유효.
3. #47은 사용자 최종 검수 대기 — 원 주문서의 "드래그로 선 연결 캔버스"는 여전히 미구현(별도 결정 필요).

## 4. 중요 결정 (변경하지 말 것)

- summary는 하네스 표준상 **항상 문자열** (GoldenExpected.expected_summary: str). dict summary는 build 프롬프트로 교정.
- output_representation 미선언 run은 lint NOT_DECLARED로 관용 (기존 run 호환). 강제는 프롬프트/리뷰 데스크에서.
- spec repair §8: golden 기대값 훼손·comparison_mode 완화 금지 — 이 보호를 우회하는 자동화 금지.
- 2C-3 viewer JS는 `edge.from`/`ev.type`/`\.type\b`/`node.x`/`Math.random`/`Date.now` 리터럴 금지 (smoke가 감지).
- factory-continue는 가급적 `--run-id`로 실행 (--run-dir도 이제 backfill 되지만 DB 연동이 더 완전).

## 5. 오픈 이슈

- continuation queue가 green 승격된 run 5(#47)를 여전히 SPEC_REPAIR로 표시 (과거 verdict 기반 stale 분류) — 실해 없음, 정리 대상.
- evidence 추출/폴리시/에디터/2C-3 어댑터는 #47 그래프 도메인 특화 — 다른 도메인 run엔 domain-adaptive 필요.
- 다수 run 배치 자동화 미착수 (전 단계 단일 run 한정).
- runs/factory_20260710_011320(#54 1차)은 core_spec 반려로 Build 미진행 상태의 기록용 run.

## 6. 다시 하지 말 것

- #47 anti-hardcode/spec repair/폴리시/에디터/실행 재적용 — 이미 on-disk 완료 상태. 재검증은 반드시 tmp 복사에서.
- runs/factory_20260710_013956 찾기 — 식별자 누락 run은 삭제됐고 014234가 대체.
- `.cli` 직접 실행 — CLI 진입점은 `python -m repo_idea_miner`.
- .env의 GOOGLE_API_KEY_1~11(AQ. prefix)/GITHUB_TOKEN 출력·커밋 금지.

## 7. 검증 명령

- 전체: `python -m pytest -q` (약 3분 20초)
- run 검증: `python -m repo_idea_miner factory-validate <run_dir>`
- 대시보드: `python -m repo_idea_miner dashboard --host 0.0.0.0 --port 8787`
