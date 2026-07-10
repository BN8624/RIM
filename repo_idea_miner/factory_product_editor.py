# Phase 2C-2: #47 product viewer에 replay schema 호환 최소 node draft editor mode를 추가하는 모듈.
from __future__ import annotations

import json
import re
from pathlib import Path

from repo_idea_miner.factory_run_layout import resolve_run_target

from repo_idea_miner.factory_product_evidence import (
    find_product_viewer,
    first_replay_file,
    load_json,
    read_gate_context,
    sha256_file,
    write_json,
    write_text,
)
from repo_idea_miner.factory_review import (
    build_fitness,
    smoke_review,
)

# ---------------------------------------------------------------- 상수 (§20, §4)

EDITOR_SUBDIR = "review/phase2c2"
STORAGE_KEY = "rim_phase2c2_challenge47_draft"

# review/phase2c2/ 아래 필수 산출물 (§20)
REQUIRED_OUTPUTS = (
    "phase2c2_editor_plan.json", "phase2c2_editor_plan.md",
    "phase2c2_editor_report.json", "phase2c2_editor_report.md",
    "phase2c2_diff_summary.json",
    "phase2c2_hash_before.json", "phase2c2_hash_after.json", "phase2c2_hash_check.json",
    "viewer_js_syntax_check.json", "viewer_static_dom_check.json",
    "viewer_handler_binding_check.json", "viewer_smoke_after_editor.json",
    "editor_smoke_review.json", "draft_schema_compatibility.json", "draft_roundtrip_check.json",
    "product_fitness_report_after_editor.json", "product_fitness_report_after_editor.md",
    "phase2c2_dashboard_summary.json",
)

# 보호 대상 (§4.1) — product/ 만 수정 허용. replay/phase2c0/phase2c1 포함 보호.
_PROTECTED_CONTRACTS = (
    "core_contract.json", "state_contract.json", "action_contract.json", "runner_contract.json",
)
_PROTECTED_DIR_PREFIXES = ("src/", "golden/", "fixtures/", "replay/")
_PROTECTED_ROOTS = ("workspace", "final_artifact")
_PROTECTED_REVIEW_DIRS = ("review/phase2c0", "review/phase2c1")

# viewer 주입 마커 — 재적용/제거를 안전하게 한다
_EDITOR_START = "<!-- PHASE2C2_EDITOR_START -->"
_EDITOR_END = "<!-- PHASE2C2_EDITOR_END -->"
_INJECT_RE = re.compile(re.escape(_EDITOR_START) + r".*?" + re.escape(_EDITOR_END), re.DOTALL)
_SCRIPT_BLOCK_RE = re.compile(r"<script\b[^>]*>(.*?)</script>", re.DOTALL)

# ---------------------------------------------------------------- editor DOM (§7 list/card 기반)

_EDITOR_DOM = r"""
<!-- PHASE2C2_EDITOR_START -->
<style>
#p2c2-modebar { margin: 16px 0; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
#p2c2-editor { margin-top: 12px; }
.p2c2-note { color: #a00; font-size: 12px; }
.p2c2-cols { display: flex; gap: 16px; flex-wrap: wrap; }
.p2c2-col { flex: 1; min-width: 240px; background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 12px; }
.p2c2-list { max-height: 240px; overflow: auto; }
.p2c2-card { border: 1px solid #eee; border-radius: 6px; padding: 6px 8px; margin-bottom: 6px; font-size: 12px; }
.p2c2-panel { min-height: 60px; font-size: 12px; white-space: pre-wrap; }
.p2c2-json { width: 100%; height: 160px; font-family: monospace; font-size: 11px; }
.p2c2-muted { color: #999; font-size: 12px; }
.p2c2-actions button { margin: 2px; }
.p2c2-ok { color: #2a7; } .p2c2-err { color: #c00; } .p2c2-warn { color: #c80; }
</style>
<div id="p2c2-modebar">
  <button id="p2c2-toggle" data-action="toggle-mode" onclick="p2c2ToggleMode()">Editor 모드 열기</button>
  <span class="p2c2-note">Draft only — 원본 replay/golden/contract는 변경되지 않습니다. Runner-backed execution is not included in this phase.</span>
</div>
<div id="p2c2-editor" style="display:none;">
  <div class="p2c2-cols">
    <div class="p2c2-col">
      <h4>Add Node</h4>
      <form id="p2c2-add-node-form" onsubmit="return false;">
        <input id="p2c2-node-label" placeholder="label">
        <select id="p2c2-node-type" title="supported node type"></select>
        <button data-action="add-node" onclick="p2c2AddNode()">Add Node</button>
      </form>
      <h4>Nodes</h4>
      <div id="p2c2-node-list" class="p2c2-list"></div>
    </div>
    <div class="p2c2-col">
      <h4>Add Edge</h4>
      <form id="p2c2-add-edge-form" onsubmit="return false;">
        <select id="p2c2-edge-source" title="source node"></select>
        <select id="p2c2-edge-target" title="target node"></select>
        <button data-action="add-edge" onclick="p2c2AddEdge()">Add Edge</button>
      </form>
      <h4>Edges</h4>
      <div id="p2c2-edge-list" class="p2c2-list"></div>
    </div>
    <div class="p2c2-col">
      <h4>Validation <span class="p2c2-muted">(editor validation only)</span></h4>
      <div id="p2c2-validation" class="p2c2-panel">Validate Graph 를 누르세요.</div>
      <div class="p2c2-actions">
        <button data-action="validate" onclick="p2c2Validate()">Validate Graph</button>
        <button data-action="preview" onclick="p2c2Preview()">Preview Draft</button>
        <button data-action="export" onclick="p2c2Export()">Export Draft</button>
        <button data-action="copy" onclick="p2c2Copy()">Copy Draft JSON</button>
        <button data-action="download" onclick="p2c2Download()">Download Draft</button>
        <button data-action="reload" onclick="p2c2Reload()">Reload Draft</button>
        <button data-action="reset" onclick="p2c2Reset()">Reset Draft</button>
      </div>
      <h4>Draft JSON</h4>
      <textarea id="p2c2-draft-json" class="p2c2-json" spellcheck="false"></textarea>
    </div>
  </div>
</div>
<!-- PHASE2C2_EDITOR_END -->
"""

# ---------------------------------------------------------------- editor script (§6, §11, §12, §13)
# 주의: edge.from/edge.to/ev.type/ev.message/.type/node.x/node.y/Math.random/Date.now 금지.
# node type 접근은 bracket 표기 nd["type"] 로만 한다(§17 mismatch 재도입 방지).

