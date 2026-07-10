# PROJECT_CANON — RIM 현행 정본

이 문서는 RIM의 **현행 아키텍처 정본**이다. v1.0 스펙(RIM_FANAL.md)과 phase별 외주 주문서들은
납품 완료 후 삭제됐고 git 이력에만 남아 있다 — 현재 시스템이 어떻게 생겼는지는 이 문서가 기준이다.
읽기 전에 `AI_INDEX.md`로 필요한 CANON-ID 섹션만 골라 읽는다(canon-router).
세션 단위의 "지금 어디까지 했나"는 이 문서가 아니라 `REENTRY.md`가 담당한다.
아키텍처가 바뀌는 커밋을 하면 해당 CANON 섹션도 같은 커밋에서 갱신한다.

---

## CANON-01 프로젝트 정체성

- RIM = Repo Idea Miner. https://github.com/BN8624/RIM, **main 브랜치만 사용**, 커밋은 의미 단위로 즉시 push.
- 세 층위가 한 리포에 공존한다.
  1. **Miner (v1.0, 2026-07-08 납품)**: GitHub 레포/검색어 → 수집·분석 → KEEP/MAYBE/DROP 아이디어 카드.
  2. **Challenge Mode**: 아이디어를 구현 챌린지로 승격·관리 (daemon/dashboard/queue).
  3. **Product Factory**: 챌린지를 실제 실행 가능한 product artifact로 빌드·수리·검수·제품화하는 하네스 (현재 Phase 2D-1까지).
- CLI 진입점은 **`python -m repo_idea_miner`** (`__main__.py`). `.cli` 직접 실행은 main 미호출로 무출력.
- LLM은 Gemma(`gemma-4-31b-it` 고정, `.env RIM_GEMMA_MODEL`), Google AI Studio key 11개 풀.

## CANON-02 모듈 지도

- Miner core: `pipeline.py` / `search_pipeline.py` / `schemas.py` — **v1.0 이후 무변경 보존이 요구사항**.
- Challenge Mode: `challenge_*.py` 11개 (dashboard 포함). Challenge 관련 수정은 이 파일들만. `challenge_dashboard.py`는 HTML 렌더링+HTTP만, 조회·phase 요약 로더·preview 화이트리스트 접근은 `challenge_dashboard_data.py`(대시보드 read model, CANON-09).
- Product Factory (`factory_*.py`):
  - `factory_core_schemas/prompts/gates/pipeline.py` — 7-Stage core harness (CANON-04).
  - `factory_continue.py` — continuation delta loop + failure 의미 정본(assess_failure_patch_safety, spec repair proposal/review 빌더 — queue·2B가 import), `factory_queue.py` — queue routing/discovery(판단은 continue의 정본 사용), `factory_frozen.py` — frozen hash guard + patch 금지 동결 파일 정본(FROZEN_FILES/FROZEN_PATH_PREFIXES — continue·core pipeline이 import) (CANON-05).
  - `factory_spec_repair.py`(2B-1) / `factory_anti_hardcode.py`(2B-1b) — 단일 run 수리 명령 (CANON-05).
  - `factory_review.py`(2C-0) / `factory_product_polish.py`(2C-1) / `factory_product_editor.py`(2C-2) / `factory_draft_execution.py`(2C-3) — 제품화 체인 (CANON-06).
  - `factory_product_evidence.py` — 제품 evidence 공통 정본: viewer/replay 탐색(find_product_viewer/first_replay_file), viewer field evidence(viewer_reads_replay_evidence/viewer_field_mismatches), protected hash(compute/compare_protected_hashes), gate context(read_gate_context), 공통 IO(load_json/write_json/write_text/sha256_file). 2C 체인·2D loop가 전부 여기서 import — 다른 모듈이 재구현하지 않는다.
  - `factory_autopilot_schemas/desks.py` + `factory_product_loop.py`(2D-0 judge) — Gemma autopilot (CANON-07).
  - `factory_product_capabilities.py`(capability profile+fresh probe) + `factory_lane_executors.py`(lane registry) + `factory_loop_executor.py`(closed loop) + `factory_product_acceptance.py`(acceptance 14검사) — 2D-1 (CANON-07).
  - `factory_validate.py` — run kind별 artifact 검증 + marker validator registry(MARKER_VALIDATORS, CANON-10), `factory_labels.py` — 대시보드 한국어 라벨, `factory_summary.py` — summary 3종.
  - `factory_run_layout.py` — run directory 해석의 정본: resolve_artifact_root/RunLayout + resolve_run_target(--run-dir/--run-id → run_dir, CLI 명령 공통) + run kind 감지(detect_run_kind, RUN_KIND_CONTINUATION/CORE/LEGACY/UNKNOWN — continuation→core→legacy 순). artifact root 선택·run 대상 해석·run kind 감지를 다른 모듈이 반복 구현하지 않는다.
  - `architecture_scanner.py` — AST 기반 구조 추출(baseline/Atlas 코어): module/LOC/import cycle/private cross-import/CLI/validator.
