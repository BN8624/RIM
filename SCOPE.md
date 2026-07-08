# 구현 범위 설명서

## 구현된 범위 (RIM_FANAL.md 기준)

- 단일 레포 분석 (`run`): §3.1, §10.1 흐름 전체 (수집 → preflight → Bouncer → Scouts → Judge → validation → ceiling → truncation → 렌더링 → secret 검증)
- 검색어 기반 후보 분석 (`search`): §3.2, §10.2 (candidates.json, 후보별 카드, top_ideas.md, search_report.md)
- 산출물 검증 (`validate`): §9.3
- Mock / Live 모드: §3.3 (mock은 외부 LLM 호출 0회)
- Direct / Search input-mode: §3.4, §13 (direct는 낮은 activity만으로 hard drop 금지)
- google_genai_gemma provider: §4, §6 (google-genai SDK, 기본 모델 `gemma-4-31b-it`, `.env` override)
- 11개 key pool: §7 (round robin, AVAILABLE/TEMP_FAILED/DISABLED, key index만 기록)
- Retry/backoff/timeout: §8 (Retry-After 우선, exponential backoff + jitter, 고정 cooldown 미사용, 재시도 불가 오류 즉시 실패)
- GitHub collector: §12 (metadata/README/issues 3-bucket/PR bot 필터/file tree depth2/dependency origin)
- Issue body sampler: §14 (head+tail+키워드 문맥, 템플릿 섹션 압축, 1500자 제한)
- Issue signal tags: §15, comments/bike-shedding: §16
- Dependency/Runtime evidence: §17 (origin 기록, Docker 오탐 방지, collector는 risk 판단 안 함)
- Evidence packet: §18
- 5개 worker: §19 (Bouncer / README Scout / Pain Scout / Structure·Risk Scout / Critic·Judge)
- Worker JSON 원칙: §20 (JSON → parse → syntax repair 1회 → Pydantic → validator → renderer)
- Judge schema: §21~22, Pydantic validation: §23, JSON repair 제한: §24
- Length truncation: §25, Score Ceiling Validator: §26 (raw/final 분리 기록 §26.9)
- Verdict 규칙: §27, idea_card.md: §28, top_ideas.md: §29, run_report.md: §30, search_report.md: §31
- llm_calls.jsonl: §32, Secret redaction: §33 (패턴 + 로딩된 값 치환 + 최종 파일 스캔)
- 필수 테스트: §34 전체 (113개, pytest)

## 미구현 / 제외 범위 (§36 구현 금지 사항)

- 웹 대시보드 / 브라우저 UI
- 유튜브·블로그 콘텐츠 자동 생성
- 자동 프로젝트 생성
- 사용자 feedback 학습 시스템
- 장기 DB 구축
- 전체 코드 clone 후 정밀 코드리뷰
- PR 생성 / GitHub write action (모든 GitHub 호출은 read-only)
- 고정 1시간 key cooldown 정책
- API key / GitHub token 로그 출력

## 알려진 한계

- unique commenter / maintainer ratio는 high-comment bucket 이슈에 대해서만 댓글을 추가 수집한다 (API rate limit 절약). 나머지 이슈는 null로 기록되며 run_report의 `unique_commenters_available`에 표시된다.
- GitHub 검색은 REST search API 기본 정렬(best match)을 사용하고 `--explore`는 updated 정렬로 전환한다. `--targeted`는 현재 기본 정렬과 동일하게 동작한다.
- REST fallback 호출(§6.3)은 디버그용으로 명세만 따르며, 기본 경로는 항상 Python SDK다.
