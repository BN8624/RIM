# REENTRY

HEAD_SOURCE:
- command: git rev-parse HEAD
- origin_command: git rev-parse origin/main
- status_command: git status --porcelain=v1
- rule: Git output is authoritative; this file does not store a self-referential HEAD hash.

STATE_SNAPSHOT:
- reflects architecture and behavior as of this document's parent state
- branch: main

SYSTEM_STATUS:
- tests: full suite PASS at A7; architecture-build 연속 2회 byte-identical;
  dashboard smoke(/, /products 200) PASS at A6
- architecture_check: PASS + WARN 채널 (literal-only artifacts 집계, route 미선언 CLI,
  AI_INDEX component query primary 초과 — 모두 §17.2 비차단)
- known_flaky: []

RECENT_SEMANTIC_CHANGES:
- A1 done: no Atlas HTML/renderer, no architecture-serve/summary CLI
- A2 done: root markdown = 4 (checklist.md deleted, git history only), docs rewritten AI-only
- A3 done: atlas.json schema V2 — repository block(head/snapshot/fingerprint/diff),
  core symbol index (AST line ranges + signatures), canonical routes, artifacts with
  role+provenance (PRODUCES/CONSUMES/LITERAL_REFERENCE; MANIFEST/AST_IO_CALL/AST_STRING_LITERAL),
  10 contracts, 11 invariants, document_routes from AI_INDEX; manifest.toml schema 2;
  [[pipeline]] removed (routes supersede)
- A4 done: architecture-context CLI — selectors --canon/--component/--route/--module/--symbol/
  --cli/--artifact/--changed (multiple), --impact=direct_static_impact (static 1-hop only),
  --compact line format, deterministic JSON; read_first symbol line ranges; LITERAL_REFERENCE
  excluded by default; do_not_modify from manifest [rules.do_not_modify]; route 17
  (architecture_context) added; README CONTEXT COMMAND = python -m form

- A5 done: check hard 항목 확장(README bootstrap 구조/REENTRY 필수 섹션/serve·summary CLI 부재/
  사람용 Atlas 토큰/AI_INDEX ATLAS_QUERY 해석 검증/contract owner/이중 빌드 결정론) + §17.2
  warning 7종·§18 문서 크기(비차단 채널); 대표 AI task fixture 8종(tests/fixtures/ai_tasks)
  recall 100% 테스트; atlas↔context import cycle 해소(공유 상수·load_manifest를 scanner로,
  context는 builder 미import — live fingerprint는 handler가 주입)

- A6 done: full pytest PASS, build×2 byte-identical, dashboard smoke, tracked md=root 4,
  HTML/serve/summary 부재 — AI-Only Atlas & Documentation Reset 마감

- A7 done: --changed 변경 탐지 정본을 `git status --porcelain=v1 -z`로 교체 (A7 주문서 §5.2/§7)
  — untracked 포함, NUL 구분(공백·한글 path 안전), rename old_path 소비;
  scanner: collect_workspace_changes/_classify_xy(CONFLICTED>RENAMED>COPIED>DELETED>ADDED>
  TYPE_CHANGED>MODIFIED)/workspace_markdown_problems(untracked 루트·소스 md = AI 문맥 오염);
  context: classify_changes 순수 함수(known/pending_build/deleted/rename/test/governance),
  UNKNOWN_PENDING_BUILD warning+component, impact.changed 스키마 개편(changed_files 원본,
  deleted_modules[previous_component/importers/possible_broken_routes·contracts],
  tests_to_run/changed_tests/related_canon_ids, atlas_rebuild_required=pending∨deleted∨fp,
  document_update_required=governance∨fp); _changed_py_stems 삭제

OPEN_BLOCKERS:
- id: hold_54
  state: waiting_human
  evidence: runs/factory_20260710_021635/review/phase2d1/loop_20260710_141947/hold_for_human_packet.json
  next_action: human decides spec repair (golden root_node/target_id) + viewer mock fallback removal
- id: hold_47
  state: waiting_human
  evidence: re-derived evidence = PRODUCT_CANDIDATE, no gap (post d84c052)
  next_action: human final review/release decision; rerun loop if a fresh record is wanted

NEXT_ACTIONS:
1. hold_54 / hold_47 인간 결정 대기 (아래 blocker 참조) — AI 측 남은 자동 작업 없음
2. deferred: 대형 파일 분해 후보(factory_validate/challenge_dashboard/factory_product_loop §21),
   escalation 설계, literal-only artifact 185개의 실증 승격은 필요 시 별도 주문

DO_NOT_REPEAT:
- do not keep untracked markdown in repo root or source paths (architecture-check hard failure)
- do not put a static current-HEAD hash back into this file (HEAD_SOURCE rule)
- do not re-add human documentation, checklist, or Atlas HTML/serve/summary
- do not touch #47/#54 base runs on disk (tmp copies only)
- escalation (lane failure → next iteration judge) is a known deferred design, not a bug
- LITERAL_REFERENCE artifacts stay non-promoted (§13) — do not upgrade them without AST/manifest proof

VERIFY:
- python -m repo_idea_miner architecture-check
- python -m repo_idea_miner architecture-build   # rerun twice → zero diff expected
- python -m pytest tests/test_architecture_atlas.py tests/test_architecture_scanner.py tests/test_architecture_context.py -q
- python -m pytest -q