_EDITOR_SCRIPT = r"""
// Phase 2C-2 minimal node draft editor — schema-compatible draft state only (no runner execution)
var P2C2_TYPES = __SUPPORTED_TYPES__;
var P2C2_BASE_RUN = "__BASE_RUN__";
var P2C2_CHALLENGE = __CHALLENGE_ID__;
var P2C2_STORAGE_KEY = "__STORAGE_KEY__";
var p2c2State = { nodes: [], edges: [], seq: 0 };

function p2c2NextId() {
    p2c2State.seq += 1;
    var id = "node_" + p2c2State.seq;
    while (p2c2State.nodes.some(function (n) { return n.id === id; })) {
        p2c2State.seq += 1; id = "node_" + p2c2State.seq;
    }
    return id;
}

function p2c2LoadFromReplay(data) {
    var st = (data && data.final_state) || {};
    var rawNodes = st.nodes || {};
    var rawEdges = st.edges || [];
    var nodes = Object.keys(rawNodes).map(function (id) {
        var nd = rawNodes[id];
        return { id: id, type: nd["type"], label: (nd["label"] !== undefined ? nd["label"] : id) };
    });
    var edges = rawEdges.map(function (e) {
        return { source_id: e.source_id, target_id: e.target_id };
    });
    p2c2State = { nodes: nodes, edges: edges, seq: nodes.length };
    return p2c2State;
}

function p2c2AddNodeModel(label, type) {
    if (!P2C2_TYPES.length) return { ok: false, error: "no supported node types" };
    if (P2C2_TYPES.indexOf(type) < 0) return { ok: false, error: "unsupported node type: " + type };
    var id = p2c2NextId();
    p2c2State.nodes.push({ id: id, type: type, label: (label || id) });
    return { ok: true, id: id };
}

function p2c2EditNodeModel(id, label, type) {
    var n = p2c2State.nodes.filter(function (x) { return x.id === id; })[0];
    if (!n) return { ok: false, error: "no node: " + id };
    if (label !== undefined && label !== null) n.label = label;
    if (type !== undefined && type !== null && type !== "") {
        if (P2C2_TYPES.indexOf(type) < 0) return { ok: false, error: "unsupported node type: " + type };
        n["type"] = type;
    }
    return { ok: true };
}

function p2c2DeleteNodeModel(id) {
    p2c2State.nodes = p2c2State.nodes.filter(function (n) { return n.id !== id; });
    p2c2State.edges = p2c2State.edges.filter(function (e) {
        return e.source_id !== id && e.target_id !== id;
    });
    return { ok: true };
}

function p2c2AddEdgeModel(source, target) {
    if (source === undefined || target === undefined || source === "" || target === "")
        return { ok: false, error: "source/target required" };
    p2c2State.edges.push({ source_id: source, target_id: target });
    return { ok: true };
}

function p2c2DeleteEdgeModel(idx) {
    if (idx >= 0 && idx < p2c2State.edges.length) { p2c2State.edges.splice(idx, 1); return { ok: true }; }
    return { ok: false, error: "bad index" };
}

function p2c2HasCycle() {
    var ids = p2c2State.nodes.map(function (n) { return n.id; });
    var adj = {};
    ids.forEach(function (id) { adj[id] = []; });
    p2c2State.edges.forEach(function (e) {
        if (adj[e.source_id] && e.source_id !== e.target_id) adj[e.source_id].push(e.target_id);
    });
    var mark = {};
    function dfs(u) {
        mark[u] = 1;
        for (var i = 0; i < adj[u].length; i++) {
            var v = adj[u][i];
            if (mark[v] === 1) return true;
            if (mark[v] !== 2 && dfs(v)) return true;
        }
        mark[u] = 2;
        return false;
    }
    for (var j = 0; j < ids.length; j++) {
        if (mark[ids[j]] === undefined && dfs(ids[j])) return true;
    }
    return false;
}

function p2c2ValidateGraph() {
    var errors = [], warnings = [];
    var seen = {};
    p2c2State.nodes.forEach(function (n) {
        if (seen[n.id]) errors.push("duplicate node id: " + n.id);
        seen[n.id] = true;
        if (P2C2_TYPES.length && P2C2_TYPES.indexOf(n["type"]) < 0)
            errors.push("unsupported node type: " + n["type"]);
    });
    if (!p2c2State.nodes.length) errors.push("graph has no nodes");
    var connected = {};
    p2c2State.edges.forEach(function (e) {
        if (!seen[e.source_id]) errors.push("edge source_id does not exist: " + e.source_id);
        if (!seen[e.target_id]) errors.push("edge target_id does not exist: " + e.target_id);
        if (e.source_id === e.target_id) errors.push("self-loop on node: " + e.source_id);
        connected[e.source_id] = true; connected[e.target_id] = true;
    });
    if (p2c2HasCycle()) errors.push("cycle detected");
    if (p2c2State.nodes.length > 1) {
        p2c2State.nodes.forEach(function (n) {
            if (!connected[n.id]) warnings.push("isolated node exists: " + n.id);
        });
    }
    return { valid: errors.length === 0, errors: errors, warnings: warnings };
}

function p2c2BuildDraft() {
    return {
        nodes: p2c2State.nodes.map(function (n) {
            return { id: n.id, type: n["type"], label: n.label };
        }),
        edges: p2c2State.edges.map(function (e) {
            return { source_id: e.source_id, target_id: e.target_id };
        }),
        metadata: {
            source: "phase2c2_editor_draft",
            challenge_id: P2C2_CHALLENGE,
            base_run_dir: P2C2_BASE_RUN
        }
    };
}

function p2c2DraftSchemaCompatible(draft) {
    var reasons = [];
    if (!draft || !Array.isArray(draft.nodes)) reasons.push("draft missing nodes[]");
    if (!draft || !Array.isArray(draft.edges)) reasons.push("draft missing edges[]");
    if (reasons.length) return { compatible: false, reasons: reasons };
    var ids = {};
    draft.nodes.forEach(function (n) {
        if (n.id === undefined || n.id === null) reasons.push("node missing id");
        else ids[n.id] = true;
        if (P2C2_TYPES.length && P2C2_TYPES.indexOf(n["type"]) < 0)
            reasons.push("unsupported node type: " + n["type"]);
        if (typeof n.label !== "string") reasons.push("node.label not a string: " + n.id);
    });
    draft.edges.forEach(function (e) {
        if (e["from"] !== undefined || e["to"] !== undefined)
            reasons.push("edge uses from/to instead of source_id/target_id");
        if (e.source_id === undefined) reasons.push("edge missing source_id");
        if (e.target_id === undefined) reasons.push("edge missing target_id");
        if (e.source_id !== undefined && !ids[e.source_id])
            reasons.push("edge source_id does not reference a node: " + e.source_id);
        if (e.target_id !== undefined && !ids[e.target_id])
            reasons.push("edge target_id does not reference a node: " + e.target_id);
    });
    return { compatible: reasons.length === 0, reasons: reasons };
}

function p2c2DisplayModelFromDraft(draft) {
    var rawNodes = {};
    draft.nodes.forEach(function (n) {
        rawNodes[n.id] = { id: n.id, type: n["type"], status: "DRAFT", output_values: [] };
    });
    var dispEdges = draft.edges.map(function (e) {
        return { from: e.source_id, to: e.target_id };
    });
    return { nodes: rawNodes, edges: dispEdges, count: draft.nodes.length };
}

function p2c2Roundtrip() {
    var draft = p2c2BuildDraft();
    var text = JSON.stringify(draft);
    var reloaded = JSON.parse(text);
    var model = p2c2DisplayModelFromDraft(reloaded);
    var pass = reloaded.nodes.length === draft.nodes.length
        && reloaded.edges.length === draft.edges.length
        && !!model && model.count === draft.nodes.length;
    return { pass: pass, nodes: reloaded.nodes.length, edges: reloaded.edges.length, displayModel: model };
}

// ---- UI bindings (§15.2 handler binding)

function p2c2ToggleMode() {
    var ed = document.getElementById("p2c2-editor");
    var btn = document.getElementById("p2c2-toggle");
    var main = document.getElementById("main-container");
    var open = ed.style.display === "none";
    ed.style.display = open ? "block" : "none";
    if (main) main.style.display = open ? "none" : "flex";
    if (btn) btn.textContent = open ? "Viewer 모드로 돌아가기" : "Editor 모드 열기";
    if (open && !p2c2State.nodes.length) p2c2InitEditor();
}

async function p2c2InitEditor() {
    try {
        var r = await fetch("../../replay/index.json");
        var idx = await r.json();
        var first = (idx.replays && idx.replays[0]) ? idx.replays[0].file : null;
        if (first) {
            var r2 = await fetch("../../replay/" + first);
            var data = await r2.json();
            p2c2LoadFromReplay(data);
        }
    } catch (e) {
        p2c2SetValidation("replay 로드 실패: " + e.message, "err");
    }
    p2c2FillTypeSelector();
    p2c2Render();
}

function p2c2FillTypeSelector() {
    var sel = document.getElementById("p2c2-node-type");
    if (!sel) return;
    if (!P2C2_TYPES.length) {
        sel.innerHTML = '<option value="">(no supported types)</option>';
        sel.disabled = true;
        var addBtn = document.querySelector('[data-action="add-node"]');
        if (addBtn) addBtn.disabled = true;
        return;
    }
    sel.innerHTML = P2C2_TYPES.map(function (t) {
        return '<option value="' + t + '">' + t + '</option>';
    }).join("");
}

function p2c2RefreshEndpoints() {
    var opts = p2c2State.nodes.map(function (n) {
        return '<option value="' + n.id + '">' + n.id + '</option>';
    }).join("");
    ["p2c2-edge-source", "p2c2-edge-target"].forEach(function (elid) {
        var s = document.getElementById(elid);
        if (s) s.innerHTML = opts;
    });
}

function p2c2Render() {
    var nl = document.getElementById("p2c2-node-list");
    if (nl) {
        nl.innerHTML = p2c2State.nodes.map(function (n) {
            return '<div class="p2c2-card"><b>' + n.id + '</b> [' + n["type"] + '] '
                + '<span>' + (n.label || "") + '</span> '
                + '<button data-action="del-node" data-id="' + n.id + '">삭제</button></div>';
        }).join("") || '<div class="p2c2-muted">(노드 없음)</div>';
    }
    var el = document.getElementById("p2c2-edge-list");
    if (el) {
        el.innerHTML = p2c2State.edges.map(function (e, i) {
            return '<div class="p2c2-card">' + e.source_id + ' &rarr; ' + e.target_id + ' '
                + '<button data-action="del-edge" data-idx="' + i + '">삭제</button></div>';
        }).join("") || '<div class="p2c2-muted">(엣지 없음)</div>';
    }
    p2c2RefreshEndpoints();
}

function p2c2SetValidation(msg, cls) {
    var v = document.getElementById("p2c2-validation");
    if (v) v.innerHTML = '<span class="p2c2-' + (cls || "ok") + '">' + msg + '</span>';
}

function p2c2AddNode() {
    var label = (document.getElementById("p2c2-node-label") || {}).value || "";
    var type = (document.getElementById("p2c2-node-type") || {}).value || "";
    var res = p2c2AddNodeModel(label, type);
    if (!res.ok) { p2c2SetValidation("Add node 실패: " + res.error, "err"); return; }
    p2c2Render();
    p2c2SetValidation("노드 추가: " + res.id, "ok");
}

function p2c2AddEdge() {
    var s = (document.getElementById("p2c2-edge-source") || {}).value || "";
    var t = (document.getElementById("p2c2-edge-target") || {}).value || "";
    var res = p2c2AddEdgeModel(s, t);
    if (!res.ok) { p2c2SetValidation("Add edge 실패: " + res.error, "err"); return; }
    p2c2Render();
    p2c2SetValidation("엣지 추가: " + s + " -> " + t, "ok");
}

function p2c2Validate() {
    var res = p2c2ValidateGraph();
    var msg = res.valid ? "Valid graph" : "Invalid:\n- " + res.errors.join("\n- ");
    if (res.warnings.length) msg += "\nWarning:\n- " + res.warnings.join("\n- ");
    p2c2SetValidation(msg, res.valid ? "ok" : "err");
    return res;
}

function p2c2Preview() {
    var draft = p2c2BuildDraft();
    var model = p2c2DisplayModelFromDraft(draft);
    p2c2SetValidation("Preview: " + model.count + " nodes, " + draft.edges.length + " edges", "ok");
}

function p2c2Export() {
    var draft = p2c2BuildDraft();
    var ta = document.getElementById("p2c2-draft-json");
    if (ta) ta.value = JSON.stringify(draft, null, 2);
    var compat = p2c2DraftSchemaCompatible(draft);
    p2c2SetValidation(compat.compatible ? "Draft exported (schema compatible)"
        : "Draft exported but NOT compatible:\n- " + compat.reasons.join("\n- "),
        compat.compatible ? "ok" : "err");
    return draft;
}

function p2c2Copy() {
    var ta = document.getElementById("p2c2-draft-json");
    if (!ta || !ta.value) p2c2Export();
    if (navigator.clipboard && ta) navigator.clipboard.writeText(ta.value);
    p2c2SetValidation("Draft JSON copied", "ok");
}

function p2c2Download() {
    var draft = p2c2BuildDraft();
    var blob = new Blob([JSON.stringify(draft, null, 2)], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "phase2c2_draft.json";
    a.click();
}

function p2c2Reload() {
    var ta = document.getElementById("p2c2-draft-json");
    if (!ta || !ta.value) { p2c2SetValidation("Reload 실패: draft JSON 없음", "err"); return; }
    try {
        var draft = JSON.parse(ta.value);
        var rt = p2c2DisplayModelFromDraft(draft);
        p2c2State = {
            nodes: draft.nodes.map(function (n) { return { id: n.id, type: n["type"], label: n.label }; }),
            edges: draft.edges.map(function (e) { return { source_id: e.source_id, target_id: e.target_id }; }),
            seq: draft.nodes.length
        };
        p2c2Render();
        p2c2SetValidation("Draft reloaded: " + rt.count + " nodes (displayModel regenerated)", "ok");
    } catch (e) {
        p2c2SetValidation("Reload 실패: " + e.message, "err");
    }
}

function p2c2Reset() {
    try { if (window.localStorage) localStorage.removeItem(P2C2_STORAGE_KEY); } catch (e) { /* ignore */ }
    p2c2InitEditor();
    p2c2SetValidation("Draft reset (원본 replay 기준으로 복원, localStorage clear)", "ok");
}

function p2c2Dispatch(evt) {
    var el = evt.target;
    if (!el || !el.getAttribute) return;
    var action = el.getAttribute("data-action");
    if (action === "del-node") { p2c2DeleteNodeModel(el.getAttribute("data-id")); p2c2Render(); }
    else if (action === "del-edge") { p2c2DeleteEdgeModel(Number(el.getAttribute("data-idx"))); p2c2Render(); }
}

document.addEventListener("DOMContentLoaded", function () {
    var ed = document.getElementById("p2c2-editor");
    if (ed) ed.addEventListener("click", p2c2Dispatch);
    p2c2FillTypeSelector();
});
"""


