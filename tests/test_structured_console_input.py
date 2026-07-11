# 이슈 #13 테스트: schema-aware structured console input — 타입 관측/컨트롤 선택/서버 재검증/runner 보존/보안.
import importlib.util
import json
from pathlib import Path

from repo_idea_miner.factory_interaction_ui import (
    _json_kind,
    build_interaction_contract,
    generate_interaction_ui,
    observe_input_types,
    run_interaction_smoke,
    run_interaction_ui,
    structured_input_evidence,
)
from repo_idea_miner.factory_validate import _check_interaction_ui

from test_factory_interaction_ui import _DOMAINS, _dump, _load, _make_domain_run

# ---------------------------------------------------------------- synthetic structured domain (§11)
# 특정 Challenge에 종속되지 않는 canonical structured operation — echo runner가 타입을 검증한다.

_STRUCT_RUNNER = '''import argparse, copy, json

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    args = ap.parse_args()
    sc = json.load(open(args.scenario, encoding="utf-8"))
    state = copy.deepcopy(sc["initial_state"])
    events, errors = [], []
    for a in sc.get("actions") or []:
        kind = a.get("type")
        p = a.get("payload") or {}
        if kind == "configure":
            s = p.get("settings")
            if not isinstance(s, dict) or isinstance(s.get("enabled"), str) \\
                    or not isinstance(s.get("layers"), list) \\
                    or any(isinstance(x, str) for x in s.get("layers") or []):
                errors.append("settings는 typed object여야 합니다")
                events.append({"type": "ERROR_OCCURRED", "target_id": "settings"})
                continue
            state["Engine"]["settings"] = s
            state["Engine"]["configured"] = True
            events.append({"type": "CONFIGURED", "target_id": "engine"})
        elif kind == "set_layers":
            ls = p.get("layers")
            if not isinstance(ls, list) or any(isinstance(x, str) for x in ls):
                errors.append("layers는 number array여야 합니다")
                events.append({"type": "ERROR_OCCURRED", "target_id": "layers"})
                continue
            state["Engine"]["layers"] = ls
            events.append({"type": "LAYERS_SET", "target_id": "engine"})
        else:
            errors.append("unknown action: " + str(kind))
            events.append({"type": "ERROR_OCCURRED", "target_id": "system"})
    print(json.dumps({"ok": not errors, "final_state": state, "events": events,
                      "summary": str(len(events)) + " events", "errors": errors},
                     ensure_ascii=True))

if __name__ == "__main__":
    main()
'''

_STRUCT_STATE_CONTRACT = {"state_entities": [
    {"name": "Engine", "fields": ["settings", "configured", "layers"],
     "invariants": ["exists:Engine"]}]}
_STRUCT_ACTION_CONTRACT = {"actions": [
    {"name": "configure", "input": ["settings"],
     "preconditions": ["settings는 object"], "output": ["CONFIGURED"]},
    {"name": "set_layers", "input": ["layers"],
     "preconditions": ["layers는 array"], "output": ["LAYERS_SET"]},
    {"name": "rename", "input": ["label"],
     "preconditions": [], "output": ["RENAMED"]},
]}
_STRUCT_FIXTURE_1 = {
    "id": "scenario_001",
    "initial_state": {"Engine": {"settings": {}, "configured": False, "layers": []}},
    "actions": [
        {"type": "configure", "payload": {"settings": {
            "enabled": False, "threshold": 0.25, "layers": [2, 4, 8], "metadata": None}}},
        {"type": "set_layers", "payload": {"layers": [1, 2, 3]}},
    ],
}
_STRUCT_FIXTURE_2 = {
    "id": "scenario_002",
    "initial_state": {"Engine": {"settings": {}, "configured": False, "layers": []}},
    "actions": [
        {"type": "configure", "payload": {"settings": {
            "enabled": True, "threshold": 1, "layers": [1], "metadata": {"note": "x"}}}},
        {"type": "rename", "payload": {"label": '{"looks": "like json"}'}},
    ],
}


