# 검증된 judge JSON을 idea_card.md / run_report.md / top_ideas.md / search_report.md로 렌더링하는 모듈.
from __future__ import annotations

IDEA_CARD_SECTIONS = [
    "## 판정",
    "## FAST DROP에 가까운가",
    "## 점수",
    "## 한 줄 결론",
    "## 왜 사람들이 관심 가졌나",
    "## 실제 사용자 고통",
    "## 기능 요청 신호",
    "## 워크플로우/자동화 신호",
    "## 가져올 패턴",
    "## 버릴 것",
    "## Dependency / Runtime Risk",
    "## 내 현재 병목에 적용",
    "## 1일 MVP",
    "## 1일 Pattern PoC",
    "## 만들면 망하는 이유",
    "## 왜 이 판정인가",
    "## 다음 행동",
]

RUN_REPORT_SECTIONS = [
    "## Input",
    "## Preflight",
    "## Collector Status",
    "## Issue Sampler",
    "## Comments Signal",
    "## LLM Key Pool",
    "## Missing Data",
    "## Errors",
    "## JSON Validation",
    "## Content Gate",
    "## Length Truncation",
    "## Judge Raw",
    "## Validator Final",
    "## Ceiling Rules",
    "## Secret Redaction",
    "## Token/API Key Exposure",
    "## Output Files",
]


def _bullets(items: list | None) -> str:
    items = [i for i in (items or []) if i]
    if not items:
        return "- (없음)"
    return "\n".join(f"- {i}" for i in items)


def render_idea_card(final: dict, repo_full_name: str) -> str:
    risk = final.get("dependency_runtime_risk") or {}
    app = final.get("application") or {}
    mvp = final.get("one_day_mvp") or {}
    poc = final.get("pattern_poc") or {}
    return f"""# Repo Idea Card

레포: {repo_full_name}

## 판정
{final.get('verdict')}

## FAST DROP에 가까운가
{'YES' if final.get('fast_drop') else 'NO'}

## 점수
{final.get('score')}

## 한 줄 결론
{final.get('one_line_conclusion')}

## 왜 사람들이 관심 가졌나
{final.get('why_people_cared') or '(불확실)'}

## 실제 사용자 고통
{_bullets(final.get('user_pain'))}

## 기능 요청 신호
{_bullets(final.get('feature_requests'))}

## 워크플로우/자동화 신호
{_bullets(final.get('workflow_pain'))}

## 가져올 패턴
{final.get('core_pattern') or '(불확실)'}

## 버릴 것
{_bullets(final.get('what_to_ignore'))}

## Dependency / Runtime Risk
- level: {risk.get('level')}
- reason: {risk.get('reason')}

## 내 현재 병목에 적용
- area: {app.get('area')}
- related_project: {app.get('related_project')}
- reason: {app.get('reason')}

## 1일 MVP
- status: {mvp.get('status')}
- feature: {mvp.get('feature')}
- input: {mvp.get('input')}
- output: {mvp.get('output')}
- excluded_scope: {', '.join(mvp.get('excluded_scope') or []) or '(없음)'}
- reason: {mvp.get('reason')}

## 1일 Pattern PoC
- status: {poc.get('status')}
- idea: {poc.get('idea')}
- input: {poc.get('input')}
- output: {poc.get('output')}
- reason: {poc.get('reason')}

## 만들면 망하는 이유
{_bullets(final.get('why_it_fails'))}

## 왜 이 판정인가
{_bullets(final.get('why_drop_or_keep'))}

## 다음 행동
{final.get('next_action')}
"""


def render_fast_drop_card(repo_full_name: str, reason: str, source: str) -> str:
    """preflight 또는 bouncer FAST DROP용 축약 카드. 필수 섹션은 유지한다."""
    filler = f"FAST DROP ({source}): 상세 분석을 실행하지 않았다."
    return f"""# Repo Idea Card

레포: {repo_full_name}

## 판정
DROP

## FAST DROP에 가까운가
YES

## 점수
0

## 한 줄 결론
{reason}

## 왜 사람들이 관심 가졌나
{filler}

## 실제 사용자 고통
- (수집 안 함)

## 기능 요청 신호
- (수집 안 함)

## 워크플로우/자동화 신호
- (수집 안 함)

## 가져올 패턴
(없음)

## 버릴 것
- 레포 전체

## Dependency / Runtime Risk
- level: not_collected
- reason: FAST DROP으로 분석 생략

## 내 현재 병목에 적용
- area: 적용 부적합
- related_project: (없음)
- reason: {filler}

## 1일 MVP
- status: 불확실
- feature: (없음)
- input: (없음)
- output: (없음)
- excluded_scope: (없음)
- reason: 분석 생략

## 1일 Pattern PoC
- status: 불확실
- idea: (없음)
- input: (없음)
- output: (없음)
- reason: 분석 생략

## 만들면 망하는 이유
- {reason}

## 왜 이 판정인가
- {reason}

## 다음 행동
다른 후보 레포를 본다
"""


