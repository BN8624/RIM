# PROJECT_CANON — semantic contracts

AI 전용 의미 정본. 코드에서 자동 추출 가능한 사실(module 목록/CLI 목록/LOC)은 담지 않는다 —
그것은 `architecture/atlas.json`이 정본이다. 여기는 불변 규칙·계약·소유권 경계·금지 변경만 둔다.
모든 섹션은 같은 형식: SCOPE / CANONICAL_ROUTES / INVARIANTS / CONTRACTS / FORBIDDEN /
COMPATIBILITY / NOTES / QUERY. 아키텍처가 바뀌는 커밋은 해당 섹션을 같은 커밋에서 갱신한다.

## CANON-01 Repository Identity

SCOPE:
- repository policy, three layers (Miner / Challenge / Product Factory), LLM binding

CANONICAL_ROUTES:
- miner_direct
- miner_search

INVARIANTS:
- INV-MINER-CORE-PRESERVED

CONTRACTS:
- none

FORBIDDEN:
- branch/PR/worktree workflows (main only), force push, rebase, amending pushed commits
- running `.cli` directly as entrypoint (no output — `__main__.py` only)

COMPATIBILITY:
- Miner v1.0 CLI behavior and outputs remain unchanged

NOTES:
- LLM = Gemma `gemma-4-31b-it` fixed via `.env RIM_GEMMA_MODEL`, Google AI Studio 11-key pool
- commit per semantic unit, push immediately

QUERY:
- architecture-context --canon CANON-01

## CANON-02 Ownership Boundaries

SCOPE:
- which component may modify which modules

CANONICAL_ROUTES:
- challenge_single
- challenge_daemon

INVARIANTS:
- INV-MINER-CORE-PRESERVED

CONTRACTS:
- none

FORBIDDEN:
- modifying `pipeline.py` / `search_pipeline.py` / `schemas.py` (Miner core, frozen since v1.0)
- Challenge work touching files outside `challenge_*.py`
- re-implementing owned canonical helpers elsewhere (run resolver, product evidence, patch-safety)

COMPATIBILITY:
- miner-family private cross-imports (3 entries) are a deliberate allowlisted exception —
  publicizing/duplicating/wrapping them all conflict with preservation; keep as-is

NOTES:
- single-owner canonical symbols: run layout → `factory_run_layout`
  (resolve_artifact_root / resolve_run_target / detect_run_kind), product evidence →
  `factory_product_evidence`, failure patch-safety → `factory_continue`,
  QA aggregate → `factory_summary.overall_qa_status`

QUERY:
- architecture-context --canon CANON-02

## CANON-03 External CLI Contracts

SCOPE:
- CLI surface stability and dispatch structure

CANONICAL_ROUTES:
- all routes declare their `cli` field in the Atlas

INVARIANTS:
- none

CONTRACTS:
- none

FORBIDDEN:
- business logic in `cli.py` (parser/dispatch/exit code only — execution lives in
  `cli_handlers.HANDLERS`, 1:1 with parser commands, regression-tested)
- removing or renaming existing commands/options without a compatibility decision

COMPATIBILITY:
- destructive commands default to `--dry-run`; `--apply`/`--execute` must be explicit

NOTES:
- exact command/option facts: atlas.json `cli` (do not duplicate the list here)

QUERY:
- architecture-context --canon CANON-03

## CANON-04 Core Build Contracts

SCOPE:
- 7-stage core harness (`factory-build`), gates, verdicts

CANONICAL_ROUTES:
- legacy_factory
- core_factory_build

INVARIANTS:
- INV-SUMMARY-STRING
- INV-MOCK-FALLBACK-NOT-PRODUCT
- INV-FRESH-VERIFICATION

CONTRACTS:
- core_contract
- output_representation
- golden_representation
- runner_result

FORBIDDEN:
- trusting recorded gate reports as if re-executed (gates re-run; validate only checks records)
- presenting demo/mock/fallback data as real execution results
- promoting green_base without: all 7 gates PASS + product layer PASS + hardcode low/medium