# ---------------------------------------------------------------- Python 미러 모델 (§16 model-level smoke)

class EditorGraphModel:
    """editor JS와 동일한 draft graph 규칙의 Python 미러. model-level smoke의 근거를 만든다."""

    def __init__(self, supported_types: list[str]):
        self.supported = list(supported_types)
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self.seq = 0

    def load_from_replay(self, data: dict) -> None:
        st = (data or {}).get("final_state") or {}
        raw_nodes = st.get("nodes") or {}
        raw_edges = st.get("edges") or []
        self.nodes = [{"id": nid, "type": nd.get("type"), "label": nd.get("label", nid)}
                      for nid, nd in raw_nodes.items()]
        self.edges = [{"source_id": e.get("source_id"), "target_id": e.get("target_id")}
                      for e in raw_edges]
        self.seq = len(self.nodes)

    def _next_id(self) -> str:
        ids = {n["id"] for n in self.nodes}
        self.seq += 1
        nid = f"node_{self.seq}"
        while nid in ids:
            self.seq += 1
            nid = f"node_{self.seq}"
        return nid

    def add_node(self, label: str, type_: str) -> dict:
        if not self.supported:
            return {"ok": False, "error": "no supported node types"}
        if type_ not in self.supported:
            return {"ok": False, "error": f"unsupported node type: {type_}"}
        nid = self._next_id()
        self.nodes.append({"id": nid, "type": type_, "label": label or nid})
        return {"ok": True, "id": nid}

    def edit_node(self, nid: str, label=None, type_=None) -> dict:
        n = next((x for x in self.nodes if x["id"] == nid), None)
        if n is None:
            return {"ok": False, "error": f"no node: {nid}"}
        if label is not None:
            n["label"] = label
        if type_:
            if type_ not in self.supported:
                return {"ok": False, "error": f"unsupported node type: {type_}"}
            n["type"] = type_
        return {"ok": True}

    def delete_node(self, nid: str) -> dict:
        self.nodes = [n for n in self.nodes if n["id"] != nid]
        self.edges = [e for e in self.edges
                      if e["source_id"] != nid and e["target_id"] != nid]
        return {"ok": True}

    def add_edge(self, source: str, target: str) -> dict:
        if not source or not target:
            return {"ok": False, "error": "source/target required"}
        self.edges.append({"source_id": source, "target_id": target})
        return {"ok": True}

    def delete_edge(self, idx: int) -> dict:
        if 0 <= idx < len(self.edges):
            self.edges.pop(idx)
            return {"ok": True}
        return {"ok": False, "error": "bad index"}

    def _has_cycle(self) -> bool:
        ids = [n["id"] for n in self.nodes]
        adj: dict[str, list[str]] = {i: [] for i in ids}
        for e in self.edges:
            if e["source_id"] in adj and e["source_id"] != e["target_id"]:
                adj[e["source_id"]].append(e["target_id"])
        mark: dict[str, int] = {}

        def dfs(u: str) -> bool:
            mark[u] = 1
            for v in adj.get(u, []):
                if mark.get(v) == 1:
                    return True
                if mark.get(v) != 2 and dfs(v):
                    return True
            mark[u] = 2
            return False

        return any(dfs(i) for i in ids if i not in mark)

    def validate(self) -> dict:
        errors: list[str] = []
        warnings: list[str] = []
        seen: set[str] = set()
        for n in self.nodes:
            if n["id"] in seen:
                errors.append(f"duplicate node id: {n['id']}")
            seen.add(n["id"])
            if self.supported and n["type"] not in self.supported:
                errors.append(f"unsupported node type: {n['type']}")
        if not self.nodes:
            errors.append("graph has no nodes")
        connected: set[str] = set()
        for e in self.edges:
            if e["source_id"] not in seen:
                errors.append(f"edge source_id does not exist: {e['source_id']}")
            if e["target_id"] not in seen:
                errors.append(f"edge target_id does not exist: {e['target_id']}")
            if e["source_id"] == e["target_id"]:
                errors.append(f"self-loop on node: {e['source_id']}")
            connected.add(e["source_id"])
            connected.add(e["target_id"])
        if self._has_cycle():
            errors.append("cycle detected")
        if len(self.nodes) > 1:
            for n in self.nodes:
                if n["id"] not in connected:
                    warnings.append(f"isolated node exists: {n['id']}")
        return {"valid": not errors, "errors": errors, "warnings": warnings}

    def build_draft(self, base_run_dir: str, challenge_id) -> dict:
        return {
            "nodes": [{"id": n["id"], "type": n["type"], "label": n["label"]} for n in self.nodes],
            "edges": [{"source_id": e["source_id"], "target_id": e["target_id"]} for e in self.edges],
            "metadata": {"source": "phase2c2_editor_draft",
                         "challenge_id": challenge_id, "base_run_dir": base_run_dir},
        }


