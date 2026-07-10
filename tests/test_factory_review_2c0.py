# Phase 2C-0 테스트: #47 green 산출물 no-code-change smoke review + evidence 기반 제품성 추천 (주문서 §18).
import json
import shutil
from pathlib import Path

import pytest

from repo_idea_miner.cli import main
from repo_idea_miner.factory_product_evidence import (
    compute_protected_hashes,
    read_gate_context,
)
from repo_idea_miner.factory_review import (
    REQUIRED_OUTPUTS,
    build_fitness,
    run_review_package,
    smoke_review,
)
from repo_idea_miner.factory_validate import (
    _check_phase2c0,
    detect_phase2c0_run,
    validate_product_run_dir,
)

# 실제 #47 산출물 — E2E 검증용 (gitignore된 runtime 산출물이라 없으면 skip)
FIXTURE_47 = Path("runs/factory_20260709_072220")

# ---------------------------------------------------------------- 합성 green run 빌더

_ENGINE = '''from collections import deque


class Engine:
    def __init__(self):
        self.nodes = {}
        self.edges = []
        self.order = []
        self.events = []

    def add_node(self, id, type):
        self.nodes[id] = {"id": id, "type": type, "input_values": [],
                          "output_values": [], "status": "IDLE"}
        self.events.append({"event": "node_created", "node_id": id})

    def add_edge(self, source_id, source_port, target_id, target_port):
        self.edges.append({"source_id": source_id, "source_port": source_port,
                           "target_id": target_id, "target_port": target_port})
        self.events.append({"event": "edge_created",
                            "edge": {"source_id": source_id, "target_id": target_id}})

    def _topo(self):
        indeg = {n: 0 for n in self.nodes}
        adj = {n: [] for n in self.nodes}
        for e in self.edges:
            adj[e["source_id"]].append(e["target_id"])
            indeg[e["target_id"]] += 1
        q = deque([n for n in self.nodes if indeg[n] == 0])
        order = []
        while q:
            u = q.popleft()
            order.append(u)
            for v in adj[u]:
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)
        if len(order) != len(self.nodes):
            raise RuntimeError("cycle_detected_error")
        return order

    def execute(self, initial_inputs):
        self.order = self._topo()
        for nid in self.order:
            node = self.nodes[nid]
            incoming = [e for e in self.edges if e["target_id"] == nid]
            if not incoming:
                inp = list(initial_inputs.get(nid, []))
            else:
                inp = []
                for e in incoming:
                    src = self.nodes[e["source_id"]]
                    inp.append(src["output_values"][0] if src["output_values"] else 0)
            v = inp[0] if inp else 0
            t = node["type"]
            if t == "INPUT":
                out = inp
            elif t == "ADD_10":
                out = [v + 10]
            elif t == "MUL_2":
                out = [v * 2]
            elif t == "MUL_3":
                out = [v * 3]
            elif t == "SUM":
                out = [sum(inp) if inp else 0]
            elif t == "OUTPUT":
                out = inp
            else:
                out = inp
            node["input_values"] = inp
            node["output_values"] = out
            node["status"] = "COMPLETED"

    def state(self):
        return {"nodes": self.nodes, "edges": self.edges,
                "execution_order": self.order, "global_tick": 1}
'''

_RUNNER = '''import json
import argparse
from core.engine import Engine
from core.summary import summarize


def run():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    a = ap.parse_args()
    with open(a.scenario, encoding="utf-8") as f:
        sc = json.load(f)
    eng = Engine()
    errors = []
    for act in sc.get("actions", []):
        try:
            t = act["type"]
            p = act["payload"]
            if t == "add_node":
                eng.add_node(**p)
            elif t == "add_edge":
                eng.add_edge(**p)
            elif t == "execute_graph":
                eng.execute(**p)
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
            break
    st = eng.state()
    print(json.dumps({"ok": len(errors) == 0, "final_state": st, "events": eng.events,
                      "summary": summarize(st, errors), "errors": errors}))


if __name__ == "__main__":
    run()
'''

_SUMMARY = '''def summarize(final_state, errors):
    nodes = (final_state or {}).get("nodes") or {}
    completed = sum(1 for n in nodes.values() if n.get("status") == "COMPLETED")
    if errors:
        return "Failed"
    if nodes and completed == len(nodes):
        return "Completed"
    return "Partially completed"
'''

