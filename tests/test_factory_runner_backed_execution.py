# 이슈 #6 §15: 도메인 중립 RUNNER_BACKED_DRAFT_EXECUTION — contract/실행/evidence/validator/lane/ladder 검증.
import json
import shutil
from pathlib import Path

import pytest

from repo_idea_miner.factory_interaction_ui import run_interaction_ui
from repo_idea_miner.factory_runner_backed_execution import (
    EXECUTION_STATUSES,
    PRE_EXECUTION_STATUSES,
    build_execution_contract,
    run_runner_backed_execution,
)
from repo_idea_miner.factory_validate import _check_draft_execution_lane


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# 공통 runner 골격 — 도메인별 action 처리만 다르다 (테스트 fixture 전용, 결정적)
_RUNNER_TEMPLATE = '''import argparse, copy, json

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
        __HANDLERS__
    print(json.dumps({"ok": not errors, "final_state": state, "events": events,
                      "summary": f"{len(events)} events", "errors": errors},
                     ensure_ascii=True))

if __name__ == "__main__":
    main()
'''

_RULES_HANDLER = '''
        if kind == "answer_card":
            grade = payload.get("grade")
            try:
                g = int(grade)
            except (TypeError, ValueError):
                errors.append("grade가 필요합니다")
                events.append({"type": "ERROR_OCCURRED", "target_id": str(grade)})
                continue
            state["ReviewState"]["streak"] += 1
            state["ReviewState"]["last_grade"] = g
            events.append({"type": "CARD_ANSWERED", "target_id": str(g)})
        else:
            errors.append(f"unknown action: {kind}")
            events.append({"type": "ERROR_OCCURRED", "target_id": "system"})
'''

_TABLE_HANDLER = '''
        if kind == "add_column":
            name = payload.get("name")
            if not name:
                errors.append("name이 필요합니다")
                events.append({"type": "ERROR_OCCURRED", "target_id": str(name)})
                continue
            state["Table"]["columns"].append(name)
            events.append({"type": "COLUMN_ADDED", "target_id": name})
        else:
            errors.append(f"unknown action: {kind}")
            events.append({"type": "ERROR_OCCURRED", "target_id": "system"})
'''

_FILES_HANDLER = '''
        if kind == "enter_folder":
            fid = payload.get("folder_id")
            if fid not in state["Tree"]["entries"]:
                errors.append("존재하지 않는 폴더")
                events.append({"type": "ERROR_OCCURRED", "target_id": str(fid)})
                continue
            state["Tree"]["current"] = fid
            events.append({"type": "FOLDER_ENTERED", "target_id": fid})
        else:
            errors.append(f"unknown action: {kind}")
            events.append({"type": "ERROR_OCCURRED", "target_id": "system"})
'''

# 세 도메인 — state-rule형 / table형 / filesystem형 (§15.5). 동일 executor로 실행돼야 한다.
_DOMAINS = {
    "rules": {
        "handler": _RULES_HANDLER,
        "state_contract": {"state_entities": [
            {"name": "ReviewState", "fields": ["streak", "last_grade"],
             "invariants": ["streak >= 0"]}]},
        "action_contract": {"actions": [
            {"name": "answer_card", "input": ["grade"],
             "preconditions": ["grade는 정수"], "output": ["CARD_ANSWERED"]}]},
        "fixture": {"id": "scenario_001", "case_type": "normal",
                    "initial_state": {"ReviewState": {"streak": 0, "last_grade": None}},
                    "actions": [{"type": "answer_card", "payload": {"grade": "3"}},
                                {"type": "answer_card", "payload": {"grade": "5"}}]},
    },
    "table": {
        "handler": _TABLE_HANDLER,
        "state_contract": {"state_entities": [
            {"name": "Table", "fields": ["columns", "rows"],
             "invariants": ["columns는 중복 없음"]}]},
        "action_contract": {"actions": [
            {"name": "add_column", "input": ["name"],
             "preconditions": ["name 비어있지 않음"], "output": ["COLUMN_ADDED"]}]},
        "fixture": {"id": "scenario_001", "case_type": "normal",
                    "initial_state": {"Table": {"columns": [], "rows": []}},
                    "actions": [{"type": "add_column", "payload": {"name": "col_a"}},
                                {"type": "add_column", "payload": {"name": "col_b"}}]},
    },
    "files": {
        "handler": _FILES_HANDLER,
        "state_contract": {"state_entities": [
            {"name": "Tree", "fields": ["current", "entries"],
             "invariants": ["current는 entries에 존재"]}]},
        "action_contract": {"actions": [
            {"name": "enter_folder", "input": ["folder_id"],
             "preconditions": ["folder_id는 존재하는 폴더"], "output": ["FOLDER_ENTERED"]}]},
        "fixture": {"id": "scenario_001", "case_type": "normal",
                    "initial_state": {"Tree": {"current": "root",
                                               "entries": ["root", "docs", "img"]}},
                    "actions": [{"type": "enter_folder", "payload": {"folder_id": "docs"}},
                                {"type": "enter_folder", "payload": {"folder_id": "img"}}]},
    },
}