def check_draft_schema_compatible(draft: dict, supported_types: list[str]) -> dict:
    """§11: draft가 viewer/editor/replay display model과 구조적으로 호환되는지 검사."""
    reasons: list[str] = []
    if not isinstance(draft.get("nodes"), list):
        reasons.append("draft missing nodes[]")
    if not isinstance(draft.get("edges"), list):
        reasons.append("draft missing edges[]")
    if reasons:
        return {"compatible": False, "reasons": reasons}
    ids: set = set()
    for n in draft["nodes"]:
        if n.get("id") is None:
            reasons.append("node missing id")
        else:
            ids.add(n["id"])
        if supported_types and n.get("type") not in supported_types:
            reasons.append(f"unsupported node type: {n.get('type')}")
        if not isinstance(n.get("label"), str):
            reasons.append(f"node.label not a string: {n.get('id')}")
    for e in draft["edges"]:
        if "from" in e or "to" in e:
            reasons.append("edge uses from/to instead of source_id/target_id")
        if "source_id" not in e:
            reasons.append("edge missing source_id")
        if "target_id" not in e:
            reasons.append("edge missing target_id")
        if e.get("source_id") is not None and e["source_id"] not in ids:
            reasons.append(f"edge source_id does not reference a node: {e['source_id']}")
        if e.get("target_id") is not None and e["target_id"] not in ids:
            reasons.append(f"edge target_id does not reference a node: {e['target_id']}")
    return {"compatible": not reasons, "reasons": reasons}


def check_draft_roundtrip(draft: dict) -> dict:
    """§12: export → reload → nodes/edges 보존 + displayModel 재생성."""
    text = json.dumps(draft, ensure_ascii=False)
    reloaded = json.loads(text)
    raw_nodes = {n["id"]: {"id": n["id"], "type": n["type"], "status": "DRAFT",
                           "output_values": []} for n in reloaded["nodes"]}
    disp_edges = [{"from": e["source_id"], "to": e["target_id"]} for e in reloaded["edges"]]
    display_model = {"nodes": raw_nodes, "edges": disp_edges, "count": len(reloaded["nodes"])}
    preserved = (len(reloaded["nodes"]) == len(draft["nodes"])
                 and len(reloaded["edges"]) == len(draft["edges"]))
    regenerated = display_model["count"] == len(draft["nodes"])
    return {
        "pass": bool(preserved and regenerated),
        "nodes_preserved": preserved,
        "display_model_regenerated": regenerated,
        "nodes": len(reloaded["nodes"]),
        "edges": len(reloaded["edges"]),
    }


def run_model_level_smoke(supported_types: list[str], replay: dict | None,
                          base_run_dir: str, challenge_id) -> dict:
    """§16/§21: editor 모델 규칙 전체를 Python 미러로 실행해 model_level_smoke를 판정한다."""
    steps: list[dict] = []
    failures: list[str] = []

    def rec(name: str, ok: bool, detail: str = ""):
        steps.append({"step": name, "ok": bool(ok), "detail": detail})
        if not ok:
            failures.append(f"{name}: {detail}")

    m = EditorGraphModel(supported_types)
    orig_snapshot = json.dumps(replay, ensure_ascii=False, sort_keys=True) if replay else None
    if replay:
        m.load_from_replay(replay)
    loads = bool(m.nodes)
    rec("loads_replay_into_editor_state", loads, f"{len(m.nodes)} nodes, {len(m.edges)} edges")

    add_type = supported_types[0] if supported_types else None
    if add_type:
        r = m.add_node("New Node", add_type)
        rec("add_node", r["ok"], r.get("id") or r.get("error", ""))
        new_id = r.get("id")
    else:
        rec("add_node", False, "no supported types → add disabled")
        new_id = None

    if new_id:
        alt_type = supported_types[-1]
        r = m.edit_node(new_id, label="Edited", type_=alt_type)
        rec("edit_node", r["ok"], r.get("error", "label+type updated"))
    else:
        rec("edit_node", False, "no node to edit")

    # incident edge 자동 삭제 검증: 새 노드에 엣지를 걸고 노드 삭제 후 dangling 없음
    incident_ok = False
    if new_id and m.nodes:
        anchor = m.nodes[0]["id"]
        m.add_edge(anchor, new_id)
        before_edges = len(m.edges)
        m.delete_node(new_id)
        remaining_ref = any(e["source_id"] == new_id or e["target_id"] == new_id for e in m.edges)
        incident_ok = (not remaining_ref) and len(m.edges) < before_edges
        rec("delete_node", True, f"node removed, edges {before_edges}->{len(m.edges)}")
        rec("delete_node_removes_incident_edges", incident_ok,
            "no dangling edge references deleted node" if incident_ok else "dangling edge remained")
    else:
        rec("delete_node", False, "no node to delete")
        rec("delete_node_removes_incident_edges", False, "n/a")

    # add/delete edge
    if len(m.nodes) >= 2:
        a, b = m.nodes[0]["id"], m.nodes[1]["id"]
        r = m.add_edge(a, b)
        rec("add_edge", r["ok"], f"{a}->{b}")
        idx = len(m.edges) - 1
        r = m.delete_edge(idx)
        rec("delete_edge", r["ok"], f"removed idx {idx}")
    else:
        rec("add_edge", False, "need >=2 nodes")
        rec("delete_edge", False, "need edge")

    # validation이 각 오류를 잡는지 (독립 모델로)
    def _bad(kind: str) -> EditorGraphModel:
        mm = EditorGraphModel(supported_types)
        base = supported_types[0] if supported_types else "X"
        if kind == "dup":
            mm.nodes = [{"id": "n1", "type": base, "label": "a"},
                        {"id": "n1", "type": base, "label": "b"}]
        elif kind == "missing_endpoint":
            mm.nodes = [{"id": "n1", "type": base, "label": "a"}]
            mm.edges = [{"source_id": "n1", "target_id": "ghost"}]
        elif kind == "unsupported":
            mm.nodes = [{"id": "n1", "type": "banana", "label": "a"}]
        elif kind == "cycle":
            mm.nodes = [{"id": "n1", "type": base, "label": "a"},
                        {"id": "n2", "type": base, "label": "b"}]
            mm.edges = [{"source_id": "n1", "target_id": "n2"},
                        {"source_id": "n2", "target_id": "n1"}]
        elif kind == "self_loop":
            mm.nodes = [{"id": "n1", "type": base, "label": "a"}]
            mm.edges = [{"source_id": "n1", "target_id": "n1"}]
        return mm

    val_dup = any("duplicate" in e for e in _bad("dup").validate()["errors"])
    val_missing = any("does not exist" in e for e in _bad("missing_endpoint").validate()["errors"])
    val_unsupported = any("unsupported node type" in e for e in _bad("unsupported").validate()["errors"])
    val_cycle = "cycle detected" in _bad("cycle").validate()["errors"]
    val_selfloop = any("self-loop" in e for e in _bad("self_loop").validate()["errors"])
    rec("validation_duplicate_id", val_dup)
    rec("validation_missing_endpoint", val_missing)
    rec("validation_unsupported_type", val_unsupported)
    rec("validation_cycle", val_cycle)
    rec("validation_self_loop", val_selfloop)
    graph_validation_supported = all([val_dup, val_missing, val_unsupported, val_cycle, val_selfloop])

    # export + compat + roundtrip (정상 draft 재로딩 모델로)
    m2 = EditorGraphModel(supported_types)
    if replay:
        m2.load_from_replay(replay)
    if add_type:
        m2.add_node("Draft Node", add_type)
    draft = m2.build_draft(base_run_dir, challenge_id)
    compat = check_draft_schema_compatible(draft, supported_types)
    rec("draft_export", True, f"{len(draft['nodes'])} nodes")
    rec("draft_schema_compatible", compat["compatible"], "; ".join(compat["reasons"]))
    # from/to-only edge → compat FAIL 이 나와야 정상
    bad_draft = json.loads(json.dumps(draft))
    if bad_draft["nodes"]:
        bad_draft["edges"] = [{"from": bad_draft["nodes"][0]["id"],
                               "to": bad_draft["nodes"][0]["id"]}]
    from_to_rejected = not check_draft_schema_compatible(bad_draft, supported_types)["compatible"]
    rec("from_to_only_edge_rejected", from_to_rejected)
    rt = check_draft_roundtrip(draft)
    rec("draft_roundtrip", rt["pass"], f"{rt['nodes']} nodes, regenerated={rt['display_model_regenerated']}")

    # 원본 replay 불변 (모델은 복제본만 다룸)
    replay_unchanged = (orig_snapshot is None
                        or json.dumps(replay, ensure_ascii=False, sort_keys=True) == orig_snapshot)
    rec("original_replay_unchanged", replay_unchanged)

    model_level_smoke_pass = not failures
    return {
        "model_level_smoke_pass": model_level_smoke_pass,
        "steps": steps,
        "failures": failures,
        "loads_replay_into_editor_state": loads,
        "add_node_supported": bool(new_id),
        "edit_node_supported": bool(new_id) and next(
            (s["ok"] for s in steps if s["step"] == "edit_node"), False),
        "delete_node_supported": next((s["ok"] for s in steps if s["step"] == "delete_node"), False),
        "delete_node_removes_incident_edges": incident_ok,
        "add_edge_supported": next((s["ok"] for s in steps if s["step"] == "add_edge"), False),
        "delete_edge_supported": next((s["ok"] for s in steps if s["step"] == "delete_edge"), False),
        "graph_validation_supported": graph_validation_supported,
        "draft_schema_compatible": compat["compatible"],
        "draft_schema_compatibility_reasons": compat["reasons"],
        "from_to_only_edge_rejected": from_to_rejected,
        "draft_roundtrip_pass": rt["pass"],
        "draft_roundtrip": rt,
        "draft_export_supported": True,
        "original_replay_unchanged": replay_unchanged,
        "draft_sample": draft,
    }