COMPATIBILITY:
- runs with harness_schema_version < 2 keep lenient representation lint (NOT_DECLARED allowed)

NOTES:
- gate set: core_contract / runner / scenario_replay / golden_output / state_invariant /
  determinism / anti_hardcode (re-run after product layer too)
- verdict ladder: DROP < NEEDS_MORE_GEMMA_LOOP < SPEC_REPAIR_REQUIRED < RUNS_BUT_WEAK <
  REVIEW_READY < PROMOTE_TO_CODEX
- runner stdout must be ASCII-safe JSON (Windows cp949 pipe)
- expected_summary is always a string at harness level

QUERY:
- architecture-context --canon CANON-04

## CANON-05 Continuation & Repair Contracts

SCOPE:
- continuation delta loop, queue routing, single-run spec/anti-hardcode repair

CANONICAL_ROUTES:
- continuation
- spec_repair
- anti_hardcode_repair

INVARIANTS:
- INV-SPEC-REPAIR-PROTECTION
- INV-PROTECTED-HASH

CONTRACTS:
- continuation_summary
- repair_execution_result

FORBIDDEN:
- continuation directly editing golden/contract (must exit as SPEC_REPAIR_REQUIRED)
- spec-repair apply that damages existing golden expectations, deletes fields, adds
  out-of-contract fields, or relaxes comparison_mode (§8 — blocked, human decision)
- queue execute outside the patch lane (limit 1); spec-repair lane is proposal-only
- rewriting stale DB verdicts (queue recomputes canonical state at read time instead)

COMPATIBILITY:
- pre-2A continuation runs stay readable (inferred_lane)

NOTES:
- failure patch-safety canonical source: `factory_continue.assess_failure_patch_safety`
- frozen hash guard covers golden/fixtures/contract; `fixtures/_variants/` excluded (gate scratch)
- out-of-scope changes after apply trigger automatic rollback
- scenario-level partial spec repair: each scenario gets one decision — APPLIED /
  DEFERRED_CORE_DEPENDENCY / DEFERRED_AMBIGUOUS / UNCHANGED_VALID (recorded in
  `spec_repair_scenario_decisions.json`); blocked scenarios are preserved as deferred,
  and green promotion is forbidden while any deferred scenario remains
- an empty repair_plan.steps is honest when requires_spec_repair=true (spec-only failures)
- a child copy inherits the parent's apply report; provenance via `child_run_origin.json`

QUERY:
- architecture-context --canon CANON-05

## CANON-06 Productization Contracts

SCOPE:
- 2C chain: review → polish → editor → draft execution (order fixed, each gates the next)

CANONICAL_ROUTES:
- productization_chain

INVARIANTS:
- INV-PROTECTED-HASH
- INV-FRESH-VERIFICATION

CONTRACTS:
- product_evidence

FORBIDDEN:
- polish adding authoring UI (result viewers legitimately stay NEEDS_PRODUCT_POLISH)
- editor creating node types not extracted from contract/replay (extraction failure = CANNOT_EDIT)
- viewer JS containing literals: `edge.from`, `ev.type`, `.type` property access,
  `node.x`, `Math.random`, `Date.now` (smoke detects these)
- injecting scripts via `re.sub` with string replacement (backslash-escape bug — use
  function replacement or `str.replace`)

COMPATIBILITY:
- each phase writes to `review/phase2cX/`; validate is a no-op when the marker is absent

NOTES:
- 2C-3 closes the loop: edit → validate → execute (bridge server → runner) → observe →
  revise → re-run, all proven by execution smoke; viewer artifacts must pass `node --check`
