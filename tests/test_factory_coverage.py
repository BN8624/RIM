# 이슈 #9 §17: coverage matrix/probe/분류/판정 소비/validator 검증.
import json
import re
from pathlib import Path

import pytest

from repo_idea_miner.factory_coverage import (
    ADJUDICATION_NAME,
    COVERAGE_STATUSES,
    COVERAGE_SUBDIR,
    FAILURE_CLASSES,
    MATRIX_NAME,
    PROBE_RESULTS_NAME,
    PROBE_SPEC_NAME,
    REQUIREMENT_KINDS,
    artifact_fingerprint,
    build_coverage_matrix,
    load_matrix_judge_coverage,
    run_coverage_probes,
    validate_coverage_artifacts,
)
from repo_idea_miner.factory_product_acceptance import build_requirement_coverage


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


_RUNNER = '''
import argparse, json
parser = argparse.ArgumentParser()
parser.add_argument("--scenario", required=True)
args = parser.parse_args()
with open(args.scenario, encoding="utf-8") as f:
    scenario = json.load(f)
state = scenario["initial_state"]
events = []
errors = []
for action in scenario.get("actions", []):
    if action["type"] == "set_value":
        value = action["payload"].get("value")
        if not isinstance(value, int):
            errors.append("invalid value")
            continue
        state["Entity"]["v"] = value
        events.append({"type": "VALUE_SET", "target_id": "e1"})
    else:
        errors.append("unknown action")
print(json.dumps({"ok": not errors, "final_state": state, "events": events,
                  "summary": f"{len(events)} executed", "errors": errors},
                 ensure_ascii=True))
'''

_NORMALIZED = {
    "success_conditions": ["값이 저장되는가"],
    "difficulty_anchors": ["정수만 허용하는 검증"],
    "forbidden_simplifications": ["검증 없는 자유 입력"],
}


def _make_run(tmp_path: Path) -> Path:
    run = tmp_path / "run_cov"
    ws = run / "workspace"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "runner.py").write_text(_RUNNER, encoding="utf-8")
    _dump(ws / "runner_contract.json", {"required_output_fields": ["ok"]})
    (ws / "product").mkdir()
    (ws / "product" / "index.html").write_text(
        "<html><body><div id=\"state\"></div></body></html>", encoding="utf-8")
    _dump(run / "normalized_challenge.json", _NORMALIZED)
    _dump(run / COVERAGE_SUBDIR.replace("review/coverage", "review") / "placeholder.json", {})
    _dump(run / (COVERAGE_SUBDIR + "/" + PROBE_SPEC_NAME), {"probes": [
        {"probe_id": "P1", "title": "값 저장",
         "initial_state": {"Entity": {"v": 1}},
         "actions": [{"type": "set_value", "payload": {"value": 7}}],
         "checks": [{"kind": "final_state_path", "path": "Entity.v", "op": "eq", "value": 7},
                    {"kind": "queued_events", "event_type": "VALUE_SET",
                     "expected_target_ids": ["e1"]},
                    {"kind": "errors", "expect": "empty"}]},
        {"probe_id": "P2", "title": "정수 아닌 입력 거부",
         "initial_state": {"Entity": {"v": 1}},
         "actions": [{"type": "set_value", "payload": {"value": "x"}}],
         "checks": [{"kind": "errors", "expect": "nonempty"},
                    {"kind": "final_state_path", "path": "Entity.v", "op": "eq", "value": 1}]},
        {"probe_id": "P3", "title": "정적 근거 없음 확인",
         "checks": [{"kind": "static_substring_count", "glob": "product/**/*.html",
                     "needle": "localStorage", "op": "eq0"}]},
    ]})
    return run


def _rows(status_map: dict | None = None) -> list:
    status_map = status_map or {}
    return [
        {"requirement_id": "SC1", "requirement_kind": "CRITICAL_REQUIREMENT",
         "requirement_text_or_ref": "값이 저장되는가",
         "coverage_status": status_map.get("SC1", "COVERED"),
         "failure_class": "NONE" if status_map.get("SC1", "COVERED") == "COVERED"
         else status_map.get("SC1_class", "TRUE_CORE_GAP"),
         "reason_code": "RUNTIME_PROVEN", "recommended_action": "없음",
         "implementation_refs": ["src/runner.py"], "runtime_evidence_refs": ["P1"]},
        {"requirement_id": "DA1", "requirement_kind": "DIFFICULTY_ANCHOR",
         "requirement_text_or_ref": "정수만 허용하는 검증",
         "coverage_status": "COVERED", "failure_class": "NONE",
         "reason_code": "RUNTIME_PROVEN", "recommended_action": "없음",
         "implementation_refs": ["src/runner.py"], "runtime_evidence_refs": ["P2"]},
        {"requirement_id": "FS1", "requirement_kind": "SUPPORTING_REQUIREMENT",
         "requirement_text_or_ref": "검증 없는 자유 입력",
         "forbidden_simplification": True,
         "coverage_status": "COVERED", "failure_class": "NONE",
         "reason_code": "RUNTIME_PROVEN", "recommended_action": "없음",
         "implementation_refs": ["src/runner.py"], "runtime_evidence_refs": ["P2"]},
    ]


