# 이슈 #5 §6·§10.3: 도메인 중립 INTERACTION_UI executor — contract 파싱/2개 도메인/거부/evidence/validator/mock 금지.
import json
from pathlib import Path

from repo_idea_miner.factory_core_gates import detect_mock_fallback
from repo_idea_miner.factory_interaction_ui import (
    KIND_ACTION_CONSOLE,
    KIND_GRAPH_EDITOR,
    build_interaction_contract,
    detect_interaction_kind,
    generate_interaction_ui,
    run_interaction_ui,
)
from repo_idea_miner.factory_validate import _check_interaction_ui


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


_LEDGER_RUNNER = '''import argparse, copy, json

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    args = ap.parse_args()
    sc = json.load(open(args.scenario, encoding="utf-8"))
    state = copy.deepcopy(sc["initial_state"])
    events, errors = [], []
    for a in sc.get("actions") or []:
        kind = a.get("type")
        payload = a.get("payload") or {}
        if kind == "add_entry":
            amount = payload.get("amount")
            try:
                value = int(amount)
            except (TypeError, ValueError):
                errors.append("amount가 필요합니다")
                events.append({"type": "ERROR_OCCURRED", "target_id": str(amount)})
                continue
            state["Ledger"]["total"] += value
            state["Ledger"]["entries"].append(value)
            events.append({"type": "ENTRY_ADDED", "target_id": str(value)})
        else:
            errors.append(f"unknown action: {kind}")
            events.append({"type": "ERROR_OCCURRED", "target_id": "system"})
    print(json.dumps({"ok": not errors, "final_state": state, "events": events,
                      "summary": f"{len(events)} events", "errors": errors},
                     ensure_ascii=True))

if __name__ == "__main__":
    main()
'''

_PANEL_RUNNER = '''import argparse, copy, json

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    args = ap.parse_args()
    sc = json.load(open(args.scenario, encoding="utf-8"))
    state = copy.deepcopy(sc["initial_state"])
    events, errors = [], []
    for a in sc.get("actions") or []:
        kind = a.get("type")
        payload = a.get("payload") or {}
        if kind == "set_mode":
            mode = payload.get("mode")
            if mode not in ("idle", "active"):
                errors.append("mode는 idle|active여야 합니다")
                events.append({"type": "ERROR_OCCURRED", "target_id": str(mode)})
                continue
            state["Panel"]["mode"] = mode
            state["Panel"]["steps"] += 1
            events.append({"type": "MODE_SET", "target_id": mode})
        else:
            errors.append(f"unknown action: {kind}")
            events.append({"type": "ERROR_OCCURRED", "target_id": "system"})
    print(json.dumps({"ok": not errors, "final_state": state, "events": events,
                      "summary": f"{len(events)} events", "errors": errors},
                     ensure_ascii=True))

if __name__ == "__main__":
    main()
'''

_DOMAINS = {
    "ledger": {
        "runner": _LEDGER_RUNNER,
        "state_contract": {"state_entities": [
            {"name": "Ledger", "fields": ["total", "entries"], "invariants": ["total >= 0"]}]},
        "action_contract": {"actions": [
            {"name": "add_entry", "input": ["amount"],
             "preconditions": ["amount는 정수여야 함"], "output": ["ENTRY_ADDED"]}]},
        "fixture": {"id": "scenario_001",
                    "initial_state": {"Ledger": {"total": 0, "entries": []}},
                    "actions": [{"type": "add_entry", "payload": {"amount": "5"}},
                                {"type": "add_entry", "payload": {"amount": "7"}}]},
    },
    "panel": {
        "runner": _PANEL_RUNNER,
        "state_contract": {"state_entities": [
            {"name": "Panel", "fields": ["mode", "steps"], "invariants": ["steps >= 0"]}]},
        "action_contract": {"actions": [
            {"name": "set_mode", "input": ["mode"],
             "preconditions": ["mode는 idle|active"], "output": ["MODE_SET"]}]},
        "fixture": {"id": "scenario_001",
                    "initial_state": {"Panel": {"mode": "idle", "steps": 0}},
                    "actions": [{"type": "set_mode", "payload": {"mode": "active"}},
                                {"type": "set_mode", "payload": {"mode": "idle"}}]},
    },
}