- human gate: `review/phase2c1/user_review_decision.md` required before 2C-2
- generic interaction contract (`factory_interaction_ui`): domain artifact →
  interaction contract adapter → generic INTERACTION_UI executor → runtime UI →
  interaction evidence → validator. Domain meaning never lives in the core executor —
  the graph domain routes to the legacy 2C-2 adapter by artifact shape (state has
  nodes+edges), everything else gets the action-console executor; no challenge/product
  branches. The contract reuses existing action/state/runner contracts and the fixture
  as scenario template (do not invent required fields)
- interaction runtime fallback policy: valid artifact → real UI; missing/invalid/
  unsupported → explicit state; mock fixtures only on test/dev paths; production
  runtime never shows automatic mock success
- interaction evidence ownership: `review/interaction_ui/interaction_evidence.json` +
  `interaction_ui_report.json` are written by the executor's runner-backed smoke; the
  loop accepts them as authoring/loop evidence only when applied=true (priority after
  the 2C-3 execution report), and the validator blocks smoke_pass overclaims
- generic runner-backed draft execution (`factory_runner_backed_execution`): draft
  (interaction contract) → canonical execution contract (execution_id/draft_ref/
  runner_ref/execution_kind/input_payload/initial_state/allowed_actions/expected_outputs/
  side_effect_policy/timeout_policy/validation_rules/evidence_requirements — reuses
  existing structures, no invented fields) → temp-copy runner execution via
  `run_scenario_once` → side effect manifest → validation → fresh evidence. The graph
  domain routes to the legacy 2C-3 adapter at the lane router by artifact shape;
  domain meaning never lives in the executor
- execution status semantics: pre-execution states (READY_TO_EXECUTE/INVALID_DRAFT/
  MISSING_RUNNER/UNSUPPORTED_EXECUTION_KIND/MISSING_INPUT/UNSAFE_SIDE_EFFECT/
  MISSING_VALIDATION_CONTRACT) are never success; EXECUTED only means the runner
  finished — `runner_backed_execution_included=true` requires EXECUTED + validation PASS
- execution side effect boundary: execution happens only in an artifact temp copy;
  undeclared created paths or protected-path (golden/replay/src/contract) changes are
  UNSAFE; stdout/stderr is stored as bounded summaries only
- execution evidence ownership: `review/draft_execution/*` (contract/result/manifest/
  evidence/report + dashboard summary) is written by the executor; loop evidence
  canonical priority is 2c3(graph) → generic draft execution → interaction → editor
  record, accepted only when applied+included; the validator blocks included overclaim,
  mock exchanges, and stale (non-fresh) provenance
- RUNNER_BACKED_EXECUTION_REQUIRED gap removal: only an execution-family report
  (applied+included) closes it — with an interaction report present but no execution
  report, the ladder rung and the hard blocker (EXECUTION_CANDIDATE cap) enforce the
  gap; probe fixture-scenario success is not draft-execution proof
- generic viewer polish (`factory_viewer_polish`): replay artifact → discovery →
  domain adapter → canonical viewer contract (viewer_id/viewer_kind/source_artifact_refs
  with sha256/replays[frames]/capabilities/validation_rules/evidence_requirements) →
  generic viewer core (reads only `product/viewer/viewer_contract.json`, never raw
  replay keys) → navigation evidence → validator. The graph domain routes to the
  legacy 2C-1 adapter at the lane router by artifact shape
- replay artifact ref priority: explicit `replay/index.json` manifest refs first;
  compatibility discovery only without an index and only with exactly one candidate
  (provenance recorded); multiple candidates = AMBIGUOUS, never auto-picked; glob or
  filename guessing is never the canonical source
- canonical frame semantics: frame_id/sequence/event_kind/summary/payload/
  affected_targets are derived mechanically from raw events (payload preserved
  verbatim); before/after state exist only where derivable (first=fixture
  initial_state matched by declared id, last=final_state) — missing values stay
  null, never fabricated
- viewer adapter boundary: selection by replay event schema shape only
  (`events[].type` = standard typed adapter shared by SRS/table/filesystem;
  `events[].event` = graph legacy read adapter); mixed/unknown shapes are
  UNSUPPORTED; no domain-name, challenge, run, or filename branches in the core
