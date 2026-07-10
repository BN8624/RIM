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
- Challenge Mode: `challenge_*.py` 10개 (dashboard 포함). Challenge 관련 수정은 이 파일들만.
- Product Factory (`factory_*.py`):
  - `factory_core_schemas/prompts/gates/pipeline.py` — 7-Stage core harness (CANON-04).
  - `factory_continue.py` — continuation delta loop, `factory_queue.py` — queue routing, `factory_frozen.py` — frozen hash guard (CANON-05).
  - `factory_spec_repair.py`(2B-1) / `factory_anti_hardcode.py`(2B-1b) — 단일 run 수리 명령 (CANON-05).
  - `factory_review.py`(2C-0) / `factory_product_polish.py`(2C-1) / `factory_product_editor.py`(2C-2) / `factory_draft_execution.py`(2C-3) — 제품화 체인 (CANON-06).
  - `factory_autopilot_schemas/desks.py` + `factory_product_loop.py`(2D-0 judge) — Gemma autopilot (CANON-07).
  - `factory_product_capabilities.py`(capability profile+fresh probe) + `factory_lane_executors.py`(lane registry) + `factory_loop_executor.py`(closed loop) + `factory_product_acceptance.py`(acceptance 14검사) — 2D-1 (CANON-07).
  - `factory_validate.py` — run type 감지+phase별 marker 검증 (CANON-10), `factory_labels.py` — 대시보드 한국어 라벨, `factory_summary.py` — summary 3종.
- `redaction.py` — secret 마스킹 (AQ. prefix 포함).

## CANON-03 CLI 명령 지도

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
- runner stdout은 **ASCII-safe JSON** (Windows cp949 파이프). mock fallback은 정적 검출기(detect_mock_fallback)가 잡는다 — product 데모 데이터에 mock/fallback 금지.

## CANON-05 Continuation / Queue / 단일 run 수리

- `factory-continue`: 실패 분류(10 failure type) → repair plan(frozen 보호) → delta patch(allowed_touch_files만) → gate 재실행 → green 승격 판단. golden/contract 수정 필요는 **SPEC_REPAIR_REQUIRED로 분리**(continuation이 직접 수정 금지).
- `factory-continue-queue` lane 4종: PATCH_CONTINUATION / SPEC_REPAIR / EXCLUDED / REVIEW_ONLY. execute는 patch lane 한정 limit 1. spec repair는 proposal만 생성.
- `factory-spec-repair-apply` **§8 보호(우회 자동화 금지)**: 기존 golden 기대값 훼손·field 삭제·contract 밖 field 추가·comparison_mode 완화 전부 차단. snapshot/rollback + frozen hash before/after/check(범위 밖 변경=자동 rollback) + gate 재실행.
- `factory-anti-hardcode-patch`: runner summary 하드코딩을 state 파생 helper로 교체. `classify_summary_source`가 hardcoded/state_derived 구분.
- **frozen hash guard**: golden/fixtures/contract sha256 — 사후 조작 탐지. anti_hardcode scratch인 `fixtures/_variants/`는 제외.

## CANON-06 제품화 체인 (2C-0 → 2C-3)

순서 고정, 각 단계가 다음 단계의 사전조건. 산출물은 `runs/<run>/review/phase2cX/`, validate는 marker 없으면 no-op.

1. **2C-0 review**: no-code-change smoke(임시 copy에서 runner 실행), 보호 artifact hash 불변, evidence 스코어 7항목 → recommended_fitness(PRODUCT_CANDIDATE/NEEDS_PRODUCT_POLISH/NEEDS_CORE_PATCH/NEEDS_SPEC_REPAIR/ARCHIVE). viewer 근거는 replay 실제 필드 참조 ≥2개, 불확실은 unknown.
2. **2C-1 polish**: viewer `<script>`만 교체(normalize/deterministic layout). 사전조건 NEEDS_PRODUCT_POLISH. polish는 authoring을 추가하지 않으므로 결과 뷰어는 계속 NEEDS_PRODUCT_POLISH가 정상.
3. **2C-2 editor**: `</body>` 앞에 editor DOM+script 주입(마커로 idempotent). supported_node_types는 contract/replay에서 추출, 실패 시 CANNOT_EDIT. Python 미러 모델로 model-level smoke. 사람 결정 파일 `review/phase2c1/user_review_decision.md` 필요.
4. **2C-3 draft execution**: `src/adapters/draft_to_runner_input.py` + `product/draft_server.py`(POST /api/execute-draft→runner subprocess) + viewer 실행 패널. 편집→검증→실행→결과→수정→재실행이 실증되면 product_loop_closed=true.
- **viewer JS 금지 리터럴**(smoke가 감지): `edge.from`/`ev.type`/`\.type\b`/`node.x`/`Math.random`/`Date.now`. viewer 산출물은 `node --check`로 파싱 검증(정규식 smoke는 JS 문법 오류를 못 잡는다). 스크립트 주입은 re.sub 문자열 치환 금지 — **함수 replacement 또는 str.replace** (백슬래시 이스케이프 해석 버그).

## CANON-07 Autopilot & Closed Loop (2D-0 / 2D-1)

