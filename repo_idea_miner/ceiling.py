# Judge의 KEEP 남발을 막는 Score Ceiling Validator 모듈. raw와 final을 분리 기록한다.
from __future__ import annotations

from dataclasses import dataclass, field

_CONF_ORDER = {"low": 0, "medium": 1, "high": 2}


@dataclass
class CeilingResult:
    final: dict
    judge_raw_verdict: str
    judge_raw_score: int
    validator_final_verdict: str
    validator_final_score: int
    correction_applied: bool
    correction_reason: str
    ceiling_rules_applied: list[str] = field(default_factory=list)


def apply_score_ceiling(judge: dict) -> CeilingResult:
    raw_verdict = judge["verdict"]
    raw_score = judge["score"]
    score = raw_score
    keep_banned = False
    applied: list[str] = []

    app_area = (judge.get("application") or {}).get("area")
    mvp_status = (judge.get("one_day_mvp") or {}).get("status")
    poc_status = (judge.get("pattern_poc") or {}).get("status")
    risk_level = (judge.get("dependency_runtime_risk") or {}).get("level")
    stats = judge.get("issue_signal_stats") or {}
    confidence = stats.get("confidence", "low")
    conf_at_least_medium = _CONF_ORDER.get(confidence, 0) >= 1

    def cap(limit: int, rule: str) -> None:
        nonlocal score
        applied.append(rule)
        if score > limit:
            score = limit

    # 26.2 적용 부적합 상한
    if app_area == "적용 부적합":
        cap(5, "application_unfit_max5_no_keep")
        keep_banned = True

    # 26.3 / 26.4 1일 MVP 축소 불가
    if mvp_status == "축소 불가":
        if poc_status == "가능":
            cap(6, "mvp_impossible_poc_possible_max6_no_keep")
            keep_banned = True
        else:
            cap(4, "mvp_impossible_no_poc_max4_no_keep")
            keep_banned = True

    # 26.5 Issue pain 약함 상한
    if (
        stats.get("product_pain_count", 0) == 0
        and stats.get("feature_request_count", 0) == 0
        and stats.get("workflow_pain_count", 0) == 0
        and stats.get("classified_issue_count", 0) >= 3
        and conf_at_least_medium
    ):
        cap(5, "weak_issue_pain_max5_no_keep")
        keep_banned = True

    # 26.6 설치/환경/버전 충돌 편중 상한
    classified = stats.get("classified_issue_count", 0)
    if (
        classified >= 5
        and stats.get("install_env_version_count", 0) / classified >= 0.7
        and conf_at_least_medium
    ):
        cap(4, "install_env_skew_max4")

    # 26.7 / 26.8 runtime risk 상한 (not_collected에는 ceiling 적용 금지)
    if risk_level == "high":
        cap(5, "runtime_risk_high_max5_no_keep")
        keep_banned = True
    elif risk_level == "unknown":
        applied.append("dependency_unknown_no_keep")
        keep_banned = True

    verdict = raw_verdict
    if keep_banned and verdict == "KEEP":
        verdict = "MAYBE" if score >= 4 else "DROP"
    # 점수 밴드와 verdict 정합 (§27)
    if score <= 3 and verdict != "DROP":
        verdict = "DROP"
    elif verdict == "KEEP" and score < 7:
        verdict = "MAYBE"

    corrected = (verdict != raw_verdict) or (score != raw_score)
    reason = "; ".join(applied) if corrected else ""

    final = dict(judge)
    final["verdict"] = verdict
    final["score"] = score
    final["ceiling_rules_applied"] = applied

    return CeilingResult(
        final=final,
        judge_raw_verdict=raw_verdict,
        judge_raw_score=raw_score,
        validator_final_verdict=verdict,
        validator_final_score=score,
        correction_applied=corrected,
        correction_reason=reason,
        ceiling_rules_applied=applied,
    )