- viewer status semantics: discovery states (FOUND/MISSING/AMBIGUOUS/INVALID/
  UNSUPPORTED) and viewer states (REPLAY_READY/COMPLETE/MISSING/INVALID/AMBIGUOUS/
  UNSUPPORTED/VALIDATION_FAILED) are displayed explicitly; REPLAY_COMPLETE only means
  the replay is fully navigable, never product success; missing/invalid artifacts are
  never replaced by empty or mock viewers
- viewer evidence ownership: `review/viewer_polish/*` (contract/discovery/evidence/
  report + dashboard summary) is written by the executor;
  `viewer_polish_included=true` requires discovery FOUND + schema-valid contract +
  model-level navigation proof (visited frames, state transition observed) + JS
  parse PASS; the validator blocks included overclaims, zero-frame success,
  digest-less sources, and stale provenance
- VIEWER_POLISH_REQUIRED gap removal: the child's recomputed viewer facts must be
  clean (viewer exists, no mismatches) and replay reading is evidenced either by the
  viewer surface itself or by an applied+included viewer polish report (the
  contract-reading viewer has no raw replay fetch to observe statically)
- viewer mismatch detection requires only the keys the viewer actually reads
  (a `.type`-only viewer never requires `message`) — the graph-schema assumption
  that flagged every non-graph domain was an accidental coupling
- generic ux polish (`factory_ux_polish`): product surfaces → canonical UX contract
  (reuses interaction/viewer/runner contracts; ux_target_id/source_artifact_refs with
  sha256/primary_task/primary_actions/state_indicators/feedback_channels/error_channels/
  viewport_requirements/keyboard_requirements/allowed_operations/forbidden_changes) →
  deterministic diagnosis (15 states, static DOM/CSS/JS analysis — never subjective
  LLM screen impressions) → bounded operation catalog → marker-block patch →
  re-diagnosis validation (rollback on failure) → machine-checkable evidence →
  validator. No domain/challenge/run/filename branches
- ux authority boundary: the executor only makes existing features discoverable and
  understandable (labels, feedback, state/error exposure, overflow, narrow-viewport
  stacking, keyboard focus, replay position, validation connection); it never adds
  features, changes contract meaning, edits domain data, redesigns pages, or fabricates
  success messages; PRODUCT_REQUIREMENT and UPSTREAM_CONTRACT defects are surfaced,
  never covered by UX patches
- ux operation catalog: only the 12 canonical operations (CLARIFY_LABEL,
  EXPOSE_PRIMARY_ACTION, ADD_ACTION_FEEDBACK, EXPOSE_STATE, EXPOSE_ERROR, FIX_OVERFLOW,
  STACK_FOR_NARROW_VIEWPORT, ADD_VISIBLE_FOCUS, FIX_FOCUS_ORDER, MARK_DISABLED_REASON,
  EXPOSE_REPLAY_POSITION, CONNECT_VALIDATION_FEEDBACK); free-form operations
  (MAKE_BEAUTIFUL/REDESIGN_PAGE/IMPROVE_STYLE/...) are forbidden; each operation is an
  idempotent `data-ux-op` marker block with precondition/patch_scope/validation/rollback;
  budget: 5 operations and 3 target surfaces per product, one operation per gap;
  STACK_FOR_NARROW_VIEWPORT also injects a marker `<meta name="viewport">` when the
  product declares none (a max-width media query never fires on mobile's ~980px fallback
  layout viewport without it), and a stacking media query without meta viewport does not
  resolve the NARROW_VIEWPORT_BROKEN diagnosis
