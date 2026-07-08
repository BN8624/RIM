# Repo Idea Miner 납품 체크리스트

RIM_FANAL.md §35/§37 기준. 2026-07-08 완료.

## 검수 (§35)
- [x] 35.1 단일 레포 mock 검수 — `runs/20260708_062637` (validate PASS)
- [x] 35.2 단일 레포 live 검수 — `runs/20260708_062704` (gemma-4-31b-it, key 회전 1→6, failover 1회 처리, validate PASS)
- [x] 35.3 검색어 mock 검수 — `runs/20260708_063201` (5후보, validate PASS)
- [x] 35.4 검색어 live 검수 — `runs/20260708_063306` (3후보, 11개 key 전부 회전, validate PASS)
- [x] 35.5 pytest — 113 passed

## 납품물 (§37)
- [x] 전체 소스코드 (`repo_idea_miner/`)
- [x] README.md (설치/실행 예시/환경변수)
- [x] .env.example (.env는 미포함, .gitignore 처리)
- [x] 테스트 코드 (`tests/`, §34 전체)
- [x] 샘플 산출물 (`samples/` — idea_card, run_report, top_ideas, search_report, evidence_packet, worker JSON, llm_calls.jsonl)
- [x] google_genai_gemma provider / key pool / rotation / retry / failover
- [x] secret redaction + 테스트
- [x] 구현/미구현 범위 명시 (SCOPE.md)

## 남은 작업
- (없음)

# Challenge Mode 추가 (ChallengeMode주문서.md) — 2026-07-09 완료

## 구현 (§3~§26)
- [x] challenge_schemas.py — OwnerBrief/ScreenStory/ChallengeCard/ChallengePackage/ChallengeIndex + §9 자동 판정 규칙
- [x] challenge_prompts.py — 통합 challenge_package prompt(§10~§11) + mock 고정 샘플(§24)
- [x] challenge_renderer.py — owner_brief/screen_story/challenge_card/implementation_prompt.md + viewer.html
- [x] challenge_db.py — challenge.db 7개 테이블(§16) + validate_db
- [x] challenge_pipeline.py / challenge_search_pipeline.py — LLM 1회 호출, §23 정렬, 실패 격리
- [x] challenge_key_scheduler.py — 11-key controlled parallel pool, 429/500 per-key cooldown(§18~§19)
- [x] challenge_daemon.py — seed refill/queue/병렬 처리/pause·resume/status(§17)
- [x] challenge_dashboard.py — Today/목록 필터/상세 탭/SAVE·MAYBE·DROP·BUILD NEXT·MARK BUILT(§22)
- [x] challenge_validate.py + cli.py 8개 명령 추가 (기존 run/search/view/serve/validate 무변경)

## 검수 (§29~§30)
- [x] challenge mock — `runs/20260708_153455` (validate PASS)
- [x] challenge live — `runs/20260708_153519` (GOOD_CHALLENGE, validate PASS)
- [x] challenge-search mock — `runs/20260708_153725` (3건, validate PASS)
- [x] challenge-search live — `runs/20260708_153754` (2건, validate --db PASS)
- [x] daemon --once mock — 11 key 병렬 11건 처리, 에러 0
- [x] dashboard — 목록/필터/상세 탭/판정 POST/COPY 확인
- [x] validate-db PASS / pytest 238 passed (기존 113개 포함)
