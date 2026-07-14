# 이슈 #25: deterministic coverage matrix automation — 생성/재사용/stale rebuild/semantic fallback 제한.
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from repo_idea_miner.factory_coverage import (
    ADJUDICATION_NAME,
    COVERAGE_PROBE_FAILED,
    COVERAGE_SEMANTIC_INFRA_FAIL,
    COVERAGE_SUBDIR,
    FINGERPRINT_VERSION,
    MATRIX_NAME,
    PROBE_RESULTS_NAME,
    PROBE_SPEC_NAME,
    artifact_fingerprint,
    ensure_deterministic_coverage_matrix,
    generate_probe_spec,
    load_matrix_judge_coverage,
    matrix_semantic_digest,
    normalized_challenge_digest,
    validate_coverage_artifacts,
)
from repo_idea_miner.factory_desks import DeskError


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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

_PROBES = [
    {"probe_id": "P1", "title": "값 저장",
     "initial_state": {"Entity": {"v": 1}},
     "actions": [{"type": "set_value", "payload": {"value": 7}}],
     "checks": [{"kind": "final_state_path", "path": "Entity.v", "op": "eq", "value": 7},
                {"kind": "errors", "expect": "empty"}],
     "covers": ["값이 저장되는가"]},
    {"probe_id": "P2", "title": "정수 아닌 입력 거부",
     "initial_state": {"Entity": {"v": 1}},
     "actions": [{"type": "set_value", "payload": {"value": "x"}}],
     "checks": [{"kind": "errors", "expect": "nonempty"},
                {"kind": "final_state_path", "path": "Entity.v", "op": "eq", "value": 1}],
     "covers": ["정수만 허용하는 검증", "검증 없는 자유 입력"]},
]


def _make_run(tmp_path: Path, name: str = "run_auto", with_spec: bool = True) -> Path:
    run = tmp_path / name
    ws = run / "workspace"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "runner.py").write_text(_RUNNER, encoding="utf-8")
    _dump(ws / "runner_contract.json", {"required_output_fields": ["ok"]})
    (ws / "product").mkdir()
    (ws / "product" / "index.html").write_text(
        "<html><body><div id=\"state\"></div></body></html>", encoding="utf-8")
    _dump(run / "normalized_challenge.json", _NORMALIZED)
    if with_spec:
        _dump(run / COVERAGE_SUBDIR / PROBE_SPEC_NAME, {
            "schema_version": 2,
            "challenge_digest": normalized_challenge_digest(_NORMALIZED),
            "probes": _PROBES,
            "requirements": [
                {"requirement_id": "SC1", "requirement_kind": "CRITICAL_REQUIREMENT",
                 "requirement_text_or_ref": "값이 저장되는가",
                 "adjudication_mode": "DETERMINISTIC_RUNTIME", "probe_refs": ["P1"]},
                {"requirement_id": "DA1", "requirement_kind": "DIFFICULTY_ANCHOR",
                 "requirement_text_or_ref": "정수만 허용하는 검증",
                 "adjudication_mode": "DETERMINISTIC_RUNTIME", "probe_refs": ["P2"]},
                {"requirement_id": "FS1", "requirement_kind": "SUPPORTING_REQUIREMENT",
                 "requirement_text_or_ref": "검증 없는 자유 입력",
                 "forbidden_simplification": True,
                 "adjudication_mode": "DETERMINISTIC_RUNTIME", "probe_refs": ["P2"]},
            ],
        })
    return run


