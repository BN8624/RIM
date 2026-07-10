# REENTRY — 다음 세션 재진입 요약

작성: 2026-07-10 (Structural Reset 진행 중). 현행 아키텍처 정본은 `PROJECT_CANON.md`(인덱스 `AI_INDEX.md`).
**진행 중인 큰 작업: RIM Structural Reset & Architecture Atlas** — 주문서는 루트의
`RIM Structural Reset & Architecture.md`(untracked, 절대 커밋 금지). 재진입 시 이 주문서와
`runs/_structural_reset/state.json`(gitignored 작업 상태)을 먼저 읽을 것.

## 1. 현재 상태

- BASE_HEAD `3363bb6`, **R0~R4 완료** HEAD `aa7dd7f`, 전부 push됨, 워킹트리 clean(주문서 md만 untracked).
- **R4 완료**: failure 의미 정본을 factory_continue로 수렴(§14.4 — assess_failure_patch_safety+
  PATCH_SAFE/CONDITIONAL/NEVER+proposal/review 빌더, queue·2B가 import), **import cycle 0**,
  compute_build_review/src_code_files/clip 공개화 + spec_repair·anti_hardcode IO를
  factory_product_evidence로 수렴 → **factory 계열 private cross-import 0**.
  §14.5 stale queue verdict는 read 시 canonical 계산(reconcile command 없음)+회귀 fixture 2종.
  targeted 292 PASS(repair 185+legacy 60+queue 47). CANON-02·05 갱신.
- **R3 완료**: factory_product_evidence.py 정본(§8.2) + run_judgment_desks 공개 API(§8.1).
  제품 체인 private import 0, 전체 pytest 979 PASS. CANON-02·06·07 갱신.
- **R2 완료**: detect_run_kind 정본 + MARKER_VALIDATORS registry. CANON-02·04·05·10 갱신.
- **R1/R0 완료**: run layout 정본 / scanner+baseline+flaky 근본 수정+characterization.
- #47/#54 closed loop 상태는 characterization 테스트가 고정(둘 다 HOLD_FOR_HUMAN, base hash PASS).
- 잔여 private cross-import 3건은 전부 miner 계열(§5.1 무변경 보존과 충돌, R6/R8 결정) — state.json notes.

## 2. 다음 작업 (R5부터, 주문서 §15~§18 순서)

1. **R5 CLI/Dashboard 분리**(주문서 §15) — cli.py는 parser/registration/dispatch/exit code만,
   business logic은 handler·정본 service로. challenge_dashboard.py에서 read model/판정 분리
   (presentation이 stage/gap/lane 독자 계산 금지). CLI command 회귀 테스트. 보안 유지.
   **완료 시 전체 pytest 필수(§9.2)**, CANON-03·09 갱신.
2. R5 후 R6 dead code → R7 Architecture Atlas → R8 최종(3회 pytest+문서).

## 3. 규칙 (주문서 요지)

- 루트 md는 정확히 5개 유지, 새 md 금지(작업 상태는 state.json에만).
- 원본 run 무손상·기존 CLI/DB/run 판독 보존·golden 의미 약화 금지(CANON-11).
- 구조 커밋마다 관련 CANON 섹션 동커밋 갱신. 테스트 실패 상태 커밋 금지.
- 전체 pytest는 R2/R3/R5/R6/R8 완료 시점에만(작은 이동마다 반복 금지). 최종 3회 연속 PASS.
- 같은 실패 signature 2회면 slice 되돌리고 더 작게 재설계(§21).

## 4. 검증 명령

- `python -m pytest tests/test_structural_reset_characterization.py -q` (의미 보존 확인)
- `python -m pytest -q` (약 4분 15초)
- baseline 재생성: `python -c "from pathlib import Path; import json; from repo_idea_miner.architecture_scanner import build_baseline; print(json.dumps({k:v for k,v in build_baseline(Path('.')).items() if k not in ('modules','artifact_refs_by_module')}, ensure_ascii=False)[:800])"`