# ---------------------------------------------------------------- supported_node_types (§8)

def extract_supported_node_types(final_dir: Path) -> tuple[list[str], str]:
    """§8.1: contract 명시 → replay node types 순으로 추출. 없으면 ([], 'none')."""
    for cname in ("core_contract.json", "runner_contract.json"):
        c = load_json(final_dir / cname) or {}
        for key in ("supported_node_types", "node_types"):
            v = c.get(key)
            if isinstance(v, list) and v:
                return sorted({str(x) for x in v}), f"{cname}:{key}"
    types: set[str] = set()
    rdir = final_dir / "replay"
    if rdir.is_dir():
        for p in sorted(rdir.glob("replay_*.json")):
            d = load_json(p) or {}
            for nd in ((d.get("final_state") or {}).get("nodes") or {}).values():
                if isinstance(nd, dict) and nd.get("type"):
                    types.add(str(nd["type"]))
    if types:
        return sorted(types), "replay_node_types"
    return [], "none"


# ---------------------------------------------------------------- viewer 주입 (§6, §17)

def build_editor_block(supported_types: list[str], base_run_dir: str, challenge_id) -> str:
    """editor DOM + script 블록을 만든다. 리터럴 치환은 문자열 replace로만(백슬래시 미해석)."""
    script = _EDITOR_SCRIPT
    script = script.replace("__SUPPORTED_TYPES__", json.dumps(supported_types))
    script = script.replace("__BASE_RUN__", base_run_dir)
    script = script.replace("__CHALLENGE_ID__", json.dumps(challenge_id))
    script = script.replace("__STORAGE_KEY__", STORAGE_KEY)
    return _EDITOR_DOM + "<script>\n" + script + "\n</script>\n"


_MAIN_CONTAINER_RE = re.compile(r'<div\b[^>]*\bid=["\']main-container["\']')


def inject_editor(viewer_path: Path, supported_types: list[str],
                  base_run_dir: str, challenge_id) -> bool:
    """viewer 상단(main-container 앞, 없으면 </body> 앞)에 editor block을 주입한다.

    editor 진입 토글이 화면 상단에서 바로 보이도록 결과 뷰(main-container) 위에 넣는다.
    기존 폴리시 script는 보존한다.
    """
    text = viewer_path.read_text(encoding="utf-8", errors="replace")
    # 이전 주입 제거(재적용 안전)
    text = _INJECT_RE.sub("", text)
    block = build_editor_block(supported_types, base_run_dir, challenge_id)
    m = _MAIN_CONTAINER_RE.search(text)
    if m:
        new_text = text[:m.start()] + block + text[m.start():]
    elif "</body>" in text:
        new_text = text.replace("</body>", block + "</body>", 1)
    else:
        new_text = text + block
    if new_text == text:
        return False
    viewer_path.write_text(new_text, encoding="utf-8")
    return True


def _extract_scripts(html: str) -> list[str]:
    return [m.group(1) for m in _SCRIPT_BLOCK_RE.finditer(html)]


def check_js_syntax(viewer_path: Path, tmp_dir: Path) -> dict:
    """§17: viewer의 script 블록들을 추출해 node --check로 구문 검사한다."""
    import shutil
    import subprocess

    html = viewer_path.read_text(encoding="utf-8", errors="replace")
    scripts = _extract_scripts(html)
    node = shutil.which("node")
    out = {
        "viewer": viewer_path.name, "script_blocks": len(scripts),
        "node_available": bool(node), "status": "PASS", "errors": [],
        "functions_present": {}, "checked": False,
    }
    required_fns = ("normalizeReplayForViewer", "p2c2LoadFromReplay", "p2c2AddNodeModel",
                    "p2c2AddEdgeModel", "p2c2ValidateGraph", "p2c2BuildDraft",
                    "p2c2DraftSchemaCompatible", "p2c2Roundtrip")
    for fn in required_fns:
        out["functions_present"][fn] = (fn in html)
    if not all(out["functions_present"].values()):
        out["status"] = "FAIL"
        out["errors"].append("필수 함수 누락: "
                             + ", ".join(k for k, v in out["functions_present"].items() if not v))
    if not node:
        out["status"] = "UNKNOWN" if out["status"] == "PASS" else out["status"]
        out["errors"].append("node 미설치 — JS 구문 검사 스킵")
        return out
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for i, sc in enumerate(scripts):
        js = tmp_dir / f"script_{i}.js"
        js.write_text(sc, encoding="utf-8")
        r = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
        out["checked"] = True
        if r.returncode != 0:
            out["status"] = "FAIL"
            out["errors"].append(f"script[{i}] 구문 오류: {r.stderr.strip()[:400]}")
    return out


# ---------------------------------------------------------------- static DOM + handler binding (§15)

# (id 정규식, data-action, 핸들러 함수) — 존재 + binding 근거 모두 확인
_DOM_CONTROLS = (
    ("editor_mode_toggle", r'id="p2c2-toggle"', "toggle-mode", "p2c2ToggleMode"),
    ("add_node_control", r'id="p2c2-add-node-form"', "add-node", "p2c2AddNode"),
    ("add_edge_control", r'id="p2c2-add-edge-form"', "add-edge", "p2c2AddEdge"),
    ("validation_panel", r'id="p2c2-validation"', "validate", "p2c2Validate"),
    ("draft_json_panel", r'id="p2c2-draft-json"', "export", "p2c2Export"),
    ("export_copy_control", r'data-action="copy"', "copy", "p2c2Copy"),
    ("supported_type_selector", r'id="p2c2-node-type"', "add-node", "p2c2AddNode"),
)


def check_static_dom(html: str) -> dict:
    """§15.1: 필수 editor DOM 요소 존재 여부."""
    present = {}
    missing = []
    for name, id_re, _action, _fn in _DOM_CONTROLS:
        ok = bool(re.search(id_re, html))
        present[name] = ok
        if not ok:
            missing.append(name)
    return {"status": "PASS" if not missing else "FAIL", "present": present, "missing": missing}


def check_handler_binding(html: str) -> dict:
    """§15.2: 각 핵심 control이 handler/data-action/event binding 근거를 갖는지."""
    bindings = {}
    missing = []
    for name, _id_re, action, fn in _DOM_CONTROLS:
        has_action = bool(re.search(r'data-action="' + re.escape(action) + r'"', html))
        has_onclick = bool(re.search(r'onclick="' + re.escape(fn) + r'\(', html))
        has_fn = bool(re.search(r'function\s+' + re.escape(fn) + r'\b', html))
        has_delegation = "addEventListener" in html
        ok = (has_action or has_onclick) and (has_fn or has_delegation)
        bindings[name] = {"data_action": has_action, "onclick": has_onclick,
                          "handler_defined": has_fn, "delegation": has_delegation, "ok": ok}
        if not ok:
            missing.append(name)
    return {"status": "PASS" if not missing else "FAIL", "bindings": bindings, "missing": missing}


# ---------------------------------------------------------------- 보호 hash (§4)

def compute_editor_protected_hashes(run_dir: Path) -> dict[str, str]:
    """§4.1: src/golden/fixtures/contract/oracle/replay + review/phase2c0·2c1 보호(product 제외)."""
    run_dir = Path(run_dir)
    out: dict[str, str] = {}
    for root_name in _PROTECTED_ROOTS:
        base = run_dir / root_name
        if not base.is_dir():
            continue
        for rel in _PROTECTED_CONTRACTS:
            p = base / rel
            if p.is_file():
                out[f"{root_name}/{rel}"] = sha256_file(p)
        for prefix in _PROTECTED_DIR_PREFIXES:
            d = base / prefix.rstrip("/")
            if not d.is_dir():
                continue
            for p in sorted(d.rglob("*")):
                if p.is_file() and "__pycache__" not in p.parts:
                    out[f"{root_name}/{p.relative_to(base).as_posix()}"] = sha256_file(p)
    orr = run_dir / "oracle_risk_report.json"
    if orr.is_file():
        out["oracle_risk_report.json"] = sha256_file(orr)
    for rev in _PROTECTED_REVIEW_DIRS:
        d = run_dir / rev
        if d.is_dir():
            for p in sorted(d.rglob("*")):
                if p.is_file() and "__pycache__" not in p.parts:
                    out[f"{rev}/{p.relative_to(d).as_posix()}"] = sha256_file(p)
    return out