def _make_domain_run(tmp_path: Path, domain: str) -> Path:
    spec = _DOMAINS[domain]
    run = tmp_path / f"run_{domain}"
    ws = run / "workspace"
    _dump(ws / "state_contract.json", spec["state_contract"])
    _dump(ws / "action_contract.json", spec["action_contract"])
    _dump(ws / "runner_contract.json",
          {"runner_command": "python src/runner.py --scenario fixtures/scenario_001.json",
           "required_output_fields": ["ok", "final_state", "events", "summary", "errors"]})
    _dump(ws / "fixtures" / "scenario_001.json", spec["fixture"])
    (ws / "src").mkdir(parents=True, exist_ok=True)
    (ws / "src" / "runner.py").write_text(
        _RUNNER_TEMPLATE.replace("__HANDLERS__", spec["handler"].strip()), encoding="utf-8")
    (ws / "golden").mkdir(exist_ok=True)
    (ws / "golden" / "expected_001.json").write_text("{}", encoding="utf-8")
    # gate 문맥 — 없으면 judge가 EVIDENCE_INSUFFICIENT로 빠진다 (실런은 항상 보유)
    _dump(run / "green_base.json",
          {"base_type": "green_base", "verdict": "REVIEW_READY"})
    # replay + replay viewer — 없으면 ladder가 VIEWER_POLISH rung에서 멈춘다 (실런은 항상 보유)
    _dump(ws / "replay" / "index.json", {"replays": [{"file": "replay_scenario_001.json"}]})
    _dump(ws / "replay" / "replay_scenario_001.json",
          {"final_state": spec["fixture"]["initial_state"], "events": [],
           "summary": "replay", "errors": []})
    (ws / "product" / "viewer").mkdir(parents=True, exist_ok=True)
    (ws / "product" / "viewer" / "index.html").write_text(
        '<html><script>fetch("replay/index.json").then(r=>r.json());'
        'fetch("replay/replay_scenario_001.json").then(r=>r.json()).then(data=>{'
        'document.body.textContent = JSON.stringify(data.final_state) + data.summary;});'
        '</script></html>', encoding="utf-8")
    return run


def _prepare_with_draft(tmp_path: Path, domain: str) -> Path:
    """INTERACTION_UI executor로 draft(interaction contract)를 만든 run을 준비한다."""
    run = _make_domain_run(tmp_path, domain)
    out = run_interaction_ui(run_dir=run, apply=True)
    assert out["applied"] is True, out
    return run


# ---------------------------------------------------------------- §15.1 Execution Contract

def test_valid_canonical_execution_contract(tmp_path):
    run = _prepare_with_draft(tmp_path, "rules")
    pre = build_execution_contract(run / "workspace", timeout=30.0)
    assert pre["pre_execution_status"] == "READY_TO_EXECUTE"
    c = pre["contract"]
    for key in ("execution_id", "draft_ref", "runner_ref", "execution_kind",
                "input_payload", "initial_state", "allowed_actions", "expected_outputs",
                "side_effect_policy", "timeout_policy", "validation_rules",
                "evidence_requirements"):
        assert key in c, key
    assert c["execution_kind"] == "action_scenario"
    assert c["allowed_actions"] == ["answer_card"]
    assert c["timeout_policy"]["per_exchange_seconds"] == 30.0


