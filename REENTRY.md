# REENTRY — 다음 세션 재진입 요약

작성: 2026-07-10 (Structural Reset 진행 중). 현행 아키텍처 정본은 `PROJECT_CANON.md`(인덱스 `AI_INDEX.md`).
**진행 중인 큰 작업: RIM Structural Reset & Architecture Atlas** — 주문서는 루트의
`RIM Structural Reset & Architecture.md`(untracked, 절대 커밋 금지). 재진입 시 이 주문서와
`runs/_structural_reset/state.json`(gitignored 작업 상태)을 먼저 읽을 것.

## 1. 현재 상태

- BASE_HEAD `3363bb6`, **R0~R5 완료** HEAD `82366fc`, 전부 push됨, 워킹트리 clean(주문서 md만 untracked).
- **R5 완료**: CLI/Dashboard 분리(§15). cli.py 1034→235줄(parser/dispatch/exit code만,
  실행·출력은 cli_handlers.py HANDLERS registry — parser command 집합과 1:1 회귀 가드).
  challenge_dashboard.py 1848→1439줄(렌더링·route·POST만), read model은
  challenge_dashboard_data.py(SQL 조회·phase 요약 로더·preview 화이트리스트/traversal 차단),
  QA 종합 판정은 factory_summary.overall_qa_status 정본 1개 — presentation의 SQL/JSON 파싱 0을
  회귀 테스트가 고정. 보안 의미 보존(127.0.0.1 기본·escaping·secret 마스킹 테스트 PASS).
  **전체 pytest 983 PASS(257s)**. CANON-02·03·09 갱신. README는 사용자 명령 무변경이라 그대로.
- **R4 완료**: failure 의미 정본 factory_continue 수렴, import cycle 0, factory 계열 private
  cross-import 0, §14.5 stale queue verdict read 시 canonical 계산. CANON-02·05 갱신.
- **R3/R2/R1/R0 완료**: 제품 체인 정본화 / validation registry / run layout 정본 / flaky 근본 수정.
- #47/#54 closed loop 상태는 characterization 테스트가 고정(둘 다 HOLD_FOR_HUMAN, base hash PASS).
- 잔여 private cross-import 3건은 전부 miner 계열(§5.1 무변경 보존과 충돌, R6/R8 결정) — state.json notes.

## 2. 다음 작업 (R6부터, 주문서 §16~§18 순서)

1. **R6 dead code 제거**(주문서 §16) — 삭제 기준 7항목 전부 만족 시에만 삭제(runtime caller 0,
   CLI entry 0, dynamic import 0, compat 불필요, canon 비현역, 대체 구현·테스트 존재).
   삭제 전 읽기 전용 adversarial review. old/new 정본 중복 0, 임시 shim 0, 루트 md 5개 유지.
   miner 계열 private import 3건 처리 여부 결정. **완료 시 전체 pytest 필수(§9.2)**.
2. R6 후 R7 Architecture Atlas(§17) → R8 최종(3회 pytest+다섯 문서 갱신, §18).

## 3. 규칙 (주문서 요지)

- 루트 md는 정확히 5개 유지, 새 md 금지(작업 상태는 state.json에만).
- 원본 run 무손상·기존 CLI/DB/run 판독 보존·golden 의미 약화 금지(CANON-11).
- 구조 커밋마다 관련 CANON 섹션 동커밋 갱신. 테스트 실패 상태 커밋 금지.
- 전체 pytest는 R6/R8 완료 시점에만(작은 이동마다 반복 금지). 최종 3회 연속 PASS.
- 같은 실패 signature 2회면 slice 되돌리고 더 작게 재설계(§21).

## 4. 검증 명령

- `python -m pytest tests/test_structural_reset_characterization.py -q` (의미 보존 확인)
- `python -m pytest -q` (약 4분 17초)
- baseline 재생성: `python -c "from pathlib import Path; import json; from repo_idea_miner.architecture_scanner import build_baseline; print(json.dumps({k:v for k,v in build_baseline(Path('.')).items() if k not in ('modules','artifact_refs_by_module')}, ensure_ascii=False)[:800])"`
