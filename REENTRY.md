# REENTRY — 다음 세션 재진입 요약

작성: 2026-07-10 (직전 커밋 bfea041 기준). 이 문서는 최신 세션 종료 시점의 스냅샷이다.
이전 내용과 충돌하면 이 문서가 우선한다. 상세 이력은 git log와 `checklist.md` 참조.
현행 아키텍처 정본은 `PROJECT_CANON.md`(인덱스 `AI_INDEX.md`) — 이 문서는 세션 상태만 담는다.

## 1. 현재 상태

- pytest **962개** — 반복 3회 중 1회 전부 통과, 2회는 알려진 flaky 2종만 실패
  (`test_patch_repair_fixes_broken_build`, `test_build_review_recomputed_after_patch`,
  patch_attempts=2 시그니처. 격리 5회 반복에서도 1회 실패 — 부하 아닌 진짜 비결정, 원인 조사 task chip 생성됨).
- 워킹트리 clean, 전부 push됨 (main).
- **Phase 2D-1 Closed Product Loop 완료** — `factory-product-loop --execute`가 judge→lane 선택→child run 실행→재검증 루프를 돈다.
  base run은 항상 무손상, gate는 매 verify마다 temp copy에서 재실행, 예산 iter 4 / lane 2 / high-risk 1 / 무진전 2 (규칙 전문: CANON-07).
- **#47 (Mini-Comfy, runs/factory_20260709_072220)**: closed loop 판정 = acceptance 14/14 PASS·probe 전항목 PASS인데
  judge가 INTERACTION_CANDIDATE / RUNNER_BACKED_EXECUTION_REQUIRED 정직 판정 → 해당 lane은 사람 승인 필수 정책이라
  **HOLD_FOR_HUMAN** (loop_20260710_134033, hold packet에 단일 질문). base hash 101파일 불변.
- **#54 (가상 파일 탐색기, run 13, runs/factory_20260710_021635)**: closed loop이 evidence ladder enforcement로
  CORE_PATCH lane을 골라 child(runs/factory_20260710_052415)에서 continuation 실행 → gates 4/7·requires_spec_repair=true로
  정직 FAILED → high-risk 예산 소진 → **HOLD_FOR_HUMAN** (loop_20260710_141947). base hash PASS.
  남은 실체: golden root_node/target_id spec repair + viewer demo mock fallback(anti_hardcode high).

## 2. 이번 세션에서 완료한 것 (커밋 9개, 796096f~bfea041)

1. `796096f` P0: anti-hardcode 스캔 시점 통일(build도 product 생성 후 재실행) + mock fallback 정적 검출 + representation strict lint(schema v2).
2. `1fbd04b` 도메인 중립 Capability Profile + Fresh Probe(성공 2·실패 1·revise 재실행 변화).
3. `87b0f20` Lane Executor Registry(9 lane) + Closed Loop Orchestrator + Acceptance(14검사)/Progress vector.
4. `5633226`~`c0be4f5` CLI --execute/--output-dir, 대시보드 카드/패널, validate marker, judge desk 경량화(include_order=False), gate temp copy 재실행.
5. `ddb9431` **evidence ladder enforcement**: live Gemma가 fresh gate 실패에도 soft gap(INTERACTION_UI)을 고르는 오분류 실측 →
   hard fact rung 5종(EVIDENCE_INSUFFICIENT/ARCHIVE/SPEC_REPAIR/CORE_PATCH/RUNNER_PATCH)은 deterministic ladder가
   live 판정을 override(gap_override 기록), hard rung lane은 GAP_TO_LANE 고정이라 live lane desk 생략.
6. `bfea041` fresh gate rerun이 evidence_sufficient의 gate 문맥 조건 충족(기록 파일 없는 run의 EVIDENCE_INSUFFICIENT 누수 차단).
7. Case A(#47)·Case B(#54) live closed loop 실측 — 위 §1 결과.

## 3. 다음 권장 액션 (우선순위 순)

1. **#47 hold packet 응답**: RUNNER_BACKED_DRAFT_EXECUTION lane을 사람 승인으로 진행할지 결정
   (2C-3 산출물은 이미 있으므로 loop 안 재실행 vs 현재 상태 검수 종결).
2. **#54 hold packet 응답**: spec repair(golden root_node/target_id — 2B-1 §8이 막는 부류라 사람 판단 필요) +
   viewer mock fallback 제거 후 loop 재실행.
3. lane 실패에서 발견된 requires_spec_repair를 다음 iteration judge에 전달하는 escalation은 **계획 밖** —
   원하면 CANON-07 규칙 갱신부터(high-risk 예산 1과 함께 설계 필요).
4. flaky 근본 원인 조사 (task chip: patch_attempts=2).

## 4. 중요 결정 (변경하지 말 것)

- closed loop은 원본 base run을 절대 수정하지 않는다 — apply류 옵션 자체가 없음 (CANON-07).
- gate/probe는 기록 report를 재사용하지 않고 매번 재실행 — 관측이 서술을 이긴다 (CANON-07).
- hard fact rung의 gap/lane은 deterministic (live desk 판정 override — CANON-07). soft rung(viewer/interaction/UX)은 Gemma 판정 존중.
- summary는 하네스 표준상 **항상 문자열**. spec repair §8 보호(CANON-05) 우회 자동화 금지.
- viewer JS는 `edge.from`/`ev.type`/`\.type\b`/`node.x`/`Math.random`/`Date.now` 리터럴 금지 (smoke가 감지).

## 5. 오픈 이슈

- CORE_PATCH→SPEC_REPAIR escalation 없음 + high-risk 예산 1 → hard lane 연쇄는 한 loop에서 불가(계획대로 HOLD).
- UX_POLISH lane은 stub(정직 BLOCKED) — live 수요 확인 전 구현 연기.
- continuation queue가 green 승격된 run 5(#47)를 여전히 SPEC_REPAIR로 표시(stale 분류) — 실해 없음.
- 다수 run 배치 자동화 미착수 — 두 도메인이 같은 orchestrator를 통과하기 전에는 시작하지 않기로 했고, 이제 통과함(둘 다 정직 HOLD, CANON-07).

## 6. 다시 하지 말 것

- #47/#54 base run 직접 수정 — 재검증은 반드시 tmp 복사 또는 closed loop child에서.
- `.cli` 직접 실행 — CLI 진입점은 `python -m repo_idea_miner`.
- .env의 GOOGLE_API_KEY_1~11(AQ. prefix)/GITHUB_TOKEN 출력·커밋 금지.

## 7. 검증 명령

- 전체: `python -m pytest -q` (약 4분 15초)
- run 검증: `python -m repo_idea_miner factory-validate <run_dir>`
- closed loop: `python -m repo_idea_miner factory-product-loop --run-dir <dir> --mode live --execute`
- 대시보드: `python -m repo_idea_miner dashboard --host 0.0.0.0 --port 8787`