def test_missing_draft_is_invalid_draft(tmp_path):
    run = _make_domain_run(tmp_path, "rules")  # interaction contract 미생성
    pre = build_execution_contract(run / "workspace", timeout=30.0)
    assert pre["pre_execution_status"] == "INVALID_DRAFT"
    out = run_runner_backed_execution(run_dir=run, apply=True)
    assert out["applied"] is False
    assert out["status"] == "PRECONDITION_INVALID_DRAFT"


def test_missing_runner_contract(tmp_path):
    run = _prepare_with_draft(tmp_path, "rules")
    (run / "workspace" / "runner_contract.json").write_text("{}", encoding="utf-8")
    pre = build_execution_contract(run / "workspace", timeout=30.0)
    assert pre["pre_execution_status"] == "MISSING_RUNNER"


def test_missing_validation_contract(tmp_path):
    run = _prepare_with_draft(tmp_path, "rules")
    draft_path = run / "workspace" / "product" / "interaction" / "contract.json"
    draft = _load(draft_path)
    draft["validation_rules"] = []
    draft["evidence_requirements"] = []
    _dump(draft_path, draft)
    pre = build_execution_contract(run / "workspace", timeout=30.0)
    assert pre["pre_execution_status"] == "MISSING_VALIDATION_CONTRACT"


def test_graph_kind_unsupported_here(tmp_path):
    ws = tmp_path / "graph_run" / "workspace"
    _dump(ws / "state_contract.json", {"state_entities": [
        {"name": "GraphState", "fields": ["nodes", "edges"], "invariants": []}]})
    _dump(ws / "action_contract.json", {"actions": [{"name": "add_node", "input": ["id"]}]})
    pre = build_execution_contract(ws, timeout=30.0)
    assert pre["pre_execution_status"] == "UNSUPPORTED_EXECUTION_KIND"


def test_unsafe_runner_command_rejected(tmp_path):
    run = _prepare_with_draft(tmp_path, "rules")
    _dump(run / "workspace" / "runner_contract.json",
          {"runner_command": "python ../outside/runner.py --scenario fixtures/scenario_001.json"})
    pre = build_execution_contract(run / "workspace", timeout=30.0)
    assert pre["pre_execution_status"] == "UNSAFE_SIDE_EFFECT"


def test_missing_input_when_fixture_has_no_actions(tmp_path):
    run = _prepare_with_draft(tmp_path, "rules")
    fx = run / "workspace" / "fixtures" / "scenario_001.json"
    data = _load(fx)
    data["actions"] = []
    _dump(fx, data)
    pre = build_execution_contract(run / "workspace", timeout=30.0)
    assert pre["pre_execution_status"] == "MISSING_INPUT"


def test_contract_is_deterministic(tmp_path):
    run = _prepare_with_draft(tmp_path, "rules")
    c1 = build_execution_contract(run / "workspace", timeout=30.0)["contract"]
    c2 = build_execution_contract(run / "workspace", timeout=30.0)["contract"]
    assert json.dumps(c1, sort_keys=True) == json.dumps(c2, sort_keys=True)
    assert c1["execution_id"] == c2["execution_id"]


def test_module_has_no_challenge_hardcode():
    src = Path("repo_idea_miner/factory_runner_backed_execution.py").read_text(encoding="utf-8")
    for token in ("challenge47", "challenge_47", "challenge54", "challenge_54",
                  "folder_id", "item_id", "FileSystem", "root_node", "scenario_001",
                  "answer_card", "add_column", "enter_folder"):
        assert token not in src, token


# ---------------------------------------------------------------- §15.2 Runner Execution