class FakeExecutor:
    """desk 호출을 흉내내는 executor — schema_name별 응답/예외를 재생하고 호출을 기록한다."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[str] = []

    def call(self, schema_name, prompt, model_cls):
        self.calls.append(schema_name)
        resp = self.responses.get(schema_name)
        if isinstance(resp, Exception):
            raise resp
        if resp is None:
            raise AssertionError(f"예상 밖 desk 호출: {schema_name}")
        return SimpleNamespace(model_dump=lambda: json.loads(json.dumps(resp))), "FAKE"


class BoomExecutor:
    def call(self, schema_name, prompt, model_cls):
        raise AssertionError(f"LLM desk가 호출되면 안 된다: {schema_name}")


# ---------------------------------------------------------------- §6.1 matrix 없음 → 자동 생성

def test_absent_matrix_auto_generated_without_llm(tmp_path):
    run = _make_run(tmp_path)
    res = ensure_deterministic_coverage_matrix(run, executor=BoomExecutor())
    assert res["status"] == "OK", res
    assert res["action"] == "GENERATED"
    assert res["desk_calls"] == {"probe_spec": 0, "semantic": 0}
    assert (run / COVERAGE_SUBDIR / MATRIX_NAME).is_file()
    assert (run / COVERAGE_SUBDIR / PROBE_RESULTS_NAME).is_file()
    assert validate_coverage_artifacts(run) == []
    assert res["deterministic_row_count"] == 3
    assert res["semantic_row_count"] == 0
    judge = load_matrix_judge_coverage(run)
    assert judge["valid"] is True
    assert judge["judge_coverage"]["값이 저장되는가"]["status"] == "implemented"
    assert judge["judge_coverage"]["검증 없는 자유 입력"]["status"] == "respected"


def test_absent_spec_without_executor_falls_to_semantic_hold_rows(tmp_path):
    """spec도 executor도 없으면 전 requirement가 정직한 AMBIGUOUS semantic row가 된다 —
    과대평가 없이 matrix 자체는 유효하고, LLM desk fallback은 일어나지 않는다."""
    run = _make_run(tmp_path, with_spec=False)
    res = ensure_deterministic_coverage_matrix(run)
    assert res["status"] == "OK"
    assert res["action"] == "SEMANTIC_FALLBACK_REQUIRED"
    assert res["semantic_row_count"] == 3
    judge = load_matrix_judge_coverage(run)
    assert judge["valid"] is True
    assert all(v["status"] == "unknown" for v in judge["judge_coverage"].values())


# ---------------------------------------------------------------- §6.2 유효 matrix → 재사용

def test_valid_matrix_reused_with_identical_digest(tmp_path):
    run = _make_run(tmp_path)
    first = ensure_deterministic_coverage_matrix(run, executor=BoomExecutor())
    assert first["action"] == "GENERATED"
    second = ensure_deterministic_coverage_matrix(run, executor=BoomExecutor())
    assert second["status"] == "OK"
    assert second["action"] == "REUSED"
    assert second["matrix_semantic_digest"] == first["matrix_semantic_digest"]
    assert second["desk_calls"] == {"probe_spec": 0, "semantic": 0}


# ---------------------------------------------------------------- §6.3 artifact 변경 → stale rebuild

@pytest.mark.parametrize("rel", ["src/runner.py", "product/index.html"])
def test_artifact_change_triggers_stale_rebuild(tmp_path, rel):
    run = _make_run(tmp_path)
    first = ensure_deterministic_coverage_matrix(run)
    target = run / "workspace" / rel
    target.write_text(target.read_text(encoding="utf-8") + "\n<!-- drift -->\n"
                      if rel.endswith(".html") else
                      target.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    res = ensure_deterministic_coverage_matrix(run)
    assert res["status"] == "OK"
    assert res["action"] == "REBUILT_STALE"
    assert res["artifact_fingerprint"] != first["artifact_fingerprint"]
    assert validate_coverage_artifacts(run) == []


def test_fingerprint_v2_covers_product_surface(tmp_path):
    run = _make_run(tmp_path)
    root = run / "workspace"
    v2_before = artifact_fingerprint(root)
    v1_before = artifact_fingerprint(root, version=1)
    html = root / "product" / "index.html"
    html.write_text(html.read_text(encoding="utf-8") + "<!-- x -->", encoding="utf-8")
    assert artifact_fingerprint(root) != v2_before          # v2는 product 변경 감지
    assert artifact_fingerprint(root, version=1) == v1_before  # v1은 legacy 재검증 호환
    assert FINGERPRINT_VERSION == 2


# ---------------------------------------------------------------- §6.4 challenge 변경 → stale 거부

def test_challenge_change_rejects_stale_matrix(tmp_path):
    run = _make_run(tmp_path)
    ensure_deterministic_coverage_matrix(run)
    changed = json.loads(json.dumps(_NORMALIZED))
    changed["success_conditions"] = ["값이 두 배로 저장되는가"]
    _dump(run / "normalized_challenge.json", changed)
    problems = validate_coverage_artifacts(run)
    assert any("challenge" in p or "누락" in p for p in problems)  # stale matrix 소비 금지
    res = ensure_deterministic_coverage_matrix(run)
    assert res["action"] in ("REBUILT_STALE",)
    matrix = _load(run / COVERAGE_SUBDIR / MATRIX_NAME)
    texts = {r["requirement_text_or_ref"] for r in matrix["rows"]}
    assert "값이 두 배로 저장되는가" in texts
    assert "값이 저장되는가" not in texts


# ---------------------------------------------------------------- §6.5 동일 입력 → byte-identical

def test_identical_input_byte_identical_matrix(tmp_path):
    run_a = _make_run(tmp_path / "a")
    run_b = _make_run(tmp_path / "b")
    ra = ensure_deterministic_coverage_matrix(run_a)
    rb = ensure_deterministic_coverage_matrix(run_b)
    assert ra["matrix_semantic_digest"] == rb["matrix_semantic_digest"]
    assert (run_a / COVERAGE_SUBDIR / MATRIX_NAME).read_bytes() == \
        (run_b / COVERAGE_SUBDIR / MATRIX_NAME).read_bytes()
    pa = _load(run_a / COVERAGE_SUBDIR / PROBE_RESULTS_NAME)
    pb = _load(run_b / COVERAGE_SUBDIR / PROBE_RESULTS_NAME)
    assert pa["probes"] == pb["probes"]


# ---------------------------------------------------------------- §6.6·§6.9 오염 → 자동 재생성

def test_tampered_adjudication_rebuilt_not_consumed(tmp_path):
    run = _make_run(tmp_path)
    ensure_deterministic_coverage_matrix(run)
    adj = _load(run / COVERAGE_SUBDIR / ADJUDICATION_NAME)
    adj["rows"][0]["runtime_evidence_refs"] = []  # COVERED인데 evidence 없음
    _dump(run / COVERAGE_SUBDIR / ADJUDICATION_NAME, adj)
    matrix_path = run / COVERAGE_SUBDIR / MATRIX_NAME
    matrix = _load(matrix_path)
    matrix["rows"][0]["runtime_evidence_refs"] = []
    _dump(matrix_path, matrix)
    assert validate_coverage_artifacts(run) != []  # 소비 금지
    res = ensure_deterministic_coverage_matrix(run)
    assert res["status"] == "OK"
    assert res["action"] == "REBUILT_STALE"
    assert validate_coverage_artifacts(run) == []


def test_tampered_aggregates_rebuilt(tmp_path):
    run = _make_run(tmp_path)
    ensure_deterministic_coverage_matrix(run)
    matrix_path = run / COVERAGE_SUBDIR / MATRIX_NAME
    matrix = _load(matrix_path)
    matrix["rows"][0]["coverage_status"] = "PARTIALLY_COVERED"  # 집계 그대로 = 조작
    _dump(matrix_path, matrix)
    assert validate_coverage_artifacts(run) != []
    res = ensure_deterministic_coverage_matrix(run)
    assert res["action"] == "REBUILT_STALE"
    assert validate_coverage_artifacts(run) == []


# ---------------------------------------------------------------- §6.10 deterministic이면 LLM 금지

def test_all_deterministic_never_calls_llm(tmp_path):
    run = _make_run(tmp_path)
    for _ in range(3):
        res = ensure_deterministic_coverage_matrix(run, executor=BoomExecutor())
        assert res["status"] == "OK"
        assert res["desk_calls"] == {"probe_spec": 0, "semantic": 0}
    judge = load_matrix_judge_coverage(run)
    assert judge["valid"] is True


# ---------------------------------------------------------------- §6.11 semantic row만 제한 fallback

def _spec_with_semantic_da1(run: Path) -> None:
    spec = _load(run / COVERAGE_SUBDIR / PROBE_SPEC_NAME)
    spec["probes"] = [p for p in spec["probes"] if p["probe_id"] == "P1"] + [
        {"probe_id": "P2", "title": "금지 단순화 부재",
         "initial_state": {"Entity": {"v": 1}},
         "actions": [{"type": "set_value", "payload": {"value": "x"}}],
         "checks": [{"kind": "errors", "expect": "nonempty"}],
         "covers": ["검증 없는 자유 입력"]}]
    for row in spec["requirements"]:
        if row["requirement_id"] == "DA1":
            row["adjudication_mode"] = "SEMANTIC_ADJUDICATION"
            row["probe_refs"] = []
    _dump(run / COVERAGE_SUBDIR / PROBE_SPEC_NAME, spec)


def test_semantic_rows_limited_fallback_merged_into_matrix(tmp_path):
    """이슈 #26: semantic desk는 structured claim을 제안하고, validator가 실제 내용을
    재검사한 경우에만 COVERED가 matrix에 병합된다."""
    run = _make_run(tmp_path)
    _spec_with_semantic_da1(run)
    executor = FakeExecutor({"coverage_semantic_claims": {"items": [
        {"requirement": "정수만 허용하는 검증", "raw_coverage_status": "COVERED",
         "claims": [{"claim_type": "FILE_CONTAINS", "file": "workspace/src/runner.py",
                     "expected": {"required_tokens": ["invalid value"]}}]},
    ]}})
    res = ensure_deterministic_coverage_matrix(run, executor=executor)
    assert res["status"] == "OK"
    # semantic desk 1회만 — 전체 requirement 재판정 없음, probe spec desk 호출 없음
    assert executor.calls == ["coverage_semantic_claims"]
    assert res["deterministic_row_count"] == 2
    assert res["semantic_row_count"] == 1
    assert res["validated_semantic_covered_count"] == 1
    assert res["plain_path_covered_count"] == 0
    assert validate_coverage_artifacts(run) == []
    judge = load_matrix_judge_coverage(run)
    assert judge["judge_coverage"]["정수만 허용하는 검증"]["status"] == "implemented"
    assert judge["judge_coverage"]["값이 저장되는가"]["status"] == "implemented"
    # 이후 검증은 재사용 — desk 재호출 없음 (판정 요동 무력화의 근거)
    res2 = ensure_deterministic_coverage_matrix(run, executor=BoomExecutor())
    assert res2["action"] == "REUSED"


def test_semantic_covered_without_claims_demoted(tmp_path):
    """§6.1: 파일 경로만 인용한 raw COVERED(claim 없음)는 AMBIGUOUS로 강등된다 —
    implemented로 산입 금지."""
    run = _make_run(tmp_path)
    _spec_with_semantic_da1(run)
    executor = FakeExecutor({"coverage_semantic_claims": {"items": [
        {"requirement": "정수만 허용하는 검증", "raw_coverage_status": "COVERED",
         "coverage_status": "COVERED",
         "evidence_refs": ["workspace/src/runner.py"], "claims": []},
    ]}})
    res = ensure_deterministic_coverage_matrix(run, executor=executor)
    assert res["status"] == "OK"
    assert res["validated_semantic_covered_count"] == 0
    assert res["plain_path_covered_count"] == 0
    judge = load_matrix_judge_coverage(run)
    assert judge["judge_coverage"]["정수만 허용하는 검증"]["status"] == "unknown"  # 강등


# ---------------------------------------------------------------- §6.12 transient 500 ≠ 미구현

def test_semantic_infra_fail_not_converted_to_not_covered(tmp_path):
    run = _make_run(tmp_path)
    _spec_with_semantic_da1(run)
    executor = FakeExecutor({
        "coverage_semantic_claims": DeskError("HTTP 500", kind="transient")})
    res = ensure_deterministic_coverage_matrix(run, executor=executor)
    assert res["status"] == "FAILED"
    assert res["failure_type"] == COVERAGE_SEMANTIC_INFRA_FAIL
    assert res["infra_failure"] is True
    assert not (run / COVERAGE_SUBDIR / MATRIX_NAME).is_file()  # 약화된 matrix 영속화 금지


def test_spec_proposal_transient_is_infra_not_generation(tmp_path):
    run = _make_run(tmp_path, with_spec=False)
    executor = FakeExecutor({
        "coverage_probe_spec": DeskError("HTTP 500", kind="transient")})
    res = ensure_deterministic_coverage_matrix(run, executor=executor)
    assert res["status"] == "FAILED"
    assert res["infra_failure"] is True
    assert not (run / COVERAGE_SUBDIR / PROBE_SPEC_NAME).is_file()  # 약화 spec 영속화 금지
    assert not (run / COVERAGE_SUBDIR / MATRIX_NAME).is_file()


# ---------------------------------------------------------------- §5.5 probe spec 제안 검증

def test_llm_spec_proposal_validated_and_executed(tmp_path):
    run = _make_run(tmp_path, with_spec=False)
    executor = FakeExecutor({"coverage_probe_spec": {
        "probes": _PROBES,
        "requirements": [
            {"requirement": "값이 저장되는가", "adjudication_mode": "DETERMINISTIC_RUNTIME"},
            {"requirement": "정수만 허용하는 검증", "adjudication_mode": "DETERMINISTIC_RUNTIME"},
            {"requirement": "검증 없는 자유 입력", "adjudication_mode": "DETERMINISTIC_RUNTIME"},
        ]}})
    res = ensure_deterministic_coverage_matrix(run, executor=executor)
    assert res["status"] == "OK"
    assert res["desk_calls"] == {"probe_spec": 1, "semantic": 0}
    assert res["deterministic_row_count"] == 3
    assert validate_coverage_artifacts(run) == []


def test_invalid_spec_proposal_demoted_to_semantic_fail_closed(tmp_path):
    run = _make_run(tmp_path, with_spec=False)
    bad = {
        "probes": [{"probe_id": "P1", "checks": [{"kind": "made_up_kind"}],
                    "covers": ["값이 저장되는가"]}],
        "requirements": [
            {"requirement": "값이 저장되는가", "adjudication_mode": "DETERMINISTIC_RUNTIME"},
            {"requirement": "정수만 허용하는 검증",
             "adjudication_mode": "SEMANTIC_ADJUDICATION_REQUIRED"},
            {"requirement": "검증 없는 자유 입력",
             "adjudication_mode": "SEMANTIC_ADJUDICATION_REQUIRED"},
        ]}
    executor = FakeExecutor({
        "coverage_probe_spec": bad,
        "coverage_semantic_claims": {"items": []},
    })
    res = ensure_deterministic_coverage_matrix(run, executor=executor)
    assert res["status"] == "OK"
    # 무효 제안은 통째로 거부 — 낙관적 부분 채택 없이 전면 semantic 강등
    assert res["deterministic_row_count"] == 0
    assert res["semantic_row_count"] == 3
    assert any("거부" in p for p in res["problems"])
    judge = load_matrix_judge_coverage(run)
    assert all(v["status"] == "unknown" for v in judge["judge_coverage"].values())


def test_generate_probe_spec_rejects_out_of_dsl(tmp_path):
    run = _make_run(tmp_path, with_spec=False)
    executor = FakeExecutor({"coverage_probe_spec": {
        "probes": [{"probe_id": "PX", "checks": [
            {"kind": "static_substring_count", "needle": "x", "glob": "../../etc/*"}],
            "covers": ["값이 저장되는가"]}],
        "requirements": [
            {"requirement": "값이 저장되는가", "adjudication_mode": "DETERMINISTIC_STATIC"},
            {"requirement": "정수만 허용하는 검증",
             "adjudication_mode": "SEMANTIC_ADJUDICATION_REQUIRED"},
            {"requirement": "검증 없는 자유 입력",
             "adjudication_mode": "SEMANTIC_ADJUDICATION_REQUIRED"},
        ]}})
    out = generate_probe_spec(run, executor=executor)
    assert out["ok"] is True
    assert out["spec"]["probes"] == []  # glob 탈출 시도 → 제안 전체 거부
    assert all(r["adjudication_mode"] == "SEMANTIC_ADJUDICATION"
               for r in out["spec"]["requirements"])


def test_spec_proposal_shape_drift_canonicalized(tmp_path):
    """live 실측 형태 편차: {"probe": {...}} 래핑 + checks dict + covers 문자열 —
    결정론적 정규화 후 strict 검증을 통과해야 한다 (판단 내용 불변)."""
    run = _make_run(tmp_path, with_spec=False)
    wrapped = {
        "probes": [
            {"probe": {"probe_id": "P1", "title": "값 저장",
                       "initial_state": {"Entity": {"v": 1}},
                       "actions": [{"type": "set_value", "payload": {"value": 7}}],
                       "checks": {"final_state_path":
                                  {"path": "Entity.v", "op": "eq", "value": 7}},
                       "covers": "값이 저장되는가"}},
        ],
        "requirements": [
            {"requirement": "값이 저장되는가", "adjudication_mode": "DETERMINISTIC_RUNTIME"},
            {"requirement": "정수만 허용하는 검증",
             "adjudication_mode": "SEMANTIC_ADJUDICATION_REQUIRED"},
            {"requirement": "검증 없는 자유 입력",
             "adjudication_mode": "SEMANTIC_ADJUDICATION_REQUIRED"},
        ]}
    executor = FakeExecutor({"coverage_probe_spec": wrapped})
    out = generate_probe_spec(run, executor=executor)
    assert out["ok"] is True
    assert [p["probe_id"] for p in out["spec"]["probes"]] == ["P1"]
    assert out["spec"]["probes"][0]["checks"][0]["kind"] == "final_state_path"
    modes = {r["requirement_id"]: r["adjudication_mode"]
             for r in out["spec"]["requirements"]}
    assert modes["SC1"] == "DETERMINISTIC_RUNTIME"


# ---------------------------------------------------------------- probe 실패 → 제품 결함으로 정직 기록

def test_failing_probe_yields_not_covered_true_core_gap(tmp_path):
    run = _make_run(tmp_path)
    spec = _load(run / COVERAGE_SUBDIR / PROBE_SPEC_NAME)
    spec["probes"][0]["checks"][0]["value"] = 999  # P1 실패 유도
    _dump(run / COVERAGE_SUBDIR / PROBE_SPEC_NAME, spec)
    res = ensure_deterministic_coverage_matrix(run)
    assert res["status"] == "OK"
    matrix = _load(run / COVERAGE_SUBDIR / MATRIX_NAME)
    sc1 = next(r for r in matrix["rows"] if r["requirement_id"] == "SC1")
    assert sc1["coverage_status"] == "NOT_COVERED"
    assert sc1["failure_class"] == "TRUE_CORE_GAP"
    judge = load_matrix_judge_coverage(run)
    assert judge["judge_coverage"]["값이 저장되는가"]["status"] == "missing"


def test_runner_crash_is_probe_failure_not_fake_coverage(tmp_path):
    run = _make_run(tmp_path)
    (run / "workspace" / "src" / "runner.py").write_text("raise SystemExit(2)",
                                                         encoding="utf-8")
    res = ensure_deterministic_coverage_matrix(run)
    assert res["status"] == "FAILED"
    assert res["failure_type"] == COVERAGE_PROBE_FAILED
    assert not (run / COVERAGE_SUBDIR / MATRIX_NAME).is_file()


# ---------------------------------------------------------------- digest 계약

def test_challenge_digest_order_preserving_and_stable():
    d1 = normalized_challenge_digest(_NORMALIZED)
    d2 = normalized_challenge_digest(json.loads(json.dumps(_NORMALIZED)))
    assert d1 == d2
    swapped = json.loads(json.dumps(_NORMALIZED))
    swapped["success_conditions"] = list(reversed(_NORMALIZED["success_conditions"] + ["x"]))
    assert normalized_challenge_digest(swapped) != d1


def test_matrix_semantic_digest_ignores_nothing_in_canonical_file(tmp_path):
    run = _make_run(tmp_path)
    ensure_deterministic_coverage_matrix(run)
    matrix = _load(run / COVERAGE_SUBDIR / MATRIX_NAME)
    assert "produced_at" not in matrix  # 시각 metadata는 canonical 밖 (§4.2)
    assert matrix_semantic_digest(matrix) == matrix_semantic_digest(_load(
        run / COVERAGE_SUBDIR / MATRIX_NAME))


# ---------------------------------------------------------------- §6.13 desk 판정 요동 무력화

class FluctuatingExecutor:
    """호출마다 다른 coverage를 돌려주는 요동 desk — matrix가 유효하면 아예 호출되면 안 된다."""

    def __init__(self):
        self.calls: list[str] = []
        self._coverages = [1.0, 0.33, 0.67]

    def call(self, schema_name, prompt, model_cls):
        self.calls.append(schema_name)
        cov = self._coverages[len(self.calls) % 3]
        return SimpleNamespace(model_dump=lambda: {"items": [], "coverage": cov}), "FAKE"


def test_desk_fluctuation_neutralized_by_valid_matrix(tmp_path):
    from repo_idea_miner import factory_loop_executor as loop
    run = _make_run(tmp_path)
    ensure_deterministic_coverage_matrix(run)
    executor = FluctuatingExecutor()
    results = [loop._judge_requirement_coverage(run, {}, {}, set(), executor, use_llm=True)
               for _ in range(3)]
    assert executor.calls == []  # desk 자체가 호출되지 않는다
    assert all(r["desk_status"] == "COVERAGE_MATRIX" for r in results)
    assert results[0]["judge_coverage"] == results[1]["judge_coverage"] \
        == results[2]["judge_coverage"]


def test_matrix_absence_is_generation_reason_not_llm_fallback(tmp_path):
    """이슈 #25 §4.5: matrix가 단순히 없다는 이유로 전체 LLM coverage desk를 호출하지 않는다."""
    from repo_idea_miner import factory_loop_executor as loop
    run = _make_run(tmp_path)
    assert not (run / COVERAGE_SUBDIR / MATRIX_NAME).is_file()
    res = loop._judge_requirement_coverage(run, {}, {}, set(), BoomExecutor(), use_llm=True)
    assert res["desk_status"] == "COVERAGE_MATRIX"  # 자동 생성 후 matrix 소비
    assert res["coverage_source"] == "DETERMINISTIC_MATRIX"