- ux evidence ownership: `review/ux_polish/*` (contract/diagnosis/operations/evidence/
  report + dashboard summary) is written by the executor; `ux_polish_included=true`
  requires status APPLIED or UX_READY + viewport(narrow) and keyboard checks PASS +
  visible action/state/feedback/error channels + JS parse PASS + runtime action refs
  (existing runner-backed evidence — UX never re-fabricates execution proof); the
  validator blocks catalog-외 operations, budget overruns, product/-외 patches, and
  included overclaims; HTTP 200/CSS-only changes/screenshots are never UX success
- UX_POLISH_REQUIRED gap removal: loop closure and 60s-understandability metrics alone
  do not close the UX rung — a ux polish report (applied or UX_READY, included=true)
  is also required; once present with clean metrics the primary gap becomes None
  (remaining blockers are requirement-coverage/human level, reported via acceptance,
  never a new blocker system); pure aesthetics stay a non-blocking
  HUMAN_AESTHETIC_REVIEW note, not a product failure
- probe07 replay-read recognition: raw `replay/`+fetch in one product file, or
  contract-mediated (product file fetches `viewer_contract.json` whose
  source_artifact_refs point to existing replay files with matching sha256) — the
  raw-substring-only rule was a stale coupling that permanently failed every
  canonical (contract-reading) viewer

QUERY:
- architecture-context --canon CANON-06

## CANON-07 Closed Loop Contracts

SCOPE:
- product judgment (2D-0) and closed product loop (2D-1)

CANONICAL_ROUTES:
- factory_judge_only
- factory_closed_loop

INVARIANTS:
- INV-BASE-RUN-IMMUTABLE
- INV-FRESH-VERIFICATION
- INV-HARD-RUNG-DETERMINISTIC
- INV-PROTECTED-HASH

CONTRACTS:
- product_evidence
- product_decision
- closed_loop_iteration
- closed_loop_summary

FORBIDDEN:
- mutating the base run (every iteration = separate child run; base hash before/after/check)
- prompts containing challenge_id/title/expected answers (evidence refs verbatim only)
- judge exceeding hard blockers; free-form file edits by the LLM (strict schema packets only)
- re-demanding a gap already closed by proven evidence (execution-family loop evidence
  canonical source = phase2c3 execution report or generic draft_execution report,
  applied+included only; else editor record)
- asking the human mid-iteration (stop only via HOLD_FOR_HUMAN packet with single question)

COMPATIBILITY:
- historical loop records are preserved as-is (characterization reads stored artifacts)

NOTES:
- evidence sources: latest phase first (2c3 → 2c2 → 2c1 → 2c0); execution-family loop
  evidence priority = 2c3(graph) → generic draft_execution → interaction → editor record
- product UI surface recognition (probe/static facts) reads all product/ html surfaces —
  a first-index.html-only read misses multi-surface products (interaction console +
  replay viewer); replay reads/mismatch judgments follow the surface that reads replay
- hard rungs (EVIDENCE_INSUFFICIENT/ARCHIVE/SPEC_REPAIR/CORE_PATCH/RUNNER_PATCH): deterministic
  ladder overrides live judgment (`gap_override` recorded), live lane desk skipped
- CORE_PATCH rung fires on gate_fail only — green_base absence alone is not a core-defect
  signal (a gates-green unpromoted run must fall through to soft rungs)
- lane-result escalation: if a lane result classifies SPEC_REPAIR_REQUIRED, the next iteration
  escalates gap/lane to SPEC_REPAIR instead of repeating the same lane (`gap_escalation`
  recorded on the iteration; budgets unchanged — the hold packet then names the true gap)
- budgets: iterations 4 / per-lane 2 / high-risk total 1 / no-progress 2 / infra retries 2
- promotion requires meaningful progress + zero regression + protected hash PASS

QUERY:
- architecture-context --canon CANON-07

## CANON-08 Storage & Run Layout Contracts

SCOPE:
- challenge.db schema policy, run directory layout, artifact root resolution

CANONICAL_ROUTES:
- none (cross-cutting storage)

INVARIANTS:
- none

CONTRACTS:
- none