def test_successful_execution_all_domains_same_executor(tmp_path):
    """§15.5: 세 도메인(state-rule/table/filesystem)이 동일 executor로 EXECUTED된다."""
    for domain in _DOMAINS:
        run = _prepare_with_draft(tmp_path, domain)
        out = run_runner_backed_execution(run_dir=run, apply=True)
        assert out["applied"] is True, (domain, out["problems"], out["error"])
        assert out["ok"] is True and out["status"] == "EXECUTED"
        ev = out["execution_evidence"]
        assert ev["state_change_observed"] is True, domain
        assert ev["invalid_action_rejected"] is True, domain
        assert ev["revise_changes_result"] is True, domain
        for rel in ("draft_execution_report.json", "execution_contract.json",
                    "execution_result.json", "side_effect_manifest.json",
                    "execution_evidence.json", "draft_execution_dashboard_summary.json"):
            assert (run / "review/draft_execution" / rel).is_file(), (domain, rel)


def test_runner_nonzero_exit_is_runner_failed(tmp_path):
    run = _prepare_with_draft(tmp_path, "rules")
    (run / "workspace" / "src" / "runner.py").write_text(
        "import sys\nsys.exit(2)\n", encoding="utf-8")
    out = run_runner_backed_execution(run_dir=run, apply=True)
    assert out["applied"] is False
    assert out["status"] == "RUNNER_FAILED"


def test_runner_non_json_output_is_runner_failed(tmp_path):
    run = _prepare_with_draft(tmp_path, "rules")
    (run / "workspace" / "src" / "runner.py").write_text(
        "print('not json at all')\n", encoding="utf-8")
    out = run_runner_backed_execution(run_dir=run, apply=True)
    assert out["applied"] is False
    assert out["status"] == "RUNNER_FAILED"


def test_runner_timeout_is_timed_out(tmp_path):
    run = _prepare_with_draft(tmp_path, "rules")
    (run / "workspace" / "src" / "runner.py").write_text(
        "import time\ntime.sleep(30)\n", encoding="utf-8")
    out = run_runner_backed_execution(run_dir=run, apply=True, timeout=2.0)
    assert out["applied"] is False
    assert out["status"] == "TIMED_OUT"


def test_no_state_transition_is_validation_failed(tmp_path):
    run = _prepare_with_draft(tmp_path, "rules")
    # 항상 initial_state를 그대로 돌려주는 runner — 실행은 성공하지만 조작 효과가 없다
    (run / "workspace" / "src" / "runner.py").write_text(
        'import argparse, json\n'
        'ap = argparse.ArgumentParser(); ap.add_argument("--scenario", required=True)\n'
        'a = ap.parse_args(); sc = json.load(open(a.scenario, encoding="utf-8"))\n'
        'print(json.dumps({"ok": True, "final_state": sc["initial_state"],\n'
        '                  "events": [], "summary": "0", "errors": []}))\n',
        encoding="utf-8")
    out = run_runner_backed_execution(run_dir=run, apply=True)
    assert out["applied"] is False
    assert out["status"] == "VALIDATION_FAILED"
    assert any("state_transition_ok" in p for p in out["problems"])


def test_protected_path_write_is_unsafe(tmp_path):
    run = _prepare_with_draft(tmp_path, "rules")
    runner_path = run / "workspace" / "src" / "runner.py"
    original = runner_path.read_text(encoding="utf-8")
    tampering = original.replace(
        "    print(json.dumps(",
        '    open("golden/tampered.json", "w").write("{}")\n    print(json.dumps(', 1)
    assert tampering != original
    runner_path.write_text(tampering, encoding="utf-8")
    out = run_runner_backed_execution(run_dir=run, apply=True)
    assert out["applied"] is False
    assert out["status"] == "UNSAFE"
    # 원본 golden은 불변이어야 한다 (temp copy에서만 실행)
    assert not (run / "workspace" / "golden" / "tampered.json").exists()


def test_side_effect_manifest_and_stdio_cap(tmp_path):
    run = _prepare_with_draft(tmp_path, "files")
    out = run_runner_backed_execution(run_dir=run, apply=True)
    manifest = _load(run / "review/draft_execution/side_effect_manifest.json")
    assert manifest["protected_paths_unchanged"] is True
    assert all(c.startswith("fixtures/_draft_execution/") for c in manifest["created"])
    assert manifest["deleted"] == [] and manifest["modified"] == []
    assert isinstance(manifest["exit_codes"], list) and manifest["any_timeout"] is False
    ev = _load(run / "review/draft_execution/execution_evidence.json")
    for e in ev["exchanges"]:
        assert len(e.get("stderr_summary") or "") <= 400