def test_repeated_validation_identical_coverage(tmp_path):
    """§7.2 unit 등가물: 동일 candidate 3회 연속 판정이 완전히 동일해야 한다."""
    from repo_idea_miner import factory_loop_executor as loop
    from repo_idea_miner.factory_product_acceptance import build_requirement_coverage
    run = _make_run(tmp_path)
    outs = []
    for _ in range(3):
        j = loop._judge_requirement_coverage(run, {}, {}, set(), None, use_llm=False)
        rc = build_requirement_coverage(run, j["judge_coverage"])
        outs.append((rc["critical_requirement_coverage"], rc["difficulty_anchor_coverage"],
                     rc["forbidden_simplification_violation_count"],
                     matrix_semantic_digest(_load(run / COVERAGE_SUBDIR / MATRIX_NAME))))
    assert outs[0] == outs[1] == outs[2]
    assert outs[0][0] == 1.0 and outs[0][1] == 1.0 and outs[0][2] == 0


# ---------------------------------------------------------------- §6.12 loop infra retry 정책

def test_loop_retries_coverage_infra_and_holds_without_repair_lane(tmp_path, monkeypatch):
    import repo_idea_miner.factory_loop_executor as fle

    run = tmp_path / "base_run"
    (run / "workspace").mkdir(parents=True)

    fake_verify = {
        "gate_summary": {}, "anti_summary": {}, "validate_ok": True, "probe": {},
        "profile": {},
        "coverage": {"infra_failure": True,
                     "desk_status": "COVERAGE_SEMANTIC_INFRA_FAIL"},
        "judge": {"desks": {"status": "PASS",
                            "gap": {"primary_gap": "CORE_PATCH_REQUIRED"},
                            "lane": {"recommended_next_lane": "CORE_PATCH"}}},
        "acceptance": {"product_candidate_allowed": False, "failed_checks": [],
                       "max_stage": "REVIEWABLE_ARTIFACT"},
        "vector": {}, "stage": "REVIEWABLE_ARTIFACT",
        "effective_stage": "REVIEWABLE_ARTIFACT", "overrating_blocked": False,
    }
    verify_calls = []
    monkeypatch.setattr(fle, "verify_candidate",
                        lambda *a, **k: (verify_calls.append(1),
                                         json.loads(json.dumps(fake_verify)))[1])

    def boom_lane(lane, ctx):
        raise AssertionError("coverage 인프라 실패에 repair lane을 실행하면 안 된다")

    monkeypatch.setattr(fle, "execute_lane", boom_lane)
    monkeypatch.setattr(fle, "compute_loop_protected_hashes", lambda p: {})
    monkeypatch.setattr(fle, "compare_protected_hashes",
                        lambda a, b: {"status": "PASS", "files_checked": 0,
                                      "changed": [], "added": [], "removed": []})

    res = fle.run_closed_product_loop(run_dir=run, mode="mock", execute=True)

    assert len(verify_calls) == 3  # 최초 1회 + infra retry 2회
    assert any("coverage 인프라 실패" in s for s in res["stop_conditions"])
    assert res["hold_packet"] is not None
    assert res["hold_packet"]["hold_reason_class"] == "EXECUTION_BLOCKED"