FORBIDDEN:
- schema changes other than additive ALTER TABLE migrations (old DBs stay readable)
- new `final_artifact if exists else workspace` logic outside `factory_run_layout`

COMPATIBILITY:
- product_reviews is append-only; existing run directories remain readable forever

NOTES:
- run layout: `runs/factory_*/` = workspace/ + final_artifact/ + golden/ + fixtures/ +
  contracts + `review/phase*/`; continuation/loop children are independent runs, same layout
- key scheduler: DB-backed 11 keys, per-key cooldown on 429/500 (30→60→120→300s)

QUERY:
- architecture-context --canon CANON-08

## CANON-09 Presentation Boundary

SCOPE:
- dashboard responsibility boundary and bind security

CANONICAL_ROUTES:
- dashboard_read

INVARIANTS:
- INV-PRESENTATION-NO-JUDGMENT

CONTRACTS:
- none

FORBIDDEN:
- presentation (`challenge_dashboard`) owning SQL execution or artifact JSON parsing
  (read model = `challenge_dashboard_data`; regression test enforces absence)
- presentation computing verdicts/stages/gaps (reads phase dashboard summaries;
  QA aggregate only from `factory_summary.overall_qa_status`)

COMPATIBILITY:
- internal enum/DB values never change for display purposes (labels layer only)

NOTES:
- no auth — default bind 127.0.0.1; 0.0.0.0 only on the Tailscale private network
- draft execution demo runs through the bridge server, not the static file server

QUERY:
- architecture-context --canon CANON-09

## CANON-10 Validation Contracts

SCOPE:
- factory-validate routing and validator registry, test policy

CANONICAL_ROUTES:
- factory_validate

INVARIANTS:
- INV-FRESH-VERIFICATION

CONTRACTS:
- none

FORBIDDEN:
- phase marker validators outside the single `MARKER_VALIDATORS` registry
  (declaration order = check order; marker absent = no-op)
- E2E re-verification touching #47/#54 base runs on disk (tmp copy only)
- verdict inconsistency: gate fail + REVIEW_READY/PROMOTE must be blocked

COMPATIBILITY:
- external contract (problem string list, CLI output) stays stable via `render_problems`
- LEGACY/UNKNOWN run kinds are SKIP, never FAIL

NOTES:
- run kind detection order: continuation → core → legacy
- known flaky: 0 (R0 root-caused stale .pyc; PYTHONDONTWRITEBYTECODE=1 in sandboxes)

QUERY:
- architecture-context --canon CANON-10

## CANON-11 Security & Global Invariants

SCOPE:
- secrets, preservation targets, global behavioral principles

CANONICAL_ROUTES:
- none (global)

INVARIANTS:
- INV-SECRET-NONDISCLOSURE
- INV-MINER-CORE-PRESERVED
- INV-BASE-RUN-IMMUTABLE
- INV-FRESH-VERIFICATION
- INV-SPEC-REPAIR-PROTECTION

CONTRACTS:
- none

FORBIDDEN:
- printing/committing/logging `GOOGLE_API_KEY_1..11` (AQ. prefix) or `GITHUB_TOKEN`
  (redaction masks; artifacts record key index only)
- automation that bypasses spec-repair §8 protection
- trusting stale reports over fresh observation

COMPATIBILITY:
- miner private-import allowlist (3 entries) documented in the Atlas manifest

NOTES:
- none

QUERY:
- architecture-context --canon CANON-11

## CANON-12 AI Architecture Interface

SCOPE:
- machine-readable Atlas, context queries, structure/document governance

CANONICAL_ROUTES:
- architecture_build
- architecture_context
- architecture_check

INVARIANTS:
- INV-AI-DOCUMENTS-ONLY

CONTRACTS:
- none

FORBIDDEN:
- human-facing Atlas surfaces (HTML/renderer/serve/summary) — check fails if present
- hand-editing generated `atlas.json`/`atlas.schema.json`
- new root markdown or human documentation/delivery-history markdown in the repo
- non-deterministic atlas output (timestamps/randomness)

