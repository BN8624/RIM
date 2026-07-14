# 이슈 #26: semantic coverage grounding — evidence bundle/structured claim/deterministic claim validator.
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from repo_idea_miner.factory_autopilot_schemas import SemanticCoverageClaim
from repo_idea_miner.factory_coverage import (
    CLAIM_VALIDATOR_VERSION,
    SEMANTIC_CLAIM_TYPES,
    build_semantic_evidence_bundle,
    canonicalize_semantic_claims,
    coverage_context_digest,
    evidence_bundle_digest,
    validate_semantic_claim,
)


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


_RUNNER_SRC = '''\
import json


def apply_action(state, action):
    if action.get("type") != "set_value":
        raise ValueError("Precondition failed: unknown action")
    state["Entity"]["v"] = action["payload"]["value"]
    return state


def helper():
    return None
'''

_INDEX_HTML = """\
<html><head><style>.never { color: red; }</style></head><body>
<div id="console"><button onclick="run()">set_value 실행</button></div>
<div id="ghost" style="display:none">hidden</div>
</body></html>
"""

_REQS = [
    {"requirement_id": "SC1",
     "requirement_text_or_ref": "invalid action을 명시적으로 거부한다"},
    {"requirement_id": "DA1",
     "requirement_text_or_ref": "콘솔에서 set_value를 실행할 수 있다"},
]


def _make_run(tmp_path: Path, name: str = "run_sem") -> Path:
    run = tmp_path / name
    ws = run / "workspace"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "runner.py").write_text(_RUNNER_SRC, encoding="utf-8")
    _dump(ws / "runner_contract.json", {"required_output_fields": ["ok"]})
    _dump(ws / "state_contract.json",
          {"entities": {"Entity": {"fields": ["v"]}}, "strict": True})
    _dump(ws / "action_contract.json", {"actions": [{"type": "set_value"}]})
    (ws / "product").mkdir()
    (ws / "product" / "index.html").write_text(_INDEX_HTML, encoding="utf-8")
    _dump(ws / "fixtures" / "scenario_001.json",
          {"initial_state": {"Entity": {"v": 1}},
           "actions": [{"type": "set_value", "payload": {"value": 7}}]})
    _dump(ws / "golden" / "expected_001.json",
          {"final_state": {"Entity": {"v": 7}}, "errors": []})
    _dump(run / "normalized_challenge.json", {
        "success_conditions": [_REQS[0]["requirement_text_or_ref"]],
        "difficulty_anchors": [_REQS[1]["requirement_text_or_ref"]],
        "forbidden_simplifications": [],
    })
    return run


def _bundle(run: Path, **kw) -> dict:
    return build_semantic_evidence_bundle(run, _REQS, **kw)


def _claim(**over) -> dict:
    base = {"claim_id": "SC1-C1", "requirement": _REQS[0]["requirement_text_or_ref"],
            "claim_type": "PYTHON_SYMBOL_CONTAINS", "file": "workspace/src/runner.py",
            "symbol": "apply_action",
            "expected": {"required_tokens": ["Precondition failed"]}}
    base.update(over)
    return base


# ---------------------------------------------------------------- §5.2 strict claim schema

def test_claim_schema_accepts_valid_claim():
    model = SemanticCoverageClaim.model_validate(_claim())
    assert model.claim_type == "PYTHON_SYMBOL_CONTAINS"


@pytest.mark.parametrize("over", [
    {"claim_type": "VIBES_GOOD"},                      # 허용 밖 claim type
    {"file": "../outside.py"},                          # 경로 탈출
    {"file": "/abs/path.py"},                           # 절대 경로
    {"file": "C:/abs/path.py"},                         # 드라이브 절대 경로
    {"line_start": 1, "line_end": 900},                 # line range 상한 초과
    {"line_start": 5, "line_end": 2},                   # 역전 range
    {"file_digest": "md5:abc"},                         # digest 형식 위반
    {"symbol": None},                                   # PYTHON_*인데 symbol 없음
    {"symbol": "1bad symbol"},                          # symbol 형식 위반
    {"expected": {}},                                   # required_tokens 없음
    {"claim_type": "JSON_POINTER_EQUALS", "symbol": None,
     "json_pointer": "no-slash", "expected": {"value": 1}},   # pointer 형식
    {"claim_type": "JSON_POINTER_EQUALS", "symbol": None,
     "json_pointer": "/a", "expected": {}},             # value 없음
    {"claim_type": "HTML_ELEMENT_EXISTS", "symbol": None,
     "file": "workspace/product/index.html", "expected": {}},  # element_id 없음
])
def test_claim_schema_rejects_invalid(over):
    with pytest.raises(ValidationError):
        SemanticCoverageClaim.model_validate(_claim(**over))


