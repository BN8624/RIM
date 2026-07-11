# 도메인 중립 INTERACTION_UI executor — interaction contract를 읽어 실조작 UI를 생성하고 runner로 검증한다 (이슈 #5 §6).
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from repo_idea_miner.factory_run_layout import resolve_artifact_root

INTERACTION_SUBDIR = "review/interaction_ui"
CONTRACT_REL = "product/interaction/contract.json"
UI_REL = "product/interaction/index.html"
SERVER_REL = "product/interaction_server.py"
REPORT_JSON = "interaction_ui_report.json"
EVIDENCE_JSON = "interaction_evidence.json"

# canonical interaction kind (§6.2). graph_editor는 legacy graph 도메인 adapter(2C-2)로 라우팅.
# table_grid(이슈 #10)는 state 모양(columns+rows)으로만 감지하는 tabular 특화 렌더 — 제품 분기 없음.
KIND_ACTION_CONSOLE = "action_console"
KIND_GRAPH_EDITOR = "graph_editor"
KIND_TABLE_GRID = "table_grid"


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def detect_interaction_kind(artifact_root: Path) -> str | None:
    """도메인 어댑터 경계 (§6.3): artifact 모양으로 interaction kind를 고른다.

    graph 도메인(state에 nodes+edges 컬렉션)은 legacy graph adapter(2C-2 editor)로,
    tabular 도메인(state에 columns+rows 컬렉션)은 grid 렌더로, action_contract가 있는
    일반 도메인은 generic action console로. 둘 다 아니면 None."""
    state = _load_json(artifact_root / "state_contract.json") or {}
    fields: set[str] = set()
    for entity in state.get("state_entities") or []:
        fields |= set(entity.get("fields") or [])
    if {"nodes", "edges"} <= fields:
        return KIND_GRAPH_EDITOR
    actions = (_load_json(artifact_root / "action_contract.json") or {}).get("actions") or []
    if not actions:
        return None
    if {"columns", "rows"} <= fields:
        return KIND_TABLE_GRID
    return KIND_ACTION_CONSOLE


def grid_render_hints(initial_state: dict) -> dict | None:
    """initial_state 모양에서 grid 렌더 대상 entity를 찾는다 (이슈 #10 §6).

    columns(dict of dict)와 rows(dict of dict)를 가진 entity가 각각 있어야 한다 —
    이름을 지어내지 않고 실제 state 키를 기록한다. 못 찾으면 None(action console 폴백)."""
    schema_entity = data_entity = None
    for name, val in sorted((initial_state or {}).items()):
        if not isinstance(val, dict):
            continue
        cols = val.get("columns")
        if schema_entity is None and isinstance(cols, dict) \
                and all(isinstance(c, dict) for c in cols.values()):
            schema_entity = name
        rows = val.get("rows")
        if data_entity is None and isinstance(rows, dict) \
                and all(isinstance(r, dict) for r in rows.values()):
            data_entity = name
    if schema_entity is None or data_entity is None:
        return None
    return {"schema_entity": schema_entity, "columns_field": "columns",
            "data_entity": data_entity, "rows_field": "rows"}


# ---------------------------------------------------------------- structured input 타입 관측 (이슈 #13)

# 관측 재귀 한도 — 병리적 fixture로 인한 폭주 방지 (검증 한도와 별개)
_TYPE_OBSERVE_MAX_DEPTH = 8