def test_original_artifact_unchanged_after_execution(tmp_path):
    """§15.2-10·11: 실행은 temp copy에서만 — 원본 workspace 파일은 전부 불변."""
    import hashlib
    run = _prepare_with_draft(tmp_path, "table")
    ws = run / "workspace"
    before = {p.relative_to(ws).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(ws.rglob("*")) if p.is_file()}
    out = run_runner_backed_execution(run_dir=run, apply=True)
    assert out["applied"] is True
    after = {p.relative_to(ws).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(ws.rglob("*")) if p.is_file()}
    assert before == after


# ---------------------------------------------------------------- §15.3 Evidence + validator

def test_evidence_has_fresh_provenance_and_digests(tmp_path):
    run = _prepare_with_draft(tmp_path, "rules")
    run_runner_backed_execution(run_dir=run, apply=True)
    ev = _load(run / "review/draft_execution/execution_evidence.json")
    prov = ev["execution_provenance"]
    assert prov["fresh"] is True and prov["started_at"] and prov["finished_at"]
    assert ev["input_digest"] and ev["initial_state_digest"] and ev["final_state_digest"]
    assert ev["runner_identity"].startswith("python ")
    result = _load(run / "review/draft_execution/execution_result.json")
    assert result["status"] == "EXECUTED"
    assert result["status"] in EXECUTION_STATUSES
    assert result["inputs_digest"] == ev["input_digest"]


def test_validator_accepts_honest_run(tmp_path):
    run = _prepare_with_draft(tmp_path, "files")
    run_runner_backed_execution(run_dir=run, apply=True)
    assert _check_draft_execution_lane(run) == []


def test_validator_blocks_included_overclaim(tmp_path):
    run = _prepare_with_draft(tmp_path, "files")
    run_runner_backed_execution(run_dir=run, apply=True)
    ev_path = run / "review/draft_execution/execution_evidence.json"
    ev = _load(ev_path)
    ev["state_change_observed"] = False
    _dump(ev_path, ev)
    assert any("state 변화 실증" in p for p in _check_draft_execution_lane(run))


def test_validator_blocks_mock_evidence(tmp_path):
    """§15.2-12: 실제 exchange 없이 included=true로 조작된 report는 mock으로 거부."""
    run = _prepare_with_draft(tmp_path, "files")
    run_runner_backed_execution(run_dir=run, apply=True)
    ev_path = run / "review/draft_execution/execution_evidence.json"
    ev = _load(ev_path)
    ev["exchanges"] = []
    _dump(ev_path, ev)
    assert any("mock 의심" in p for p in _check_draft_execution_lane(run))


def test_validator_blocks_stale_provenance(tmp_path):
    """§15.3-7: fresh provenance 없는(과거 재사용 의심) evidence 거부."""
    run = _prepare_with_draft(tmp_path, "files")
    run_runner_backed_execution(run_dir=run, apply=True)
    ev_path = run / "review/draft_execution/execution_evidence.json"
    ev = _load(ev_path)
    ev["execution_provenance"]["fresh"] = False
    _dump(ev_path, ev)
    assert any("fresh provenance" in p for p in _check_draft_execution_lane(run))


def test_failed_execution_report_is_honest(tmp_path):
    """실패 run의 report는 applied=false·included=false로 남고 validator를 통과한다."""
    run = _prepare_with_draft(tmp_path, "rules")
    (run / "workspace" / "src" / "runner.py").write_text(
        "import sys\nsys.exit(2)\n", encoding="utf-8")
    run_runner_backed_execution(run_dir=run, apply=True)
    report = _load(run / "review/draft_execution/draft_execution_report.json")
    assert report["applied"] is False
    assert report["runner_backed_execution_included"] is False
    assert report["execution_status"] == "RUNNER_FAILED"
    assert _check_draft_execution_lane(run) == []


# ---------------------------------------------------------------- §15.4 Product Loop 통합

