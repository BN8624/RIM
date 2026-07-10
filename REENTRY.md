# REENTRY — 다음 세션 재진입 요약

작성: 2026-07-10 (Structural Reset 진행 중). 현행 아키텍처 정본은 `PROJECT_CANON.md`(인덱스 `AI_INDEX.md`).
**진행 중인 큰 작업: RIM Structural Reset & Architecture Atlas** — 주문서는 루트의
`RIM Structural Reset & Architecture.md`(untracked, 절대 커밋 금지). 재진입 시 이 주문서와
`runs/_structural_reset/state.json`(gitignored 작업 상태)을 먼저 읽을 것.

## 1. 현재 상태

- BASE_HEAD `3363bb6`, **R0+R1+R2 완료** HEAD `cb4c09f`, 전부 push됨, 워킹트리 clean(주문서 md만 untracked).
- **R2 완료**: run kind 감지 정본화(`factory_run_layout.detect_run_kind`/`RUN_KIND_*` — e8582e7) +
  validator registry(`factory_validate.MARKER_VALIDATORS` 10종 선언, 선언 순서=검사 순서,
  core/continuation 공유 — cb4c09f). CheckResult 내부 공통 결과 + render_problems 호환 렌더러,
  secret scan 통합. phase append 체인 중복 제거. **전체 pytest 979 PASS**(R2 게이트).
  CANON-02·04·05·10 동커밋 갱신(CANON-10의 stale flaky 기재 정정 포함).
- **R1 완료**: factory_run_layout.py 정본(resolve_artifact_root — §8.3 child 전체 복제 제거 / resolve_run_target).
- **R0 완료**: architecture_scanner.py + baseline.json, flaky 근본 수정(.pyc stale bytecode —
  PYTHONDONTWRITEBYTECODE=1), characterization 6종.
- #47/#54 closed loop 상태는 characterization 테스트가 고정(둘 다 HOLD_FOR_HUMAN, base hash PASS).

## 2. 다음 작업 (R3부터, 주문서 §13~§18 순서)

1. **R3 Product Judgment/Closed Loop 정본화**(주문서 §13) — factory_loop_executor의
   factory_product_loop private import 6종(§8.1) 제거 → 공개 Product Judgment API,
   factory_review private helper 의존(§8.2) 정리, protected hash 정본 1개,
   production private cross-import 0. 완료 시 전체 pytest+adversarial review+CANON-06·07·11 갱신.
2. R3 후 R4 build/continuation 수렴(+stale queue fixture §14.5) → R5 CLI/Dashboard 분리
   → R6 dead code → R7 Architecture Atlas → R8 최종(3회 pytest+문서).
- baseline의 private_cross_imports/import_cycles 목록이 R3·R4의 작업 대상 목록이다.

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