def test_claim_schema_unwraps_claim_wrapper():
    """live 실측 형태 편차(loop 101130): {"claim": {...}} 래핑 — 정규화 후 strict 검증 통과."""
    model = SemanticCoverageClaim.model_validate(
        {"claim": _claim(), "requirement": _REQS[0]["requirement_text_or_ref"]})
    assert model.claim_type == "PYTHON_SYMBOL_CONTAINS"
    assert model.file == "workspace/src/runner.py"
    # 래핑 해제 후에도 무효 내용은 그대로 거부된다 (판단 내용 불변)
    with pytest.raises(ValidationError):
        SemanticCoverageClaim.model_validate({"claim": _claim(claim_type="VIBES")})


def test_wrapped_claims_flow_to_validated_covered(tmp_path):
    """래핑된 claim이 flow에서 정상 검증·병합되는지 (live 결함 회귀 고정)."""
    run = _make_flow_run(tmp_path)
    res = ensure_deterministic_coverage_matrix(
        run, executor=_claims_desk([
            {"requirement": "정수만 허용하는 검증", "raw_coverage_status": "PARTIAL",
             "claims": [{"claim": {**_VALID_CLAIM,
                                   "requirement": "정수만 허용하는 검증"}}]}]))
    assert res["status"] == "OK"
    assert res["proposal_rejected_count"] == 0
    assert res["validated_semantic_covered_count"] == 1


# ---------------------------------------------------------------- §5.1 evidence bundle

def test_bundle_deterministic_across_identical_dirs(tmp_path):
    ba = _bundle(_make_run(tmp_path / "a"))
    bb = _bundle(_make_run(tmp_path / "b"))
    assert ba == bb
    assert evidence_bundle_digest(ba) == evidence_bundle_digest(bb)
    assert json.dumps(ba, sort_keys=True) == json.dumps(bb, sort_keys=True)


def test_bundle_contains_real_bounded_content_and_structure(tmp_path):
    run = _make_run(tmp_path)
    bundle = _bundle(run)
    files = bundle["files"]
    runner = files["workspace/src/runner.py"]
    assert runner["digest"].startswith("sha256:")
    assert {"symbol": "apply_action", "line_start": 4, "line_end": 8} \
        in runner["python_symbols"]
    html = files["workspace/product/index.html"]
    assert "console" in html["html_element_ids"]
    contract = files["workspace/state_contract.json"]
    assert {"pointer": "/strict", "value": True} in contract["json_pointers"]
    sc1 = next(r for r in bundle["requirements"] if r["requirement_id"] == "SC1")
    assert sc1["files"]
    assert all(f["excerpts"] for f in sc1["files"])


def test_bundle_budget_enforced_on_large_file(tmp_path):
    """§6.8: 큰 파일을 통째로 넣지 않는다 — file/excerpt/line 상한 준수 + 결정론."""
    run = _make_run(tmp_path)
    big = "\n".join(f"line_{i} = {i}  # invalid action 거부" for i in range(2000))
    (run / "workspace" / "src" / "big.py").write_text(big, encoding="utf-8")
    for i in range(10):
        (run / "workspace" / "src" / f"extra_{i}.py").write_text(
            f"# invalid action 파일 {i}\n", encoding="utf-8")
    b1 = _bundle(run, max_files_per_requirement=3, max_excerpts_per_file=2,
                 max_lines_per_excerpt=40)
    b2 = _bundle(run, max_files_per_requirement=3, max_excerpts_per_file=2,
                 max_lines_per_excerpt=40)
    assert b1 == b2  # 선택 순서 deterministic
    for req in b1["requirements"]:
        assert len(req["files"]) <= 3
        for f in req["files"]:
            assert len(f["excerpts"]) <= 2
            for ex in f["excerpts"]:
                assert ex["line_end"] - ex["line_start"] + 1 <= 40
                assert len(ex["text"].splitlines()) <= 40


def test_bundle_excludes_coverage_self_outputs(tmp_path):
    run = _make_run(tmp_path)
    _dump(run / "review" / "coverage" / "coverage_matrix.json", {"rows": []})
    _dump(run / "review" / "other" / "evidence.json", {"ok": True})
    bundle = _bundle(run)
    refs = set(bundle["files"]) | {f["file"] for r in bundle["requirements"]
                                   for f in r["files"]}
    assert not any(r.startswith("review/coverage/") for r in refs)


# ---------------------------------------------------------------- §5.4 claim validator

