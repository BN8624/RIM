# REENTRY

HEAD:
- commit: (A3 commit — atlas schema V2)
- branch: main
- clean: true (untracked order docs only — never commit them)

SYSTEM_STATUS:
- tests: full suite PASS at 7fce157 (1001 passed, pre-A3); after A3 targeted 50 PASS
  (architecture atlas/scanner/cli/dependency), full suite NOT re-run after A3
- architecture_check: PASS (atlas schema V2, build byte-identical x2)
- known_flaky: []

RECENT_SEMANTIC_CHANGES:
- AI-Only Atlas reset in progress (order doc: root `RIM AI-Only Architecture Atlas & Do.md`)
- A1 done: no Atlas HTML/renderer, no architecture-serve/summary CLI
- A2 done: root markdown = 4 (checklist.md deleted, git history only), docs rewritten AI-only
- A3 done: atlas.json schema V2 — repository block(head/snapshot/fingerprint/diff),
  core symbol index (AST line ranges + signatures), 16 canonical routes, artifacts with
  role+provenance (PRODUCES/CONSUMES/LITERAL_REFERENCE; MANIFEST/AST_IO_CALL/AST_STRING_LITERAL),
  10 contracts, 11 invariants, document_routes from AI_INDEX; manifest.toml schema 2;
  [[pipeline]] removed (routes supersede)

OPEN_BLOCKERS:
- id: ai_only_atlas_A4_A6
  state: pending (A0~A3 done)
  evidence: runs/_ai_only_atlas/state.json (detailed per-stage plan) + order doc at repo root
  next_action: A4 architecture-context CLI (+ add architecture_context route to manifest)
  → A5 check 22 items + 8 task fixtures → A6 regression + final report
- id: hold_54
  state: waiting_human
  evidence: runs/factory_20260710_021635/review/phase2d1/loop_20260710_141947/hold_for_human_packet.json
  next_action: human decides spec repair (golden root_node/target_id) + viewer mock fallback removal
- id: hold_47
  state: waiting_human
  evidence: re-derived evidence = PRODUCT_CANDIDATE, no gap (post d84c052)
  next_action: human final review/release decision; rerun loop if a fresh record is wanted

NEXT_ACTIONS:
1. A4: architecture-context CLI (selectors --canon/--route/--module/--symbol/--cli/--artifact/--changed,
   --impact=direct_static_impact, --compact, JSON deterministic; then README/CANON-12 QUERY 정합
   + architecture_context route 17번째로 추가)
2. A5: architecture-check 22 hard failures + warnings(doc size) + 8 representative AI task fixtures
3. A6: build×2 byte-identical, full pytest, runtime UI regression, final report (response only)

DO_NOT_REPEAT:
- do not commit the two untracked root order docs
- do not re-add human documentation, checklist, or Atlas HTML/serve/summary
- do not touch #47/#54 base runs on disk (tmp copies only)
- escalation (lane failure → next iteration judge) is a known deferred design, not a bug
- LITERAL_REFERENCE artifacts stay non-promoted (§13) — do not upgrade them without AST/manifest proof

VERIFY:
- python -m repo_idea_miner architecture-check
- python -m repo_idea_miner architecture-build   # rerun twice → zero diff expected
- python -m pytest tests/test_architecture_atlas.py tests/test_architecture_scanner.py -q
- python -m pytest -q
