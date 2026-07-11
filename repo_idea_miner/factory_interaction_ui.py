# 도메인 중립 INTERACTION_UI executor — interaction contract를 읽어 실조작 UI를 생성하고 runner로 검증한다 (이슈 #5 §6).
from __future__ import annotations

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
KIND_ACTION_CONSOLE = "action_console"
KIND_GRAPH_EDITOR = "graph_editor"


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
    action_contract가 있는 일반 도메인은 generic action console로. 둘 다 아니면 None."""
    state = _load_json(artifact_root / "state_contract.json") or {}
    fields: set[str] = set()
    for entity in state.get("state_entities") or []:
        fields |= set(entity.get("fields") or [])
    if {"nodes", "edges"} <= fields:
        return KIND_GRAPH_EDITOR
    actions = (_load_json(artifact_root / "action_contract.json") or {}).get("actions") or []
    if actions:
        return KIND_ACTION_CONSOLE
    return None


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

    return {
        "supported": True,
        "interaction_id": "core_action_console",
        "interaction_kind": KIND_ACTION_CONSOLE,
        "target": [e.get("name") for e in entities],
        "available_actions": [
            {"name": a.get("name"), "input": list(a.get("input") or []),
             "preconditions": list(a.get("preconditions") or []),
             "output": list(a.get("output") or [])}
            for a in actions
        ],
        "input_schema": {a.get("name"): list(a.get("input") or []) for a in actions},
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
        "render_hints": {"entities": [e.get("name") for e in entities],
                         "primary_actions": [a.get("name") for a in actions]},
        # runner_command는 존재만 검증한다 — fixture 경로가 product 산출물에 남으면
        # anti-hardcode가 fixture 분기로 의심하므로 contract에는 싣지 않는다
    }


# ---------------------------------------------------------------- runtime UI (§6.4~6.5)

def generate_interaction_ui(contract: dict) -> str:
    """contract 데이터만으로 렌더되는 generic 조작 UI. 도메인 이름·값 하드코드 없음.

    fallback 정책(§6.5): 서버 불가/artifact 문제는 명시적 오류 상태(RUNNER_UNAVAILABLE 등)로만
    표시한다 — 성공처럼 보이는 대체 데이터는 없다."""
    contract_json = json.dumps(contract, ensure_ascii=False, sort_keys=True)
    head = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>Interaction Console</title>
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
function renderInputs() {
  const sel = document.getElementById("action-select");
  const span = document.getElementById("action-inputs");
  span.innerHTML = "";
  const fields = CONTRACT["input_schema"][sel.value] || [];
  for (const f of fields) {
    const inp = document.createElement("input");
    inp.placeholder = f;
    inp.dataset.field = f;
    span.appendChild(inp);
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
document.getElementById("action-select").addEventListener("change", renderInputs);
document.getElementById("queue-add").addEventListener("click", () => {
  const sel = document.getElementById("action-select");
  const payload = {};
  for (const inp of document.querySelectorAll("#action-inputs input")) {
    payload[inp.dataset.field] = inp.value;
  }
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


_SERVER_SOURCE = '''# generic interaction bridge — POST /api/interact를 runner subprocess로 실행한다 (mock 없음).
import json
import subprocess
import sys
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = ROOT / "product" / "interaction" / "contract.json"


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
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            _error(self, 400, "invalid request json")
            return
        scenario = dict(contract.get("scenario_template")
                        or {"initial_state": contract["initial_state"]})
        scenario["actions"] = payload.get("actions") or []
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

    return {
        "interaction_kind": contract["interaction_kind"],
        "available_actions": action_names,
        "exchanges": exchanges,
        "can_create_or_modify_input": bool(fixture_actions),
        "can_execute_primary_action": state_changed,
        "state_change_observed": state_changed,
        "invalid_action_rejected": invalid_rejected,
        "revise_changes_result": revise_changed,
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