def _json_kind(value) -> str:
    """JSON 값의 canonical kind. bool은 number보다 먼저 판정한다 (Python bool ⊂ int 함정)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "unsupported"


def _merge_type_descriptor(desc: dict | None, value, depth: int = 0) -> dict:
    """관측값 하나를 type descriptor에 병합한다. descriptor는 JSON 직렬화 가능·결정론적이다.

    {"kinds": [정렬된 관측 kind], "fields": {object field별 descriptor}, "items": array 원소 descriptor}
    """
    desc = desc or {"kinds": []}
    kind = _json_kind(value)
    if kind not in desc["kinds"]:
        desc["kinds"] = sorted(desc["kinds"] + [kind])
    if depth >= _TYPE_OBSERVE_MAX_DEPTH:
        return desc
    if kind == "object":
        fields = desc.setdefault("fields", {})
        for k in sorted(value):
            fields[k] = _merge_type_descriptor(fields.get(k), value[k], depth + 1)
    elif kind == "array":
        items = desc.get("items")
        for it in value:
            items = _merge_type_descriptor(items, it, depth + 1)
        if items is not None:
            desc["items"] = items
    return desc


def observe_input_types(artifact_root: Path, action_names: set[str]) -> dict:
    """fixture 전체의 action payload에서 field별 type descriptor를 관측한다 (이슈 #13 §4).

    action_contract에는 타입 정보가 없으므로 fixture 실사용 값이 결정론적 타입 정본이다.
    관측이 없는 field는 결과에 없다 — 그 field는 기존 text 입력과 검증 skip을 유지한다."""
    observed: dict[str, dict] = {}
    for path in sorted(artifact_root.glob("fixtures/scenario_*.json")):
        fixture = _load_json(path)
        if not fixture:
            continue
        for action in fixture.get("actions") or []:
            if not isinstance(action, dict):
                continue
            name = action.get("type")
            payload = action.get("payload")
            if name not in action_names or not isinstance(payload, dict):
                continue
            slot = observed.setdefault(name, {})
            for field in sorted(payload):
                slot[field] = _merge_type_descriptor(slot.get(field), payload[field])
    return observed


def first_fixture(artifact_root: Path) -> dict | None:
    for p in sorted((artifact_root / "fixtures").glob("scenario_*.json")):
        data = _load_json(p)
        if data and isinstance(data.get("initial_state"), dict):
            return data
    return None


def build_interaction_contract(artifact_root: Path) -> dict:
    """기존 artifact(action/state contract + fixture)에서 canonical interaction contract를 만든다 (§6.2).

    필드를 새로 지어내지 않는다 — 없는 정보는 명시적 missing으로 남긴다."""
    missing: list[str] = []
    action_contract = _load_json(artifact_root / "action_contract.json")
    state_contract = _load_json(artifact_root / "state_contract.json")
    runner_contract = _load_json(artifact_root / "runner_contract.json")
    fixture = first_fixture(artifact_root)
    if action_contract is None:
        missing.append("action_contract.json")
    if state_contract is None:
        missing.append("state_contract.json")
    if runner_contract is None or not runner_contract.get("runner_command"):
        missing.append("runner_contract.json(runner_command)")
    if fixture is None:
        missing.append("fixtures/scenario_*.json(initial_state)")
    if missing:
        return {"supported": False, "reason": "필수 artifact 없음", "missing": missing}

    actions = action_contract.get("actions") or []
    if not actions:
        return {"supported": False, "reason": "action_contract에 action이 없음", "missing": []}

    entities = state_contract.get("state_entities") or []
    validation_rules = []
    for a in actions:
        for pre in a.get("preconditions") or []:
            validation_rules.append({"action": a.get("name"), "rule": pre})
    for e in entities:
        for inv in e.get("invariants") or []:
            validation_rules.append({"entity": e.get("name"), "rule": inv})

    # tabular 감지(이슈 #10): state 필드에 columns+rows가 있고 initial_state에서 대상
    # entity를 실제로 찾을 수 있을 때만 grid — 못 찾으면 정직하게 action console 폴백.
    fields: set[str] = set()
    for e in entities:
        fields |= set(e.get("fields") or [])
    grid = grid_render_hints(fixture["initial_state"]) \
        if {"columns", "rows"} <= fields else None
    kind = KIND_TABLE_GRID if grid else KIND_ACTION_CONSOLE

    render_hints = {"entities": [e.get("name") for e in entities],
                    "primary_actions": [a.get("name") for a in actions]}
    if grid:
        render_hints["grid"] = grid

    return {
        "supported": True,
        "interaction_id": "core_table_grid" if grid else "core_action_console",
        "interaction_kind": kind,
        "target": [e.get("name") for e in entities],
        "available_actions": [
            {"name": a.get("name"), "input": list(a.get("input") or []),
             "preconditions": list(a.get("preconditions") or []),
             "output": list(a.get("output") or [])}
            for a in actions
        ],
        "input_schema": {a.get("name"): list(a.get("input") or []) for a in actions},
        # 이슈 #13: fixture 실사용 값에서 관측한 field type descriptor — object/array schema일
        # 때만 structured JSON input을 열고, 관측 없는 field는 기존 text 입력을 유지한다.
        "input_types": observe_input_types(
            artifact_root, {a.get("name") for a in actions}),
        "input_types_provenance": "fixtures/scenario_*.json action payload 관측",
        "state_schema": {e.get("name"): list(e.get("fields") or []) for e in entities},
        "initial_state": fixture["initial_state"],
        # runner의 시나리오 스키마는 도메인마다 다르다 — fixture를 템플릿으로 재사용해
        # 필수 필드(case_type 등)를 지어내지 않는다 (§6.2 기존 artifact 재사용).
        # 단 product 산출물에 fixture id/설명이 남으면 anti-hardcode가 fixture 분기로
        # 의심하므로 id는 중립값으로, 설명용 필드는 제외한다.
        "scenario_template": {
            **{k: v for k, v in fixture.items()
               if k not in ("actions", "title", "expected_behavior", "must_check")},
            **({"id": "interactive_session"} if "id" in fixture else {}),
        },
        "validation_rules": validation_rules,
        "evidence_requirements": [
            "valid action이 runner로 실행되고 state가 변한다",
            "invalid action이 명시적으로 거부된다",
            "수정 후 재실행이 결과를 바꾼다",
        ],
        "render_hints": render_hints,
        # runner_command는 존재만 검증한다 — fixture 경로가 product 산출물에 남으면
        # anti-hardcode가 fixture 분기로 의심하므로 contract에는 싣지 않는다
    }


# ---------------------------------------------------------------- runtime UI (§6.4~6.5)

def generate_interaction_ui(contract: dict) -> str:
    """contract 데이터만으로 렌더되는 generic 조작 UI. 도메인 이름·값 하드코드 없음.

    fallback 정책(§6.5): 서버 불가/artifact 문제는 명시적 오류 상태(RUNNER_UNAVAILABLE 등)로만
    표시한다 — 성공처럼 보이는 대체 데이터는 없다."""
    if contract.get("interaction_kind") == KIND_TABLE_GRID:
        return generate_table_grid_ui(contract)
    contract_json = json.dumps(contract, ensure_ascii=False, sort_keys=True)
    head = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Interaction Console</title>
<style>
body{font-family:system-ui,sans-serif;margin:16px;background:#111;color:#eee}
h1{font-size:18px} h2{font-size:14px;margin:12px 0 4px}
.panel{border:1px solid #444;border-radius:6px;padding:10px;margin-bottom:12px}
pre{background:#1b1b1b;padding:8px;border-radius:4px;overflow:auto;max-height:320px}
button{padding:6px 12px;margin:4px 4px 4px 0;cursor:pointer}
input,select{padding:4px;margin:2px}
textarea{padding:4px;margin:2px;font-family:ui-monospace,monospace;width:100%;
  box-sizing:border-box;background:#1b1b1b;color:#eee;border:1px solid #444}
.err{color:#ff7b72;white-space:pre-wrap}
.okmsg{color:#7ee787}
.state-tag{font-weight:bold}
.field-box{display:block;margin:6px 0}
.field-hint{color:#8b949e;font-size:11px}
.parse-status{font-size:12px;white-space:pre-wrap}
.parse-status.ok{color:#7ee787}
.parse-status.bad{color:#ff7b72}
#validation-view{color:#f0b429;white-space:pre-wrap}
#queue li{margin:2px 0}
@media (max-width:640px){
  body{margin:8px}
  .panel{padding:8px}
  button{width:100%;margin:4px 0;box-sizing:border-box}
  #action-inputs input,#action-inputs select{width:100%;box-sizing:border-box;margin:4px 0}
}
</style></head><body>
<h1>Interaction Console</h1>
<div class="panel"><h2>State</h2>
<div id="state-status" class="state-tag">INITIAL</div>
<pre id="state-view"></pre></div>
<div class="panel"><h2>Actions</h2>
<select id="action-select"></select>
<span id="action-inputs"></span>
<button id="queue-add">대기열에 추가</button>
<button id="run-actions">실행</button>
<button id="reset-actions">초기화</button>
<div id="validation-view"></div>
<ol id="queue"></ol></div>
<div class="panel"><h2>Events</h2><pre id="events-view"></pre></div>
<div class="panel"><h2>Errors</h2><div id="error-view" class="err"></div></div>
"""
    script = """<script>
"use strict";
const CONTRACT = __CONTRACT_JSON__;
let queued = [];
let lastState = CONTRACT["initial_state"];
let lastEvents = [];
// 이슈 #9 SC(localStorage 지속): 실제 runner 결과 상태만 저장/복원한다 — 생성 데이터 없음.
// key는 contract 내용 해시라 같은 origin의 다른 제품과 충돌하지 않는다.
const STORE_KEY = (() => {
  let h = 5381;
  const s = JSON.stringify(CONTRACT);
  for (let i = 0; i < s.length; i++) { h = ((h << 5) + h + s.charCodeAt(i)) >>> 0; }
  return "rim_console_state_" + h.toString(16);
})();
function persistState() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(
      {"queued": queued, "lastState": lastState, "lastEvents": lastEvents}));
  } catch (e) { /* storage 불가 환경 — 지속만 비활성, 다른 동작 불변 */ }
}
function restoreState() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) { return false; }
    const saved = JSON.parse(raw);
    if (!saved || typeof saved !== "object" || !saved["lastState"]) { return false; }
    queued = Array.isArray(saved["queued"]) ? saved["queued"] : [];
    lastState = saved["lastState"];
    lastEvents = Array.isArray(saved["lastEvents"]) ? saved["lastEvents"] : [];
    renderQueue();
    renderState(lastState, "RESTORED_SAVED_STATE");
    renderEvents(lastEvents);
    return true;
  } catch (e) { return false; }
}

function renderState(state, label) {
  document.getElementById("state-view").textContent = JSON.stringify(state, null, 2);
  document.getElementById("state-status").textContent = label;
}
function renderEvents(events) {
  document.getElementById("events-view").textContent = JSON.stringify(events || [], null, 2);
}
function showError(msg) {
  document.getElementById("error-view").textContent = msg || "";
}
function renderActionSelect() {
  const sel = document.getElementById("action-select");
  sel.innerHTML = "";
  for (const a of CONTRACT["available_actions"]) {
    const opt = document.createElement("option");
    opt.value = a["name"];
    opt.textContent = a["name"] + " (" + a["input"].join(", ") + ")";
    sel.appendChild(opt);
  }
  renderInputs();
}
// ---- structured input (이슈 #13): control은 field 이름이 아니라 관측된 schema kind로만 정한다.
// primitive string은 {...}/[...] 형태라도 절대 자동 JSON parse하지 않는다.
const STRUCT_MAX_CHARS = 200000;
const STRUCT_MAX_DEPTH = 16;
const FORBIDDEN_KEYS = ["__proto__", "prototype", "constructor"];

function descFor(action, field) {
  const perAction = (CONTRACT["input_types"] || {})[action] || {};
  return perAction[field] || null;
}
function controlKindForDesc(desc) {
  if (!desc || !Array.isArray(desc["kinds"]) || !desc["kinds"].length) { return "text"; }
  const ks = desc["kinds"].filter((k) => k !== "null");
  if (ks.length !== 1) { return "text"; }  // 혼합/미상 관측 → 기존 text 유지 (추측 금지)
  if (ks[0] === "object" || ks[0] === "array") { return ks[0]; }
  if (ks[0] === "boolean") { return "boolean"; }
  if (ks[0] === "number") { return "number"; }
  return "text";
}
function jsKindOf(v) {
  if (v === null) { return "null"; }
  if (Array.isArray(v)) { return "array"; }
  const t = typeof v;
  if (t === "boolean" || t === "number" || t === "string") { return t === "number" ? "number" : t; }
  if (t === "object") { return "object"; }
  return "unsupported";
}
function structuralProblems(v, depth, path, problems) {
  if (depth > STRUCT_MAX_DEPTH) {
    problems.push("EXCESSIVE_NESTING: " + path + " 깊이 " + STRUCT_MAX_DEPTH + " 초과");
    return;
  }
  if (Array.isArray(v)) {
    v.forEach((it, i) => structuralProblems(it, depth + 1, path + "[" + i + "]", problems));
  } else if (v !== null && typeof v === "object") {
    for (const key of Object.keys(v)) {
      if (FORBIDDEN_KEYS.indexOf(key) >= 0) {
        problems.push("FORBIDDEN_KEY: " + path + "." + key);
        continue;
      }
      structuralProblems(v[key], depth + 1, path + "." + key, problems);
    }
  }
}
function checkAgainstDesc(v, desc, path, problems) {
  if (!desc || !Array.isArray(desc["kinds"]) || !desc["kinds"].length) { return; }
  const k = jsKindOf(v);
  if (desc["kinds"].indexOf(k) < 0) {
    problems.push("INVALID_FIELD_TYPE: " + path + " = " + k +
                  " (기대: " + desc["kinds"].join("|") + ")");
    return;
  }
  if (k === "object" && desc["fields"]) {
    for (const key of Object.keys(v)) {
      if (desc["fields"][key]) { checkAgainstDesc(v[key], desc["fields"][key], path + "." + key, problems); }
    }
  }
  if (k === "array" && desc["items"]) {
    v.forEach((it, i) => {
      const p = [];
      checkAgainstDesc(it, desc["items"], path + "[" + i + "]", p);
      for (const msg of p) { problems.push(msg.replace("INVALID_FIELD_TYPE", "INVALID_ARRAY_ITEM")); }
    });
  }
}
function parseStructured(raw, kind, allowNull, desc) {
  const text = String(raw);
  if (text.length > STRUCT_MAX_CHARS) {
    return {"valid": false, "error": "PAYLOAD_TOO_LARGE: 입력이 " + STRUCT_MAX_CHARS + "자를 초과"};
  }
  if (text.trim() === "") {
    return {"valid": false, "error": "MISSING_REQUIRED_FIELD: JSON " + kind + " 값이 필요합니다"};
  }
  let value;
  try {
    value = JSON.parse(text);
  } catch (e) {
    return {"valid": false, "error": "INVALID_JSON: " + e.message};
  }
  const topKind = jsKindOf(value);
  if (topKind !== kind && !(allowNull && topKind === "null")) {
    return {"valid": false, "error": "WRONG_TOP_LEVEL_TYPE: " + topKind +
            " (기대: " + kind + (allowNull ? "|null" : "") + ")"};
  }
  const problems = [];
  structuralProblems(value, 0, "$", problems);
  if (!problems.length && topKind !== "null") { checkAgainstDesc(value, desc, "$", problems); }
  if (problems.length) { return {"valid": false, "error": problems.join("\\n")}; }
  return {"valid": true, "value": value};
}
function updateParseStatus(el) {
  const status = document.getElementById("parse-status-" + el.dataset.field);
  if (!status) { return; }
  const desc = descFor(document.getElementById("action-select").value, el.dataset.field);
  const out = parseStructured(el.value, el.dataset.kind, el.dataset.allownull === "1", desc);
  status.textContent = out["valid"] ? "parse OK (" + jsKindOf(out["value"]) + ")" : out["error"];
  status.className = "parse-status " + (out["valid"] ? "ok" : "bad");
}
function showValidation(msg) {
  document.getElementById("validation-view").textContent = msg || "";
}
function renderInputs() {
  const sel = document.getElementById("action-select");
  const span = document.getElementById("action-inputs");
  span.innerHTML = "";
  const fields = CONTRACT["input_schema"][sel.value] || [];
  for (const f of fields) {
    const desc = descFor(sel.value, f);
    const kind = controlKindForDesc(desc);
    if (kind === "object" || kind === "array") {
      const allowNull = desc["kinds"].indexOf("null") >= 0;
      const box = document.createElement("label");
      box.className = "field-box";
      const hint = document.createElement("div");
      hint.className = "field-hint";
      hint.textContent = f + " — JSON " + kind + (allowNull ? " 또는 null" : "");
      const ta = document.createElement("textarea");
      ta.rows = 4;
      ta.dataset.field = f;
      ta.dataset.kind = kind;
      ta.dataset.allownull = allowNull ? "1" : "0";
      ta.placeholder = kind === "object" ? '{"key": value}' : "[value, ...]";
      ta.addEventListener("input", () => updateParseStatus(ta));
      const status = document.createElement("div");
      status.id = "parse-status-" + f;
      status.className = "parse-status";
      box.appendChild(hint);
      box.appendChild(ta);
      box.appendChild(status);
      span.appendChild(box);
      continue;
    }
    if (kind === "boolean") {
      const bsel = document.createElement("select");
      bsel.dataset.field = f;
      bsel.dataset.kind = "boolean";
      for (const [val, label] of [["", f + " (true/false)"], ["true", "true"], ["false", "false"]]) {
        const opt = document.createElement("option");
        opt.value = val;
        opt.textContent = label;
        bsel.appendChild(opt);
      }
      span.appendChild(bsel);
      continue;
    }
    const inp = document.createElement("input");
    inp.placeholder = f;
    inp.dataset.field = f;
    inp.dataset.kind = kind;
    if (kind === "number") {
      inp.type = "number";
      inp.step = "any";
    }
    span.appendChild(inp);
  }
  showValidation("");
}
function coerceConsoleControl(el) {
  const kind = el.dataset.kind || "text";
  if (kind === "object" || kind === "array") {
    const desc = descFor(document.getElementById("action-select").value, el.dataset.field);
    return parseStructured(el.value, kind, el.dataset.allownull === "1", desc);
  }
  if (kind === "boolean") {
    if (el.value !== "true" && el.value !== "false") {
      return {"valid": false, "error": "INVALID_FIELD_TYPE: true/false 값을 선택하세요"};
    }
    return {"valid": true, "value": el.value === "true"};
  }
  if (kind === "number") {
    const raw = el.value.trim();
    if (raw === "") { return {"valid": false, "error": "MISSING_REQUIRED_FIELD: 숫자 값이 필요합니다"}; }
    const n = Number(raw);
    if (!isFinite(n)) { return {"valid": false, "error": "INVALID_FIELD_TYPE: 숫자가 아닙니다: " + raw}; }
    return {"valid": true, "value": n};
  }
  return {"valid": true, "value": el.value};  // string schema는 JSON처럼 보여도 문자열 유지
}
function renderQueue() {
  const ol = document.getElementById("queue");
  ol.innerHTML = "";
  for (const q of queued) {
    const li = document.createElement("li");
    li.textContent = q["type"] + " " + JSON.stringify(q["payload"]);
    ol.appendChild(li);
  }
}
document.getElementById("action-select").addEventListener("change", renderInputs);
document.getElementById("queue-add").addEventListener("click", () => {
  const sel = document.getElementById("action-select");
  const payload = {};
  const problems = [];
  for (const el of document.querySelectorAll(
      "#action-inputs input, #action-inputs select, #action-inputs textarea")) {
    const out = coerceConsoleControl(el);
    if (!out["valid"]) {
      problems.push(el.dataset.field + ": " + out["error"]);
      continue;
    }
    payload[el.dataset.field] = out["value"];
  }
  if (problems.length) {
    // invalid 입력은 대기열에 넣지 않는다 — runner 호출 0, state 변화 0 (fail-closed)
    showValidation("입력 거부:\\n" + problems.join("\\n"));
    return;
  }
  showValidation("");
  queued.push({"type": sel.value, "payload": payload});
  renderQueue();
});
document.getElementById("reset-actions").addEventListener("click", () => {
  queued = [];
  lastState = CONTRACT["initial_state"];
  lastEvents = [];
  try { localStorage.removeItem(STORE_KEY); } catch (e) { /* storage 불가 환경 */ }
  renderQueue();
  renderState(CONTRACT["initial_state"], "INITIAL");
  renderEvents([]);
  showError("");
  showValidation("");
});
document.getElementById("run-actions").addEventListener("click", async () => {
  showError("");
  try {
    const res = await fetch("/api/interact", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({"actions": queued}),
    });
    const data = await res.json();
    if (!res.ok || data["error"]) {
      renderState(lastState, "UNCHANGED_AFTER_ERROR");
      showError("실행 거부/실패: " + (data["error"] || res.status));
      return;
    }
    lastState = data["final_state"];
    lastEvents = data["events"] || [];
    renderState(data["final_state"], "AFTER_ACTIONS");
    renderEvents(data["events"]);
    persistState();
    if (data["errors"] && data["errors"].length) {
      showError("action 오류 (상태는 runner 결과 그대로 표시):\\n" + data["errors"].join("\\n"));
    }
  } catch (e) {
    // 서버가 없으면 성공처럼 보이는 대체 데이터 없이 명시적 오류만 표시한다 (RUNNER_UNAVAILABLE)
    renderState(lastState, "RUNNER_UNAVAILABLE");
    showError("interaction server에 연결할 수 없음 — python product/interaction_server.py 실행 필요");
  }
});
renderActionSelect();
if (!restoreState()) {
  renderState(CONTRACT["initial_state"], "INITIAL");
  renderEvents([]);
}
</script></body></html>
"""
    return head + script.replace("__CONTRACT_JSON__", contract_json)


def generate_table_grid_ui(contract: dict) -> str:
    """tabular state를 실제 row/column grid로 렌더하는 generic 조작 UI (이슈 #10 §6~§7).

    - grid는 render_hints.grid가 가리키는 실제 state entity만 읽는다 (이름 하드코드 없음).
    - 입력 컨트롤은 대상 column의 schema type 문자열로만 정한다: bool 계열은 명시적
      true/false select, 숫자 계열은 number input+parse 검증, 그 외 text.
    - payload는 타입 그대로 전송한다 — 전부 문자열로 보내는 단순화(F3)를 하지 않는다.
    - 서버 불가/오류는 명시적 상태(RUNNER_UNAVAILABLE 등)로만 표시한다 (§6.5)."""
    contract_json = json.dumps(contract, ensure_ascii=False, sort_keys=True)
    head = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Table Grid Console</title>
<style>
body{font-family:system-ui,sans-serif;margin:16px;background:#111;color:#eee}
h1{font-size:18px} h2{font-size:14px;margin:12px 0 4px}
.panel{border:1px solid #444;border-radius:6px;padding:10px;margin-bottom:12px}
pre{background:#1b1b1b;padding:8px;border-radius:4px;overflow:auto;max-height:320px}
button{padding:6px 12px;margin:4px 4px 4px 0;cursor:pointer}
input,select{padding:4px;margin:2px}
.err{color:#ff7b72;white-space:pre-wrap}
.okmsg{color:#7ee787}
.state-tag{font-weight:bold}
#queue li{margin:2px 0}
.grid-wrap{overflow-x:auto}
#grid-table{border-collapse:collapse;min-width:100%;width:max-content}
#grid-table th,#grid-table td{border:1px solid #444;padding:6px 10px;text-align:left}
#grid-table th{background:#1b1b1b}
.type-badge{color:#8b949e;font-size:11px;font-weight:normal}
.cell-changed{background:#173a17}
.cell-error{background:#4a1f1f}
.cell-selected{outline:2px solid #58a6ff}
.cell-missing{color:#8b949e;font-style:italic}
#validation-view{color:#f0b429;white-space:pre-wrap}
@media (max-width:640px){
  body{margin:8px}
  .panel{padding:8px}
  button{width:100%;margin:4px 0;box-sizing:border-box}
  #action-inputs input,#action-inputs select,#cell-editor input,#cell-editor select{
    width:100%;box-sizing:border-box;margin:4px 0}
}
</style></head><body>
<h1>Table Grid Console</h1>
<div class="panel"><h2>Grid</h2>
<div id="state-status" class="state-tag">INITIAL</div>
<div class="grid-wrap"><table id="grid-table"></table></div>
<div id="cell-editor"></div>
<details><summary>raw state</summary><pre id="state-view"></pre></details></div>
<div class="panel"><h2>Actions</h2>
<select id="action-select"></select>
<span id="action-inputs"></span>
<button id="queue-add">대기열에 추가</button>
<button id="run-actions">실행</button>
<button id="reset-actions">초기화</button>
<div id="validation-view"></div>
<ol id="queue"></ol></div>
<div class="panel"><h2>Events</h2><pre id="events-view"></pre></div>
<div class="panel"><h2>Errors</h2><div id="error-view" class="err"></div></div>
"""
    script = """<script>
"use strict";
const CONTRACT = __CONTRACT_JSON__;
const HINTS = CONTRACT["render_hints"]["grid"];
let queued = [];
let lastState = CONTRACT["initial_state"];
let lastEvents = [];
let prevRowsSnapshot = null;
let selectedCell = null;
const STORE_KEY = (() => {
  let h = 5381;
  const s = JSON.stringify(CONTRACT);
  for (let i = 0; i < s.length; i++) { h = ((h << 5) + h + s.charCodeAt(i)) >>> 0; }
  return "rim_console_state_" + h.toString(16);
})();

function schemaCols(state) {
  const ent = state[HINTS["schema_entity"]] || {};
  return ent[HINTS["columns_field"]] || {};
}
function dataRows(state) {
  const ent = state[HINTS["data_entity"]] || {};
  return ent[HINTS["rows_field"]] || {};
}
function controlKindForType(t) {
  const s = String(t || "").toLowerCase();
  if (s.indexOf("bool") >= 0) { return "boolean"; }
  if (s.indexOf("num") >= 0 || s.indexOf("int") >= 0 || s.indexOf("float") >= 0
      || s.indexOf("decimal") >= 0) { return "number"; }
  return "text";
}
function classifyField(f) {
  const s = String(f).toLowerCase();
  if (s.indexOf("col") >= 0) { return "column_ref"; }
  if (s.indexOf("row") >= 0) { return "row_ref"; }
  if (s.indexOf("type") >= 0) { return "type_ref"; }
  if (s.indexOf("value") >= 0) { return "value"; }
  return "text";
}
function findCellEditAction() {
  for (const a of CONTRACT["available_actions"]) {
    const kinds = a["input"].map(classifyField);
    if (kinds.indexOf("row_ref") >= 0 && kinds.indexOf("column_ref") >= 0
        && kinds.indexOf("value") >= 0) { return a; }
  }
  return null;
}
function fmtCell(present, v) {
  if (!present) { return "(없음)"; }
  if (typeof v === "boolean") { return v ? "true" : "false"; }
  if (v === null) { return "null"; }
  return String(v);
}
function makeValueControl(kind, id) {
  if (kind === "boolean") {
    const sel = document.createElement("select");
    sel.id = id;
    sel.dataset.kind = "boolean";
    for (const [val, label] of [["", "(true/false 선택)"], ["true", "true"], ["false", "false"]]) {
      const opt = document.createElement("option");
      opt.value = val;
      opt.textContent = label;
      sel.appendChild(opt);
    }
    return sel;
  }
  const inp = document.createElement("input");
  inp.id = id;
  if (kind === "number") {
    inp.type = "number";
    inp.step = "any";
    inp.dataset.kind = "number";
    inp.placeholder = "숫자 값";
  } else {
    inp.type = "text";
    inp.dataset.kind = "text";
    inp.placeholder = "값";
  }
  return inp;
}
function coerceControl(el) {
  const kind = el.dataset.kind || "text";
  if (kind === "boolean") {
    if (el.value !== "true" && el.value !== "false") {
      return {"ok": false, "error": "true/false 값을 선택하세요"};
    }
    return {"ok": true, "value": el.value === "true"};
  }
  if (kind === "number") {
    const raw = el.value.trim();
    if (raw === "") { return {"ok": false, "error": "숫자 값이 필요합니다"}; }
    const n = Number(raw);
    if (!isFinite(n)) { return {"ok": false, "error": "숫자가 아닙니다: " + raw}; }
    return {"ok": true, "value": n};
  }
  return {"ok": true, "value": el.value};
}
function markCell(rowId, colId, cls) {
  const td = document.querySelector(
    '#grid-table td[data-row="' + CSS.escape(rowId) + '"][data-col="' + CSS.escape(colId) + '"]');
  if (td) { td.classList.add(cls); }
}
function renderGrid(state) {
  const cols = schemaCols(state);
  const rows = dataRows(state);
  const colIds = Object.keys(cols).sort();
  const rowIds = Object.keys(rows).sort();
  const table = document.getElementById("grid-table");
  table.innerHTML = "";
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  const corner = document.createElement("th");
  corner.textContent = "row";
  hr.appendChild(corner);
  for (const cid of colIds) {
    const th = document.createElement("th");
    const info = cols[cid] || {};
    const nameDiv = document.createElement("div");
    nameDiv.textContent = String(info["name"] !== undefined ? info["name"] : cid);
    const badge = document.createElement("div");
    badge.className = "type-badge";
    badge.textContent = cid + " · " + String(info["type"] !== undefined ? info["type"] : "?");
    th.appendChild(nameDiv);
    th.appendChild(badge);
    hr.appendChild(th);
  }
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  for (const rid of rowIds) {
    const tr = document.createElement("tr");
    const rh = document.createElement("th");
    rh.scope = "row";
    rh.textContent = rid;
    tr.appendChild(rh);
    for (const cid of colIds) {
      const td = document.createElement("td");
      const present = Object.prototype.hasOwnProperty.call(rows[rid], cid);
      td.textContent = fmtCell(present, rows[rid][cid]);
      td.dataset.row = rid;
      td.dataset.col = cid;
      td.tabIndex = 0;
      if (!present) { td.classList.add("cell-missing"); }
      if (prevRowsSnapshot) {
        const prevRow = prevRowsSnapshot[rid];
        const prevPresent = prevRow ? Object.prototype.hasOwnProperty.call(prevRow, cid) : false;
        const prevVal = prevRow ? prevRow[cid] : undefined;
        if (prevPresent !== present || JSON.stringify(prevVal) !== JSON.stringify(rows[rid][cid])) {
          td.classList.add("cell-changed");
        }
      }
      if (selectedCell && selectedCell["row"] === rid && selectedCell["col"] === cid) {
        td.classList.add("cell-selected");
      }
      td.addEventListener("click", () => { selectCell(rid, cid); });
      td.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); selectCell(rid, cid); }
      });
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
}
function renderCellEditor() {
  const box = document.getElementById("cell-editor");
  box.innerHTML = "";
  const action = findCellEditAction();
  if (!action) { return; }
  if (!selectedCell) {
    const hint = document.createElement("div");
    hint.className = "type-badge";
    hint.textContent = "셀을 클릭하면 타입에 맞는 편집 폼이 열립니다";
    box.appendChild(hint);
    return;
  }
  const cols = schemaCols(lastState);
  const info = cols[selectedCell["col"]];
  if (!info) { selectedCell = null; renderCellEditor(); return; }
  const kind = controlKindForType(info["type"]);
  const label = document.createElement("div");
  label.textContent = "선택: " + selectedCell["row"] + " · " + selectedCell["col"]
    + " (" + String(info["type"]) + ")";
  box.appendChild(label);
  const control = makeValueControl(kind, "cell-value-input");
  box.appendChild(control);
  const applyBtn = document.createElement("button");
  applyBtn.id = "cell-apply-run";
  applyBtn.textContent = "셀 변경 실행";
  applyBtn.addEventListener("click", async () => {
    const coerced = coerceControl(document.getElementById("cell-value-input"));
    if (!coerced["ok"]) {
      showValidation(coerced["error"]);
      markCell(selectedCell["row"], selectedCell["col"], "cell-error");
      return;
    }
    showValidation("");
    const payload = {};
    for (const f of action["input"]) {
      const k = classifyField(f);
      if (k === "row_ref") { payload[f] = selectedCell["row"]; }
      else if (k === "column_ref") { payload[f] = selectedCell["col"]; }
      else if (k === "value") { payload[f] = coerced["value"]; }
      else { payload[f] = ""; }
    }
    queued.push({"type": action["name"], "payload": payload});
    renderQueue();
    await runActions();
  });
  box.appendChild(applyBtn);
}
function renderDatalists(state) {
  for (const oldDl of document.querySelectorAll("datalist")) { oldDl.remove(); }
  const cols = schemaCols(state);
  const rows = dataRows(state);
  const types = new Set();
  for (const cid of Object.keys(cols)) {
    if (cols[cid] && cols[cid]["type"] !== undefined) { types.add(String(cols[cid]["type"])); }
  }
  const lists = [["dl-columns", Object.keys(cols).sort()],
                 ["dl-rows", Object.keys(rows).sort()],
                 ["dl-types", Array.from(types).sort()]];
  for (const [id, values] of lists) {
    const dl = document.createElement("datalist");
    dl.id = id;
    for (const v of values) {
      const opt = document.createElement("option");
      opt.value = v;
      dl.appendChild(opt);
    }
    document.body.appendChild(dl);
  }
}
function renderState(state, label) {
  document.getElementById("state-view").textContent = JSON.stringify(state, null, 2);
  document.getElementById("state-status").textContent = label;
  renderGrid(state);
  renderDatalists(state);
  renderCellEditor();
  renderInputs();
}
function renderEvents(events) {
  document.getElementById("events-view").textContent = JSON.stringify(events || [], null, 2);
}
function showError(msg) {
  document.getElementById("error-view").textContent = msg || "";
}
function showValidation(msg) {
  document.getElementById("validation-view").textContent = msg || "";
}
function selectCell(rowId, colId) {
  selectedCell = {"row": rowId, "col": colId};
  renderGrid(lastState);
  renderCellEditor();
}
function renderActionSelect() {
  const sel = document.getElementById("action-select");
  sel.innerHTML = "";
  for (const a of CONTRACT["available_actions"]) {
    const opt = document.createElement("option");
    opt.value = a["name"];
    opt.textContent = a["name"] + " (" + a["input"].join(", ") + ")";
    sel.appendChild(opt);
  }
  renderInputs();
}
function renderValueControlFor(span) {
  const old = span.querySelector('[data-role="value-control"]');
  const colInput = span.querySelector('[data-fieldkind="column_ref"]');
  const cols = schemaCols(lastState);
  const info = colInput ? cols[colInput.value] : null;
  const kind = info ? controlKindForType(info["type"]) : "text";
  const fresh = makeValueControl(kind, "");
  fresh.dataset.role = "value-control";
  const fieldName = old ? old.dataset.field : null;
  if (fieldName !== null) { fresh.dataset.field = fieldName; }
  if (old) { old.replaceWith(fresh); }
}
function renderInputs() {
  const sel = document.getElementById("action-select");
  const span = document.getElementById("action-inputs");
  span.innerHTML = "";
  if (!sel.value) { return; }
  const fields = CONTRACT["input_schema"][sel.value] || [];
  for (const f of fields) {
    const k = classifyField(f);
    let el;
    if (k === "value") {
      el = makeValueControl("text", "");
      el.dataset.role = "value-control";
    } else {
      el = document.createElement("input");
      el.placeholder = f;
      el.dataset.kind = "text";
      if (k === "column_ref") { el.setAttribute("list", "dl-columns"); }
      if (k === "row_ref") { el.setAttribute("list", "dl-rows"); }
      if (k === "type_ref") { el.setAttribute("list", "dl-types"); }
    }
    el.dataset.field = f;
    el.dataset.fieldkind = k;
    span.appendChild(el);
  }
  const colInput = span.querySelector('[data-fieldkind="column_ref"]');
  if (colInput && span.querySelector('[data-role="value-control"]')) {
    colInput.addEventListener("input", () => { renderValueControlFor(span); });
    renderValueControlFor(span);
  }
}
function renderQueue() {
  const ol = document.getElementById("queue");
  ol.innerHTML = "";
  for (const q of queued) {
    const li = document.createElement("li");
    li.textContent = q["type"] + " " + JSON.stringify(q["payload"]);
    ol.appendChild(li);
  }
}
function persistState() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(
      {"queued": queued, "lastState": lastState, "lastEvents": lastEvents}));
  } catch (e) { /* storage 불가 환경 — 지속만 비활성, 다른 동작 불변 */ }
}
function restoreState() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) { return false; }
    const saved = JSON.parse(raw);
    if (!saved || typeof saved !== "object" || !saved["lastState"]) { return false; }
    queued = Array.isArray(saved["queued"]) ? saved["queued"] : [];
    lastState = saved["lastState"];
    lastEvents = Array.isArray(saved["lastEvents"]) ? saved["lastEvents"] : [];
    renderQueue();
    renderState(lastState, "RESTORED_SAVED_STATE");
    renderEvents(lastEvents);
    return true;
  } catch (e) { return false; }
}
async function runActions() {
  showError("");
  const targets = queued
    .map((q) => {
      const out = {};
      for (const [f, v] of Object.entries(q["payload"] || {})) {
        const k = classifyField(f);
        if (k === "row_ref") { out["row"] = v; }
        if (k === "column_ref") { out["col"] = v; }
      }
      return out;
    })
    .filter((t) => t["row"] !== undefined && t["col"] !== undefined);
  try {
    const res = await fetch("/api/interact", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({"actions": queued}),
    });
    const data = await res.json();
    if (!res.ok || data["error"]) {
      renderState(lastState, "UNCHANGED_AFTER_ERROR");
      showError("실행 거부/실패: " + (data["error"] || res.status));
      return;
    }
    prevRowsSnapshot = JSON.parse(JSON.stringify(dataRows(lastState)));
    lastState = data["final_state"];
    lastEvents = data["events"] || [];
    renderState(data["final_state"], "AFTER_ACTIONS");
    renderEvents(data["events"]);
    persistState();
    if (data["errors"] && data["errors"].length) {
      showError("action 오류 (상태는 runner 결과 그대로 표시): " + data["errors"].join(" / "));
      for (const t of targets) { markCell(t["row"], t["col"], "cell-error"); }
    }
  } catch (e) {
    // 서버가 없으면 성공처럼 보이는 대체 데이터 없이 명시적 오류만 표시한다 (RUNNER_UNAVAILABLE)
    renderState(lastState, "RUNNER_UNAVAILABLE");
    showError("interaction server에 연결할 수 없음 — python product/interaction_server.py 실행 필요");
  }
}
document.getElementById("action-select").addEventListener("change", renderInputs);
document.getElementById("queue-add").addEventListener("click", () => {
  const sel = document.getElementById("action-select");
  const payload = {};
  for (const el of document.querySelectorAll("#action-inputs [data-field]")) {
    const coerced = coerceControl(el);
    if (!coerced["ok"]) {
      showValidation(el.dataset.field + ": " + coerced["error"]);
      return;
    }
    payload[el.dataset.field] = coerced["value"];
  }
  showValidation("");
  queued.push({"type": sel.value, "payload": payload});
  renderQueue();
});
document.getElementById("run-actions").addEventListener("click", runActions);
document.getElementById("reset-actions").addEventListener("click", () => {
  queued = [];
  lastState = CONTRACT["initial_state"];
  lastEvents = [];
  prevRowsSnapshot = null;
  selectedCell = null;
  try { localStorage.removeItem(STORE_KEY); } catch (e) { /* storage 불가 환경 */ }
  renderQueue();
  renderState(CONTRACT["initial_state"], "INITIAL");
  renderEvents([]);
  showError("");
  showValidation("");
});
renderActionSelect();
if (!restoreState()) {
  renderState(CONTRACT["initial_state"], "INITIAL");
  renderEvents([]);
}
</script></body></html>
"""
    return head + script.replace("__CONTRACT_JSON__", contract_json)


_SERVER_SOURCE = '''# generic interaction bridge — POST /api/interact를 runner subprocess로 실행한다 (mock 없음).
import json
import subprocess
import sys
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = ROOT / "product" / "interaction" / "contract.json"

# 이슈 #13: client 검증만 신뢰하지 않는다 — 서버가 contract input_types로 재검증한다.
MAX_BODY_BYTES = 1_000_000
MAX_DEPTH = 16
FORBIDDEN_KEYS = ("__proto__", "prototype", "constructor")


def _kind_of(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "unsupported"


def _structural_problems(value, depth, path, problems):
    if depth > MAX_DEPTH:
        problems.append("EXCESSIVE_NESTING: %s 깊이 %d 초과" % (path, MAX_DEPTH))
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            _structural_problems(item, depth + 1, "%s[%d]" % (path, i), problems)
    elif isinstance(value, dict):
        for key in value:
            if key in FORBIDDEN_KEYS:
                problems.append("FORBIDDEN_KEY: %s.%s" % (path, key))
                continue
            _structural_problems(value[key], depth + 1, "%s.%s" % (path, key), problems)


def _check_desc(value, desc, path, problems):
    kinds = (desc or {}).get("kinds") or []
    if not kinds:
        return
    kind = _kind_of(value)
    if kind not in kinds:
        # schema가 object/array를 요구하는데 문자열이 오면 자동 parse 없이 거부한다 (fail closed)
        problems.append("TYPE_MISMATCH: %s = %s (기대: %s)" % (path, kind, "|".join(kinds)))
        return
    if kind == "object" and desc.get("fields"):
        for key in sorted(value):
            if key in desc["fields"]:
                _check_desc(value[key], desc["fields"][key], "%s.%s" % (path, key), problems)
    if kind == "array" and desc.get("items"):
        for i, item in enumerate(value):
            sub = []
            _check_desc(item, desc["items"], "%s[%d]" % (path, i), sub)
            problems.extend(p.replace("TYPE_MISMATCH", "INVALID_ARRAY_ITEM") for p in sub)


def validate_actions(contract, actions):
    """request actions를 contract 선언(input_schema)과 관측 타입(input_types)으로 재검증한다."""
    problems = []
    if not isinstance(actions, list):
        return ["TYPE_MISMATCH: actions가 array가 아님"]
    input_schema = contract.get("input_schema") or {}
    input_types = contract.get("input_types") or {}
    for i, action in enumerate(actions):
        path = "actions[%d]" % i
        if not isinstance(action, dict):
            problems.append("TYPE_MISMATCH: %s가 object가 아님" % path)
            continue
        payload = action.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        _structural_problems(payload, 0, path + ".payload", problems)
        name = action.get("type")
        fields = input_schema.get(name)
        if fields is None:
            continue  # 미선언 action은 runner가 기존 계약대로 거부한다
        for field in fields:
            if field not in payload:
                problems.append("MISSING_REQUIRED_FIELD: %s.payload.%s" % (path, field))
        for field, desc in sorted((input_types.get(name) or {}).items()):
            if field in payload:
                _check_desc(payload[field], desc, "%s.payload.%s" % (path, field), problems)
    return problems


def _error(handler, code, message):
    body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_POST(self):
        if self.path != "/api/interact":
            _error(self, 404, "unknown endpoint")
            return
        if not CONTRACT_PATH.is_file():
            _error(self, 500, "interaction contract missing — explicit error, no fallback")
            return
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                _error(self, 413, "PAYLOAD_TOO_LARGE: request가 %d bytes 초과" % MAX_BODY_BYTES)
                return
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            _error(self, 400, "invalid request json")
            return
        actions = payload.get("actions") or []
        validation_problems = validate_actions(contract, actions)
        if validation_problems:
            # invalid input은 runner 호출 전에 거부한다 — state 변화 0 (이슈 #13 §7.3)
            _error(self, 400, "; ".join(validation_problems[:20]))
            return
        scenario = dict(contract.get("scenario_template")
                        or {"initial_state": contract["initial_state"]})
        scenario["actions"] = actions
        fd_path = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                             encoding="utf-8") as f:
                json.dump(scenario, f, ensure_ascii=True)
                fd_path = f.name
            proc = subprocess.run(
                [sys.executable, str(Path("src") / "runner.py"), "--scenario", fd_path],
                cwd=str(ROOT), capture_output=True, text=True, timeout=60,
            )
            parsed = json.loads(proc.stdout)
        except subprocess.TimeoutExpired:
            _error(self, 500, "runner timeout")
            return
        except (json.JSONDecodeError, ValueError):
            _error(self, 500, "runner output is not json — explicit error, no fallback")
            return
        finally:
            if fd_path:
                Path(fd_path).unlink(missing_ok=True)
        body = json.dumps(parsed, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8797
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
'''


# ---------------------------------------------------------------- model-level smoke (§6.4)

def _run_runner(artifact_root: Path, scenario: dict, timeout: float) -> tuple[int, dict | None, str]:
    fd, tmp = tempfile.mkstemp(prefix="interaction_", suffix=".json")
    try:
        Path(tmp).write_text(json.dumps(scenario, ensure_ascii=True), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(Path("src") / "runner.py"), "--scenario", tmp],
            cwd=str(artifact_root), capture_output=True, text=True, timeout=timeout,
        )
        try:
            parsed = json.loads(proc.stdout)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        return proc.returncode, parsed, (proc.stderr or "")[:2000]
    except subprocess.TimeoutExpired:
        return -1, None, "runner timeout"
    finally:
        try:
            Path(tmp).unlink()
        except OSError:
            pass


def has_error_signal(parsed: dict | None) -> bool:
    if not parsed:
        return True
    if parsed.get("errors"):
        return True
    for ev in parsed.get("events") or []:
        kind = ev.get("event") if isinstance(ev, dict) and "event" in ev else \
            (ev.get("type") if isinstance(ev, dict) else ev)
        if isinstance(kind, str) and "ERROR" in kind.upper():
            return True
    return False


def structured_input_evidence(contract: dict, actions: list[dict]) -> list[dict]:
    """object/array schema field의 실제 전달 타입 evidence (이슈 #13 §9.1).

    전체 payload 대신 digest+타입만 남긴다 — 민감 값 로그 최소화."""
    types = contract.get("input_types") or {}
    out: list[dict] = []
    for action in actions:
        name = action.get("type")
        payload = action.get("payload") or {}
        for field, desc in sorted((types.get(name) or {}).items()):
            kinds = desc.get("kinds") or []
            if not ({"object", "array"} & set(kinds)) or field not in payload:
                continue
            value = payload[field]
            digest = hashlib.sha256(
                json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()[:16]
            out.append({
                "action": name, "field": field,
                "schema_kinds": list(kinds),
                "value_kind": _json_kind(value),
                "input_digest": digest,
                "type_preserved": _json_kind(value) in kinds,
            })
    return out


def run_interaction_smoke(artifact_root: Path, contract: dict, timeout: float = 60.0) -> dict:
    """browser 없이 interaction 계약을 runner로 실증한다 (§6.4).

    1) fixture의 실제 action → state 변경, 2) 필수 input이 빠진 action → 명시적 거부,
    3) action 목록 수정 → 결과 변화. 실증 못 하면 false로 남긴다 — 과장 금지."""
    fixture = first_fixture(artifact_root) or {}
    fixture_actions = [a for a in (fixture.get("actions") or [])
                       if isinstance(a, dict) and a.get("type")]
    initial = contract["initial_state"]
    exchanges: list[dict] = []
    problems: list[str] = []

    def exchange(name: str, actions: list[dict]) -> dict | None:
        scenario = dict(contract.get("scenario_template") or {"initial_state": initial})
        scenario["actions"] = actions
        code, parsed, stderr = _run_runner(artifact_root, scenario, timeout)
        entry = {"exchange": name, "actions": [a.get("type") for a in actions],
                 "exit_code": code, "parsed": parsed is not None,
                 "error_signal": has_error_signal(parsed)}
        if parsed is None:
            problems.append(f"{name}: runner 출력이 JSON이 아님 ({stderr[:200]})")
        exchanges.append(entry)
        return parsed

    state_changed = False
    revise_changed = False
    invalid_rejected = False
    first_final = None
    if not fixture_actions:
        problems.append("fixture에 실행 가능한 action이 없음 — valid exchange 실증 불가")
    else:
        valid = exchange("valid_action", fixture_actions[:1])
        if valid is not None:
            first_final = valid.get("final_state")
            state_changed = bool(first_final is not None and first_final != initial
                                 and not has_error_signal(valid))
            if not state_changed:
                problems.append("valid action이 state를 바꾸지 못함")
        # 수정 후 재실행: action 목록을 바꿔 결과가 달라지는지
        revised_actions = fixture_actions[:2] if len(fixture_actions) >= 2 \
            else fixture_actions[:1] * 2
        revised = exchange("revise_and_rerun", revised_actions)
        if revised is not None and first_final is not None:
            revise_changed = revised.get("final_state") != first_final or \
                (revised.get("events") or []) != []

    action_names = [a["name"] for a in contract["available_actions"]]
    with_input = next((a for a in contract["available_actions"] if a["input"]), None)
    if with_input is None:
        problems.append("input이 있는 action이 없어 invalid 거부를 실증할 수 없음")
    else:
        invalid = exchange("invalid_action_missing_input",
                           [{"type": with_input["name"], "payload": {}}])
        if invalid is not None:
            invalid_rejected = has_error_signal(invalid)
            if not invalid_rejected:
                problems.append("필수 input이 빠진 action이 거부되지 않음")

    # 이슈 #13 §9.3: object/array schema field가 runner로 문자열 변질돼 가면 실패다
    structured = structured_input_evidence(contract, fixture_actions)
    for entry in structured:
        if not entry["type_preserved"]:
            problems.append(
                f"structured input 타입 손실: {entry['action']}.{entry['field']} = "
                f"{entry['value_kind']} (기대: {'|'.join(entry['schema_kinds'])})")

    return {
        "interaction_kind": contract["interaction_kind"],
        "available_actions": action_names,
        "exchanges": exchanges,
        "can_create_or_modify_input": bool(fixture_actions),
        "can_execute_primary_action": state_changed,
        "state_change_observed": state_changed,
        "invalid_action_rejected": invalid_rejected,
        "revise_changes_result": revise_changed,
        "structured_input": structured,
        "problems": problems,
        "pass": state_changed and invalid_rejected and not problems,
    }


# ---------------------------------------------------------------- executor 본체 (§6)

def _roots(run_dir: Path) -> list[Path]:
    return [run_dir / name for name in ("workspace", "final_artifact")
            if (run_dir / name).is_dir()]


def run_interaction_ui(run_dir=None, run_id=None, apply: bool = False, db_conn=None,
                       timeout: float = 60.0) -> dict:
    """도메인 중립 INTERACTION_UI executor (§6). graph 도메인은 lane 라우터가 legacy adapter로 보낸다.

    반환 계약은 lane executor(_exec_apply_tool)와 동일: applied/patched_files/problems/error/ok/status."""
    result: dict = {"ok": False, "status": None, "applied": False, "patched_files": [],
                    "interaction_kind": None, "problems": [], "error": None,
                    "interaction_smoke": None}
    if run_dir is None:
        result["status"] = "PRECONDITION_NO_TARGET"
        result["error"] = "run_dir가 필요합니다"
        return result
    run_dir = Path(run_dir)
    artifact_root = resolve_artifact_root(run_dir)
    if artifact_root is None or not Path(artifact_root).is_dir():
        result["status"] = "PRECONDITION_NO_ARTIFACT_ROOT"
        result["error"] = "artifact root(workspace/final_artifact) 없음 — explicit missing state"
        return result
    artifact_root = Path(artifact_root)

    kind = detect_interaction_kind(artifact_root)
    if kind == KIND_GRAPH_EDITOR:
        result["status"] = "PRECONDITION_GRAPH_DOMAIN"
        result["interaction_kind"] = kind
        result["error"] = "graph 도메인은 graph adapter(2C-2 editor)가 담당 — lane 라우터에서 분기"
        return result

    contract = build_interaction_contract(artifact_root)
    if not contract.get("supported"):
        result["status"] = "PRECONDITION_UNSUPPORTED_INTERACTION"
        result["problems"] = [f"unsupported interaction: {contract.get('reason')}"] + [
            f"missing: {m}" for m in contract.get("missing") or []]
        result["error"] = "interaction contract를 만들 수 없음 — explicit unsupported state"
        return result
    result["interaction_kind"] = contract["interaction_kind"]

    if not apply:
        result["ok"] = True
        result["status"] = "PLAN_ONLY"
        result["plan"] = {"would_write": [CONTRACT_REL, UI_REL, SERVER_REL],
                          "interaction_kind": contract["interaction_kind"],
                          "available_actions": [a["name"] for a in contract["available_actions"]]}
        return result

    ui_html = generate_interaction_ui(contract)
    roots = _roots(run_dir)
    # lane allowed scope(product/)와 같은 artifact-root 상대 경로로 보고한다
    patched = [CONTRACT_REL, UI_REL, SERVER_REL]
    for root in roots:
        for rel, text in ((CONTRACT_REL, _dump(contract) + "\n"), (UI_REL, ui_html),
                          (SERVER_REL, _SERVER_SOURCE)):
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    result["patched_files"] = patched
    result["roots_written"] = [r.name for r in roots]
    result["applied"] = True

    smoke = run_interaction_smoke(artifact_root, contract, timeout=timeout)
    result["interaction_smoke"] = smoke
    result["problems"] = list(smoke["problems"])

    out_dir = run_dir / INTERACTION_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / EVIDENCE_JSON).write_text(_dump({
        "interaction_kind": contract["interaction_kind"],
        "exchanges": smoke["exchanges"],
        "state_change_observed": smoke["state_change_observed"],
        "invalid_action_rejected": smoke["invalid_action_rejected"],
        "revise_changes_result": smoke["revise_changes_result"],
    }) + "\n", encoding="utf-8")
    report = {
        "applied": True,
        "interaction_kind": contract["interaction_kind"],
        "patched_files": patched,
        "interaction_smoke": smoke,
        "smoke_pass": smoke["pass"],
        "problems": smoke["problems"],
    }
    (out_dir / REPORT_JSON).write_text(_dump(report) + "\n", encoding="utf-8")

    result["ok"] = smoke["pass"]
    result["status"] = "APPLIED" if smoke["pass"] else "APPLIED_SMOKE_FAILED"
    if not smoke["pass"] and not result["error"]:
        result["error"] = "; ".join(smoke["problems"]) or "interaction smoke 실증 실패"
    return result