- `redaction.py` — secret 마스킹 (AQ. prefix 포함).

## CANON-03 CLI 명령 지도

- 구조: `cli.py`는 parser/command 등록/dispatch/exit code만 담당하고, command 실행·출력은 `cli_handlers.py`의 handler(`HANDLERS` registry — parser command 집합과 1:1, 회귀 테스트가 고정)가 담당한다. DB open(존재 시)·live scheduler 생성·`--dry-run/--apply` 충돌·run target 검증은 handler 공통 헬퍼를 쓴다.
- Miner: `run`, `search`, `view`, `serve`, `validate`.
- Challenge: `challenge`, `challenge-search`, `daemon`, `dashboard`, `status`, `pause`, `resume`, `validate-db`.
- Factory 빌드/검증: `factory`(자동 배치, 구 파이프라인), `factory-build`(7-stage core harness), `factory-status`, `factory-validate <run_dir>`.
- Factory 수리: `factory-continue --run-id|--run-dir`(가급적 --run-id), `factory-continue-queue --lane patch|spec-repair --dry-run|--execute|--proposal-only`, `factory-spec-repair-apply --dry-run|--apply`, `factory-anti-hardcode-patch --dry-run|--apply`.
- Factory 제품화: `factory-review`, `factory-product-polish --target viewer-field-mapping`, `factory-product-editor`, `factory-draft-execution` (전부 `--dry-run` 기본, `--apply` 명시).
- Autopilot: `factory-product-loop --run-dir|--run-id --mode mock|live --gemma-mode sequential|unified [--execute --max-iterations 4 --output-dir runs]` — `--execute` 없으면 judge-only, 있으면 closed loop (CANON-07).

## CANON-04 Core Harness (7-Stage / 7 Gate)

- `factory-build` = `run_core_factory`: 승격 게이트 → Desk 체인 → core 구현 → gate → debug 루프 → QA/Judge → final_artifact.
- **Gate 7종**: core_contract / runner / scenario_replay / golden_output(exact·partial·invariant) / state_invariant(invariant DSL: `x >= 0`, `exists:x`, length/entity 최소 해석) / determinism(역순 재실행) / anti_hardcode(L1 + 변형 fixture L2, **product layer 생성 후에도 재실행** — post_product_anti_hardcode).
- Verdict 사다리: DROP < NEEDS_MORE_GEMMA_LOOP < SPEC_REPAIR_REQUIRED < RUNS_BUT_WEAK < REVIEW_READY < PROMOTE_TO_CODEX. **green_base** = 전 gate PASS + product layer PASS + hardcode low/medium. continuation_base = core_contract+runner 통과+patchable.
- **표현 계약**: core_contract에 `output_representation`(event 형태/키/kinds, summary 형식) 필수(신규 run). `lint_golden_representation`이 구현 전 golden↔계약 표현을 기계 검사, harness_schema_version≥2는 strict(미선언 FAIL). summary는 하네스 표준상 **항상 문자열**.
- runner stdout은 **ASCII-safe JSON** (Windows cp949 파이프). mock fallback은 정적 검출기(detect_mock_fallback)가 잡는다 — demo/mock/fallback 데이터를 실제 실행 결과처럼 표시하면 실패. fallback이 꼭 필요하면 `DEMO_ONLY`/`NOT_EXECUTED`/`RUNNER_UNAVAILABLE` 상태로만 표시하고, 이 상태로는 PRODUCT_CANDIDATE 불가.
- **gate 실행과 artifact 검증은 분리**: gate는 factory_core_gates가 실제 재실행하고, factory_validate(CANON-10)는 기록된 산출물의 정합성만 검사한다 — 기록된 gate report를 재실행 결과처럼 신뢰하지 않는다.