- **Stage 7종**(사다리): CORE_GREEN → REVIEWABLE_ARTIFACT → POLISHABLE_PROTOTYPE → INTERACTION_CANDIDATE → EXECUTION_CANDIDATE → PRODUCT_CANDIDATE (+ARCHIVE). **gap 10종 → lane 9종** 고정 매핑(GAP_TO_LANE). lane risk policy: SPEC_REPAIR/CORE_PATCH=high, 전 lane auto_execute_allowed=false(원본 apply 기준 — child run 실행은 §13으로 허용).
- **2D-0 judge desks**(sequential/unified): 프롬프트에 challenge_id/title/기대정답 절대 미포함, evidence_refs는 카탈로그 verbatim(날조 차단), strict schema+repair 1회(의미 변경=INVALID), hard blocker는 judge가 넘을 수 없는 상한.
- **evidence ladder enforcement (§7 관측이 서술을 이긴다)**: boolean fact에서 직접 유도되는 **hard rung 5종**(EVIDENCE_INSUFFICIENT/ARCHIVE_RECOMMENDED/SPEC_REPAIR_REQUIRED/CORE_PATCH_REQUIRED/RUNNER_PATCH_REQUIRED)은 deterministic ladder가 live desk 판정을 override(`gap_override` 기록)하고 live lane desk를 생략한다. soft rung(viewer/interaction/UX)은 Gemma 판정 존중.
- **2D-1 closed loop**(`--execute`): verify(gate를 **항상 temp copy에서 재실행** — stale report 불신, fresh gate가 evidence_sufficient의 gate 문맥도 충족) → fresh probe(성공 2·실패 1·revise 재실행 변화) → judge → lane executor가 **child run**에서 실행 → 재검증. **원본 base run은 절대 불변(§13)** — base hash before/after/check, apply류 옵션 자체가 없음.
- 예산(§10): iteration 4 / lane별 2 / high-risk lane 합계 1 / 연속 무진전 2 / infra 재시도 2. 소진·사람 결정 필요 시 **HOLD_FOR_HUMAN packet**(단일 질문+선택지, §11)을 남기고 정지 — 중간에 사람에게 묻지 않는다.
- acceptance 14검사(코어 gate 전부, validate, anti-hardcode, mock fallback 0, coverage, loop closed 등)가 PRODUCT_CANDIDATE 과대평가를 차단. 산출물: `runs/<base>/review/phase2d1/loop_*/`.
- 알려진 한계: lane 실패로 발견된 정보(예: requires_spec_repair)는 다음 iteration judge에 전달되지 않음(escalation은 계획 밖 — 도입하려면 주문서부터).

## CANON-08 DB & 산출물 레이아웃

- `challenge.db`(SQLite, gitignore): repos/repo_queue/challenges/owner_reviews/api_keys/events/settings + product_runs/product_tasks/product_events/product_artifacts/product_reviews. product_reviews는 append-only. 스키마 확장은 ALTER TABLE 마이그레이션(구 DB 호환 유지).
- key scheduler: DB-backed 11-key, 429/500은 해당 key만 cooldown(30→60→120→300s).
- run 디렉터리: `runs/factory_YYYYMMDD_HHMMSS/` — workspace/ + final_artifact/(납품물) + golden/ + fixtures/ + *_contract.json + review/phase{2c0,2c1,2c2,2c3,2d0,2d1}/ + 각종 summary json. continuation/loop child도 같은 layout의 독립 run.

## CANON-09 대시보드

- `dashboard`(포트 8787): Challenge Inbox + Product Runs 검수함. 한국어 라벨(factory_labels, 내부 enum 불변), 기술 원문은 <details> 접힘. phase별 카드/패널/report 탭은 최신 phase 우선(2D-1>2D-0>2C-3>…).
- 인증 없음 — 기본 host 127.0.0.1, `0.0.0.0`은 Tailscale 사설망(100.89.73.83)에서만.
- #47 실행 데모는 정적 서버가 아니라 브리지 서버(`python product/draft_server.py --port 8799`)로 접속해야 동작.

## CANON-10 검증 & 테스트

- `factory-validate <run_dir>`: run type 자동 감지(CONTINUATION/CORE/LEGACY) + phase marker별 검사(2C-0~2D-1, marker 없으면 no-op — 구 run 무영향). verdict 정합(gate fail+REVIEW_READY 차단 등), frozen/보호 hash, PRODUCT_CANDIDATE 엄격 조건.
- `python -m pytest -q` — 약 4분. 알려진 flaky 2종: `test_patch_repair_fixes_broken_build` / `test_build_review_recomputed_after_patch` (patch_attempts=2 시그니처, 비결정 — 원인 조사 미완).
- 재검증 E2E는 **반드시 tmp 복사에서** — #47/#54 base run on-disk 상태를 직접 건드리지 않는다.

## CANON-11 Secret / 불변 규칙

- `.env`의 `GOOGLE_API_KEY_1~11`(AQ. prefix)과 `GITHUB_TOKEN`은 **절대 출력/커밋/로그 금지** — redaction.py가 마스킹, 산출물에는 key index만 기록.
- Miner core(pipeline/search_pipeline/schemas)는 무변경 보존.
- spec repair §8 보호를 우회하는 자동화 금지. 원본 base run 직접 수정 금지(§13). 기록된 report보다 fresh 관측 우선(§7).