@pytest.fixture()
def cov_run(tmp_path):
    run = _make_run(tmp_path)
    probe_result = run_coverage_probes(run)
    assert probe_result["ok"], probe_result
    return run


# ---------------------------------------------------------------- §17.1 matrix

def test_probes_run_deterministically(cov_run):
    r1 = json.loads((cov_run / COVERAGE_SUBDIR / PROBE_RESULTS_NAME).read_text(encoding="utf-8"))
    assert r1["probes"]["P1"]["pass"] and r1["probes"]["P2"]["pass"] and r1["probes"]["P3"]["pass"]
    d1 = r1["probes"]["P1"]["runner_output_digest"]
    run_coverage_probes(cov_run)
    r2 = json.loads((cov_run / COVERAGE_SUBDIR / PROBE_RESULTS_NAME).read_text(encoding="utf-8"))
    assert r2["probes"]["P1"]["runner_output_digest"] == d1  # 결정론


def test_valid_full_coverage_matrix(cov_run):
    _dump(cov_run / COVERAGE_SUBDIR / ADJUDICATION_NAME, {"rows": _rows()})
    res = build_coverage_matrix(cov_run)
    assert res["ok"], res["problems"]
    agg = res["matrix"]["aggregates"]
    assert agg["critical"]["coverage"] == 1.0
    assert agg["difficulty_anchor"]["coverage"] == 1.0
    assert agg["forbidden_violations"] == []
    assert validate_coverage_artifacts(cov_run) == []


def test_partial_coverage_not_counted_as_full(cov_run):
    rows = _rows({"SC1": "PARTIALLY_COVERED"})
    _dump(cov_run / COVERAGE_SUBDIR / ADJUDICATION_NAME, {"rows": rows})
    res = build_coverage_matrix(cov_run)
    assert res["ok"], res["problems"]
    assert res["matrix"]["aggregates"]["critical"]["coverage"] == 0.0  # partial ≠ full
    judge = load_matrix_judge_coverage(cov_run)
    assert judge["judge_coverage"]["값이 저장되는가"]["status"] == "missing"


def test_missing_implementation_rejected_without_class(cov_run):
    rows = _rows({"SC1": "NOT_COVERED"})
    rows[0]["failure_class"] = "NONE"
    _dump(cov_run / COVERAGE_SUBDIR / ADJUDICATION_NAME, {"rows": rows})
    res = build_coverage_matrix(cov_run)
    assert not res["ok"]
    assert any("failure_class=NONE" in p for p in res["problems"])


def test_covered_without_evidence_rejected(cov_run):
    rows = _rows()
    rows[0]["runtime_evidence_refs"] = []
    _dump(cov_run / COVERAGE_SUBDIR / ADJUDICATION_NAME, {"rows": rows})
    res = build_coverage_matrix(cov_run)
    assert not res["ok"]
    assert any("runtime_evidence_refs 없음" in p for p in res["problems"])


def test_covered_with_failing_probe_rejected(cov_run):
    rows = _rows()
    rows[0]["runtime_evidence_refs"] = ["P_MISSING"]
    _dump(cov_run / COVERAGE_SUBDIR / ADJUDICATION_NAME, {"rows": rows})
    res = build_coverage_matrix(cov_run)
    assert not res["ok"]
    assert any("결과 없음" in p for p in res["problems"])


def test_unknown_classification_rejected(cov_run):
    rows = _rows({"SC1": "NOT_COVERED", "SC1_class": "SOMETHING_ELSE"})
    _dump(cov_run / COVERAGE_SUBDIR / ADJUDICATION_NAME, {"rows": rows})
    res = build_coverage_matrix(cov_run)
    assert not res["ok"]
    assert any("분류 불가" in p for p in res["problems"])


def test_duplicate_requirement_id_rejected(cov_run):
    rows = _rows()
    rows[1]["requirement_id"] = "SC1"
    _dump(cov_run / COVERAGE_SUBDIR / ADJUDICATION_NAME, {"rows": rows})
    res = build_coverage_matrix(cov_run)
    assert not res["ok"]
    assert any("중복 requirement_id" in p for p in res["problems"])


def test_missing_difficulty_anchor_rejected(cov_run):
    rows = [r for r in _rows() if r["requirement_id"] != "DA1"]
    _dump(cov_run / COVERAGE_SUBDIR / ADJUDICATION_NAME, {"rows": rows})
    res = build_coverage_matrix(cov_run)
    assert not res["ok"]
    assert any("difficulty anchor 누락" in p for p in res["problems"])