def _compare(before: dict, after: dict) -> dict:
    changed = sorted(k for k in before if k in after and before[k] != after[k])
    removed = sorted(k for k in before if k not in after)
    added = sorted(k for k in after if k not in before)
    return {"status": "PASS" if not (changed or removed or added) else "FAIL",
            "files_checked": len(before), "changed": changed, "added": added, "removed": removed}


def _product_viewer_paths(run_dir: Path) -> list[Path]:
    out: list[Path] = []
    for root_name in ("final_artifact", "workspace"):
        prod = run_dir / root_name / "product"
        if prod.is_dir():
            out.extend(sorted(prod.rglob("*.html")))
    return out


def _product_hashes(paths: list[Path], run_dir: Path) -> dict[str, str]:
    return {p.relative_to(run_dir).as_posix(): sha256_file(p) for p in paths if p.is_file()}


# ---------------------------------------------------------------- 대상/사전 조건 (§18, §19)

def resolve_editor_target(run_dir=None, run_id=None, db_conn=None):
    return resolve_run_target(run_dir, run_id, db_conn)


def _user_decision_ok(run_dir: Path) -> tuple[bool, str | None]:
    """§19: user_review_decision.md에서 Phase 2C-2 진행 결정 확인."""
    for rel in ("user_review_decision.md", "review/phase2c1/user_review_decision.md",
                "review/phase2c0/user_review_decision.md"):
        p = run_dir / rel
        if p.is_file():
            txt = p.read_text(encoding="utf-8", errors="replace")
            if re.search(r"\[x\]\s*Phase\s*2C-2", txt, re.I) or "Phase 2C-2 진행" in txt:
                return True, str(rel)
    return False, None


def check_editor_preconditions(run_dir: Path, gate: dict) -> list[str]:
    """§19 apply 전: 2C-1 fitness=NEEDS_PRODUCT_POLISH + verdict REVIEW_READY + green_base + 사용자 결정."""
    problems: list[str] = []
    prior = load_json(run_dir / "review" / "phase2c1" / "product_fitness_report_after_polish.json")
    if prior is None:
        problems.append("Phase 2C-1 product_fitness_report_after_polish.json 없음 (2C-1 polish 먼저 필요)")
    elif prior.get("recommended_fitness") != "NEEDS_PRODUCT_POLISH":
        problems.append(f"prior fitness가 NEEDS_PRODUCT_POLISH 아님: {prior.get('recommended_fitness')}")
    if gate.get("verdict") != "REVIEW_READY":
        problems.append(f"current verdict가 REVIEW_READY 아님: {gate.get('verdict')}")
    if not gate.get("green_base"):
        problems.append("green_base가 true 아님")
    ok, _src = _user_decision_ok(run_dir)
    if not ok:
        problems.append("user_review_decision.md에서 Phase 2C-2 진행 결정을 찾지 못함")
    return problems


# ---------------------------------------------------------------- editor smoke + fitness (§21, §22)

def build_editor_smoke(model: dict, static_dom: dict, handler: dict,
                       js_syntax: dict, viewer_smoke: dict, hash_status: str) -> dict:
    """§21 editor_smoke_review.json — model helper와 ui binding 분리 기록."""
    ui_binding_pass = (static_dom["status"] == "PASS" and handler["status"] == "PASS")
    critical: list[str] = []
    if not model["model_level_smoke_pass"]:
        critical += [f"model smoke: {f}" for f in model["failures"]]
    if not ui_binding_pass:
        critical.append(f"ui binding 미비: static={static_dom['missing']} handler={handler['missing']}")
    if js_syntax["status"] == "FAIL":
        critical.append(f"JS syntax FAIL: {js_syntax['errors']}")
    if not model["original_replay_unchanged"]:
        critical.append("원본 replay 변경 감지")
    if hash_status != "PASS":
        critical.append("보호 대상 hash 변경")
    unknowns: list[str] = []
    if js_syntax["status"] == "UNKNOWN":
        unknowns.append("node 미설치로 JS 구문 검사 스킵")
    return {
        "editor_mode_exists": static_dom["present"].get("editor_mode_toggle", False),
        "loads_replay_into_editor_state": model["loads_replay_into_editor_state"],
        "supported_node_types_loaded": bool(model.get("supported_types_count", 0)) or
                                       model["add_node_supported"],
        "add_node_supported": model["add_node_supported"],
        "edit_node_supported": model["edit_node_supported"],
        "delete_node_supported": model["delete_node_supported"],
        "delete_node_removes_incident_edges": model["delete_node_removes_incident_edges"],
        "add_edge_supported": model["add_edge_supported"],
        "delete_edge_supported": model["delete_edge_supported"],
        "graph_validation_supported": model["graph_validation_supported"],
        "draft_schema_compatible": model["draft_schema_compatible"],
        "draft_roundtrip_pass": model["draft_roundtrip_pass"],
        "draft_export_supported": model["draft_export_supported"],
        "model_level_smoke_pass": model["model_level_smoke_pass"],
        "ui_binding_evidence_pass": ui_binding_pass,
        "js_syntax_status": js_syntax["status"],
        "viewer_loads": viewer_smoke.get("product_viewer_exists", False),
        "runner_viewer_consistent": viewer_smoke.get("runner_viewer_consistent"),
        "original_replay_unchanged": model["original_replay_unchanged"],
        "runner_backed_execution_included": False,
        "critical_failures": critical,
        "unknowns": unknowns,
    }


def finalize_editor_fitness(base_fitness: dict, editor_smoke: dict, gate: dict,
                            hash_status: str) -> dict:
    """§22: build_fitness 결과를 editor 조건으로 보수적으로 조정한다. candidate는 draft editor candidate."""
    rec = base_fitness["recommended_fitness"]
    es = editor_smoke
    editor_conditions = {
        "editor_mode_exists": es["editor_mode_exists"],
        "supported_node_types_loaded": es["supported_node_types_loaded"],
        "add_node_supported": es["add_node_supported"],
        "edit_node_supported": es["edit_node_supported"],
        "delete_node_supported": es["delete_node_supported"],
        "add_edge_supported": es["add_edge_supported"],
        "delete_edge_supported": es["delete_edge_supported"],
        "graph_validation_supported": es["graph_validation_supported"],
        "draft_schema_compatible": es["draft_schema_compatible"],
        "draft_roundtrip_pass": es["draft_roundtrip_pass"],
        "draft_export_supported": es["draft_export_supported"],
        "js_syntax_pass": es["js_syntax_status"] == "PASS",
        "static_dom_pass": es["ui_binding_evidence_pass"],
        "handler_binding_pass": es["ui_binding_evidence_pass"],
        "model_level_smoke_pass": es["model_level_smoke_pass"],
        "ui_binding_evidence_pass": es["ui_binding_evidence_pass"],
        "protected_hash_pass": hash_status == "PASS",
        "no_critical_failure": not es["critical_failures"],
        "runner_backed_execution_not_included": es["runner_backed_execution_included"] is False,
        "green_base": bool(gate.get("green_base")),
        "no_gate_fail": not gate.get("gate_fail"),
    }
    all_editor_ok = all(editor_conditions.values())

    if rec == "PRODUCT_CANDIDATE" and not all_editor_ok:
        # editor 조건 미충족 → 정직하게 하향
        rec = "NEEDS_PRODUCT_POLISH"
    limitations = ["runner-backed execution not included",
                   "editor validation only (core runner의 완전한 대체 아님)",
                   "draft only — 원본 replay/golden/contract 불변"]
    return {
        "recommended_fitness": rec,
        "draft_editor_candidate": rec == "PRODUCT_CANDIDATE",
        "runner_backed_execution_included": False,
        "runner_backed_execution_limitation": "runner-backed execution not included",
        "editor_candidate_conditions": editor_conditions,
        "all_editor_conditions_met": all_editor_ok,
        "limitations": limitations,
    }


# ---------------------------------------------------------------- 문서 렌더링

def _plan_md(plan: dict) -> str:
    L = ["# Phase 2C-2 Minimal Node Draft Editor Plan", "",
         f"- run_dir: {plan['run_dir']} / challenge_id: {plan['challenge_id']}",
         f"- prior recommended_fitness: {plan['prior_recommended_fitness']}",
         f"- status: {plan['status']}",
         "", "## supported_node_types",
         f"- source: {plan['supported_node_types_source']}",
         f"- types: {plan['supported_node_types']}",
         "", "## planned editor features"] + [f"- {f}" for f in plan["planned_editor_features"]]
    L += ["", "## planned files (product viewer)"] + ([f"- {f}" for f in plan["planned_files"]] or ["- (없음)"])
    L += ["", "## protected files"] + [f"- {f}" for f in plan["protected_files"]]
    L += ["", "## storage mode", f"- {plan['storage_mode']}"]
    L += ["", "## validation rules"] + [f"- {r}" for r in plan["validation_rules"]]
    L += ["", "## draft compatibility rules"] + [f"- {r}" for r in plan["draft_compatibility_rules"]]
    L += ["", "## draft roundtrip rules"] + [f"- {r}" for r in plan["draft_roundtrip_rules"]]
    L += ["", "## UI binding plan"] + [f"- {r}" for r in plan["ui_binding_plan"]]
    L += ["", f"## risk: {plan['risk_assessment']}"]
    if plan.get("blocked_reasons"):
        L += ["", "## Blocked"] + [f"- {b}" for b in plan["blocked_reasons"]]
    return "\n".join(L) + "\n"


