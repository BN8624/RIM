# REENTRY — 다음 세션 재진입 요약

작성: 2026-07-10 (Structural Reset 진행 중). 현행 아키텍처 정본은 `PROJECT_CANON.md`(인덱스 `AI_INDEX.md`).
**진행 중인 큰 작업: RIM Structural Reset & Architecture Atlas** — 주문서는 루트의
`RIM Structural Reset & Architecture.md`(untracked, 절대 커밋 금지). 재진입 시 이 주문서와
`runs/_structural_reset/state.json`(gitignored 작업 상태)을 먼저 읽을 것.

## 1. 현재 상태

- BASE_HEAD `3363bb6`, **R0~R6 완료** HEAD `bb54552`, 전부 push됨, 워킹트리 clean(주문서 md만 untracked).
- **R6 완료**: dead 심볼 6건 삭제(전수 참조 스캔 — errors 예외 3종, format_verdict_desc,
  queue.SPEC_REPAIR_REVIEW_RESULTS, review.FITNESS_GRADES) + 중복 상수 정본 수렴
  (FROZEN_FILES/PREFIXES→factory_frozen, validate.LANES→continue, validate.MIN_SRC_FILES→gates).
  의미 다른 동명(2C-2/2C-3 check_*, viewer.detect_run_kind, JSON_RULES 3본)은 보존.
  **miner 3건 private cross-import는 §5.1 보존 우선 의도적 예외 확정**(CANON-11 기록,
  R7 architecture-check에서 allowlist). 임시 shim 0, 테스트 삭제 0.
  **전체 pytest 983 PASS(247s)**. CANON-02·11 갱신.
- **R5 완료**: CLI/Dashboard 분리 — cli.py는 parser/dispatch만(실행은 cli_handlers HANDLERS),
  dashboard는 렌더링·HTTP만(read model은 challenge_dashboard_data, QA 종합 판정은
  factory_summary.overall_qa_status). CANON-02·03·09 갱신.
- **R4~R0 완료**: failure 의미 정본/cycle 0 · 제품 체인 정본화 · validation registry ·
  run layout 정본 · flaky 근본 수정.
- #47/#54 closed loop 상태는 characterization 테스트가 고정(둘 다 HOLD_FOR_HUMAN, base hash PASS).

## 2. 다음 작업 (R7부터, 주문서 §17~§18 순서)

1. **R7 Architecture Atlas**(주문서 §17) — architecture/(manifest.toml, atlas.schema.json,
   atlas.json, index.html — 새 md 금지). scanner는 architecture_scanner.py 확장(재작성 금지).
   CLI: architecture-build/check/summary(+선택 serve, 새 웹 framework 금지). 결정론(§17.9
   byte-identical), structural fingerprint(§17.10), check 20항목(§17.11 — private import는
   miner 3건 allowlist, root md whitelist는 git tracked 기준으로 구현해 untracked 주문서와
   충돌 방지). 모바일 360px/다크모드/외부 CDN 0(§17.8). 테스트 §17.13.
   완료 시 CANON-12 추가 + AI_INDEX 라우팅 + README Atlas 사용법(같은 commit).
2. R7 후 R8 최종(§18) — pytest 3회 연속, CLI smoke, 기존 run 회귀, #47/#54, 다섯 문서 전면
   정합, checklist에 완료 섹션 1개 추가, 최종 보고(응답으로만).

## 3. 규칙 (주문서 요지)

- 루트 md는 정확히 5개 유지, 새 md 금지(작업 상태는 state.json에만).
- 원본 run 무손상·기존 CLI/DB/run 판독 보존·golden 의미 약화 금지(CANON-11).
- 구조 커밋마다 관련 CANON 섹션 동커밋 갱신. 테스트 실패 상태 커밋 금지.
- 전체 pytest는 R8 완료 시점(3회 연속 PASS). 작은 이동마다 반복 금지.
- 같은 실패 signature 2회면 slice 되돌리고 더 작게 재설계(§21).

## 4. 검증 명령

- `python -m pytest tests/test_structural_reset_characterization.py -q` (의미 보존 확인)
- `python -m pytest -q` (약 4분 17초)
- baseline 재생성: `python -c "from pathlib import Path; import json; from repo_idea_miner.architecture_scanner import build_baseline; print(json.dumps({k:v for k,v in build_baseline(Path('.')).items() if k not in ('modules','artifact_refs_by_module')}, ensure_ascii=False)[:800])"`