# 필드 매핑이 정확하고 저작 조작(addNode/input)이 있는 viewer → PRODUCT_CANDIDATE 후보
_VIEWER_CLEAN = '''<!DOCTYPE html><html><body>
<select id="s"></select><button onclick="load()">Load</button>
<button onclick="addNode()">Add Node</button>
<input id="newtype" placeholder="node type">
<div id="g"></div><div id="d"></div>
<script>
async function init(){ const r = await fetch("../../replay/index.json"); const data = await r.json();
  const sel = document.getElementById("s");
  data.replays.forEach(x=>{const o=document.createElement("option"); o.value=x.file;
    o.textContent=x.id+" "+(x.ok?"OK":"FAIL"); sel.appendChild(o);}); }
async function load(){ const f = document.getElementById("s").value;
  const r = await fetch("../../replay/"+f); const data = await r.json();
  document.getElementById("d").innerHTML = "<pre>"+JSON.stringify(data.summary)+"</pre>";
  data.events.forEach(ev=>{ const e=document.createElement("div"); e.textContent = ev.event;
    document.getElementById("d").appendChild(e); });
  const st = data.final_state; const nodes = st.nodes; const edges = st.edges;
  Object.entries(nodes).forEach(([id,node])=>{ const n=document.createElement("div");
    n.className="node "+node.status; n.textContent=id+" "+node.status;
    document.getElementById("g").appendChild(n); });
  edges.forEach(edge=>{ if(nodes[edge.source_id] && nodes[edge.target_id]){
    const e=document.createElement("div"); e.className="edge";
    document.getElementById("g").appendChild(e);} });
}
function addNode(){ /* author a new node */ }
window.onload = init;
</script></body></html>
'''

# 필드는 정확하지만 저작 조작이 전혀 없는 결과 뷰어 → 기본 NEEDS_PRODUCT_POLISH (§12.3)
_VIEWER_READONLY = _VIEWER_CLEAN.replace(
    '<button onclick="addNode()">Add Node</button>\n<input id="newtype" placeholder="node type">', ""
).replace("function addNode(){ /* author a new node */ }", "")

# #47류: viewer가 replay 스키마와 어긋난 필드(edge.from/ev.type/node.x)를 읽음 → 렌더링 결함
_VIEWER_MISMATCH = '''<!DOCTYPE html><html><body>
<select id="s"></select><button onclick="load()">Load</button>
<div id="g"></div><div id="d"></div>
<script>
async function init(){ const r = await fetch("../../replay/index.json"); const data = await r.json(); }
async function load(){ const f = document.getElementById("s").value;
  const r = await fetch("../../replay/"+f); const data = await r.json();
  document.getElementById("d").innerHTML = JSON.stringify(data.summary);
  data.events.forEach(ev=>{ const e=document.createElement("div");
    e.textContent = ev.type + ": " + ev.message; });
  const st = data.final_state; const nodes = st.nodes; const edges = st.edges;
  Object.entries(nodes).forEach(([id,node])=>{ const n=document.createElement("div");
    n.style.left = node.x + "px"; n.style.top = node.y + "px"; n.textContent = node.status; });
  edges.forEach(edge=>{ const a = nodes[edge.from]; const b = nodes[edge.to]; });
}
window.onload = init;
</script></body></html>
'''

# viewer가 replay를 fetch만 하고 실제 필드를 읽지 않음 → reads=False
_VIEWER_FETCH_ONLY = '''<!DOCTYPE html><html><body><div id="g"></div>
<script>fetch("../../replay/index.json");</script></body></html>
'''

_REPLAY_001 = {
    "ok": True,
    "final_state": {
        "nodes": {
            "a": {"id": "a", "type": "INPUT", "input_values": [5], "output_values": [5], "status": "COMPLETED"},
            "b": {"id": "b", "type": "ADD_10", "input_values": [5], "output_values": [15], "status": "COMPLETED"},
        },
        "edges": [{"source_id": "a", "source_port": 0, "target_id": "b", "target_port": 0}],
        "execution_order": ["a", "b"],
        "global_tick": 1,
    },
    "events": [
        {"event": "node_created", "node_id": "a"},
        {"event": "node_created", "node_id": "b"},
        {"event": "edge_created", "edge": {"source_id": "a", "target_id": "b"}},
    ],
    "summary": "Completed",
    "errors": [],
}