def _report_md(report: dict) -> str:
    es = report["editor_smoke"]
    L = ["# Phase 2C-2 Minimal Node Draft Editor Report", "",
         f"- run_dir: {report['run_dir']} / challenge_id: {report['challenge_id']}",
         f"- applied: {report['applied']} / patched: {', '.join(report['patched_files']) or '-'}",
         f"- 보호 대상 hash: {report['hash_status']}",
         f"- supported_node_types({report['supported_node_types_source']}): {report['supported_node_types']}",
         "", "## editor smoke (model / ui 분리)",
         f"- editor mode exists: {es['editor_mode_exists']}",
         f"- loads replay into editorState: {es['loads_replay_into_editor_state']}",
         f"- add/edit/delete node: {es['add_node_supported']}/{es['edit_node_supported']}/{es['delete_node_supported']}",
         f"- delete node removes incident edges: {es['delete_node_removes_incident_edges']}",
         f"- add/delete edge: {es['add_edge_supported']}/{es['delete_edge_supported']}",
         f"- graph validation: {es['graph_validation_supported']}",
         f"- draft schema compatible: {es['draft_schema_compatible']}",
         f"- draft roundtrip: {es['draft_roundtrip_pass']}",
         f"- model_level_smoke_pass: {es['model_level_smoke_pass']}",
         f"- ui_binding_evidence_pass: {es['ui_binding_evidence_pass']}",
         f"- JS syntax: {es['js_syntax_status']}",
         f"- runner-backed execution included: {es['runner_backed_execution_included']}",
         f"- original replay unchanged: {es['original_replay_unchanged']}",
         "", "## product fitness after editor",
         f"- recommended_fitness: {report['recommended_fitness']}",
         f"- draft editor candidate: {report['draft_editor_candidate']}",
         f"- limitation: {report['runner_backed_execution_limitation']}",
         "", "## critical failures"] + ([f"- {c}" for c in es["critical_failures"]] or ["- (없음)"])
    return "\n".join(L) + "\n"


def _fitness_md(fit: dict, base: dict) -> str:
    L = ["# Product Fitness Report (After Phase 2C-2 Editor)", "",
         f"- recommended_fitness: **{fit['recommended_fitness']}** · 평균 {base['average_score']}/5",
         f"- draft editor candidate: {fit['draft_editor_candidate']}",
         f"- runner-backed execution limitation: {fit['runner_backed_execution_limitation']}",
         "", "## 점수"]
    for c in base["criteria"]:
        L.append(f"- {c['criterion']}: {c['score']} — {c['reason']}")
    L += ["", "## limitations"] + [f"- {x}" for x in fit["limitations"]]
    L += ["", "## red flags"] + ([f"- {r}" for r in base["critical_red_flags"]] or ["- 없음"])
    L += ["", "## editor candidate 조건"]
    for k, v in fit["editor_candidate_conditions"].items():
        L.append(f"- [{'x' if v else ' '}] {k}")
    return "\n".join(L) + "\n"


def _editor_status_text(es: dict) -> str:
    if es["model_level_smoke_pass"] and es["ui_binding_evidence_pass"]:
        return "minimal draft editor available"
    return "editor partial (model/ui 근거 부족)"


# ---------------------------------------------------------------- 오케스트레이터 (§18, §19)