def render_run_report(ctx: dict) -> str:
    """§30 형식의 run_report.md."""
    g = ctx.get
    ceiling = g("ceiling") or {}
    trunc = g("truncation") or {}
    sampler = g("issue_sampler") or {}
    comments = g("comments_signal") or {}
    pool = g("key_pool") or {}
    collector = g("collector_status") or {}
    return f"""# Run Report

## Input
- repo: {g('repo')}
- mode: {g('mode')}
- input_mode: {g('input_mode')}
- timestamp: {g('timestamp')}

## Preflight
- status: {g('preflight_status')}
- reason: {g('preflight_reason')}

## Collector Status
- metadata: {collector.get('metadata', 'SKIPPED')}
- readme: {collector.get('readme', 'SKIPPED')}
- issues: {collector.get('issues', 'SKIPPED')}
- prs: {collector.get('prs', 'SKIPPED')}
- file_tree: {collector.get('file_tree', 'SKIPPED')}
- dependency: {collector.get('dependency', 'SKIPPED')}

## Issue Sampler
- sampled_issue_count: {sampler.get('sampled_issue_count', 0)}
- sample_max_chars: 1500
- template_sections_compressed: {sampler.get('template_sections_compressed', 'YES')}
- defect_count: {sampler.get('defect_count', 0)}
- feature_request_count: {sampler.get('feature_request_count', 0)}
- workflow_pain_count: {sampler.get('workflow_pain_count', 0)}
- confusion_count: {sampler.get('confusion_count', 0)}
- noise_count: {sampler.get('noise_count', 0)}
- uncertain_count: {sampler.get('uncertain_count', 0)}

## Comments Signal
- high_comment_issue_count: {comments.get('high_comment_issue_count', 0)}
- unique_commenters_available: {comments.get('unique_commenters_available', 'NO')}
- bike_shedding_possible_count: {comments.get('bike_shedding_possible_count', 0)}

## LLM Key Pool
- provider: {pool.get('provider')}
- model: {pool.get('model')}
- configured_key_count: {pool.get('configured_key_count')}
- loaded_key_count: {pool.get('loaded_key_count')}
- strategy: {pool.get('strategy')}
- used_key_indexes: {pool.get('used_key_indexes')}
- disabled_key_indexes: {pool.get('disabled_key_indexes')}
- temp_failed_key_indexes: {pool.get('temp_failed_key_indexes')}
- retry_count: {pool.get('retry_count')}
- failover_count: {pool.get('failover_count')}
- retry_backoff_strategy: {pool.get('retry_backoff_strategy')}
- retry_initial_delay_seconds: {pool.get('retry_initial_delay_seconds')}
- retry_max_delay_seconds: {pool.get('retry_max_delay_seconds')}
- request_timeout_seconds: {pool.get('request_timeout_seconds')}
- respect_retry_after: {pool.get('respect_retry_after')}

## Missing Data
{_bullets(g('missing_data'))}

## Errors
{_bullets(g('errors'))}

## JSON Validation
{g('json_validation', 'FAIL')}

## Content Gate
{g('content_gate', 'FAIL')}

## Length Truncation
- length_truncated: {'YES' if trunc.get('truncated_fields') else 'NO'}
- truncated_field_count: {len(trunc.get('truncated_fields') or [])}
- truncated_fields: {', '.join(trunc.get('truncated_fields') or []) or '(없음)'}

## Judge Raw
- raw_verdict: {ceiling.get('judge_raw_verdict')}
- raw_score: {ceiling.get('judge_raw_score')}

## Validator Final
- final_verdict: {ceiling.get('validator_final_verdict')}
- final_score: {ceiling.get('validator_final_score')}

## Ceiling Rules
- applied: {', '.join(ceiling.get('ceiling_rules_applied') or []) or '(없음)'}
- corrected: {'YES' if ceiling.get('correction_applied') else 'NO'}
- correction_reason: {ceiling.get('correction_reason') or '(없음)'}
- before_score: {ceiling.get('judge_raw_score')}
- after_score: {ceiling.get('validator_final_score')}
- before_verdict: {ceiling.get('judge_raw_verdict')}
- after_verdict: {ceiling.get('validator_final_verdict')}

## Secret Redaction
{g('secret_redaction', 'FAIL')}

## Token/API Key Exposure
{g('token_exposure', 'NO')}

## Output Files
{_bullets(g('output_files'))}
"""


