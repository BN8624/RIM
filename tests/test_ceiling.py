# score ceiling validator 테스트 (§34.12).
from repo_idea_miner.ceiling import apply_score_ceiling


def keepish(judge_json, **overrides):
    j = dict(judge_json)
    j["verdict"] = "KEEP"
    j["score"] = 9
    for path, value in overrides.items():
        parts = path.split(".")
        if len(parts) == 1:
            j[parts[0]] = value
        else:
            j[parts[0]] = dict(j[parts[0]])
            j[parts[0]][parts[1]] = value
    return j


def test_unfit_area_no_keep_max5(judge_json):
    j = keepish(judge_json, **{"application.area": "적용 부적합"})
    r = apply_score_ceiling(j)
    assert r.validator_final_verdict != "KEEP"
    assert r.validator_final_score <= 5
    assert r.correction_applied


def test_mvp_impossible_no_poc_max4(judge_json):
    j = keepish(judge_json, **{"one_day_mvp.status": "축소 불가", "pattern_poc.status": "불가능"})
    r = apply_score_ceiling(j)
    assert r.validator_final_verdict != "KEEP"
    assert r.validator_final_score <= 4


def test_mvp_impossible_poc_possible_maybe_max6(judge_json):
    j = keepish(judge_json, **{"one_day_mvp.status": "축소 불가", "pattern_poc.status": "가능"})
    r = apply_score_ceiling(j)
    assert r.validator_final_verdict == "MAYBE"
    assert r.validator_final_score <= 6


def test_dependency_not_collected_no_ceiling(judge_json):
    j = keepish(judge_json, **{"dependency_runtime_risk.level": "not_collected"})
    r = apply_score_ceiling(j)
    assert r.validator_final_verdict == "KEEP"
    assert r.validator_final_score == 9


def test_dependency_unknown_no_keep(judge_json):
    j = keepish(judge_json, **{"dependency_runtime_risk.level": "unknown"})
    r = apply_score_ceiling(j)
    assert r.validator_final_verdict != "KEEP"


def test_runtime_high_no_keep_max5(judge_json):
    j = keepish(judge_json, **{"dependency_runtime_risk.level": "high"})
    r = apply_score_ceiling(j)
    assert r.validator_final_verdict != "KEEP"
    assert r.validator_final_score <= 5


def test_weak_issue_pain_max5(judge_json):
    stats = dict(judge_json["issue_signal_stats"])
    stats.update(product_pain_count=0, feature_request_count=0, workflow_pain_count=0, classified_issue_count=5, confidence="medium")
    j = keepish(judge_json, issue_signal_stats=stats)
    r = apply_score_ceiling(j)
    assert r.validator_final_verdict != "KEEP"
    assert r.validator_final_score <= 5


def test_install_skew_max4(judge_json):
    stats = dict(judge_json["issue_signal_stats"])
    stats.update(classified_issue_count=10, install_env_version_count=8, confidence="high")
    j = keepish(judge_json, issue_signal_stats=stats)
    r = apply_score_ceiling(j)
    assert r.validator_final_score <= 4


def test_clean_keep_untouched(judge_json):
    j = keepish(judge_json)
    r = apply_score_ceiling(j)
    assert r.validator_final_verdict == "KEEP"
    assert r.validator_final_score == 9
    assert not r.correction_applied


def test_raw_and_final_recorded(judge_json):
    j = keepish(judge_json, **{"dependency_runtime_risk.level": "high"})
    r = apply_score_ceiling(j)
    assert r.judge_raw_verdict == "KEEP" and r.judge_raw_score == 9
    assert r.correction_reason