def test_symbol_contains_claim_passes_on_real_content(tmp_path):
    """§6.2: symbol 실존 + bounded body 안 token + digest 일치 → PASS."""
    run = _make_run(tmp_path)
    bundle = _bundle(run)
    res = validate_semantic_claim(run, _claim(), bundle)
    assert res["status"] == "PASS", res
    assert res["file_digest_ok"] is True
    assert res["location_ok"] is True
    assert res["validator_version"] == CLAIM_VALIDATOR_VERSION


def test_symbol_exists_but_expected_content_missing_fails(tmp_path):
    """§6.3: 파일/symbol 존재만으로는 COVERED 불가 — 실제 내용이 없으면 FAIL."""
    run = _make_run(tmp_path)
    src = run / "workspace" / "src" / "runner.py"
    src.write_text(_RUNNER_SRC.replace("Precondition failed: unknown action",
                                       "silently ignore"), encoding="utf-8")
    bundle = _bundle(run)
    res = validate_semantic_claim(run, _claim(), bundle)
    assert res["status"] == "FAIL"
    assert res["reason_code"] == "CONTENT_MISMATCH"
    assert res["observed"]["missing_tokens"] == ["Precondition failed"]


def test_symbol_missing_fails(tmp_path):
    run = _make_run(tmp_path)
    bundle = _bundle(run)
    res = validate_semantic_claim(run, _claim(symbol="ghost_function"), bundle)
    assert res["status"] == "FAIL"
    assert res["reason_code"] == "SYMBOL_NOT_FOUND"
    assert res["location_ok"] is False