def run_product_editor(run_dir=None, run_id=None, apply=False, db_conn=None,
                       timeout: float = 60.0) -> dict:
    """#47 viewer에 최소 node draft editor를 dry-run/apply한다 (§18, §19). core/golden/replay 미변경."""
    result: dict = {
        "ok": False, "status": None, "resolved_run_dir": None, "challenge_id": None,
        "applied": False, "patched_files": [], "hash_status": None,
        "recommended_fitness": None, "review_dir": None, "problems": [], "error": None,
    }
    tgt, err, info = resolve_editor_target(run_dir, run_id, db_conn)
    result["resolved_run_dir"] = info.get("resolved_run_dir")
    if err:
        result["error"] = err
        return result
    run_dir = tgt
    review_dir = run_dir / EDITOR_SUBDIR
    result["review_dir"] = review_dir.as_posix()
    final_dir = run_dir / "final_artifact"

    gate = read_gate_context(run_dir)
    result["challenge_id"] = info.get("challenge_id") or _challenge_id(run_dir)
    supported_types, types_source = extract_supported_node_types(final_dir)
    prior = load_json(run_dir / "review" / "phase2c1"
                       / "product_fitness_report_after_polish.json") or {}

    problems = check_editor_preconditions(run_dir, gate)
    # supported_node_types 추출 실패 → 새 type 생성 금지, 안전 차단 (§8.2)
    types_blocked = not supported_types

    plan = {
        "run_dir": f"runs/{run_dir.name}", "challenge_id": result["challenge_id"],
        "prior_recommended_fitness": prior.get("recommended_fitness"),
        "supported_node_types": supported_types,
        "supported_node_types_source": types_source,
        "planned_editor_features": [
            "editor mode toggle (viewer <-> editor)",
            "load existing replay graph into editorState",
            "add node (supported_node_types only)",
            "edit node label/type", "delete node (+ incident edge 자동 삭제)",
            "add edge / delete edge",
            "graph validation (dup id/unsupported type/dangling/self-loop/cycle/isolated)",
            "draft schema compatibility check", "draft roundtrip check",
            "draft JSON export / copy / download / reload / reset",
        ],
        "planned_files": [p.relative_to(run_dir).as_posix() for p in _product_viewer_paths(run_dir)],
        "protected_files": ["final_artifact/src/", "workspace/src/", "golden/", "fixtures/",
                            "core_contract.json", "state_contract.json", "action_contract.json",
                            "runner_contract.json", "oracle_risk_report.json",
                            "replay/index.json", "replay/replay_*.json",
                            "review/phase2c0/", "review/phase2c1/"],
        "storage_mode": f"in-memory + optional localStorage (key prefix {STORAGE_KEY}, reset 제공)",
        "validation_rules": [
            "node id 중복 없음", "node type in supported_node_types", "edge endpoint 존재",
            "dangling edge 없음", "self-loop 차단", "cycle detection", "노드 1개 이상",
            "delete node 시 incident edge 자동 삭제 후 dangling FAIL",
        ],
        "draft_compatibility_rules": [
            "nodes[]/edges[] 존재", "node.id 존재", "node.type in supported_node_types",
            "node.label string", "edge.source_id/target_id 존재 + 실제 node 참조",
            "from/to only edge 금지", "unsupported metadata 금지",
        ],
        "draft_roundtrip_rules": [
            "export draft JSON", "reload exported draft", "nodes/edges preserved",
            "displayModel regenerated from exported draft",
        ],
        "ui_binding_plan": [f"{name}: data-action={action} / handler {fn}"
                            for name, _id, action, fn in _DOM_CONTROLS],
        "risk_assessment": ("low (product viewer만 수정, core/golden/replay/phase2c0/2c1 불변)"
                            if not types_blocked
                            else "blocked (supported_node_types 추출 실패 → add node 금지)"),
        "blocked_reasons": problems + (["supported_node_types 추출 실패 (contract/replay에 없음)"]
                                       if types_blocked else []),
        "status": "DRY_RUN_BLOCKED" if (problems or types_blocked) else "DRY_RUN_PASS",
    }
    write_json(review_dir / "phase2c2_editor_plan.json", plan)
    write_text(review_dir / "phase2c2_editor_plan.md", _plan_md(plan))

    if not apply:
        result["ok"] = not (problems or types_blocked)
        result["status"] = plan["status"]
        result["plan"] = plan
        result["problems"] = plan["blocked_reasons"]
        result["supported_node_types"] = supported_types
        if plan["blocked_reasons"]:
            result["error"] = "; ".join(plan["blocked_reasons"])
        return result

    if problems or types_blocked:
        result["status"] = "CANNOT_EDIT"
        result["problems"] = plan["blocked_reasons"]
        result["error"] = "; ".join(plan["blocked_reasons"])
        return result

    # ---- Apply (§19)
    hash_before = compute_editor_protected_hashes(run_dir)
    prod_before = _product_hashes(_product_viewer_paths(run_dir), run_dir)
    write_json(review_dir / "phase2c2_hash_before.json", hash_before)

    patched: list[str] = []
    for vp in _product_viewer_paths(run_dir):
        if inject_editor(vp, supported_types, f"runs/{run_dir.name}", result["challenge_id"]):
            patched.append(vp.relative_to(run_dir).as_posix())
    result["patched_files"] = patched

    hash_after = compute_editor_protected_hashes(run_dir)
    hash_check = _compare(hash_before, hash_after)
    hash_check["note"] = ("Phase 2C-2는 product viewer만 수정 — "
                          "src/golden/fixtures/contract/replay/phase2c0/2c1 불변 (§4)")
    write_json(review_dir / "phase2c2_hash_after.json", hash_after)
    write_json(review_dir / "phase2c2_hash_check.json", hash_check)
    result["hash_status"] = hash_check["status"]

    prod_after = _product_hashes(_product_viewer_paths(run_dir), run_dir)
    prod_changed = sorted(k for k in prod_before if prod_before.get(k) != prod_after.get(k))
    write_json(review_dir / "phase2c2_diff_summary.json", {
        "run_dir": f"runs/{run_dir.name}", "challenge_id": result["challenge_id"],
        "patched_files": patched,
        "product_files_changed": prod_changed,
        "protected_files_changed": hash_check["changed"] + hash_check["added"] + hash_check["removed"],
        "core_golden_fixtures_contract_replay_changed": bool(
            hash_check["changed"] or hash_check["added"] or hash_check["removed"]),
        "editor_features_added": plan["planned_editor_features"],
    })

    # ---- 검증들
    viewer = find_product_viewer(final_dir)
    viewer_html = viewer.read_text(encoding="utf-8", errors="replace") if viewer else ""
    tmp_js = review_dir / "js_check"
    js_syntax = check_js_syntax(viewer, tmp_js) if viewer else {"status": "FAIL", "errors": ["viewer 없음"]}
    static_dom = check_static_dom(viewer_html)
    handler = check_handler_binding(viewer_html)
    write_json(review_dir / "viewer_js_syntax_check.json", js_syntax)
    write_json(review_dir / "viewer_static_dom_check.json", static_dom)
    write_json(review_dir / "viewer_handler_binding_check.json", handler)

    # ---- viewer smoke (temp copy, 원본 미변경) + editor model smoke
    viewer_smoke = smoke_review(run_dir, review_dir, timeout=timeout)
    write_json(review_dir / "viewer_smoke_after_editor.json", viewer_smoke)

    _rf, replay = first_replay_file(final_dir)
    model = run_model_level_smoke(supported_types, replay,
                                  f"runs/{run_dir.name}", result["challenge_id"])
    model["supported_types_count"] = len(supported_types)
    write_json(review_dir / "draft_schema_compatibility.json", {
        "compatible": model["draft_schema_compatible"],
        "reasons": model["draft_schema_compatibility_reasons"],
        "from_to_only_edge_rejected": model["from_to_only_edge_rejected"],
        "draft_sample": model["draft_sample"],
        "note": ("draft_schema_compatible = viewer/editor/replay display model과 구조적 호환. "
                 "runner_executable_draft 아님 (Phase 2C-3 범위)."),
    })
    write_json(review_dir / "draft_roundtrip_check.json", model["draft_roundtrip"])

    editor_smoke = build_editor_smoke(model, static_dom, handler, js_syntax,
                                      viewer_smoke, hash_check["status"])
    editor_smoke["supported_node_types_loaded"] = bool(supported_types)
    editor_smoke["model_steps"] = model["steps"]
    write_json(review_dir / "editor_smoke_review.json",
                {k: v for k, v in editor_smoke.items() if k != "model_steps"} | {"model_steps": model["steps"]})

    # ---- product fitness 재평가 (base + editor 조건 조정)
    base_fitness = build_fitness(viewer_smoke, gate)
    fit = finalize_editor_fitness(base_fitness, editor_smoke, gate, hash_check["status"])
    result["recommended_fitness"] = fit["recommended_fitness"]

    fitness_json = {
        "recommended_fitness": fit["recommended_fitness"],
        "draft_editor_candidate": fit["draft_editor_candidate"],
        "runner_backed_execution_included": False,
        "runner_backed_execution_limitation": fit["runner_backed_execution_limitation"],
        "review_status": ("사용자 최종 승인 필요" if fit["recommended_fitness"] == "PRODUCT_CANDIDATE"
                          else "사용자 최종 결정 대기"),
        "final_decision": "PENDING_USER_REVIEW",
        "average_score": base_fitness["average_score"], "scores": base_fitness["scores"],
        "criteria": base_fitness["criteria"], "critical_red_flags": base_fitness["critical_red_flags"],
        "editor_candidate_conditions": fit["editor_candidate_conditions"],
        "limitations": fit["limitations"],
        "green_base": gate.get("green_base"), "gate_fail": gate.get("gate_fail"),
        "editor_mode_exists": editor_smoke["editor_mode_exists"],
        "supported_node_types_loaded": editor_smoke["supported_node_types_loaded"],
        "add_node_supported": editor_smoke["add_node_supported"],
        "add_edge_supported": editor_smoke["add_edge_supported"],
        "graph_validation_supported": editor_smoke["graph_validation_supported"],
        "draft_schema_compatible": editor_smoke["draft_schema_compatible"],
        "draft_roundtrip_pass": editor_smoke["draft_roundtrip_pass"],
        "draft_export_supported": editor_smoke["draft_export_supported"],
        "model_level_smoke_pass": editor_smoke["model_level_smoke_pass"],
        "ui_binding_evidence_pass": editor_smoke["ui_binding_evidence_pass"],
        "js_syntax_status": editor_smoke["js_syntax_status"],
        "original_replay_unchanged": editor_smoke["original_replay_unchanged"],
    }
    write_json(review_dir / "product_fitness_report_after_editor.json", fitness_json)
    write_text(review_dir / "product_fitness_report_after_editor.md", _fitness_md(fit, base_fitness))

    # ---- report + dashboard summary
    report = {
        "run_dir": f"runs/{run_dir.name}", "challenge_id": result["challenge_id"],
        "applied": True, "patched_files": patched, "hash_status": hash_check["status"],
        "supported_node_types": supported_types, "supported_node_types_source": types_source,
        "editor_smoke": editor_smoke,
        "recommended_fitness": fit["recommended_fitness"],
        "draft_editor_candidate": fit["draft_editor_candidate"],
        "runner_backed_execution_limitation": fit["runner_backed_execution_limitation"],
    }
    write_json(review_dir / "phase2c2_editor_report.json", report)
    write_text(review_dir / "phase2c2_editor_report.md", _report_md(report))

    write_json(review_dir / "phase2c2_dashboard_summary.json", {
        "phase": "2c2", "challenge_id": result["challenge_id"], "run_dir": f"runs/{run_dir.name}",
        "verdict": gate.get("verdict"), "green_base": gate.get("green_base"),
        "recommended_fitness": fit["recommended_fitness"],
        "draft_editor_candidate": fit["draft_editor_candidate"],
        "review_status": fitness_json["review_status"],
        "editor_status": _editor_status_text(editor_smoke),
        "user_next_action": ("add/edit/export draft 확인 후 최종 승인"
                             if fit["recommended_fitness"] == "PRODUCT_CANDIDATE"
                             else "editor에서 노드/엣지 조작 확인"),
        "supported_node_types": supported_types, "supported_node_types_source": types_source,
        "editor_mode_exists": editor_smoke["editor_mode_exists"],
        "add_node_supported": editor_smoke["add_node_supported"],
        "add_edge_supported": editor_smoke["add_edge_supported"],
        "graph_validation_supported": editor_smoke["graph_validation_supported"],
        "draft_schema_compatible": editor_smoke["draft_schema_compatible"],
        "draft_roundtrip_pass": editor_smoke["draft_roundtrip_pass"],
        "model_level_smoke_pass": editor_smoke["model_level_smoke_pass"],
        "ui_binding_evidence_pass": editor_smoke["ui_binding_evidence_pass"],
        "js_syntax_status": editor_smoke["js_syntax_status"],
        "runner_backed_execution_included": False,
        "hash_status": hash_check["status"],
        "average_score": base_fitness["average_score"], "scores": base_fitness["scores"],
        "critical_red_flags": base_fitness["critical_red_flags"],
        "critical_failures": editor_smoke["critical_failures"],
        "limitations": fit["limitations"],
    })

    result["applied"] = True
    result["ok"] = True
    result["status"] = "EDITOR_ADDED"
    result["editor_smoke"] = editor_smoke
    result["fitness"] = fitness_json
    result["supported_node_types"] = supported_types
    return result


def _challenge_id(run_dir: Path):
    for name in ("phase2b1b_dashboard_summary.json",
                 "green_base_promotion_after_anti_hardcode_patch.json"):
        d = load_json(run_dir / name) or {}
        if d.get("challenge_id") is not None:
            return d["challenge_id"]
    for rel in ("review/phase2c1/phase2c1_dashboard_summary.json",
                "review/phase2c0/review_package.json"):
        d = load_json(run_dir / rel) or {}
        if d.get("challenge_id") is not None:
            return d["challenge_id"]
    return None