## CANON-05 Continuation / Queue / 단일 run 수리

- `factory-continue`: 실패 분류(10 failure type) → repair plan(frozen 보호) → delta patch(allowed_touch_files만) → gate 재실행 → green 승격 판단. golden/contract 수정 필요는 **SPEC_REPAIR_REQUIRED로 분리**(continuation이 직접 수정 금지).
- `factory-continue-queue` lane 4종: PATCH_CONTINUATION / SPEC_REPAIR / EXCLUDED / REVIEW_ONLY. execute는 patch lane 한정 limit 1. spec repair는 proposal만 생성.
- **failure patch-safety 정본은 factory_continue**(assess_failure_patch_safety: patch|spec|unclear, PATCH_SAFE/CONDITIONAL/NEVER 상수, build_spec_repair_proposal/review) — queue와 2B 모듈이 import하며 재구현하지 않는다. continue↔queue import cycle 없음.
- **stale verdict는 read 시 canonical 계산**(§14.5): 2B가 base run을 in-place green 승격하면 DB/이력 verdict가 낡는다 — queue classify가 run_dir의 승격 기록(read_gate_context)을 읽어 성공 verdict로 재계산한다(REVIEW_ONLY). 승격 기록이 없으면 verdict를 고쳐 쓰지 않는다. 별도 reconcile command는 없다.
- `factory-spec-repair-apply` **§8 보호(우회 자동화 금지)**: 기존 golden 기대값 훼손·field 삭제·contract 밖 field 추가·comparison_mode 완화 전부 차단. snapshot/rollback + frozen hash before/after/check(범위 밖 변경=자동 rollback) + gate 재실행.
- `factory-anti-hardcode-patch`: runner summary 하드코딩을 state 파생 helper로 교체. `classify_summary_source`가 hardcoded/state_derived 구분.
- **frozen hash guard**: golden/fixtures/contract sha256 — 사후 조작 탐지. anti_hardcode scratch인 `fixtures/_variants/`는 제외. 사후 정합성 검증은 CANON-10 registry의 frozen_hash_guard validator가 수행.

## CANON-06 제품화 체인 (2C-0 → 2C-3)

순서 고정, 각 단계가 다음 단계의 사전조건. 산출물은 `runs/<run>/review/phase2cX/`, validate는 marker 없으면 no-op.
viewer/replay 탐색·field evidence·protected hash·gate context는 전 단계가 `factory_product_evidence.py`(CANON-02) 정본을 공유한다.

1. **2C-0 review**: no-code-change smoke(임시 copy에서 runner 실행), 보호 artifact hash 불변, evidence 스코어 7항목 → recommended_fitness(PRODUCT_CANDIDATE/NEEDS_PRODUCT_POLISH/NEEDS_CORE_PATCH/NEEDS_SPEC_REPAIR/ARCHIVE). viewer 근거는 replay 실제 필드 참조 ≥2개, 불확실은 unknown.
2. **2C-1 polish**: viewer `<script>`만 교체(normalize/deterministic layout). 사전조건 NEEDS_PRODUCT_POLISH. polish는 authoring을 추가하지 않으므로 결과 뷰어는 계속 NEEDS_PRODUCT_POLISH가 정상.
3. **2C-2 editor**: `</body>` 앞에 editor DOM+script 주입(마커로 idempotent). supported_node_types는 contract/replay에서 추출, 실패 시 CANNOT_EDIT. Python 미러 모델로 model-level smoke. 사람 결정 파일 `review/phase2c1/user_review_decision.md` 필요.
4. **2C-3 draft execution**: `src/adapters/draft_to_runner_input.py` + `product/draft_server.py`(POST /api/execute-draft→runner subprocess) + viewer 실행 패널. 편집→검증→실행→결과→수정→재실행이 실증되면 product_loop_closed=true.
- **viewer JS 금지 리터럴**(smoke가 감지): `edge.from`/`ev.type`/`\.type\b`/`node.x`/`Math.random`/`Date.now`. viewer 산출물은 `node --check`로 파싱 검증(정규식 smoke는 JS 문법 오류를 못 잡는다). 스크립트 주입은 re.sub 문자열 치환 금지 — **함수 replacement 또는 str.replace** (백슬래시 이스케이프 해석 버그).

