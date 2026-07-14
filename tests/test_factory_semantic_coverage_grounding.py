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