def test_stale_file_digest_rejected(tmp_path):
    """§6.4: claim(bundle) 생성 후 target 변경 → STALE — 기존 판정 소비 금지."""
    run = _make_run(tmp_path)
    bundle = _bundle(run)
    src = run / "workspace" / "src" / "runner.py"
    src.write_text(src.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    res = validate_semantic_claim(run, _claim(), bundle)
    assert res["status"] == "STALE"
    assert res["reason_code"] == "FILE_DIGEST_MISMATCH"
    assert res["file_digest_ok"] is False


def test_json_pointer_claims(tmp_path):
    """§6.5: pointer 실존+값 일치 → PASS, pointer 없음/값 불일치 → FAIL."""
    run = _make_run(tmp_path)
    bundle = _bundle(run)
    base = {"requirement": _REQS[0]["requirement_text_or_ref"],
            "file": "workspace/state_contract.json"}
    ok = validate_semantic_claim(run, {**base, "claim_type": "JSON_POINTER_EQUALS",
                                       "json_pointer": "/entities/Entity/fields/0",
                                       "expected": {"value": "v"}}, bundle)
    assert ok["status"] == "PASS"
    missing = validate_semantic_claim(run, {**base, "claim_type": "JSON_POINTER_EQUALS",
                                            "json_pointer": "/entities/Ghost",
                                            "expected": {"value": 1}}, bundle)
    assert missing["status"] == "FAIL"
    assert missing["reason_code"] == "POINTER_NOT_FOUND"
    wrong = validate_semantic_claim(run, {**base, "claim_type": "JSON_POINTER_EQUALS",
                                          "json_pointer": "/entities/Entity/fields/0",
                                          "expected": {"value": "x"}}, bundle)
    assert wrong["status"] == "FAIL"
    assert wrong["reason_code"] == "VALUE_MISMATCH"
    true_ok = validate_semantic_claim(run, {**base, "claim_type": "JSON_POINTER_TRUE",
                                            "json_pointer": "/strict"}, bundle)
    assert true_ok["status"] == "PASS"


def test_html_element_claims(tmp_path):
    """§6.6: element 실존+표시 → PASS, 숨김/부재 → FAIL."""
    run = _make_run(tmp_path)
    bundle = _bundle(run)
    base = {"requirement": _REQS[1]["requirement_text_or_ref"],
            "claim_type": "HTML_ELEMENT_EXISTS",
            "file": "workspace/product/index.html"}
    ok = validate_semantic_claim(run, {**base, "expected": {"element_id": "console"}},
                                 bundle)
    assert ok["status"] == "PASS"
    hidden = validate_semantic_claim(run, {**base, "expected": {"element_id": "ghost"}},
                                     bundle)
    assert hidden["status"] == "FAIL"
    assert hidden["reason_code"] == "ELEMENT_HIDDEN"
    absent = validate_semantic_claim(run, {**base, "expected": {"element_id": "nope"}},
                                     bundle)
    assert absent["status"] == "FAIL"
    assert absent["reason_code"] == "ELEMENT_NOT_FOUND"


def test_unsupported_claim_type_is_unsupported_not_pass(tmp_path):
    """§6.7: 허용 enum 밖 claim type은 validator 우회 없이 UNSUPPORTED."""
    run = _make_run(tmp_path)
    bundle = _bundle(run)
    res = validate_semantic_claim(run, _claim(claim_type="FEELS_INTUITIVE"), bundle)
    assert res["status"] == "UNSUPPORTED"
    assert res["reason_code"] == "UNSUPPORTED_CLAIM_TYPE"
    assert "FEELS_INTUITIVE" not in SEMANTIC_CLAIM_TYPES


def test_file_outside_bundle_is_invalid(tmp_path):
    """bundle 밖 실존 파일 인용은 bounded evidence가 아니다 — INVALID."""
    run = _make_run(tmp_path)
    bundle = _bundle(run)
    (run / "loose.py").write_text("Precondition failed", encoding="utf-8")
    res = validate_semantic_claim(run, _claim(file="loose.py"), bundle)
    assert res["status"] == "INVALID"
    assert res["reason_code"] == "FILE_NOT_IN_BUNDLE"


def test_path_escape_is_invalid(tmp_path):
    run = _make_run(tmp_path)
    bundle = _bundle(run)
    res = validate_semantic_claim(run, _claim(file="../secrets.py"), bundle)
    assert res["status"] == "INVALID"
    assert res["reason_code"] == "UNSAFE_PATH"


# ---------------------------------------------------------------- §4.7 canonicalization

def test_claims_canonicalize_order_duplicates_and_reason_variance():
    """§6.11 단위: 순서/중복/reason/claim_id/digest 표기 차이 → canonical set 동일."""
    a = [_claim(claim_id="X1", reason="첫 표현", file_digest="sha256:" + "0" * 64),
         _claim(claim_id="X2", reason="다른 표현")]
    b = [_claim(claim_id="Y9", reason="세 번째 표현"),
         _claim(claim_id="Y8", reason="네 번째"),
         _claim(claim_id="Y7")]
    ca, cb = canonicalize_semantic_claims(a), canonicalize_semantic_claims(b)
    assert ca == cb
    assert len(ca) == 1
    assert "reason" not in ca[0] and "claim_id" not in ca[0] \
        and "file_digest" not in ca[0]


def test_canonical_claims_sorted_deterministically():
    c1 = _claim()
    c2 = {"requirement": _REQS[0]["requirement_text_or_ref"],
          "claim_type": "FILE_CONTAINS", "file": "workspace/src/runner.py",
          "expected": {"required_tokens": ["Precondition failed"]}}
    assert canonicalize_semantic_claims([c1, c2]) == \
        canonicalize_semantic_claims([c2, c1])


# ---------------------------------------------------------------- §4.8 coverage context digest

def test_context_digest_detects_contract_golden_fixture_changes(tmp_path):
    """§6.9: source/product 밖 입력(contract/golden/fixture) 변경도 감지한다."""
    run = _make_run(tmp_path)
    before = coverage_context_digest(run)
    assert before is not None
    for rel in ("workspace/state_contract.json", "workspace/action_contract.json",
                "workspace/golden/expected_001.json",
                "workspace/fixtures/scenario_001.json"):
        target = run / rel
        original = target.read_text(encoding="utf-8")
        data = json.loads(original)
        data["_changed"] = True
        target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        assert coverage_context_digest(run) != before, rel
        target.write_text(original, encoding="utf-8")
        assert coverage_context_digest(run) == before, rel


def test_context_digest_ignores_nonessential_metadata(tmp_path):
    """§6.10: mtime/생성 시각만 바뀌면 digest 동일."""
    import os
    run = _make_run(tmp_path)
    before = coverage_context_digest(run)
    target = run / "workspace" / "golden" / "expected_001.json"
    os.utime(target, (0, 0))  # mtime만 변경
    assert coverage_context_digest(run) == before


# ================================================================ automation flow (이슈 #26 §5.3~§5.9)

from types import SimpleNamespace  # noqa: E402

from repo_idea_miner.factory_coverage import (  # noqa: E402
    COVERAGE_SUBDIR,
    EVIDENCE_BUNDLE_NAME,
    CLAIM_PROPOSAL_NAME,
    CLAIM_RESULTS_NAME,
    MATRIX_NAME,
    PROBE_SPEC_NAME,
    ensure_deterministic_coverage_matrix,
    load_matrix_judge_coverage,
    normalized_challenge_digest,
    validate_coverage_artifacts,
)

_FLOW_RUNNER = '''\
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
                  "errors": errors}, ensure_ascii=True))
'''

_FLOW_NORMALIZED = {
    "success_conditions": ["값이 저장되는가"],
    "difficulty_anchors": ["정수만 허용하는 검증"],
    "forbidden_simplifications": ["검증 없는 자유 입력"],
}


def _make_flow_run(tmp_path: Path, name: str = "flow_run") -> Path:
    run = tmp_path / name
    ws = run / "workspace"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "runner.py").write_text(_FLOW_RUNNER, encoding="utf-8")
    _dump(ws / "runner_contract.json", {"required_output_fields": ["ok"]})
    _dump(ws / "state_contract.json", {"entities": {"Entity": {"fields": ["v"]}}})
    (ws / "product").mkdir()
    (ws / "product" / "index.html").write_text(
        "<html><body><div id=\"state\"></div></body></html>", encoding="utf-8")
    _dump(run / "normalized_challenge.json", _FLOW_NORMALIZED)
    _dump(run / COVERAGE_SUBDIR / PROBE_SPEC_NAME, {
        "schema_version": 2,
        "challenge_digest": normalized_challenge_digest(_FLOW_NORMALIZED),
        "probes": [
            {"probe_id": "P1", "title": "값 저장",
             "initial_state": {"Entity": {"v": 1}},
             "actions": [{"type": "set_value", "payload": {"value": 7}}],
             "checks": [{"kind": "final_state_path", "path": "Entity.v",
                         "op": "eq", "value": 7}],
             "covers": ["값이 저장되는가"]},
            {"probe_id": "P2", "title": "금지 단순화 부재",
             "initial_state": {"Entity": {"v": 1}},
             "actions": [{"type": "set_value", "payload": {"value": "x"}}],
             "checks": [{"kind": "errors", "expect": "nonempty"}],
             "covers": ["검증 없는 자유 입력"]},
        ],
        "requirements": [
            {"requirement_id": "SC1", "requirement_kind": "CRITICAL_REQUIREMENT",
             "requirement_text_or_ref": "값이 저장되는가",
             "adjudication_mode": "DETERMINISTIC_RUNTIME", "probe_refs": ["P1"]},
            {"requirement_id": "DA1", "requirement_kind": "DIFFICULTY_ANCHOR",
             "requirement_text_or_ref": "정수만 허용하는 검증",
             "adjudication_mode": "SEMANTIC_ADJUDICATION", "probe_refs": []},
            {"requirement_id": "FS1", "requirement_kind": "SUPPORTING_REQUIREMENT",
             "requirement_text_or_ref": "검증 없는 자유 입력",
             "forbidden_simplification": True,
             "adjudication_mode": "DETERMINISTIC_RUNTIME", "probe_refs": ["P2"]},
        ],
    })
    return run