COMPATIBILITY:
- structural fingerprint ignores function-internal changes; stale fingerprint = check FAIL

ATLAS_AUTHORITY:
- Atlas is an initial structure reference map — it narrows the candidate files/symbols/
  routes/contracts/invariants/tests to read first; it is not an oracle that finalizes edit scope
- context membership alone does not make a file an edit target
- files absent from the context may still be required — confirm via actual code relations
  (call sites, contracts) and read them
- read the actual `read_first` code before deciding the final work scope

EVIDENCE_PRIORITY:
- order: (1) actual current code (2) fresh execution/probe/validator results
  (3) schemas and contracts (4) related tests (5) Atlas context (6) past reports
- when Atlas conflicts with actual code or fresh observation, do not prefer Atlas:
  verify the code → decide whether atlas/manifest is stale → apply the structural update
  → `architecture-build` / `architecture-check`

IMPACT_LIMIT:
- `direct_static_impact` means direct imports, routes, artifacts, validators, contracts,
  invariants, and test links only
- it is not a full runtime analysis: dynamic dispatch, registry runtime state,
  filesystem/DB state, and subprocess behavior need actual code and execution checks

REQUIRED_WORKFLOW:
- before edit: REENTRY state → AI_INDEX selector → selected CANON sections →
  `architecture-context` initial scope → read actual `read_first` symbols →
  compare `--impact` with call sites → check contracts/invariants/tests → decide final scope
- after edit: targeted tests → `architecture-context --changed --impact` →
  `architecture-check` → structural change: `architecture-build` + related CANON section
  in the same commit → state change: REENTRY

VALIDATED_LIMIT:
- A7 blind validation: required structure information was present in the context for 5/5 tasks
- blind AI final item selection was complete in 4/5 tasks
- Atlas is a reliable initial structure reference; it does not replace reading the actual
  code and making the final judgment

ATLAS_MAINTENANCE:
- fingerprint-neutral edits (function-internal changes) may not require a rebuild
- module / public canonical symbol / CLI / route / validator / artifact relation change
  → run `architecture-build`
- canonical route / contract / invariant / ownership boundary change → update
  `manifest.toml` and the related CANON section together
- do not accumulate work history, completion reports, or one-off orders in Atlas/CANON —
  keep current structural facts only; history lives in git

DO_NOT:
- do not edit from Atlas output alone; do not read or modify every file in the context
- do not deny a real dependency because Atlas lacks it
- do not read `direct_static_impact` as a complete runtime call graph
- do not add unrelated primary files to raise recall; no task hardcode to pass a task

NOTES:
- outputs: `architecture/manifest.toml` (human-declared meaning: routes/contracts/invariants)
  + generated `atlas.json` (schema V2: repository/symbols/routes/artifacts role+provenance/
  contracts/invariants/document_routes) + `atlas.schema.json`
- artifact roles: ambiguous string literals stay LITERAL_REFERENCE — promotion to
  PRODUCES/CONSUMES requires AST_IO_CALL or MANIFEST provenance
- document canon: current facts=atlas.json / meaning=PROJECT_CANON / routing=AI_INDEX /
  state=REENTRY / bootstrap=README / history=git log
- workspace change canon: `git status --porcelain -uall` output is the single source —
  untracked files participate in `--changed` (untracked production py = UNKNOWN_PENDING_BUILD)
- module/symbol canonical ID is the full import path; short names resolve only on a
  unique match, ambiguity is a deterministic error (AMBIGUOUS_*_SELECTOR, CLI exit 1)
- `tests_to_run`/verification commands carry real repo-relative test paths (atlas
  `test_paths`), never guessed `tests/<stem>.py`
- blind fixtures (`tests/fixtures/ai_tasks/blind_*`) come from independent-AI validation
  ground truth — they regression-pin context recall, not implementation details

QUERY:
- architecture-context --canon CANON-12