def _make_domain_run(tmp_path: Path, domain: str) -> Path:
    spec = _DOMAINS[domain]
    run = tmp_path / f"run_{domain}"
    ws = run / "workspace"
    _dump(ws / "state_contract.json", spec["state_contract"])
    _dump(ws / "action_contract.json", spec["action_contract"])
    _dump(ws / "runner_contract.json",
          {"runner_command": "python src/runner.py --scenario fixtures/scenario_001.json"})
    _dump(ws / "fixtures" / "scenario_001.json", spec["fixture"])
    (ws / "src").mkdir(parents=True, exist_ok=True)
    (ws / "src" / "runner.py").write_text(spec["runner"], encoding="utf-8")
    return run


# ---------------------------------------------------------------- kind 감지 / contract (§6.2~6.3)

def test_detect_kind_by_artifact_shape(tmp_path):
    """graph(state에 nodes+edges)는 graph adapter로, action_contract가 있으면 console로."""
    run = _make_domain_run(tmp_path, "ledger")
    assert detect_interaction_kind(run / "workspace") == KIND_ACTION_CONSOLE

    graph = tmp_path / "graph_run" / "workspace"
    _dump(graph / "state_contract.json", {"state_entities": [
        {"name": "GraphState", "fields": ["nodes", "edges", "global_tick"], "invariants": []}]})
    _dump(graph / "action_contract.json", {"actions": [{"name": "add_node", "input": ["id"]}]})
    assert detect_interaction_kind(graph) == KIND_GRAPH_EDITOR

    empty = tmp_path / "empty_run" / "workspace"
    empty.mkdir(parents=True)
    assert detect_interaction_kind(empty) is None


def test_contract_reuses_existing_artifacts_and_is_deterministic(tmp_path):
    """§6.2: contract는 기존 artifact에서 유도되고 결정적이다 — 새 정보를 지어내지 않는다."""
    run = _make_domain_run(tmp_path, "ledger")
    c1 = build_interaction_contract(run / "workspace")
    c2 = build_interaction_contract(run / "workspace")
    assert c1 == c2
    assert c1["supported"] is True
    assert c1["interaction_kind"] == KIND_ACTION_CONSOLE
    assert c1["input_schema"] == {"add_entry": ["amount"]}
    assert c1["state_schema"] == {"Ledger": ["total", "entries"]}
    assert c1["initial_state"] == _DOMAINS["ledger"]["fixture"]["initial_state"]
    assert any(r.get("rule") == "total >= 0" for r in c1["validation_rules"])
    # UI 생성도 결정적
    assert generate_interaction_ui(c1) == generate_interaction_ui(c2)


def test_missing_artifact_explicit_unsupported(tmp_path):
    """§6.5: 필수 artifact가 없으면 명시적 missing — mock 대체 없음, 파일 미생성."""
    run = tmp_path / "bare_run"
    (run / "workspace").mkdir(parents=True)
    out = run_interaction_ui(run_dir=run, apply=True)
    assert out["applied"] is False
    assert out["status"] == "PRECONDITION_UNSUPPORTED_INTERACTION"
    assert any("missing" in p for p in out["problems"])
    assert not (run / "workspace" / "product").exists()


def test_invalid_artifact_explicit_error(tmp_path):
    """§6.5: 깨진 artifact는 명시적 오류 상태 — 성공처럼 진행하지 않는다."""
    run = _make_domain_run(tmp_path, "ledger")
    (run / "workspace" / "action_contract.json").write_text("{broken json", encoding="utf-8")
    out = run_interaction_ui(run_dir=run, apply=True)
    assert out["applied"] is False
    assert out["status"] == "PRECONDITION_UNSUPPORTED_INTERACTION"


# ---------------------------------------------------------------- 2개 도메인 실증 (§6.4, §7.4)

def _apply_domain(tmp_path, domain):
    run = _make_domain_run(tmp_path, domain)
    out = run_interaction_ui(run_dir=run, apply=True)
    return run, out


def test_same_executor_covers_two_domains(tmp_path):
    """§7.4: 서로 다른 두 도메인에서 동일 executor로 실조작 UI + runner 실증."""
    for domain in ("ledger", "panel"):
        run, out = _apply_domain(tmp_path, domain)
        assert out["applied"] is True, (domain, out)
        assert out["ok"] is True, (domain, out["problems"])
        assert out["status"] == "APPLIED"
        smoke = out["interaction_smoke"]
        assert smoke["state_change_observed"] is True
        assert smoke["invalid_action_rejected"] is True
        assert smoke["revise_changes_result"] is True
        for rel in ("product/interaction/contract.json", "product/interaction/index.html",
                    "product/interaction_server.py"):
            assert (run / "workspace" / rel).is_file(), (domain, rel)
        assert (run / "review/interaction_ui/interaction_evidence.json").is_file()
        assert (run / "review/interaction_ui/interaction_ui_report.json").is_file()