def render_top_ideas(query: str, results: list[dict], top: int) -> str:
    analyzed = [r for r in results if r.get("verdict")]
    fast_drops = [r for r in results if r.get("fast_drop")]
    keeps = sorted((r for r in analyzed if r["verdict"] == "KEEP"), key=lambda r: -(r.get("score") or 0))
    maybes = sorted((r for r in analyzed if r["verdict"] == "MAYBE"), key=lambda r: -(r.get("score") or 0))
    drops = [r for r in analyzed if r["verdict"] == "DROP"]

    def entry(r):
        return f"- **{r['repo']}** (score {r.get('score')}): {r.get('one_line_conclusion') or ''}"

    lines = [
        "# Top Ideas",
        "",
        "## 검색어",
        query,
        "",
        "## 전체 요약",
        f"- 분석 후보 수: {len(results)}",
        f"- FAST DROP 수: {len(fast_drops)}",
        f"- KEEP 수: {len(keeps)}",
        f"- MAYBE 수: {len(maybes)}",
        f"- DROP 수: {len(drops)}",
        "",
        "## Top KEEP",
    ]
    lines += [entry(r) for r in keeps[:top]] or ["KEEP 없음"]
    lines += ["", "## Top MAYBE"]
    lines += [entry(r) for r in maybes[:top]] or ["MAYBE 없음"]
    lines += ["", "## 빠르게 버린 후보"]
    lines += [f"- {r['repo']}: {r.get('drop_reason') or r.get('one_line_conclusion') or 'FAST DROP'}" for r in fast_drops] or ["(없음)"]
    lines += ["", "## 비교해볼 만한 패턴"]
    patterns = [f"- {r['repo']}: {r['core_pattern']}" for r in analyzed if r.get("core_pattern")]
    lines += patterns[:top] or ["(없음)"]
    lines += ["", "## 다음 행동"]
    if keeps:
        lines.append("KEEP 후보의 1일 MVP 범위를 확정하고 착수한다.")
    elif maybes:
        lines.append("MAYBE 상위 후보를 유사 레포와 비교해 KEEP/DROP을 확정한다.")
    else:
        lines.append("KEEP 없음. 검색어를 바꿔 새 후보를 수집한다.")
    lines.append("")
    return "\n".join(lines)


def render_search_report(ctx: dict) -> str:
    g = ctx.get
    pool = g("key_pool") or {}
    correction_rate = g("correction_rate", 0.0)
    rate_flag = ""
    if correction_rate > 0.6:
        rate_flag = " (FAIL: correction rate > 60%)"
    elif correction_rate > 0.4:
        rate_flag = " (경고: correction rate > 40%)"
    return f"""# Search Report

## Query
{g('query')}

## Candidate Collection
- requested_limit: {g('requested_limit')}
- collected_count: {g('collected_count')}
- after_preflight_count: {g('after_preflight_count')}
- analyzed_count: {g('analyzed_count')}

## Preflight Summary
- proceed: {g('proceed_count', 0)}
- low_signal_proceed: {g('low_signal_count', 0)}
- fast_drop_preflight: {g('fast_drop_count', 0)}
- error_stop: {g('error_stop_count', 0)}

## Verdict Summary
- keep: {g('keep_count', 0)}
- maybe: {g('maybe_count', 0)}
- drop: {g('drop_count', 0)}

## LLM Key Pool Summary
- configured_key_count: {pool.get('configured_key_count')}
- loaded_key_count: {pool.get('loaded_key_count')}
- used_key_indexes: {pool.get('used_key_indexes')}
- disabled_key_indexes: {pool.get('disabled_key_indexes')}
- retry_count: {pool.get('retry_count')}
- failover_count: {pool.get('failover_count')}

## Validator Correction Summary
- correction_count: {g('correction_count', 0)}
- correction_rate: {round(correction_rate * 100, 1)}%{rate_flag}

## Errors
{_bullets(g('errors'))}

## Output Files
{_bullets(g('output_files'))}
"""