class FakeExecutor:
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


_VALID_CLAIM = {"claim_type": "FILE_CONTAINS", "file": "workspace/src/runner.py",
                "expected": {"required_tokens": ["invalid value"]}}


def _claims_desk(items) -> FakeExecutor:
    return FakeExecutor({"coverage_semantic_claims": {"items": items}})


def _matrix_bytes(run: Path) -> bytes:
    return (run / COVERAGE_SUBDIR / MATRIX_NAME).read_bytes()


# ---------------------------------------------------------------- §6.1 plain path COVERED 거부

def test_plain_path_covered_rejected_end_to_end(tmp_path):
    run = _make_flow_run(tmp_path)
    executor = _claims_desk([
        {"requirement": "정수만 허용하는 검증", "raw_coverage_status": "COVERED",
         "coverage_status": "COVERED", "evidence_refs": ["workspace/src/runner.py"],
         "claims": []},
    ])
    res = ensure_deterministic_coverage_matrix(run, executor=executor)
    assert res["status"] == "OK"
    matrix = json.loads(_matrix_bytes(run).decode("utf-8"))
    da1 = next(r for r in matrix["rows"] if r["requirement_id"] == "DA1")
    assert da1["coverage_status"] == "AMBIGUOUS"
    assert da1["row_source"] == "AMBIGUOUS_SEMANTIC"
    assert res["plain_path_covered_count"] == 0
    judge = load_matrix_judge_coverage(run)
    assert judge["judge_coverage"]["정수만 허용하는 검증"]["status"] == "unknown"