_SCENARIO_001 = {
    "id": "scenario_001",
    "actions": [
        {"type": "add_node", "payload": {"id": "a", "type": "INPUT"}},
        {"type": "add_node", "payload": {"id": "b", "type": "ADD_10"}},
        {"type": "add_edge", "payload": {"source_id": "a", "source_port": 0,
                                         "target_id": "b", "target_port": 0}},
        {"type": "execute_graph", "payload": {"initial_inputs": {"a": [5]}}},
    ],
}

_ALL_GATES = {g: True for g in ("core_contract", "runner", "scenario_replay",
                                "golden_output", "state_invariant", "determinism", "anti_hardcode")}


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_green_run(root: Path, viewer_html: str, *, gates=None,
                     green=True, summary_source="state_derived") -> Path:
    """review 대상 green run(final_artifact + workspace + green/gate 산출물)을 만든다."""
    run = root / "run_2c0"
    fa = run / "final_artifact"
    ws = run / "workspace"
    gates = gates or dict(_ALL_GATES)

    # src (runner/engine/summary)
    for base in (fa, ws):
        (base / "src" / "core").mkdir(parents=True, exist_ok=True)
        (base / "src" / "runner.py").write_text(_RUNNER, encoding="utf-8")
        (base / "src" / "core" / "engine.py").write_text(_ENGINE, encoding="utf-8")
        (base / "src" / "core" / "summary.py").write_text(_SUMMARY, encoding="utf-8")
        for rel in ("core_contract.json", "state_contract.json", "action_contract.json"):
            _dump(base / rel, {"name": rel})
    _dump(fa / "runner_contract.json", {
        "runner_command": "python src/runner.py --scenario fixtures/scenario_001.json",
        "required_output_fields": ["ok", "final_state", "events", "summary", "errors"],
    })

    # product viewer
    (fa / "product" / "viewer").mkdir(parents=True, exist_ok=True)
    (fa / "product" / "viewer" / "index.html").write_text(viewer_html, encoding="utf-8")

    # replay + fixtures + golden (>=3 시나리오)
    _dump(fa / "replay" / "index.json", {"replays": [
        {"id": "scenario_001", "file": "replay_scenario_001.json", "ok": True},
        {"id": "scenario_002", "file": "replay_scenario_002.json", "ok": True},
        {"id": "scenario_003", "file": "replay_scenario_003.json", "ok": True},
    ]})
    _dump(fa / "replay" / "replay_scenario_001.json", _REPLAY_001)
    for n in ("002", "003"):
        _dump(fa / "replay" / f"replay_scenario_{n}.json", _REPLAY_001)
    for n in ("001", "002", "003"):
        _dump(fa / "fixtures" / f"scenario_{n}.json", _SCENARIO_001)
        _dump(fa / "golden" / f"expected_{n}.json",
              {"scenario_id": f"scenario_{n}", "comparison_mode": "exact", "expected_summary": "Completed"})

    # green/gate 산출물
    _dump(run / "green_base.json", {
        "base_type": "green_base" if green else "continuation_base",
        "verdict": "REVIEW_READY", "source": "anti_hardcode_patch",
        "next_goal": "사용자 검수 후 제품화 판단"})
    _dump(run / "gate_rerun_after_anti_hardcode_patch.json", {
        "gates": gates, "summary_source": summary_source, "summary_hardcode_risk": "low"})
    _dump(run / "phase2b1b_dashboard_summary.json", {
        "challenge_id": 99, "base_run_id": 1, "verdict": "REVIEW_READY",
        "promoted_to_green_base": green, "gates": gates,
        "summary_source": summary_source, "summary_hardcode_risk": "low",
        "gates_passed": sum(1 for v in gates.values() if v), "gates_total": len(gates)})
    return run


def _review(run: Path) -> tuple[dict, Path]:
    out = run_review_package(run_dir=run)
    return out, run / "review" / "phase2c0"


# ---------------------------------------------------------------- Group A: 산출물/스모크

def test_all_required_outputs_generated(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_CLEAN)
    out, rd = _review(run)
    assert out["ok"] and out["status"] == "REVIEWED"
    for rel in REQUIRED_OUTPUTS:
        assert (rd / rel).is_file(), rel
    # run_dir/review/phase2c0/ 아래에 생성 (§3.3)
    assert rd == run / "review" / "phase2c0"


def test_smoke_runs_in_temp_copy_protected_hash_unchanged(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_CLEAN)
    before = compute_protected_hashes(run)
    _review(run)
    after = compute_protected_hashes(run)
    assert before == after  # 원본 artifact 미변경 (§4.1)
    check = json.loads((run / "review" / "phase2c0" / "review_no_code_hash_check.json").read_text("utf-8"))
    assert check["status"] == "PASS"