def test_lane_routes_graph_to_legacy_and_generic_to_new(tmp_path, monkeypatch):
    import repo_idea_miner.factory_draft_execution as fde
    import repo_idea_miner.factory_lane_executors as fle
    import repo_idea_miner.factory_runner_backed_execution as frbe

    calls = []

    def fake_legacy(run_dir=None, apply=False, timeout=60.0, **kw):
        calls.append("graph_adapter")
        return {"applied": False, "patched_files": [], "problems": [], "error": None,
                "ok": False, "status": "PRECONDITION_TEST"}

    def fake_generic(run_dir=None, apply=False, timeout=60.0, **kw):
        calls.append("generic")
        return {"applied": False, "patched_files": [], "problems": [], "error": None,
                "ok": False, "status": "PRECONDITION_TEST"}

    monkeypatch.setattr(fde, "run_draft_execution", fake_legacy)
    monkeypatch.setattr(frbe, "run_runner_backed_execution", fake_generic)

    generic_run = _make_domain_run(tmp_path, "rules")
    fle.execute_lane("RUNNER_BACKED_DRAFT_EXECUTION",
                     {"parent_run_dir": generic_run, "children_root": tmp_path / "children"})
    graph_run = tmp_path / "graph_parent"
    _dump(graph_run / "workspace" / "state_contract.json", {"state_entities": [
        {"name": "GraphState", "fields": ["nodes", "edges"], "invariants": []}]})
    fle.execute_lane("RUNNER_BACKED_DRAFT_EXECUTION",
                     {"parent_run_dir": graph_run, "children_root": tmp_path / "children"})
    assert calls == ["generic", "graph_adapter"]


def _judge_parts(run):
    from repo_idea_miner.factory_autopilot_desks import derive_primary_gap, mock_product_judge
    from repo_idea_miner.factory_product_loop import (
        apply_hard_blockers,
        extract_artifact_evidence,
        extract_user_facing_quality,
    )
    ev = extract_artifact_evidence(run)
    q = extract_user_facing_quality(ev)
    h = apply_hard_blockers(ev, q)
    sl = mock_product_judge(ev, q, h)
    gap = derive_primary_gap(ev, q, sl)
    return ev, h, sl, gap


def test_gap_requires_execution_after_interaction(tmp_path):
    """§10.2: interaction draft만 있으면 gap=RUNNER_BACKED_EXECUTION_REQUIRED + stage 상한."""
    run = _prepare_with_draft(tmp_path, "rules")
    ev, h, sl, gap = _judge_parts(run)
    assert ev["facts"]["has_interaction_report"] is True
    assert ev["facts"]["has_execution_report"] is False
    assert gap == "RUNNER_BACKED_EXECUTION_REQUIRED"
    from repo_idea_miner.factory_autopilot_schemas import STAGE_RANK
    assert STAGE_RANK[h["max_stage"]] <= STAGE_RANK["INTERACTION_CANDIDATE"]


def test_gap_removed_after_successful_execution(tmp_path):
    """§10.4: 실행·검증 성공 후 RUNNER_BACKED_EXECUTION_REQUIRED가 제거된다."""
    run = _prepare_with_draft(tmp_path, "rules")
    out = run_runner_backed_execution(run_dir=run, apply=True)
    assert out["applied"] is True
    ev, h, sl, gap = _judge_parts(run)
    assert ev["facts"]["has_execution_report"] is True
    assert gap != "RUNNER_BACKED_EXECUTION_REQUIRED"


def test_gap_kept_when_validation_failed(tmp_path):
    """§10.4: validation 실패면 gap이 유지된다 — 실패를 성공으로 포장하지 않는다."""
    run = _prepare_with_draft(tmp_path, "rules")
    (run / "workspace" / "src" / "runner.py").write_text(
        'import argparse, json\n'
        'ap = argparse.ArgumentParser(); ap.add_argument("--scenario", required=True)\n'
        'a = ap.parse_args(); sc = json.load(open(a.scenario, encoding="utf-8"))\n'
        'print(json.dumps({"ok": True, "final_state": sc["initial_state"],\n'
        '                  "events": [], "summary": "0", "errors": []}))\n',
        encoding="utf-8")
    out = run_runner_backed_execution(run_dir=run, apply=True)
    assert out["applied"] is False
    ev, h, sl, gap = _judge_parts(run)
    assert ev["facts"]["has_execution_report"] is False
    assert gap == "RUNNER_BACKED_EXECUTION_REQUIRED"