def test_evidence_records_transition_and_rejection(tmp_path):
    """§6.4: evidence에 valid 실행/invalid 거부/재실행 변화가 남는다."""
    run, out = _apply_domain(tmp_path, "panel")
    ev = _load(run / "review/interaction_ui/interaction_evidence.json")
    names = [e["exchange"] for e in ev["exchanges"]]
    assert "valid_action" in names and "invalid_action_missing_input" in names
    assert ev["state_change_observed"] is True
    assert ev["invalid_action_rejected"] is True
    invalid = next(e for e in ev["exchanges"] if e["exchange"] == "invalid_action_missing_input")
    assert invalid["error_signal"] is True


def test_plan_only_writes_nothing(tmp_path):
    run = _make_domain_run(tmp_path, "ledger")
    out = run_interaction_ui(run_dir=run, apply=False)
    assert out["ok"] is True and out["status"] == "PLAN_ONLY"
    assert not (run / "workspace" / "product").exists()
    assert not (run / "review").exists()


# ---------------------------------------------------------------- validator / mock 금지 (§6.5)

def test_validator_accepts_honest_run_and_blocks_overclaim(tmp_path):
    run, _ = _apply_domain(tmp_path, "ledger")
    assert _check_interaction_ui(run) == []
    # smoke_pass=true인데 실증 필드가 꺼져 있으면 차단
    report_path = run / "review/interaction_ui/interaction_ui_report.json"
    report = _load(report_path)
    report["interaction_smoke"]["state_change_observed"] = False
    _dump(report_path, report)
    assert any("state 변경 실증" in p for p in _check_interaction_ui(run))


def test_generated_ui_has_no_mock_fallback(tmp_path):
    """production 경로 mock success 금지 — 정적 검출기와 fake-result 규칙 통과."""
    run, _ = _apply_domain(tmp_path, "ledger")
    files = {}
    for rel in ("product/interaction/index.html", "product/interaction_server.py"):
        files[rel] = (run / "workspace" / rel).read_text(encoding="utf-8")
    result = detect_mock_fallback(files)
    assert result["mock_fallback_count"] == 0, result["problems"]
    for text in files.values():
        assert "Math.random" not in text and "Date.now" not in text


def test_module_has_no_challenge_hardcode():
    """§6.3 금지: executor 소스에 특정 challenge/도메인 의미 하드코드 없음."""
    src = Path("repo_idea_miner/factory_interaction_ui.py").read_text(encoding="utf-8")
    for token in ("challenge47", "challenge_47", "challenge54", "challenge_54",
                  "folder_id", "item_id", "FileSystem", "root_node",
                  "supported_node_types", "add_entry", "set_mode"):
        assert token not in src, token


# ---------------------------------------------------------------- lane 라우팅 (§6.3)

def test_lane_routes_graph_to_legacy_adapter(tmp_path, monkeypatch):
    """graph 도메인은 legacy graph adapter(2C-2), 그 외는 generic executor로 라우팅."""
    import repo_idea_miner.factory_interaction_ui as fiu
    import repo_idea_miner.factory_lane_executors as fle
    import repo_idea_miner.factory_product_editor as fpe

    calls = []

    def fake_editor(run_dir=None, apply=False, timeout=60.0, **kw):
        calls.append("graph_adapter")
        return {"applied": False, "patched_files": [], "problems": [], "error": None,
                "ok": False, "status": "PRECONDITION_TEST"}

    def fake_generic(run_dir=None, apply=False, timeout=60.0, **kw):
        calls.append("generic")
        return {"applied": False, "patched_files": [], "problems": [], "error": None,
                "ok": False, "status": "PRECONDITION_TEST"}

    monkeypatch.setattr(fpe, "run_product_editor", fake_editor)
    monkeypatch.setattr(fiu, "run_interaction_ui", fake_generic)

    generic_run = _make_domain_run(tmp_path, "ledger")
    fle.execute_lane("INTERACTION_UI", {"parent_run_dir": generic_run,
                                        "children_root": tmp_path / "children"})
    graph_run = tmp_path / "graph_parent"
    _dump(graph_run / "workspace" / "state_contract.json", {"state_entities": [
        {"name": "GraphState", "fields": ["nodes", "edges"], "invariants": []}]})
    fle.execute_lane("INTERACTION_UI", {"parent_run_dir": graph_run,
                                        "children_root": tmp_path / "children"})
    assert calls == ["generic", "graph_adapter"]