def test_runner_smoke_records_exit_cwd_evidence(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_CLEAN)
    smoke = smoke_review(run, run / "review" / "phase2c0")
    assert smoke["runner_executable"] is True
    assert smoke["runner_exit_code"] == 0
    assert smoke["runner_cwd"] == "final_artifact"
    assert smoke["runner_evidence_path"]
    assert (run / smoke["runner_evidence_path"]).is_file()
    assert smoke["replay_output_exists"] is True
    assert smoke["product_viewer_exists"] is True


def test_viewer_reads_replay_needs_two_evidence(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_CLEAN)
    smoke = smoke_review(run, run / "review" / "phase2c0")
    assert smoke["product_viewer_reads_replay"] is True
    assert len(smoke["product_viewer_reads_replay_evidence"]) >= 2


def test_fetch_only_viewer_not_reads_replay(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_FETCH_ONLY)
    smoke = smoke_review(run, run / "review" / "phase2c0")
    # 단순 fetch 문자열 하나로는 true 불가 (§6.2)
    assert smoke["product_viewer_reads_replay"] is False


def test_consistency_two_fields_true(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_CLEAN)
    smoke = smoke_review(run, run / "review" / "phase2c0")
    assert smoke["runner_viewer_consistent"] is True
    assert len(smoke["runner_viewer_consistency_fields"]) >= 2


def test_consistency_unknown_when_no_viewer(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_CLEAN)
    shutil.rmtree(run / "final_artifact" / "product")
    smoke = smoke_review(run, run / "review" / "phase2c0")
    assert smoke["runner_viewer_consistent"] == "unknown"


# ---------------------------------------------------------------- Group B: 추천 판정

def test_clean_interactive_is_product_candidate(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_CLEAN)
    out, _ = _review(run)
    assert out["recommended_fitness"] == "PRODUCT_CANDIDATE", out["fitness"]["scores"]
    assert out["fitness"]["candidate_conditions"]["average>=4.0"] is True


def test_mismatch_viewer_is_needs_product_polish(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_MISMATCH)
    out, _ = _review(run)
    assert out["recommended_fitness"] == "NEEDS_PRODUCT_POLISH"
    assert out["fitness"]["scores"]["Product layer usefulness"] == 2
    assert out["smoke"]["mismatches"]


def test_readonly_viewer_defaults_to_polish(tmp_path):
    """필드가 정확해도 조작 가능한 experience가 없으면 기본 NEEDS_PRODUCT_POLISH (§12.3)."""
    run = _build_green_run(tmp_path, _VIEWER_READONLY)
    out, _ = _review(run)
    assert out["recommended_fitness"] == "NEEDS_PRODUCT_POLISH"
    assert any("조작 가능한 product experience" in r for r in out["critical_red_flags"])


def test_green_base_false_not_candidate(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_CLEAN, green=False)
    out, _ = _review(run)
    assert out["recommended_fitness"] != "PRODUCT_CANDIDATE"


def test_gate_fail_not_candidate(tmp_path):
    gates = dict(_ALL_GATES)
    gates["golden_output"] = False
    run = _build_green_run(tmp_path, _VIEWER_CLEAN, gates=gates)
    out, _ = _review(run)
    assert out["recommended_fitness"] != "PRODUCT_CANDIDATE"


def test_every_high_score_has_evidence(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_CLEAN)
    out, _ = _review(run)
    for c in out["fitness"]["criteria"]:
        if c["score"] >= 4:
            assert c["evidence"], c["criterion"]


def test_seven_criteria_present(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_CLEAN)
    out, _ = _review(run)
    names = {c["criterion"] for c in out["fitness"]["criteria"]}
    assert names == {"Core usefulness", "Interaction clarity", "Product layer usefulness",
                     "Demo understandability", "Extension potential", "Evidence quality",
                     "Anti-hardcode confidence"}


def test_demo_manifest_verified_and_no_fabricated_url(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_CLEAN)
    _, rd = _review(run)
    demo = json.loads((rd / "demo_manifest.json").read_text("utf-8"))
    assert demo["dashboard_url"] == "unknown"  # 추정 금지 (§10)
    rr = demo["commands"]["run_runner"]
    assert rr["verified"] is True
    assert rr["exit_code"] == 0 and rr["cwd"] and rr["evidence_path"]
    assert demo["commands"]["open_product"]["verified"] is False