# ---------------------------------------------------------------- §6.14 closed loop 전체 흐름

_GOOD_PROBE = {"status": "PASS", "success_scenarios_passed": 2, "failure_scenarios_passed": 1,
               "revise_and_rerun_changed": True, "mock_fallback_count": 0,
               "viewer_static_ok": True, "field_consistency_ok": True,
               "critical_flow_handlers_ok": True}
_LOOP_CLOSED = {"can_create_or_modify_input": True, "can_validate_input": True,
                "can_execute_primary_action": True, "can_observe_state_change": True,
                "can_understand_success": True, "can_understand_failure": True,
                "can_revise_and_retry": True, "product_loop_closed": True}
_GATES = {g: True for g in ("core_contract", "runner", "scenario_replay", "golden_output",
                            "state_invariant", "determinism", "anti_hardcode")}

_BROKEN_RUNNER = _RUNNER.replace('state["Entity"]["v"] = value',
                                 'state["Entity"]["v"] = value + 1')


def test_closed_loop_reaches_candidate_with_auto_matrix(tmp_path, monkeypatch):
    """§6.14: run_closed_product_loop(execute=True)가 수동 matrix 준비 없이 child의
    coverage matrix를 자동 생성하고 acceptance 14/14 PRODUCT_CANDIDATE에 도달한다.

    coverage 경로(automation→matrix→acceptance)는 전부 실물이고, coverage와 무관한
    무거운 검증(gate/anti-hardcode/probe/judge desk)만 고정한다 — 기본 budget 유지."""
    import repo_idea_miner.factory_loop_executor as fle
    from repo_idea_miner import factory_validate

    parent = _make_run(tmp_path, name="parent_run")
    # parent는 실제 수정이 필요한 gap을 가진다: runner가 값을 잘못 저장 → P1 probe FAIL
    (parent / "workspace" / "src" / "runner.py").write_text(_BROKEN_RUNNER, encoding="utf-8")

    monkeypatch.setattr(fle, "run_core_gates", lambda *a, **k: {
        "summary": dict(_GATES), "problems": {g: [] for g in _GATES}})
    monkeypatch.setattr(fle, "run_anti_hardcode_gate",
                        lambda *a, **k: ({}, {"status": "PASS"}))
    monkeypatch.setattr(fle, "run_fresh_probe", lambda *a, **k: dict(_GOOD_PROBE))
    monkeypatch.setattr(fle, "build_capability_profile", lambda run_dir: {})
    monkeypatch.setattr(factory_validate, "validate_product_run_dir",
                        lambda run_dir, extra: (True, []))
    monkeypatch.setattr(fle, "_judge", lambda *a, **k: {
        "evidence": {"known_refs": set(), "product_loop": dict(_LOOP_CLOSED),
                     "facts": {}, "refs": {}},
        "quality": {"fields": {"first_screen_cta_evidence": True,
                               "success_feedback_visible": True,
                               "failure_feedback_visible": True}},
        "hard": {"blockers": []},
        "desks": {"status": "PASS", "stage_label": {"stage": "PRODUCT_CANDIDATE"},
                  "gap": {"primary_gap": "CORE_GAP"},
                  "lane": {"recommended_next_lane": "CORE_PATCH",
                           "human_decision_required": False}},
        "prompts": {}})

    def fix_runner_lane(lane, ctx):
        from repo_idea_miner.factory_lane_executors import copy_run_as_child
        # 실제 child 복사 계약 사용 — coverage evidence는 상속되지 않고(§7.3),
        # probe spec은 challenge 계약으로 상속된다.
        child = copy_run_as_child(Path(ctx["parent_run_dir"]),
                                  Path(ctx["children_root"]) / "child01")
        assert not (child / COVERAGE_SUBDIR / MATRIX_NAME).is_file()
        assert not (child / COVERAGE_SUBDIR / PROBE_RESULTS_NAME).is_file()
        assert not (child / COVERAGE_SUBDIR / ADJUDICATION_NAME).is_file()
        assert (child / COVERAGE_SUBDIR / PROBE_SPEC_NAME).is_file()
        (child / "workspace" / "src" / "runner.py").write_text(_RUNNER, encoding="utf-8")
        return {"lane": lane, "status": "APPLIED", "child_run_dir": str(child),
                "changed_files": ["src/runner.py"], "allowed_scope_check": "PASS",
                "protected_hash_check": "PASS", "targeted_tests": [],
                "targeted_test_status": "PASS", "failure_signature": None,
                "problems": [], "error": None, "underlying_status": "DONE", "route": ""}

    monkeypatch.setattr(fle, "execute_lane", fix_runner_lane)

    res = fle.run_closed_product_loop(run_dir=parent, mode="mock", execute=True,
                                      output_dir=tmp_path / "children")

    assert res["status"] == "PRODUCT_CANDIDATE", res["stop_conditions"]
    assert any("엄격한 PRODUCT_CANDIDATE 도달" in s for s in res["stop_conditions"])
    assert res["base_hash_status"] == "PASS"

    child = Path(res["active_candidate_run_dir"])
    assert child.name == "child01"
    # child matrix가 자동 생성됐고 유효하다 — 수동 coverage 명령/편집 0회
    assert (child / COVERAGE_SUBDIR / MATRIX_NAME).is_file()
    assert validate_coverage_artifacts(child) == []
    child_matrix = _load(child / COVERAGE_SUBDIR / MATRIX_NAME)
    parent_matrix = _load(parent / COVERAGE_SUBDIR / MATRIX_NAME)
    # §7.3: parent matrix 재사용 금지 — fingerprint/판정이 분리된다
    assert child_matrix["artifact_fingerprint"] != parent_matrix["artifact_fingerprint"]
    sc1_parent = next(r for r in parent_matrix["rows"] if r["requirement_id"] == "SC1")
    sc1_child = next(r for r in child_matrix["rows"] if r["requirement_id"] == "SC1")
    assert sc1_parent["coverage_status"] == "NOT_COVERED"  # 시작 gap 실재
    assert sc1_child["coverage_status"] == "COVERED"

    # acceptance 14/14 + coverage provenance 추적 (§5.9)
    it1 = res["iterations"][0]
    assert it1["metric_delta"]["product_acceptance_passed"] == 14
    prov = it1["child_coverage_provenance"]
    assert prov["coverage_source"] == "DETERMINISTIC_MATRIX"
    assert prov["matrix_action"] in ("GENERATED", "REBUILT_STALE")
    assert prov["critical_requirement_coverage"] == 1.0
    assert prov["difficulty_anchor_coverage"] == 1.0
    assert prov["coverage_desk_calls"] == {"probe_spec": 0, "semantic": 0}
    lineage = _load(Path(res["loop_dir"]) / "lineage.json")
    assert lineage["entries"][0]["parent_coverage_provenance"]["matrix_action"] in (
        "GENERATED", "REBUILT_STALE")
    assert lineage["entries"][0]["child_coverage_provenance"]["coverage_source"] == \
        "DETERMINISTIC_MATRIX"