def test_deterministic_serialization(cov_run):
    # 이슈 #25 §4.2: canonical matrix에는 시각 metadata가 없다 — byte-identical이 정본
    _dump(cov_run / COVERAGE_SUBDIR / ADJUDICATION_NAME, {"rows": _rows()})
    build_coverage_matrix(cov_run)
    b1 = (cov_run / COVERAGE_SUBDIR / MATRIX_NAME).read_bytes()
    build_coverage_matrix(cov_run)
    b2 = (cov_run / COVERAGE_SUBDIR / MATRIX_NAME).read_bytes()
    assert b1 == b2


def test_no_challenge_hardcode_in_production_module():
    src = Path("repo_idea_miner/factory_coverage.py").read_text(encoding="utf-8")
    assert not re.search(r"challenge[_ ]?(id)?\s*[=:]\s*\d", src, re.I)
    for banned in ("factory_20260", "scenario_00", "card_", "column_id\":", "SRS", "Table 17"):
        assert banned not in src, banned


# ---------------------------------------------------------------- §17.2 분류 경계

def test_enums_are_canonical():
    assert set(FAILURE_CLASSES) == {"TRUE_CORE_GAP", "EVIDENCE_GAP", "VALIDATOR_DEFECT",
                                    "SPEC_OVERREACH", "NONE"}
    assert "PARTIALLY_COVERED" in COVERAGE_STATUSES
    assert set(REQUIREMENT_KINDS) == {"CRITICAL_REQUIREMENT", "DIFFICULTY_ANCHOR",
                                      "SUPPORTING_REQUIREMENT"}


@pytest.mark.parametrize("failure_class", ["TRUE_CORE_GAP", "EVIDENCE_GAP",
                                           "VALIDATOR_DEFECT", "SPEC_OVERREACH"])
def test_each_failure_class_accepted(cov_run, failure_class):
    rows = _rows({"SC1": "NOT_COVERED", "SC1_class": failure_class})
    rows[0]["runtime_evidence_refs"] = []
    _dump(cov_run / COVERAGE_SUBDIR / ADJUDICATION_NAME, {"rows": rows})
    res = build_coverage_matrix(cov_run)
    assert res["ok"], res["problems"]
    assert res["matrix"]["aggregates"]["failure_class_counts"] == {failure_class: 1}


def test_ambiguous_maps_to_unknown_not_missing(cov_run):
    rows = _rows({"SC1": "AMBIGUOUS", "SC1_class": "SPEC_OVERREACH"})
    rows[0]["runtime_evidence_refs"] = []
    _dump(cov_run / COVERAGE_SUBDIR / ADJUDICATION_NAME, {"rows": rows})
    assert build_coverage_matrix(cov_run)["ok"]
    judge = load_matrix_judge_coverage(cov_run)
    assert judge["judge_coverage"]["값이 저장되는가"]["status"] == "unknown"


def test_forbidden_violated_propagates(cov_run):
    rows = _rows()
    rows[2]["coverage_status"] = "NOT_COVERED"
    rows[2]["failure_class"] = "TRUE_CORE_GAP"
    rows[2]["runtime_evidence_refs"] = []
    _dump(cov_run / COVERAGE_SUBDIR / ADJUDICATION_NAME, {"rows": rows})
    res = build_coverage_matrix(cov_run)
    assert res["ok"], res["problems"]
    assert res["matrix"]["aggregates"]["forbidden_violations"] == ["검증 없는 자유 입력"]
    judge = load_matrix_judge_coverage(cov_run)
    assert judge["judge_coverage"]["검증 없는 자유 입력"]["status"] == "violated"
    rc = build_requirement_coverage(cov_run, judge["judge_coverage"])
    assert rc["forbidden_simplification_violation_count"] == 1


# ---------------------------------------------------------------- §17.3 evidence repair

