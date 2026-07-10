# AI_INDEX — PROJECT_CANON.md 라우팅 인덱스

작업 유형에 맞는 CANON-ID 섹션만 골라 읽는다 (canon-router). 세션 상태는 REENTRY.md.

- **CANON-01 프로젝트 정체성** — 리포/브랜치/커밋 정책, 세 층위(Miner/Challenge/Factory), CLI 진입점, Gemma 모델. 키워드: 개요, onboarding, entrypoint.
- **CANON-02 모듈 지도** — 어떤 파일이 무슨 역할인지. 키워드: 모듈, 파일 구조, factory_*, challenge_*.
- **CANON-03 CLI 명령 지도** — 명령 전체와 핵심 옵션. 키워드: 명령어, 실행법, dry-run/apply.
- **CANON-04 Core Harness** — 7-stage 빌드, gate 7종, verdict/green_base, 표현 계약/lint, ASCII stdout. 키워드: factory-build, gate, golden, verdict, representation.
- **CANON-05 Continuation/Queue/수리** — factory-continue, queue lane 4종, spec repair §8 보호, anti-hardcode patch, frozen hash. 키워드: patch, spec repair, frozen, queue.
- **CANON-06 제품화 체인 2C-0~2C-3** — review→polish→editor→draft execution 순서/사전조건/보호 hash, viewer JS 금지 리터럴. 키워드: viewer, polish, editor, draft 실행, product loop.
- **CANON-07 Autopilot & Closed Loop** — stage/gap/lane 체계, judge desk 규칙, evidence ladder hard rung override, 2D-1 closed loop 예산/HOLD packet/base 불변. 키워드: autopilot, factory-product-loop, judge, lane, HOLD_FOR_HUMAN.
- **CANON-08 DB & 산출물 레이아웃** — challenge.db 테이블, key scheduler, runs/ 구조. 키워드: DB, 테이블, run 디렉터리.
- **CANON-09 대시보드** — 검수함, 한국어 라벨, 포트/Tailscale, 브리지 서버. 키워드: dashboard, 검수, 8787, 8799.
- **CANON-10 검증 & 테스트** — factory-validate 라우팅, pytest, 알려진 flaky, tmp 복사 재검증 규칙. 키워드: validate, pytest, flaky, E2E.
- **CANON-11 Secret / 불변 규칙** — key 취급, 무변경 보존 대상, §7/§8/§13 원칙. 키워드: secret, .env, 금지사항.
- **CANON-12 Architecture Atlas & Structural Rules** — atlas 산출물/CLI/지문/검사 20항목. 키워드: atlas, architecture-build, architecture-check, fingerprint, manifest.