def test_read_gate_context(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_CLEAN)
    gate = read_gate_context(run)
    assert gate["green_base"] is True
    assert gate["gate_fail"] is False
    assert gate["anti_hardcode"] is True
    assert gate["summary_source"] == "state_derived"


# ---------------------------------------------------------------- Group C: validate 규칙 (§17)

def _write_min_review(run_dir: Path, *, recommended="NEEDS_PRODUCT_POLISH", scores=None,
                      red_flags=None, hash_status="PASS", smoke_bools=True, next_goal=None,
                      criteria=None):
    rd = run_dir / "review" / "phase2c0"
    scores = scores or {"Core usefulness": 4, "Interaction clarity": 3,
                        "Product layer usefulness": 2, "Demo understandability": 2,
                        "Extension potential": 3, "Evidence quality": 4, "Anti-hardcode confidence": 4}
    fitness = {
        "recommended_fitness": recommended, "review_status": "사용자 최종 결정 대기",
        "average_score": round(sum(scores.values()) / len(scores), 2),
        "scores": scores, "criteria": criteria or [{"criterion": k, "score": v, "evidence": ["x"]}
                                                    for k, v in scores.items()],
        "critical_red_flags": red_flags or [], "green_base": True, "gate_fail": False,
        "runner_executable": smoke_bools, "product_viewer_reads_replay": smoke_bools,
        "runner_viewer_consistent": smoke_bools,
    }
    if next_goal:
        fitness["next_goal"] = next_goal
    smoke = {"runner_executable": smoke_bools, "product_viewer_reads_replay": smoke_bools,
             "runner_viewer_consistent": smoke_bools}
    for rel in REQUIRED_OUTPUTS:
        if rel.endswith(".md"):
            (rd / rel).parent.mkdir(parents=True, exist_ok=True)
            (rd / rel).write_text("# stub\n", encoding="utf-8")
    _dump(rd / "product_fitness_report.json", fitness)
    _dump(rd / "artifact_smoke_review.json", smoke)
    _dump(rd / "review_no_code_hash_check.json", {"status": hash_status})
    _dump(rd / "review_no_code_hash_before.json", {})
    _dump(rd / "review_no_code_hash_after.json", {})
    _dump(rd / "demo_manifest.json", {"dashboard_url": "unknown"})
    _dump(rd / "review_package.json", {"recommended_fitness": recommended})
    _dump(rd / "phase2c0_dashboard_summary.json", {"recommended_fitness": recommended})
    return rd


def test_detect_marker(tmp_path):
    run = tmp_path / "r"
    run.mkdir()
    assert detect_phase2c0_run(run) is False
    _write_min_review(run)
    assert detect_phase2c0_run(run) is True


def test_validate_clean_polish_passes(tmp_path):
    run = tmp_path / "r"
    _write_min_review(run)
    assert _check_phase2c0(run) == []


def test_validate_no_marker_no_check(tmp_path):
    run = tmp_path / "r"
    run.mkdir()
    assert _check_phase2c0(run) == []


def test_validate_candidate_with_gate_fail_fails(tmp_path):
    run = tmp_path / "r"
    _write_min_review(run, recommended="PRODUCT_CANDIDATE",
                      scores={k: 4 for k in ("Core usefulness", "Interaction clarity",
                              "Product layer usefulness", "Demo understandability",
                              "Extension potential", "Evidence quality", "Anti-hardcode confidence")})
    (run / "gate_rerun_after_anti_hardcode_patch.json").write_text(
        json.dumps({"gates": {"golden_output": False, "runner": True}}), encoding="utf-8")
    problems = _check_phase2c0(run)
    assert any("gate fail" in p for p in problems)


def test_validate_candidate_with_red_flag_fails(tmp_path):
    run = tmp_path / "r"
    _write_min_review(run, recommended="PRODUCT_CANDIDATE",
                      scores={k: 4 for k in ("Core usefulness", "Interaction clarity",
                              "Product layer usefulness", "Demo understandability",
                              "Extension potential", "Evidence quality", "Anti-hardcode confidence")},
                      red_flags=["조작 가능한 product experience 없음"])
    problems = _check_phase2c0(run)
    assert any("critical red flag" in p for p in problems)


def test_validate_candidate_low_critical_fails(tmp_path):
    run = tmp_path / "r"
    _write_min_review(run, recommended="PRODUCT_CANDIDATE")  # 기본 scores는 PL/Demo=2
    problems = _check_phase2c0(run)
    assert any("핵심 항목 4점 미만" in p for p in problems)