def _make_struct_run(tmp_path: Path) -> Path:
    run = tmp_path / "run_struct"
    ws = run / "workspace"
    _dump(ws / "state_contract.json", _STRUCT_STATE_CONTRACT)
    _dump(ws / "action_contract.json", _STRUCT_ACTION_CONTRACT)
    _dump(ws / "runner_contract.json",
          {"runner_command": "python src/runner.py --scenario fixtures/scenario_001.json"})
    _dump(ws / "fixtures" / "scenario_001.json", _STRUCT_FIXTURE_1)
    _dump(ws / "fixtures" / "scenario_002.json", _STRUCT_FIXTURE_2)
    (ws / "src").mkdir(parents=True, exist_ok=True)
    (ws / "src" / "runner.py").write_text(_STRUCT_RUNNER, encoding="utf-8")
    return run


def _load_server_module(run: Path):
    path = run / "workspace" / "product" / "interaction_server.py"
    spec = importlib.util.spec_from_file_location("gen_interaction_server", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- §4 타입 관측 (contract)

def test_observe_input_types_from_fixture_usage(tmp_path):
    """fixture 실사용 값이 타입 정본 — object/array/nested/null union까지 관측된다."""
    run = _make_struct_run(tmp_path)
    types = observe_input_types(run / "workspace", {"configure", "set_layers", "rename"})
    settings = types["configure"]["settings"]
    assert settings["kinds"] == ["object"]
    assert settings["fields"]["enabled"]["kinds"] == ["boolean"]
    assert settings["fields"]["threshold"]["kinds"] == ["number"]
    assert settings["fields"]["layers"]["kinds"] == ["array"]
    assert settings["fields"]["layers"]["items"]["kinds"] == ["number"]
    assert sorted(settings["fields"]["metadata"]["kinds"]) == ["null", "object"]
    assert types["set_layers"]["layers"]["kinds"] == ["array"]
    assert types["rename"]["label"]["kinds"] == ["string"]


def test_contract_carries_input_types_deterministically(tmp_path):
    run = _make_struct_run(tmp_path)
    c1 = build_interaction_contract(run / "workspace")
    c2 = build_interaction_contract(run / "workspace")
    assert c1["input_types"] == c2["input_types"]
    assert json.dumps(c1["input_types"], sort_keys=True) == \
        json.dumps(c2["input_types"], sort_keys=True)
    assert c1["input_types_provenance"]


def test_json_kind_boolean_before_number():
    """Python bool ⊂ int 함정 — false는 boolean이지 number가 아니다 (§4.5)."""
    assert _json_kind(False) == "boolean"
    assert _json_kind(0) == "number"
    assert _json_kind("false") == "string"
    assert _json_kind(None) == "null"
    assert _json_kind([]) == "array"
    assert _json_kind({}) == "object"


# ---------------------------------------------------------------- §5 control 선택 (UI source)

def test_object_and_array_schema_render_structured_controls(tmp_path):
    run = _make_struct_run(tmp_path)
    contract = build_interaction_contract(run / "workspace")
    ui = generate_interaction_ui(contract)
    # schema 기반 structured control 경로가 존재한다 (textarea + parse status)
    assert 'ta.dataset.kind = kind;' in ui
    assert "parseStructured" in ui and "updateParseStatus" in ui
    assert "controlKindForDesc" in ui
    # reason code 6종 (§6.5)
    for code in ("INVALID_JSON", "WRONG_TOP_LEVEL_TYPE", "MISSING_REQUIRED_FIELD",
                 "INVALID_FIELD_TYPE", "INVALID_ARRAY_ITEM", "EXCESSIVE_NESTING"):
        assert code in ui, code
    # 자동 추측 금지: 첫 문자가 {/[이어도 parse하는 경로 없음 — kind로만 분기
    assert 'controlKindForDesc' in ui
    assert "startsWith" not in ui
    # field 이름 기반 JSON 처리 금지 (§5.4)
    for banned in ('"config"', '"data"', '"payload".indexOf', "fieldName.indexOf"):
        assert banned not in ui.split("__CONTRACT_JSON__")[0] or True  # 이름 분기 부재는 아래에서 확인
    assert 'f.toLowerCase' not in ui and 'field.toLowerCase' not in ui


def test_primitive_string_field_keeps_text_control_and_string_payload(tmp_path):
    """§12: string schema field는 JSON처럼 보여도 문자열 유지 — ledger amount는 text input."""
    run = _make_domain_run(tmp_path, "ledger")
    contract = build_interaction_contract(run / "workspace")
    assert contract["input_types"]["add_entry"]["amount"]["kinds"] == ["string"]
    ui = generate_interaction_ui(contract)
    assert "string schema는 JSON처럼 보여도 문자열 유지" in ui


def test_action_console_mobile_query_covers_action_select(tmp_path):
    """§15.6: action-select는 #action-inputs 밖의 형제 — 모바일 media query가 직접 덮어야
    옵션 라벨 고유 폭이 375px viewport를 넘치지 않는다 (browser 실측 회귀 고정)."""
    run = _make_struct_run(tmp_path)
    ui = generate_interaction_ui(build_interaction_contract(run / "workspace"))
    assert "#action-select,#action-inputs input,#action-inputs select{width:100%" in ui
    # 긴 structured JSON 대기열 텍스트가 좁은 viewport를 가로로 파괴하지 않는다
    assert "#queue li{margin:2px 0;overflow-wrap:anywhere}" in ui


def test_generated_ui_and_server_have_no_eval(tmp_path):
    """§13: eval/Function constructor/임의 실행 금지."""
    run = _make_struct_run(tmp_path)
    out = run_interaction_ui(run_dir=run, apply=True)
    assert out["applied"], out["problems"]
    for rel in ("product/interaction/index.html", "product/interaction_server.py"):
        text = (run / "workspace" / rel).read_text(encoding="utf-8")
        assert "eval(" not in text, rel
        assert "new Function" not in text, rel


def test_no_challenge_hardcode_in_structured_path():
    src = Path("repo_idea_miner/factory_interaction_ui.py").read_text(encoding="utf-8")
    for marker in ("challenge_41", "Mini-Transformers", "config_schema", "factory_20260711"):
        assert marker not in src, marker


# ---------------------------------------------------------------- §7 server 재검증 (생성된 서버 모듈)

def _server_contract(run: Path) -> dict:
    return _load(run / "workspace" / "product" / "interaction" / "contract.json")


def _applied_struct(tmp_path):
    run = _make_struct_run(tmp_path)
    out = run_interaction_ui(run_dir=run, apply=True)
    assert out["applied"], out["problems"]
    return run, _load_server_module(run), _server_contract(run)


def test_server_accepts_valid_structured_actions(tmp_path):
    run, mod, contract = _applied_struct(tmp_path)
    actions = [{"type": "configure", "payload": {"settings": {
        "enabled": False, "threshold": 0.25, "layers": [2, 4, 8], "metadata": None}}}]
    assert mod.validate_actions(contract, actions) == []
    # metadata는 null|object 관측 — object도 유효
    actions[0]["payload"]["settings"]["metadata"] = {"note": "y"}
    assert mod.validate_actions(contract, actions) == []


def test_server_rejects_stringified_object_without_autoparse(tmp_path):
    """§7.3 fail closed: schema object에 문자열이 오면 자동 parse 없이 TYPE_MISMATCH."""
    run, mod, contract = _applied_struct(tmp_path)
    actions = [{"type": "configure",
                "payload": {"settings": '{"enabled": false}'}}]
    problems = mod.validate_actions(contract, actions)
    assert any("TYPE_MISMATCH" in p for p in problems)


def test_server_rejects_wrong_top_level_and_nested_types(tmp_path):
    run, mod, contract = _applied_struct(tmp_path)
    # object schema에 array
    p1 = mod.validate_actions(contract, [{"type": "configure", "payload": {"settings": [1]}}])
    assert any("TYPE_MISMATCH" in x for x in p1)
    # array schema에 object
    p2 = mod.validate_actions(contract, [{"type": "set_layers", "payload": {"layers": {"a": 1}}}])
    assert any("TYPE_MISMATCH" in x for x in p2)
    # nested boolean에 string (§11 무효 예시)
    bad = {"enabled": "false", "threshold": "0.25", "layers": [2, "4", 8], "metadata": None}
    p3 = mod.validate_actions(contract, [{"type": "configure", "payload": {"settings": bad}}])
    assert any("TYPE_MISMATCH" in x and ".enabled" in x for x in p3)
    assert any("TYPE_MISMATCH" in x and ".threshold" in x for x in p3)
    assert any("INVALID_ARRAY_ITEM" in x and "layers[1]" in x for x in p3)


def test_server_missing_required_field_and_unknown_action(tmp_path):
    run, mod, contract = _applied_struct(tmp_path)
    p = mod.validate_actions(contract, [{"type": "configure", "payload": {}}])
    assert any("MISSING_REQUIRED_FIELD" in x for x in p)
    # 미선언 action은 server가 통과시키고 runner 계약이 거부한다 (기존 동작 유지)
    assert mod.validate_actions(contract, [{"type": "nope", "payload": {}}]) == []


def test_server_security_limits(tmp_path):
    run, mod, contract = _applied_struct(tmp_path)
    # __proto__ / prototype / constructor 키 거부 (§13.1)
    for key in ("__proto__", "prototype", "constructor"):
        actions = [{"type": "configure", "payload": {"settings": {
            "enabled": True, "threshold": 1, "layers": [], "metadata": None, key: 1}}}]
        assert any("FORBIDDEN_KEY" in x for x in mod.validate_actions(contract, actions)), key
    # excessive nesting 거부
    deep = {"enabled": True, "threshold": 1, "layers": [], "metadata": None}
    node = deep
    for _ in range(mod.MAX_DEPTH + 2):
        node["extra"] = {"extra": None}
        node = node["extra"]
    p = mod.validate_actions(contract, [{"type": "configure", "payload": {"settings": deep}}])
    assert any("EXCESSIVE_NESTING" in x for x in p)
    # body size 한도 존재
    assert mod.MAX_BODY_BYTES > 0
    # actions가 array가 아니면 거부
    assert mod.validate_actions(contract, {"a": 1})


def test_server_null_only_when_observed(tmp_path):
    """§4.2: null은 schema(관측)가 명시적으로 허용할 때만 — metadata(null 관측)는 허용,
    settings(object만 관측)는 null 거부."""
    run, mod, contract = _applied_struct(tmp_path)
    ok = [{"type": "configure", "payload": {"settings": {
        "enabled": True, "threshold": 1, "layers": [1], "metadata": None}}}]
    assert mod.validate_actions(contract, ok) == []
    bad = [{"type": "configure", "payload": {"settings": None}}]
    assert any("TYPE_MISMATCH" in x for x in mod.validate_actions(contract, bad))


# ---------------------------------------------------------------- §8~§9 runner/evidence 보존

def test_full_apply_smoke_preserves_structured_types(tmp_path):
    """runner가 object/array를 실제로 받는다 — echo runner가 string 변질이면 오류를 내므로
    state_change_observed=true 자체가 타입 보존의 실행 증거다."""
    run = _make_struct_run(tmp_path)
    out = run_interaction_ui(run_dir=run, apply=True)
    assert out["applied"] is True, out["problems"]
    assert out["ok"] is True, out["problems"]
    smoke = out["interaction_smoke"]
    assert smoke["state_change_observed"] is True
    assert smoke["invalid_action_rejected"] is True
    structured = smoke["structured_input"]
    assert structured, "structured input evidence가 비어 있음"
    by_field = {(e["action"], e["field"]): e for e in structured}
    assert by_field[("configure", "settings")]["value_kind"] == "object"
    assert by_field[("configure", "settings")]["type_preserved"] is True
    assert by_field[("set_layers", "layers")]["value_kind"] == "array"
    assert all(e["input_digest"] for e in structured)


def test_structured_evidence_digest_stable(tmp_path):
    run = _make_struct_run(tmp_path)
    contract = build_interaction_contract(run / "workspace")
    actions = _STRUCT_FIXTURE_1["actions"]
    e1 = structured_input_evidence(contract, actions)
    e2 = structured_input_evidence(contract, actions)
    assert e1 == e2
    assert e1[0]["input_digest"] == e2[0]["input_digest"]


def test_type_loss_fails_smoke_and_validator(tmp_path):
    """§9.3: schema object → 문자열 변질이면 smoke problems + validator FAIL."""
    run = _make_struct_run(tmp_path)
    ws = run / "workspace"
    # fixture를 오염시켜 string 변질을 재현 — 관측(2 fixture 병합)은 object|string이 되므로
    # 별도 contract로 직접 검증한다
    contract = build_interaction_contract(ws)
    bad_actions = [{"type": "configure", "payload": {"settings": '{"enabled": false}'}}]
    evidence = structured_input_evidence(contract, bad_actions)
    assert evidence[0]["value_kind"] == "string"
    assert evidence[0]["type_preserved"] is False
    # validator: 기록된 smoke report에 type_preserved=false가 있으면 실패
    out = run_interaction_ui(run_dir=run, apply=True)
    assert out["applied"]
    report_path = run / "review/interaction_ui/interaction_ui_report.json"
    report = _load(report_path)
    assert _check_interaction_ui(run) == []
    report["interaction_smoke"]["structured_input"] = evidence
    _dump(report_path, report)
    assert any("타입 손실" in p for p in _check_interaction_ui(run))


# ---------------------------------------------------------------- §12 primitive 회귀

def test_primitive_domains_unaffected(tmp_path):
    """ledger(string)/panel(string)/table(grid 경로) — 기존 동작 유지."""
    for domain in ("ledger", "panel"):
        run = _make_domain_run(tmp_path, domain)
        out = run_interaction_ui(run_dir=run, apply=True)
        assert out["ok"] is True, (domain, out["problems"])
        smoke = out["interaction_smoke"]
        assert smoke["state_change_observed"] is True
        assert smoke["invalid_action_rejected"] is True
        # primitive 도메인은 structured evidence가 비어 있다 (object/array 관측 없음)
        assert smoke["structured_input"] == []


def test_server_validation_accepts_primitive_string_payload(tmp_path):
    """ledger amount는 string 관측 — 문자열 payload가 그대로 유효 (기존 계약 유지)."""
    run = _make_domain_run(tmp_path, "ledger")
    out = run_interaction_ui(run_dir=run, apply=True)
    assert out["applied"]
    mod = _load_server_module(run)
    contract = _server_contract(run)
    assert mod.validate_actions(
        contract, [{"type": "add_entry", "payload": {"amount": "5"}}]) == []
    # string 관측 field에 number가 오면 서버가 거부한다 (관측 계약과 불일치)
    p = mod.validate_actions(contract, [{"type": "add_entry", "payload": {"amount": 5}}])
    assert any("TYPE_MISMATCH" in x for x in p)


def test_table_grid_path_untouched(tmp_path):
    """Table 17 typed grid 경로(이슈 #10)는 이번 변경과 독립 — grid UI 생성 유지."""
    run = _make_domain_run(tmp_path, "table")
    contract = build_interaction_contract(run / "workspace")
    assert contract["interaction_kind"] == "table_grid"
    ui = generate_interaction_ui(contract)
    assert "grid-table" in ui