## CANON-07 Autopilot & Closed Loop (2D-0 / 2D-1)

- **Stage 7종**(사다리): CORE_GREEN → REVIEWABLE_ARTIFACT → POLISHABLE_PROTOTYPE → INTERACTION_CANDIDATE → EXECUTION_CANDIDATE → PRODUCT_CANDIDATE (+ARCHIVE). **gap 10종 → lane 9종** 고정 매핑(GAP_TO_LANE). lane risk policy: SPEC_REPAIR/CORE_PATCH=high, 전 lane auto_execute_allowed=false(원본 apply 기준 — child run 실행은 §13으로 허용).
- **2D-0 judge desks**(sequential/unified): 프롬프트에 challenge_id/title/기대정답 절대 미포함, evidence_refs는 카탈로그 verbatim(날조 차단), strict schema+repair 1회(의미 변경=INVALID), hard blocker는 judge가 넘을 수 없는 상한.
- **공개 Product Judgment API**(judge-only와 closed loop가 동일 사용): `extract_artifact_evidence` → `extract_user_facing_quality` → `apply_hard_blockers` → `run_judgment_desks`(include_order=False면 judge/gap/lane까지만 — 2D-1은 auto_order/blueprint desk 생략). factory_loop_executor는 factory_product_loop의 private을 import하지 않는다.
- **evidence 소스는 최신 phase 우선**(2c3 → 2c2 → 2c1 → 2c0): 실행 계열 loop evidence(can_execute/can_observe/can_revise)는 **2C-3 execution_smoke가 실증 정본** — `phase2c3_execution_report.json`이 apply 완료 + `runner_backed_execution_included=true`일 때만 인정(dry-run/미실증 report는 무시), 없으면 editor 기록 기반. 이미 실증으로 닫힌 gap을 다시 요구하지 않는다(과거 #47 hold가 이 누락으로 stale RUNNER_BACKED_EXECUTION_REQUIRED를 냈던 회귀를 테스트가 고정).
- **evidence ladder enforcement (§7 관측이 서술을 이긴다)**: boolean fact에서 직접 유도되는 **hard rung 5종**(EVIDENCE_INSUFFICIENT/ARCHIVE_RECOMMENDED/SPEC_REPAIR_REQUIRED/CORE_PATCH_REQUIRED/RUNNER_PATCH_REQUIRED)은 deterministic ladder가 live desk 판정을 override(`gap_override` 기록)하고 live lane desk를 생략한다. soft rung(viewer/interaction/UX)은 Gemma 판정 존중.
- **2D-1 closed loop**(`--execute`) 절대 원칙: 원본 base run 직접 수정 금지(매 iteration은 별도 child run, apply류 옵션 자체가 없음, base hash before/after/check). Gemma가 자유 형식으로 임의 파일을 수정하게 하지 않는다 — strict schema packet만, lane executor가 allowed/protected scope 검증 후 적용. golden/fixture/contract 의미를 약화해 gate를 통과시키지 않는다. 수정 후 기존 report 값 재사용 금지 — fresh 재검증(gate는 **항상 temp copy에서 재실행**, fresh gate가 evidence_sufficient의 gate 문맥도 충족). 사람은 중간 iteration에서 질문받지 않는다.
- **Fresh probe 10종**(iteration 전후): runner 실제 실행 / success scenario 2개 / failure scenario 1개 / 입력 수정 후 재실행+결과 차이 / viewer가 실제 result artifact 표시 / mock·fallback 검사 / core↔product 필드 정합 / critical flow handler 연결. probe에는 명령·exit code·입출력 hash·경로를 기록.
- **검증 순서**(apply 후 고정): targeted lane test → syntax → core gate 7종 → product layer check → post-product anti-hardcode → acceptance → factory-validate → fresh probe → rejudge. 한 단계라도 실패하면 green/PRODUCT_CANDIDATE 기록 금지.
- **Acceptance 14검사**(PRODUCT_CANDIDATE 요건): core gate 전부 / factory-validate / post-product anti-hardcode / mock_fallback 0 / protected hash / critical requirement coverage 1.0 / difficulty anchor coverage 1.0 / forbidden simplification 0 / product_loop_closed / success 2 / failure 1 / revise 재실행 변화 / 첫 화면 CTA / 성공·실패 feedback 실제 표시. critical requirement 하나라도 미구현이면 stage 상한 EXECUTION_CANDIDATE/POLISHABLE로 제한(과대평가 차단).
- **Progress 판정**: metric vector(stage_rank/gates/acceptance/hard blocker/coverage/loop parts/scenario/mock/regression) 전후 비교. 의미 있는 개선(사다리 상승·blocker 감소·coverage 증가 등) + regression 0 + protected hash PASS여야 child가 다음 parent로 승격 — 아니면 NO_MEANINGFUL_PROGRESS로 기록하고 미승격(실패 child는 기록만 남는다). 의미 없는 UI 문구 변경은 progress가 아니다.
- **Lane executor 공통 결과**: status(APPLIED/BLOCKED/FAILED/NO_CHANGE) + child_run_dir + changed_files + scope/hash check + failure_signature. 예산: iteration 4 / lane별 2 / high-risk(SPEC_REPAIR·CORE_PATCH) 합계 1 / 연속 무진전 2 / infra 재시도 2. 중단: 엄격 PRODUCT_CANDIDATE 도달·ARCHIVE·protected 변경·같은 failure signature 2회·예산 초과·evidence 부족·사람 결정 필요. 같은 primary gap이라도 signature가 다르고 metric이 개선되면 계속한다.
- 자동 진행 불가 시 **HOLD_FOR_HUMAN packet**(현재 최고 candidate/stage/blocking gap/시도 lane·diff·signature/보호 결과/자동 결정 못 한 이유/**사람이 결정할 단 하나의 질문**/추천 선택지)을 남기고 정지. 산출물: `runs/<base>/review/phase2d1/loop_*/`.
- 2026-07-10 완료 기준 충족: #47(graph)·#54(file_operation) 두 도메인이 같은 orchestrator를 통과(둘 다 정직 HOLD) — **다수 run batch 자동화의 선행 조건이 풀렸다**(아직 미착수).
- 알려진 한계: lane 실패로 발견된 정보(예: requires_spec_repair)는 다음 iteration judge에 전달되지 않음(escalation 미설계 — 도입하려면 이 섹션 규칙 갱신부터).

## CANON-08 DB & 산출물 레이아웃

- `challenge.db`(SQLite, gitignore): repos/repo_queue/challenges/owner_reviews/api_keys/events/settings + product_runs/product_tasks/product_events/product_artifacts/product_reviews. product_reviews는 append-only. 스키마 확장은 ALTER TABLE 마이그레이션(구 DB 호환 유지).
- key scheduler: DB-backed 11-key, 429/500은 해당 key만 cooldown(30→60→120→300s).
- run 디렉터리: `runs/factory_YYYYMMDD_HHMMSS/` — workspace/ + final_artifact/(납품물) + golden/ + fixtures/ + *_contract.json + review/phase{2c0,2c1,2c2,2c3,2d0,2d1}/ + 각종 summary json. continuation/loop child도 같은 layout의 독립 run.
- **artifact root 해석은 `factory_run_layout.resolve_artifact_root`가 정본** — final_artifact/가 있으면 그것, 없으면 workspace/. workspace-only child(continuation 등)는 복제 없이 그대로 검증·probe·judge 대상이 된다. `final_artifact if exists else workspace` 패턴을 개별 모듈에 새로 쓰지 않는다.

## CANON-09 대시보드

- `dashboard`(포트 8787): Challenge Inbox + Product Runs 검수함. 한국어 라벨(factory_labels, 내부 enum 불변), 기술 원문은 <details> 접힘. phase별 카드/패널/report 탭은 최신 phase 우선(2D-1>2D-0>2C-3>…).
- 책임 분리: `challenge_dashboard.py`는 HTML 렌더링·route dispatch·POST action만. SQL 조회·phase 요약 로더·report/source preview 화이트리스트와 경로 안전 검사는 `challenge_dashboard_data.py`(read model). 판정은 소유하지 않는다 — stage/gap/lane은 phase별 dashboard summary(정본 service 산출물)에서 읽고, QA 종합 상태는 `factory_summary.overall_qa_status` 하나다(회귀 테스트가 presentation의 SQL/JSON 파싱 부재를 고정).
- 인증 없음 — 기본 host 127.0.0.1, `0.0.0.0`은 Tailscale 사설망(100.89.73.83)에서만.
- #47 실행 데모는 정적 서버가 아니라 브리지 서버(`python product/draft_server.py --port 8799`)로 접속해야 동작.

## CANON-10 검증 & 테스트

- `factory-validate <run_dir>`: run kind 자동 감지(`factory_run_layout.detect_run_kind` — CONTINUATION/CORE/LEGACY/UNKNOWN, CANON-02) 후 kind별 검증으로 라우팅. phase marker 검사(frozen hash·spec repair·anti-hardcode patch·2C-0~2C-3·2D-0·2D-1)는 `factory_validate.MARKER_VALIDATORS` **registry 하나**를 core·continuation이 공유한다(선언 순서 = 검사 순서, marker 없으면 no-op — 구 run 무영향, LEGACY/UNKNOWN은 SKIP).
- validator는 `ValidatorSpec`(validator_id/run_kinds/markers/inputs/severity/related_tests)로 선언하고 내부 결과는 `CheckResult`(check_id/status/severity/problems). 외부 계약(problems 문자열 목록, CLI 출력)은 `render_problems`가 호환 유지. verdict 정합(gate fail+REVIEW_READY 차단 등), frozen/보호 hash, PRODUCT_CANDIDATE 엄격 조건은 기존 의미 그대로.
- `python -m pytest -q` — 약 4분 반. 과거 flaky 2종(`test_patch_repair_fixes_broken_build` / `test_build_review_recomputed_after_patch`)은 R0에서 근본 수정됨(.pyc stale bytecode — sandbox 로컬 env·docker에 PYTHONDONTWRITEBYTECODE=1 주입). 현재 known flaky 0.
- 재검증 E2E는 **반드시 tmp 복사에서** — #47/#54 base run on-disk 상태를 직접 건드리지 않는다.

## CANON-11 Secret / 불변 규칙

- `.env`의 `GOOGLE_API_KEY_1~11`(AQ. prefix)과 `GITHUB_TOKEN`은 **절대 출력/커밋/로그 금지** — redaction.py가 마스킹, 산출물에는 key index만 기록.
- Miner core(pipeline/search_pipeline/schemas)는 무변경 보존. 이 보존 때문에 miner 계열 private cross-import 3건(challenge_search_pipeline·viewer←search_pipeline `_safe_name`, search_pipeline←pipeline `_key_pool_report`)은 의도적 예외로 유지한다 — 공개화(보존 파일 수정)·복제(중복 구현)·wrapper(은닉) 전부 금지 규칙과 충돌하므로 그대로 두고 Atlas health에서 allowlist 처리한다.
- spec repair §8 보호를 우회하는 자동화 금지. 원본 base run 직접 수정 금지(§13). 기록된 report보다 fresh 관측 우선(§7).

## CANON-12 Architecture Atlas & Structural Rules

- 산출물: `architecture/manifest.toml`(사람 정의 — component/canon_id/금지 의존/private allowlist/artifact producer/pipeline 노드) + 자동 생성 `atlas.json`/`atlas.schema.json`/`index.html`(직접 수정 금지).
- CLI: `architecture-build`(결정론 — 같은 HEAD·manifest면 byte-identical, 생성시각/랜덤 없음), `architecture-check`(§17.11 구조·문서 거버넌스 검사, 실패 시 exit 1), `architecture-summary`, `architecture-serve --host 127.0.0.1 --port 8788`(serve.py 재사용, 읽기 전용).
- 구조 지문(fingerprint): module 목록/공개 심볼/import edge/CLI/validator/artifact/test mapping/manifest의 sha256 — 함수 내부만 바뀌면 stale 아님. committed atlas.json 지문과 현재 지문이 다르면 check가 stale로 FAIL.
- 코어: `architecture_scanner.py`(AST 사실 추출) + `architecture_atlas.py`(빌더/검사) + `architecture_render.py`(단일 self-contained HTML — 모바일 우선 360px, 다크모드, 외부 CDN/URL 0).
- 검사 요지: root md 5개(git tracked 기준), AI_INDEX↔CANON ID 정합, manifest 정합(canon_id/모듈 실재), 금지 의존, cycle 0, private import allowlist(miner 3건 — CANON-11) 밖 0, dashboard summary producer 선언 정합, presentation의 SQL/JSON 파싱 금지, stale Atlas, secret/외부 URL 0, README CLI 실재, §17.12 구조 변경 커밋에 PROJECT_CANON 동반.