def test_validate_candidate_smoke_bool_false_fails(tmp_path):
    run = tmp_path / "r"
    _write_min_review(run, recommended="PRODUCT_CANDIDATE",
                      scores={k: 4 for k in ("Core usefulness", "Interaction clarity",
                              "Product layer usefulness", "Demo understandability",
                              "Extension potential", "Evidence quality", "Anti-hardcode confidence")},
                      smoke_bools=False)
    problems = _check_phase2c0(run)
    assert any("runner_executable != true" in p or "product_viewer_reads_replay != true" in p
               or "runner_viewer_consistent != true" in p for p in problems)


def test_validate_archive_allowed(tmp_path):
    run = tmp_path / "r"
    _write_min_review(run, recommended="ARCHIVE")
    assert _check_phase2c0(run) == []  # REVIEW_READY + ARCHIVE 모순 아님 (§17.2)


def test_validate_spec_repair_needs_next_goal(tmp_path):
    run = tmp_path / "r"
    _write_min_review(run, recommended="NEEDS_SPEC_REPAIR")
    assert any("next_goal" in p for p in _check_phase2c0(run))
    run2 = tmp_path / "r2"
    _write_min_review(run2, recommended="NEEDS_SPEC_REPAIR", next_goal="spec 보정")
    assert _check_phase2c0(run2) == []


def test_validate_no_code_change_fail(tmp_path):
    run = tmp_path / "r"
    _write_min_review(run, hash_status="FAIL")
    assert any("보호 대상 artifact 변경" in p for p in _check_phase2c0(run))


def test_validate_missing_required_output_fails(tmp_path):
    run = tmp_path / "r"
    rd = _write_min_review(run)
    (rd / "sixty_second_review_script.md").unlink()
    assert any("산출물 없음" in p for p in _check_phase2c0(run))


def test_validate_evidence_less_high_score_blocked(tmp_path):
    run = tmp_path / "r"
    crit = [{"criterion": "Core usefulness", "score": 5, "evidence": []}]
    _write_min_review(run, criteria=crit)
    assert any("evidence 없는" in p for p in _check_phase2c0(run))


def test_validate_unknown_grade_fails(tmp_path):
    run = tmp_path / "r"
    _write_min_review(run, recommended="WHATEVER")
    assert any("알 수 없는 recommended_fitness" in p for p in _check_phase2c0(run))


# ---------------------------------------------------------------- Group D: CLI

def test_cli_requires_target(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["factory-review"]) == 1


def test_cli_runs_on_synthetic(tmp_path, monkeypatch):
    run = _build_green_run(tmp_path, _VIEWER_CLEAN)
    monkeypatch.chdir(tmp_path)
    rc = main(["factory-review", "--run-dir", str(run)])
    assert rc == 0
    assert (run / "review" / "phase2c0" / "review_package.md").is_file()


# ---------------------------------------------------------------- Group E: 실제 #47 E2E

@pytest.mark.skipif(not FIXTURE_47.is_dir(), reason="#47 runtime 산출물 없음")
def test_e2e_47_review_no_contamination(tmp_path):
    run = tmp_path / FIXTURE_47.name
    shutil.copytree(FIXTURE_47, run)
    # 기존 review 산출물이 있으면 제거하고 다시 생성
    if (run / "review").is_dir():
        shutil.rmtree(run / "review")
    # on-disk #47이 Phase 2C-1로 이미 polish됐을 수 있으므로, mismatch 감지 경로를
    # 결정적으로 테스트하기 위해 알려진 결함 viewer로 되돌린다
    for base in ("final_artifact", "workspace"):
        v = run / base / "product" / "viewer" / "index.html"
        if v.is_file():
            v.write_text(_VIEWER_MISMATCH, encoding="utf-8")
    before = compute_protected_hashes(run)
    out = run_review_package(run_dir=run)
    after = compute_protected_hashes(run)
    assert out["ok"] and out["status"] == "REVIEWED"
    assert before == after  # 원본 artifact 미오염
    assert out["no_code_change_status"] == "PASS"
    # #47은 viewer 필드 스키마 불일치가 있어 제품화 후보가 아니다
    assert out["recommended_fitness"] == "NEEDS_PRODUCT_POLISH"
    assert out["smoke"]["runner_executable"] is True
    assert out["smoke"]["product_viewer_reads_replay"] is True
    assert out["smoke"]["mismatches"]
    ok, problems = validate_product_run_dir(run, [])
    assert ok, problems