def test_tampered_plain_path_covered_row_rejected_by_validator(tmp_path):
    """조작 방어: claim 없는 semantic COVERED row를 손으로 넣어도 validator가 거부한다."""
    run = _make_flow_run(tmp_path)
    ensure_deterministic_coverage_matrix(run, executor=_claims_desk([]))
    matrix_path = run / COVERAGE_SUBDIR / MATRIX_NAME
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    for row in matrix["rows"]:
        if row["requirement_id"] == "DA1":
            row.update(coverage_status="COVERED", failure_class="NONE",
                       reason_code="OPTIMISM",
                       static_evidence_refs=["workspace/src/runner.py"])
    matrix["aggregates"]["difficulty_anchor"] = {"total": 1, "covered": 1,
                                                 "coverage": 1.0}
    _dump(matrix_path, matrix)
    problems = validate_coverage_artifacts(run)
    assert any("plain file path" in p or "validated claim 없음" in p for p in problems)


# ---------------------------------------------------------------- §6.2·§6.15 claim 기반 실판정

def test_validated_claims_cover_and_real_defect_uncovers(tmp_path):
    run = _make_flow_run(tmp_path)
    res = ensure_deterministic_coverage_matrix(
        run, executor=_claims_desk([
            {"requirement": "정수만 허용하는 검증", "raw_coverage_status": "COVERED",
             "claims": [_VALID_CLAIM]}]))
    assert res["status"] == "OK"
    assert res["validated_semantic_covered_count"] == 1
    assert validate_coverage_artifacts(run) == []
    assert (run / COVERAGE_SUBDIR / EVIDENCE_BUNDLE_NAME).is_file()
    assert (run / COVERAGE_SUBDIR / CLAIM_RESULTS_NAME).is_file()
    judge = load_matrix_judge_coverage(run)
    assert judge["judge_coverage"]["정수만 허용하는 검증"]["status"] == "implemented"

    # §6.15: 실제 구현 제거 → 같은 claim이 FAIL → NOT_COVERED (재현성이 과대평가로
    # 이어지지 않는다)
    run2 = _make_flow_run(tmp_path, name="flow_defect")
    src = run2 / "workspace" / "src" / "runner.py"
    src.write_text(_FLOW_RUNNER.replace(
        'if not isinstance(value, int):\n            errors.append("invalid value")\n            continue\n        ',
        ""), encoding="utf-8")
    res2 = ensure_deterministic_coverage_matrix(
        run2, executor=_claims_desk([
            {"requirement": "정수만 허용하는 검증", "raw_coverage_status": "COVERED",
             "claims": [_VALID_CLAIM]}]))
    assert res2["status"] == "OK"
    matrix = json.loads(_matrix_bytes(run2).decode("utf-8"))
    da1 = next(r for r in matrix["rows"] if r["requirement_id"] == "DA1")
    assert da1["coverage_status"] == "NOT_COVERED"
    assert da1["failure_class"] == "TRUE_CORE_GAP"
    assert da1["claim_fail_count"] == 1
    judge = load_matrix_judge_coverage(run2)
    assert judge["judge_coverage"]["정수만 허용하는 검증"]["status"] == "missing"


# ---------------------------------------------------------------- §6.4 stale claim → rebuild