def test_lane_execution_in_child_keeps_parent_untouched(tmp_path):
    """execute_lane 경유: child에만 실행 산출물, parent 보호 hash PASS."""
    import repo_idea_miner.factory_lane_executors as fle

    run = _prepare_with_draft(tmp_path, "files")
    result = fle.execute_lane("RUNNER_BACKED_DRAFT_EXECUTION",
                              {"parent_run_dir": run, "children_root": tmp_path / "children"})
    assert result["status"] == "APPLIED", result
    assert result["protected_hash_check"] == "PASS"
    assert result["allowed_scope_check"] == "PASS"
    child = Path(result["child_run_dir"])
    assert (child / "review/draft_execution/draft_execution_report.json").is_file()
    assert not (run / "review/draft_execution").exists()


# ---------------------------------------------------------------- 인식 수리 회귀 (probe/static/lineage)

def test_static_viewer_facts_aggregate_multiple_surfaces(tmp_path):
    """UI 표면이 복수일 때 replay를 읽는 표면 기준으로 판정한다 (이슈 #6 수리)."""
    from repo_idea_miner.factory_product_loop import _static_viewer_facts

    run = tmp_path / "run_multi"
    ws = run / "workspace"
    _dump(ws / "replay" / "index.json",
          {"replays": [{"file": "replay_scenario_001.json"}]})
    _dump(ws / "replay" / "replay_scenario_001.json",
          {"final_state": {"x": 1}, "events": [], "summary": "s", "errors": []})
    # 정렬상 앞서는 interaction console(replay 미접근)과 뒤의 replay viewer
    (ws / "product" / "interaction").mkdir(parents=True)
    (ws / "product" / "interaction" / "index.html").write_text(
        "<html><body><button>run</button></body></html>", encoding="utf-8")
    (ws / "product" / "viewer").mkdir(parents=True)
    (ws / "product" / "viewer" / "index.html").write_text(
        '<html><script>fetch("replay/index.json").then(r=>r.json());'
        'fetch("replay/replay_scenario_001.json");'
        'document.body.textContent = data.final_state + data.summary;</script></html>',
        encoding="utf-8")
    facts = _static_viewer_facts(run)
    assert facts["viewer_reads_replay"] is True
    assert facts["viewer_path"].endswith("product/viewer/index.html")


def test_spec_repair_apply_lineage_multi_hop(tmp_path):
    """child-of-child도 apply report 계보를 승계한다 (단일 hop 오탐 수리)."""
    from repo_idea_miner.factory_validate import _check_spec_repair_apply

    grand = tmp_path / "grand_origin"
    grand.mkdir()
    mid = tmp_path / "mid_child"
    mid.mkdir()
    _dump(mid / "child_run_origin.json", {"parent_run_dir": grand.as_posix()})
    leaf = tmp_path / "leaf_child"
    leaf.mkdir()
    _dump(leaf / "child_run_origin.json", {"parent_run_dir": mid.as_posix()})
    report = {"applied": True, "review_result": "APPROVE_FOR_PHASE2B", "target_count": 1,
              "resolved_run_dir": f"runs/{grand.name}"}
    _dump(leaf / "spec_repair_apply_report.json", report)
    problems = _check_spec_repair_apply(leaf)
    assert not any("resolved_run_dir 불일치" in p for p in problems)
    # 계보에 없는 run 이름이면 여전히 오배치로 검출
    report["resolved_run_dir"] = "runs/unrelated_run"
    _dump(leaf / "spec_repair_apply_report.json", report)
    problems = _check_spec_repair_apply(leaf)
    assert any("resolved_run_dir 불일치" in p for p in problems)


def test_pre_execution_statuses_are_never_success():
    assert "READY_TO_EXECUTE" in PRE_EXECUTION_STATUSES
    assert set(PRE_EXECUTION_STATUSES).isdisjoint({"EXECUTED"})
    assert "EXECUTED" in EXECUTION_STATUSES