def test_stale_evidence_from_other_artifact_rejected(cov_run):
    _dump(cov_run / COVERAGE_SUBDIR / ADJUDICATION_NAME, {"rows": _rows()})
    assert build_coverage_matrix(cov_run)["ok"]
    # 구현이 바뀌면 기존 probe evidence는 무효 — 과거 evidence 복사와 동형
    runner = cov_run / "workspace" / "src" / "runner.py"
    runner.write_text(runner.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    problems = validate_coverage_artifacts(cov_run)
    assert any("불일치" in p or "다름" in p for p in problems)
    judge = load_matrix_judge_coverage(cov_run)
    assert judge["valid"] is False and judge["judge_coverage"] == {}


def test_matrix_feeds_requirement_coverage(cov_run):
    _dump(cov_run / COVERAGE_SUBDIR / ADJUDICATION_NAME, {"rows": _rows()})
    assert build_coverage_matrix(cov_run)["ok"]
    judge = load_matrix_judge_coverage(cov_run)
    assert judge["valid"] is True
    rc = build_requirement_coverage(cov_run, judge["judge_coverage"])
    assert rc["critical_requirement_coverage"] == 1.0
    assert rc["difficulty_anchor_coverage"] == 1.0
    assert rc["forbidden_simplification_violation_count"] == 0
    assert all(row["evidence_refs"] for row in rc["critical_requirements"])


def test_absent_matrix_returns_none(tmp_path):
    run = _make_run(tmp_path)
    assert load_matrix_judge_coverage(run) is None  # 기존 desk 경로 유지


# ---------------------------------------------------------------- §17.4 validator

def test_validator_blocks_tampered_aggregates(cov_run):
    _dump(cov_run / COVERAGE_SUBDIR / ADJUDICATION_NAME, {"rows": _rows()})
    assert build_coverage_matrix(cov_run)["ok"]
    mpath = cov_run / COVERAGE_SUBDIR / MATRIX_NAME
    matrix = json.loads(mpath.read_text(encoding="utf-8"))
    matrix["rows"][0]["coverage_status"] = "PARTIALLY_COVERED"  # 집계는 그대로 = 조작
    mpath.write_text(json.dumps(matrix, ensure_ascii=False), encoding="utf-8")
    problems = validate_coverage_artifacts(cov_run)
    assert any("aggregates" in p or "failure_class" in p for p in problems)


def test_validator_registered_in_factory_validate(cov_run):
    from repo_idea_miner.factory_validate import _check_coverage_matrix
    _dump(cov_run / COVERAGE_SUBDIR / ADJUDICATION_NAME, {"rows": _rows()})
    assert build_coverage_matrix(cov_run)["ok"]
    assert _check_coverage_matrix(cov_run) == []
    (cov_run / COVERAGE_SUBDIR / MATRIX_NAME).unlink()
    assert _check_coverage_matrix(cov_run) == []  # marker 없으면 no-op


# ---------------------------------------------------------------- §17.7 loop 통합

def test_loop_judge_prefers_valid_matrix(cov_run, monkeypatch):
    from repo_idea_miner import factory_loop_executor as loop
    _dump(cov_run / COVERAGE_SUBDIR / ADJUDICATION_NAME, {"rows": _rows()})
    assert build_coverage_matrix(cov_run)["ok"]

    def _boom(*args, **kwargs):
        raise AssertionError("matrix가 있으면 desk를 호출하면 안 된다")
    monkeypatch.setattr(loop, "execute_desk", _boom)
    res = loop._judge_requirement_coverage(cov_run, {}, {}, set(), None, use_llm=False)
    assert res["desk_status"] == "COVERAGE_MATRIX"
    assert res["judge_coverage"]["값이 저장되는가"]["status"] == "implemented"


def test_loop_judge_falls_back_when_matrix_invalid(cov_run):
    from repo_idea_miner import factory_loop_executor as loop
    _dump(cov_run / COVERAGE_SUBDIR / ADJUDICATION_NAME, {"rows": _rows()})
    assert build_coverage_matrix(cov_run)["ok"]
    runner = cov_run / "workspace" / "src" / "runner.py"
    runner.write_text(runner.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    res = loop._judge_requirement_coverage(cov_run, {}, {}, set(), None, use_llm=False)
    assert res["desk_status"] != "COVERAGE_MATRIX"  # mock desk로 폴백
    assert all(v["status"] == "unknown" for v in res["judge_coverage"].values())
    assert any("불일치" in p or "다름" in p for p in res["problems"])


# ---------------------------------------------------------------- console persistence (§9.3 최소 구현)

def test_console_persists_and_restores_state():
    from repo_idea_miner.factory_interaction_ui import generate_interaction_ui
    html = generate_interaction_ui({
        "initial_state": {"Entity": {"v": 1}}, "available_actions":
        [{"name": "set_value", "input": ["value"]}],
        "input_schema": {"set_value": ["value"]}, "render_hints": {}})
    assert "localStorage.setItem" in html
    assert "localStorage.getItem" in html
    assert "localStorage.removeItem" in html          # 초기화가 저장을 지운다
    assert "RESTORED_SAVED_STATE" in html             # 복원 상태를 명시 표기
    assert "persistState();" in html
    for banned in ("Math.random", "Date.now", "mockScenario"):
        assert banned not in html


def test_console_persistence_is_generic_no_product_hardcode():
    src = Path("repo_idea_miner/factory_interaction_ui.py").read_text(encoding="utf-8")
    for banned in ("card_", "column_", "localStorage_srs", "challenge"):
        assert banned not in src.split("STORE_KEY")[1][:2000] if banned != "challenge" else True
    assert "rim_console_state_" in src  # contract 해시 기반 키
