# REENTRY — 다음 세션 재진입 요약

작성: 2026-07-10 (Structural Reset 진행 중). 현행 아키텍처 정본은 `PROJECT_CANON.md`(인덱스 `AI_INDEX.md`).
**진행 중인 큰 작업: RIM Structural Reset & Architecture Atlas** — 주문서는 루트의
`RIM Structural Reset & Architecture.md`(untracked, 절대 커밋 금지). 재진입 시 이 주문서와
`runs/_structural_reset/state.json`(gitignored 작업 상태)을 먼저 읽을 것.

## 1. 현재 상태

- BASE_HEAD `3363bb6`, **R0~R3 완료** HEAD `490e2f7`, 전부 push됨, 워킹트리 clean(주문서 md만 untracked).
- **R3 완료**: `factory_product_evidence.py` 정본 신설(§8.2 — viewer/replay 탐색·field evidence·
  protected hash·gate context·공통 IO, 구현 이동·의미 불변) + `run_judgment_desks` 공개 API(§8.1) +
  scanner 특성화를 재유입 방지 가드로 전환. **제품 체인 private cross-import 0**,
  **전체 pytest 979 PASS**(R3 게이트). CANON-02·06·07 동커밋 갱신.
- **R2 완료**: run kind 감지 정본화(`factory_run_layout.detect_run_kind`) + validator registry
  (`factory_validate.MARKER_VALIDATORS` — 선언 순서=검사 순서, core/continuation 공유). CANON-02·04·05·10 갱신.
- **R1 완료**: factory_run_layout.py 정본(resolve_artifact_root/resolve_run_target).
- **R0 완료**: architecture_scanner.py + baseline.json, flaky 근본 수정(.pyc stale bytecode), characterization.
- #47/#54 closed loop 상태는 characterization 테스트가 고정(둘 다 HOLD_FOR_HUMAN, base hash PASS).
- 잔여 private cross-import 10건(전부 R4 대상 repair/build 계열 + miner 계열)과 cycle 1건
  (factory_continue↔factory_queue)은 state.json notes에 목록 있음.

## 2. 다음 작업 (R4부터, 주문서 §14~§18 순서)

1. **R4 build/continuation/repair 수렴**(주문서 §14) — factory_pipeline/core_pipeline/continue/queue/
   spec_repair/anti_hardcode caller·contract 조사(증거 없이 삭제 금지, legacy active 명시),
   repair 결과·failure 의미 정본화, continue↔queue cycle 해소, repair 계열 private import 정리,
   stale queue 상태 회귀 fixture(§14.5). 완료 시 CANON-02·03·05·08 갱신.
2. R4 후 R5 CLI/Dashboard 분리 → R6 dead code → R7 Architecture Atlas → R8 최종(3회 pytest+문서).
- state.json notes의 private_imports_remaining_10이 R4의 작업 대상 목록이다. miner 계열 3건은
  §5.1 무변경 보존과 충돌 — R6/R8에서 결정.

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