def test_stale_claim_target_forces_rebuild(tmp_path):
    run = _make_flow_run(tmp_path)
    executor = _claims_desk([
        {"requirement": "정수만 허용하는 검증", "claims": [_VALID_CLAIM]}])
    first = ensure_deterministic_coverage_matrix(run, executor=executor)
    assert first["action"] == "GENERATED"
    src = run / "workspace" / "src" / "runner.py"
    src.write_text(src.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    problems = validate_coverage_artifacts(run)
    assert problems != []  # stale 상태의 기존 semantic row 소비 금지
    res = ensure_deterministic_coverage_matrix(run, executor=executor)
    assert res["action"] == "REBUILT_STALE"
    assert validate_coverage_artifacts(run) == []


# ---------------------------------------------------------------- §6.7 unsupported claim

def test_unsupported_claim_type_never_covers(tmp_path):
    run = _make_flow_run(tmp_path)
    res = ensure_deterministic_coverage_matrix(
        run, executor=_claims_desk([
            {"requirement": "정수만 허용하는 검증", "raw_coverage_status": "COVERED",
             "claims": [{"claim_type": "FEELS_INTUITIVE",
                         "file": "workspace/src/runner.py", "expected": {}}]}]))
    assert res["status"] == "OK"
    assert res["proposal_rejected_count"] == 1
    matrix = json.loads(_matrix_bytes(run).decode("utf-8"))
    da1 = next(r for r in matrix["rows"] if r["requirement_id"] == "DA1")
    assert da1["coverage_status"] == "AMBIGUOUS"
    judge = load_matrix_judge_coverage(run)
    assert judge["judge_coverage"]["정수만 허용하는 검증"]["status"] == "unknown"


# ---------------------------------------------------------------- §6.9·§6.10 context 감지

def test_contract_change_forces_rebuild_beyond_fingerprint(tmp_path):
    """§6.9: fingerprint(src/product)에 없는 state_contract 변경도 context digest가 잡는다."""
    run = _make_flow_run(tmp_path)
    executor = _claims_desk([
        {"requirement": "정수만 허용하는 검증", "claims": [_VALID_CLAIM]}])
    first = ensure_deterministic_coverage_matrix(run, executor=executor)
    _dump(run / "workspace" / "state_contract.json",
          {"entities": {"Entity": {"fields": ["v", "w"]}}})
    res = ensure_deterministic_coverage_matrix(run, executor=executor)
    assert res["action"] == "REBUILT_STALE"
    assert res["coverage_context_digest"] != first["coverage_context_digest"]
    assert any("context digest" in p for p in res["problems"])


def test_nonessential_metadata_keeps_reuse(tmp_path):
    """§6.10: mtime만 변경 → 기존 matrix 그대로 REUSED, digest 불변."""
    import os
    run = _make_flow_run(tmp_path)
    executor = _claims_desk([
        {"requirement": "정수만 허용하는 검증", "claims": [_VALID_CLAIM]}])
    first = ensure_deterministic_coverage_matrix(run, executor=executor)
    os.utime(run / "workspace" / "state_contract.json", (0, 0))
    res = ensure_deterministic_coverage_matrix(run, executor=FakeExecutor({}))
    assert res["action"] == "REUSED"
    assert res["matrix_semantic_digest"] == first["matrix_semantic_digest"]


# ---------------------------------------------------------------- §6.11~§6.14 cross-fresh 수렴

def test_proposal_expression_variance_converges(tmp_path):
    """§6.11: claim 순서/중복/reason/raw status 차이 → canonical set·matrix 동일."""
    # flow runner는 top-level 함수가 없으므로 FILE_CONTAINS 2종으로 구성
    other = {"claim_type": "FILE_CONTAINS", "file": "workspace/src/runner.py",
             "expected": {"required_tokens": ["isinstance"]}}
    run_a = _make_flow_run(tmp_path / "a")
    run_b = _make_flow_run(tmp_path / "b")
    ra = ensure_deterministic_coverage_matrix(run_a, executor=_claims_desk([
        {"requirement": "정수만 허용하는 검증", "raw_coverage_status": "COVERED",
         "claims": [{**_VALID_CLAIM, "reason": "표현 1"}, {**other, "reason": "표현 2"}]}]))
    rb = ensure_deterministic_coverage_matrix(run_b, executor=_claims_desk([
        {"requirement": "정수만 허용하는 검증", "raw_coverage_status": "PARTIALLY_COVERED",
         "claims": [{**other, "reason": "다른 말"}, {**_VALID_CLAIM, "reason": "또 다른"},
                    {**_VALID_CLAIM, "reason": "중복"}]}]))
    assert ra["matrix_semantic_digest"] == rb["matrix_semantic_digest"]
    assert _matrix_bytes(run_a) == _matrix_bytes(run_b)
    assert ra["evidence_bundle_digest"] == rb["evidence_bundle_digest"]
    # raw proposal은 달랐다 — 기록은 남고 정본은 흔들리지 않는다 (§6.14)
    assert ra["raw_proposal_digest"] != rb["raw_proposal_digest"]
    assert (run_a / COVERAGE_SUBDIR / CLAIM_PROPOSAL_NAME).is_file()


def test_invalid_claims_dropped_converge_to_same_truth(tmp_path):
    """§6.12: A(유효+무효 claim) vs B(유효만) → 무효는 제거되고 최종 matrix 동일."""
    run_a = _make_flow_run(tmp_path / "a")
    run_b = _make_flow_run(tmp_path / "b")
    ra = ensure_deterministic_coverage_matrix(run_a, executor=_claims_desk([
        {"requirement": "정수만 허용하는 검증",
         "claims": [_VALID_CLAIM,
                    {"claim_type": "FILE_CONTAINS", "file": "../escape.py",
                     "expected": {"required_tokens": ["x"]}}]}]))
    rb = ensure_deterministic_coverage_matrix(run_b, executor=_claims_desk([
        {"requirement": "정수만 허용하는 검증", "claims": [_VALID_CLAIM]}]))
    assert ra["proposal_rejected_count"] == 1
    assert rb["proposal_rejected_count"] == 0
    assert ra["matrix_semantic_digest"] == rb["matrix_semantic_digest"]
    assert _matrix_bytes(run_a) == _matrix_bytes(run_b)
    ja = load_matrix_judge_coverage(run_a)["judge_coverage"]
    jb = load_matrix_judge_coverage(run_b)["judge_coverage"]
    assert ja == jb


def test_independent_fresh_clones_identical_first_matrix(tmp_path):
    """§6.13: coverage evidence가 전혀 없는 독립 clone A/B의 최초 생성 결과 전부 동일."""
    run_a = _make_flow_run(tmp_path / "clone_a")
    run_b = _make_flow_run(tmp_path / "clone_b")
    for run in (run_a, run_b):
        assert not (run / COVERAGE_SUBDIR / MATRIX_NAME).is_file()
        assert not (run / COVERAGE_SUBDIR / CLAIM_RESULTS_NAME).is_file()
    make_exec = lambda: _claims_desk([
        {"requirement": "정수만 허용하는 검증", "claims": [_VALID_CLAIM]}])
    ra = ensure_deterministic_coverage_matrix(run_a, executor=make_exec())
    rb = ensure_deterministic_coverage_matrix(run_b, executor=make_exec())
    assert ra["artifact_fingerprint"] == rb["artifact_fingerprint"]
    assert ra["challenge_digest"] == rb["challenge_digest"]
    assert ra["coverage_context_digest"] == rb["coverage_context_digest"]
    assert ra["evidence_bundle_digest"] == rb["evidence_bundle_digest"]
    assert ra["matrix_semantic_digest"] == rb["matrix_semantic_digest"]
    assert _matrix_bytes(run_a) == _matrix_bytes(run_b)
    assert (run_a / COVERAGE_SUBDIR / CLAIM_RESULTS_NAME).read_bytes() == \
        (run_b / COVERAGE_SUBDIR / CLAIM_RESULTS_NAME).read_bytes()
    ma = json.loads(_matrix_bytes(run_a).decode("utf-8"))
    mb = json.loads(_matrix_bytes(run_b).decode("utf-8"))
    assert [(r["requirement_id"], r["coverage_status"]) for r in ma["rows"]] == \
        [(r["requirement_id"], r["coverage_status"]) for r in mb["rows"]]
    assert ma["aggregates"] == mb["aggregates"]
    assert load_matrix_judge_coverage(run_a)["judge_coverage"] == \
        load_matrix_judge_coverage(run_b)["judge_coverage"]


def test_desk_status_fluctuation_neutralized(tmp_path):
    """§6.14: clone별 raw status/reason 요동 — 같은 claim truth면 matrix 동일,
    raw LLM status는 acceptance에 닿지 못한다."""
    run_a = _make_flow_run(tmp_path / "a")
    run_b = _make_flow_run(tmp_path / "b")
    ra = ensure_deterministic_coverage_matrix(run_a, executor=_claims_desk([
        {"requirement": "정수만 허용하는 검증", "raw_coverage_status": "NOT_COVERED",
         "claims": [{**_VALID_CLAIM, "reason": "회의적"}]}]))
    rb = ensure_deterministic_coverage_matrix(run_b, executor=_claims_desk([
        {"requirement": "정수만 허용하는 검증", "raw_coverage_status": "COVERED",
         "claims": [{**_VALID_CLAIM, "reason": "낙관적"}]}]))
    assert ra["matrix_semantic_digest"] == rb["matrix_semantic_digest"]
    ma = json.loads(_matrix_bytes(run_a).decode("utf-8"))
    da1 = next(r for r in ma["rows"] if r["requirement_id"] == "DA1")
    # validator가 계산한 status(COVERED)가 정본 — raw NOT_COVERED가 아니다
    assert da1["coverage_status"] == "COVERED"
    assert da1["reason_code"] == "VALIDATED_SEMANTIC_CLAIMS"


# ---------------------------------------------------------------- §6.18 child 비상속

def test_child_does_not_inherit_semantic_claim_evidence(tmp_path):
    from repo_idea_miner.factory_lane_executors import copy_run_as_child
    run = _make_flow_run(tmp_path)
    ensure_deterministic_coverage_matrix(run, executor=_claims_desk([
        {"requirement": "정수만 허용하는 검증", "claims": [_VALID_CLAIM]}]))
    for name in (EVIDENCE_BUNDLE_NAME, CLAIM_PROPOSAL_NAME, CLAIM_RESULTS_NAME):
        assert (run / COVERAGE_SUBDIR / name).is_file()
    child = copy_run_as_child(run, tmp_path / "child01")
    for name in (MATRIX_NAME, EVIDENCE_BUNDLE_NAME, CLAIM_PROPOSAL_NAME,
                 CLAIM_RESULTS_NAME):
        assert not (child / COVERAGE_SUBDIR / name).is_file(), name
    assert (child / COVERAGE_SUBDIR / PROBE_SPEC_NAME).is_file()  # spec만 계약 상속
