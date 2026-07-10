# Phase 2C-3: #47 draft editor의 초안을 실제 runner로 실행하는 runner-backed draft execution 모듈.
from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from repo_idea_miner.factory_product_editor import (
    EditorGraphModel,
    check_js_syntax,
    extract_supported_node_types,
)
from repo_idea_miner.factory_review import (
    _find_product_viewer,
    _first_replay_file,
    _load_json,
    _sha256,
    _write_json,
    _write_text,
    build_fitness,
    read_gate_context,
    smoke_review,
)

# ---------------------------------------------------------------- 상수 (auto_order §4, §5, §8)

EXEC_SUBDIR = "review/phase2c3"
ADAPTER_REL = "src/adapters/draft_to_runner_input.py"
BRIDGE_REL = "product/draft_server.py"
DEFAULT_BRIDGE_PORT = 8799

# review/phase2c3/ 아래 필수 산출물
REQUIRED_OUTPUTS = (
    "phase2c3_execution_plan.json", "phase2c3_execution_plan.md",
    "phase2c3_execution_report.json", "phase2c3_execution_report.md",
    "phase2c3_diff_summary.json",
    "phase2c3_hash_before.json", "phase2c3_hash_after.json", "phase2c3_hash_check.json",
    "adapter_check.json", "execution_smoke.json", "execution_smoke.md",
    "viewer_js_syntax_check.json", "viewer_static_dom_check.json",
    "viewer_handler_binding_check.json", "viewer_smoke_after_execution.json",
    "product_fitness_report_after_execution.json", "product_fitness_report_after_execution.md",
    "phase2c3_dashboard_summary.json",
)

# 보호 대상 (auto_order §5) — product/와 src/adapters/만 수정 허용.
_PROTECTED_CONTRACTS = (
    "core_contract.json", "state_contract.json", "action_contract.json", "runner_contract.json",
)
_PROTECTED_DIR_PREFIXES = ("golden/", "fixtures/", "replay/", "src/core/")
_PROTECTED_FILES = ("src/runner.py",)
_PROTECTED_ROOTS = ("workspace", "final_artifact")
_PROTECTED_REVIEW_DIRS = ("review/phase2c0", "review/phase2c1", "review/phase2c2")

# 허용 변경 범위 (auto_order §4)
ALLOWED_SCOPE_PREFIXES = (
    "final_artifact/product/", "workspace/product/",
    "final_artifact/src/adapters/", "workspace/src/adapters/",
)

_EXEC_START = "<!-- PHASE2C3_EXEC_START -->"
_EXEC_END = "<!-- PHASE2C3_EXEC_END -->"
_EDITOR_END_MARKER = "<!-- PHASE2C2_EDITOR_END -->"

# ---------------------------------------------------------------- 어댑터 소스 (artifact에 파일로 기록)
# draft(nodes/edges) → runner 시나리오 JSON. 독립 실행 가능해야 하므로 repo 의존 없음.

ADAPTER_SOURCE = '''# 에디터 draft(nodes/edges)를 runner가 실행 가능한 시나리오 JSON으로 변환하는 어댑터.


def draft_to_scenario(draft, input_value=10):
    """draft {nodes[], edges[]} -> {ok, problems, scenario}.

    - add_node: draft node 순서 그대로 (결정적)
    - add_edge: target별 들어오는 순서대로 target_port 0,1,2... (SUM 등 다입력 노드 지원)
    - execute_graph: 들어오는 edge가 없는 노드 전부에 [input_value] 주입
    """
    problems = []
    if not isinstance(input_value, (int, float)) or isinstance(input_value, bool):
        problems.append("input_value must be a number")
    nodes = list((draft or {}).get("nodes") or [])
    edges = list((draft or {}).get("edges") or [])
    if not nodes:
        problems.append("draft has no nodes")
    ids = []
    for n in nodes:
        nid = n.get("id")
        ntype = n.get("type")
        if nid is None:
            problems.append("node missing id")
        elif nid in ids:
            problems.append("duplicate node id: %s" % nid)
        else:
            ids.append(nid)
        if not ntype:
            problems.append("node missing type: %s" % nid)
    id_set = set(ids)
    for e in edges:
        if "from" in e or "to" in e:
            problems.append("edge uses from/to (source_id/target_id required)")
        src = e.get("source_id")
        tgt = e.get("target_id")
        if src not in id_set:
            problems.append("edge source_id does not reference a node: %s" % src)
        if tgt not in id_set:
            problems.append("edge target_id does not reference a node: %s" % tgt)
        if src is not None and src == tgt:
            problems.append("self-loop edge: %s" % src)
    if problems:
        return {"ok": False, "problems": problems, "scenario": None}

    actions = []
    for n in nodes:
        actions.append({"type": "add_node",
                        "payload": {"id": n["id"], "type": n["type"]}})
    port_counter = {}
    for e in edges:
        tp = port_counter.get(e["target_id"], 0)
        port_counter[e["target_id"]] = tp + 1
        actions.append({"type": "add_edge", "payload": {
            "source_id": e["source_id"], "source_port": 0,
            "target_id": e["target_id"], "target_port": tp,
        }})
    has_incoming = set(port_counter)
    initial_inputs = {nid: [input_value] for nid in ids if nid not in has_incoming}
    actions.append({"type": "execute_graph",
                    "payload": {"initial_inputs": initial_inputs}})
    scenario = {
        "id": "draft_scenario",
        "title": "phase2c3 draft execution",
        "case_type": "draft",
        "actions": actions,
        "metadata": {"source": "phase2c3_draft_adapter", "input_value": input_value},
    }
    return {"ok": True, "problems": [], "scenario": scenario}
'''

# ---------------------------------------------------------------- 브리지 서버 소스 (artifact에 파일로 기록)
# 정적 서빙 + POST /api/execute-draft. 원본 replay/golden은 절대 쓰지 않는다.

BRIDGE_SOURCE = '''# 초안(draft)을 runner로 실제 실행해 결과를 돌려주는 로컬 브리지 서버 (정적 서빙 + POST /api/execute-draft).
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ARTIFACT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADAPTER_PATH = os.path.join(ARTIFACT_ROOT, "src", "adapters", "draft_to_runner_input.py")


def _load_adapter():
    spec = importlib.util.spec_from_file_location("draft_to_runner_input", ADAPTER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def execute_draft(draft, input_value=10, timeout=30):
    """draft를 시나리오로 변환해 runner subprocess로 실행하고 결과 JSON을 돌려준다."""
    try:
        adapter = _load_adapter()
    except Exception as exc:
        return {"ok": False, "stage": "adapter_load", "errors": [str(exc)]}
    conv = adapter.draft_to_scenario(draft, input_value=input_value)
    if not conv["ok"]:
        return {"ok": False, "stage": "adapter", "errors": conv["problems"]}
    fd, tmp = tempfile.mkstemp(prefix="draft_scenario_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(conv["scenario"], f, ensure_ascii=True)
        proc = subprocess.run(
            [sys.executable, os.path.join("src", "runner.py"), "--scenario", tmp],
            cwd=ARTIFACT_ROOT, capture_output=True, text=True, timeout=timeout,
        )
        try:
            result = json.loads(proc.stdout)
        except (json.JSONDecodeError, ValueError):
            return {"ok": False, "stage": "runner", "exit_code": proc.returncode,
                    "errors": ["runner output is not JSON"],
                    "stderr": (proc.stderr or "")[:2000]}
        return {"ok": bool(result.get("ok")) and proc.returncode == 0,
                "stage": "runner", "exit_code": proc.returncode,
                "action_count": len(conv["scenario"]["actions"]),
                "result": result}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stage": "runner", "errors": ["runner timeout"]}
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


class DraftHandler(SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path.rstrip("/") != "/api/execute-draft":
            self.send_error(404, "unknown endpoint")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._respond({"ok": False, "stage": "request", "errors": ["invalid JSON body"]})
            return
        out = execute_draft(body.get("draft") or {}, body.get("input_value", 10))
        self._respond(out)

    def _respond(self, obj):
        data = json.dumps(obj, ensure_ascii=True).encode("ascii")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        sys.stderr.write("[draft_server] %s\\n" % (fmt % args))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    handler = partial(DraftHandler, directory=ARTIFACT_ROOT)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(json.dumps({"serving": ARTIFACT_ROOT, "host": args.host, "port": args.port},
                     ensure_ascii=True), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
'''

# ---------------------------------------------------------------- viewer 주입 블록
# 주의: edge.from/edge.to/ev.type/.type/node.x/node.y/Math.random/Date.now 금지 (§17 mismatch 재도입 방지).
# node type 접근은 bracket 표기 nd["type"] 로만 한다.

_EXEC_BLOCK = r"""
<!-- PHASE2C3_EXEC_START -->
<div id="p2c3-exec" style="border:1px solid #888; border-radius:6px; margin:10px; padding:10px;">
  <h4 style="margin:4px 0;">Draft 실행 (runner-backed · Phase 2C-3)</h4>
  <div>
    <label>시작값(입력 노드) <input id="p2c3-input-value" type="number" value="10" style="width:70px;"></label>
    <button data-action="execute-draft" onclick="p2c3Execute()">Execute Draft (runner)</button>
  </div>
  <div id="p2c3-exec-status" style="margin:6px 0; white-space:pre-wrap;">아직 실행하지 않음 — Editor에서 draft를 만들고 Execute를 누르세요.</div>
  <div id="p2c3-exec-result"></div>
</div>
<script>
// Phase 2C-3 runner-backed draft execution — 결과는 화면 표시 전용 (원본 replay 미변경)
function p2c3Status(msg, cls) {
    var el = document.getElementById("p2c3-exec-status");
    if (el) {
        el.textContent = msg;
        el.style.color = cls === "err" ? "#c0392b" : "#1e8449";
    }
}

function p2c3RenderResult(res) {
    var result = res.result || {};
    var fs = result.final_state || {};
    var nodes = fs.nodes || {};
    var order = fs.execution_order || Object.keys(nodes);
    var rows = order.map(function (id) {
        var nd = nodes[id] || {};
        var outs = (nd["output_values"] || []).join(", ");
        return '<div style="border-bottom:1px dashed #ccc; padding:2px 0;"><b>' + id + '</b>'
            + ' [' + nd["type"] + '] status=' + nd["status"] + ' output=[' + outs + ']</div>';
    }).join("");
    var evCount = (result.events || []).length;
    var errList = result.errors || [];
    var errHtml = errList.length
        ? '<div style="color:#c0392b;">errors: ' + errList.join("; ") + '</div>' : "";
    var el = document.getElementById("p2c3-exec-result");
    if (el) {
        el.innerHTML = '<div><b>summary:</b> ' + (result.summary || "") + '</div>'
            + '<div><b>events:</b> ' + evCount + '</div>' + errHtml + rows;
    }
}

async function p2c3Execute() {
    var draft;
    try {
        draft = p2c2BuildDraft();
    } catch (e) {
        p2c3Status("draft 없음 — Editor 모드를 먼저 여세요. (" + e.message + ")", "err");
        return;
    }
    var v = p2c2ValidateGraph();
    if (!v.valid) {
        p2c3Status("draft가 유효하지 않아 실행 중단:\n- " + v.errors.join("\n- "), "err");
        return;
    }
    var ivEl = document.getElementById("p2c3-input-value");
    var iv = ivEl ? Number(ivEl.value) : 10;
    if (!isFinite(iv)) { iv = 10; }
    p2c3Status("runner 실행 중...", "ok");
    try {
        var r = await fetch("/api/execute-draft", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ draft: draft, input_value: iv })
        });
        var res = await r.json();
        if (!res.ok) {
            p2c3Status("실행 실패 (" + (res.stage || "?") + "): "
                + ((res.errors || []).join("; ") || ""), "err");
            if (res.result) { p2c3RenderResult(res); }
            return;
        }
        p2c3Status("실행 완료 (runner exit " + res.exit_code
            + "). 값이나 그래프를 바꾸고 다시 실행해 보세요 (revise).", "ok");
        p2c3RenderResult(res);
    } catch (e) {
        p2c3Status("실행 서버에 연결하지 못했습니다. 아티팩트 루트에서 "
            + "`python product/draft_server.py --port 8799` 실행 후 "
            + "http://127.0.0.1:8799/product/viewer/index.html 로 접속하세요. ("
            + e.message + ")", "err");
    }
}
</script>
<!-- PHASE2C3_EXEC_END -->
"""


# ---------------------------------------------------------------- viewer 주입

def inject_execution_panel(viewer_path: Path) -> bool:
    """2C-2 editor 블록 바로 뒤에 실행 패널을 주입한다 (idempotent, 문자열 기반 — 백슬래시 안전)."""
    text = viewer_path.read_text(encoding="utf-8", errors="replace")
    # 이전 주입 제거 (재적용 안전) — 문자열 인덱스 기반, re.sub 치환 문자열 미사용
    while True:
        s = text.find(_EXEC_START)
        e = text.find(_EXEC_END)
        if s < 0 or e < 0:
            break
        text = text[:s] + text[e + len(_EXEC_END):]
    anchor = text.find(_EDITOR_END_MARKER)
    if anchor < 0:
        return False
    pos = anchor + len(_EDITOR_END_MARKER)
    new_text = text[:pos] + _EXEC_BLOCK + text[pos:]
    viewer_path.write_text(new_text, encoding="utf-8")
    return True


# ---------------------------------------------------------------- static DOM + handler binding

_DOM_CONTROLS = (
    ("execute_button", r'data-action="execute-draft"', "execute-draft", "p2c3Execute"),
    ("input_value_field", r'id="p2c3-input-value"', "execute-draft", "p2c3Execute"),
    ("exec_status_panel", r'id="p2c3-exec-status"', "execute-draft", "p2c3Status"),
    ("exec_result_panel", r'id="p2c3-exec-result"', "execute-draft", "p2c3RenderResult"),
)


def check_static_dom(html: str) -> dict:
    present = {}
    missing = []
    for name, id_re, _action, _fn in _DOM_CONTROLS:
        ok = bool(re.search(id_re, html))
        present[name] = ok
        if not ok:
            missing.append(name)
    # 실행 API wiring + editor draft 연동 근거
    present["exec_api_wiring"] = "/api/execute-draft" in html
    present["editor_draft_integration"] = "p2c2BuildDraft()" in html
    for name in ("exec_api_wiring", "editor_draft_integration"):
        if not present[name]:
            missing.append(name)
    return {"status": "PASS" if not missing else "FAIL", "present": present, "missing": missing}


def check_handler_binding(html: str) -> dict:
    bindings = {}
    missing = []
    for name, _id_re, action, fn in _DOM_CONTROLS:
        has_action = bool(re.search(r'data-action="' + re.escape(action) + r'"', html))
        has_onclick = bool(re.search(r'onclick="p2c3Execute\(', html))
        has_fn = bool(re.search(r'function\s+' + re.escape(fn) + r'\b', html))
        ok = (has_action or has_onclick) and has_fn
        bindings[name] = {"data_action": has_action, "onclick": has_onclick,
                          "handler_defined": has_fn, "ok": ok}
        if not ok:
            missing.append(name)
    return {"status": "PASS" if not missing else "FAIL", "bindings": bindings, "missing": missing}


# ---------------------------------------------------------------- 보호 hash (auto_order §5)

def compute_execution_protected_hashes(run_dir: Path) -> dict[str, str]:
    """golden/fixtures/replay/src\\/core/runner.py/contract + review/phase2c0·2c1·2c2 보호.

    product/와 src/adapters/는 수정 허용이므로 제외.
    """
    run_dir = Path(run_dir)
    out: dict[str, str] = {}
    for root_name in _PROTECTED_ROOTS:
        base = run_dir / root_name
        if not base.is_dir():
            continue
        for rel in _PROTECTED_CONTRACTS + _PROTECTED_FILES:
            p = base / rel
            if p.is_file():
                out[f"{root_name}/{rel}"] = _sha256(p)
        for prefix in _PROTECTED_DIR_PREFIXES:
            d = base / prefix.rstrip("/")
            if not d.is_dir():
                continue
            for p in sorted(d.rglob("*")):
                if p.is_file() and "__pycache__" not in p.parts:
                    out[f"{root_name}/{p.relative_to(base).as_posix()}"] = _sha256(p)
    orr = run_dir / "oracle_risk_report.json"
    if orr.is_file():
        out["oracle_risk_report.json"] = _sha256(orr)
    for rev in _PROTECTED_REVIEW_DIRS:
        d = run_dir / rev
        if d.is_dir():
            for p in sorted(d.rglob("*")):
                if p.is_file() and "__pycache__" not in p.parts:
                    out[f"{rev}/{p.relative_to(d).as_posix()}"] = _sha256(p)
    return out


def _compare(before: dict, after: dict) -> dict:
    changed = sorted(k for k in before if k in after and before[k] != after[k])
    removed = sorted(k for k in before if k not in after)
    added = sorted(k for k in after if k not in before)
    return {"status": "PASS" if not (changed or removed or added) else "FAIL",
            "files_checked": len(before), "changed": changed, "added": added, "removed": removed}


# ---------------------------------------------------------------- 실행 스모크 (edit→validate→execute→result→revise)

def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _load_adapter_module(adapter_path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("p2c3_adapter_smoke", adapter_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_runner(artifact_root: Path, scenario: dict, timeout: float) -> tuple[int, dict | None, str]:
    fd, tmp = tempfile.mkstemp(prefix="p2c3_scenario_", suffix=".json")
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
    finally:
        try:
            Path(tmp).unlink()
        except OSError:
            pass


def _hash_dir(base: Path) -> dict[str, str]:
    if not base.is_dir():
        return {}
    return {p.relative_to(base).as_posix(): _sha256(p)
            for p in sorted(base.rglob("*")) if p.is_file()}


def run_execution_smoke(run_dir: Path, timeout: float = 60.0) -> dict:
    """final_artifact temp copy에서 edit→validate→execute→result→revise 전체 사이클을 실증한다.

    원본은 절대 건드리지 않는다. 브리지 서버(POST /api/execute-draft)도 실제로 띄워 검증한다.
    """
    final_dir = Path(run_dir) / "final_artifact"
    out: dict = {
        "steps": [], "failures": [],
        "adapter_ok": False, "runner_execution_ok": False, "runner_exit_code": None,
        "result_reflects_edit": False, "revise_cycle_changes_result": False,
        "bridge_server_ok": False, "viewer_served_ok": False,
        "original_replay_unchanged": False,
        "can_execute_input": False, "can_see_result_from_created_input": False,
        "product_loop_closed": False, "execution_smoke_pass": False,
        "added_node_id": None, "edited_draft_nodes": None,
    }

    def rec(name: str, ok: bool, detail: str = ""):
        out["steps"].append({"step": name, "ok": bool(ok), "detail": detail})
        if not ok:
            out["failures"].append(f"{name}: {detail}")

    tmp = Path(tempfile.mkdtemp(prefix="phase2c3_smoke_"))
    try:
        tmp_final = tmp / "final_artifact"
        shutil.copytree(final_dir, tmp_final,
                        ignore=shutil.ignore_patterns("__pycache__"))
        rec("copy_artifact_to_temp", True, str(tmp_final))

        replay_hash_before = _hash_dir(tmp_final / "replay")

        # ---- Edit: replay 로드 → 노드/엣지 추가 (2C-2 모델 재사용)
        supported, _src = extract_supported_node_types(tmp_final)
        _rf, replay = _first_replay_file(tmp_final)
        if not supported or not replay:
            rec("load_replay_and_types", False,
                f"supported={len(supported)} replay={'yes' if replay else 'no'}")
            return out
        model = EditorGraphModel(supported)
        model.load_from_replay(replay)
        base_count = len(model.nodes)
        add = model.add_node("smoke node", supported[0])
        rec("edit_add_node", add.get("ok", False), str(add))
        if not add.get("ok"):
            return out
        new_id = add["id"]
        out["added_node_id"] = new_id
        first_existing = next((n["id"] for n in model.nodes if n["id"] != new_id), None)
        edge = model.add_edge(first_existing, new_id)
        rec("edit_add_edge", edge.get("ok", False), f"{first_existing} -> {new_id}")

        # ---- Validate
        val = model.validate()
        rec("validate_draft", val["valid"], "; ".join(val["errors"]))
        if not val["valid"]:
            return out
        draft = model.build_draft(str(run_dir), None)
        out["edited_draft_nodes"] = len(draft["nodes"])

        # ---- Adapter
        adapter_path = tmp_final / ADAPTER_REL
        if not adapter_path.is_file():
            rec("adapter_exists", False, str(adapter_path))
            return out
        try:
            adapter = _load_adapter_module(adapter_path)
            conv = adapter.draft_to_scenario(draft, input_value=10)
        except Exception as exc:  # noqa: BLE001 — 스모크 실패는 판정에 기록
            rec("adapter_transform", False, str(exc))
            return out
        rec("adapter_transform", conv["ok"], "; ".join(conv["problems"]))
        out["adapter_ok"] = conv["ok"]
        if not conv["ok"]:
            return out

        # ---- Execute (runner subprocess)
        exit1, res1, err1 = _run_runner(tmp_final, conv["scenario"], timeout)
        out["runner_exit_code"] = exit1
        ok1 = exit1 == 0 and isinstance(res1, dict) and bool(res1.get("ok"))
        rec("runner_execute", ok1, f"exit={exit1} stderr={err1[:200]}")
        out["runner_execution_ok"] = ok1
        if not ok1:
            return out

        # ---- Result reflects edit: 추가한 노드가 결과에 존재 + 완료 상태
        nodes1 = ((res1.get("final_state") or {}).get("nodes")) or {}
        new_node = nodes1.get(new_id) or {}
        reflects = (new_id in nodes1
                    and new_node.get("status") == "COMPLETED"
                    and len(nodes1) == len(draft["nodes"])
                    and len(nodes1) == base_count + 1)
        rec("result_reflects_edit", reflects,
            f"added={new_id in nodes1} status={new_node.get('status')} "
            f"nodes={len(nodes1)}/{len(draft['nodes'])}")
        out["result_reflects_edit"] = reflects

        # ---- Revise: 입력값 10→20 재실행 → 결과가 실제로 달라져야 함 (연쇄 갱신 증거)
        conv2 = adapter.draft_to_scenario(draft, input_value=20)
        exit2, res2, _err2 = _run_runner(tmp_final, conv2["scenario"], timeout)
        outputs1 = {nid: (nd or {}).get("output_values")
                    for nid, nd in nodes1.items()}
        nodes2 = ((res2 or {}).get("final_state") or {}).get("nodes") or {}
        outputs2 = {nid: (nd or {}).get("output_values")
                    for nid, nd in nodes2.items()}
        revise_ok = exit2 == 0 and bool(nodes2) and outputs1 != outputs2
        rec("revise_rerun_changes_result", revise_ok,
            f"exit={exit2} outputs_changed={outputs1 != outputs2}")
        out["revise_cycle_changes_result"] = revise_ok

        # ---- Bridge server: 실제 HTTP로 draft 실행 + viewer 정적 서빙
        bridge_path = tmp_final / BRIDGE_REL
        if not bridge_path.is_file():
            rec("bridge_exists", False, str(bridge_path))
        else:
            port = _free_port()
            proc = subprocess.Popen(
                [sys.executable, str(bridge_path), "--port", str(port)],
                cwd=str(tmp_final), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            try:
                base_url = f"http://127.0.0.1:{port}"
                ready = False
                for _ in range(50):
                    if proc.poll() is not None:
                        break
                    try:
                        with urllib.request.urlopen(f"{base_url}/replay/index.json",
                                                    timeout=1) as r:
                            if r.status == 200:
                                ready = True
                                break
                    except OSError:
                        time.sleep(0.2)
                rec("bridge_server_ready", ready, f"port={port}")
                if ready:
                    viewer_rel = "product/viewer/index.html"
                    viewer_err = ""
                    try:
                        with urllib.request.urlopen(f"{base_url}/{viewer_rel}",
                                                    timeout=5) as r:
                            out["viewer_served_ok"] = r.status == 200
                    except OSError as exc:
                        viewer_err = str(exc)
                    rec("bridge_serves_viewer", out["viewer_served_ok"],
                        viewer_err or viewer_rel)
                    req = urllib.request.Request(
                        f"{base_url}/api/execute-draft",
                        data=json.dumps({"draft": draft, "input_value": 10},
                                        ensure_ascii=True).encode("ascii"),
                        headers={"Content-Type": "application/json"}, method="POST")
                    try:
                        with urllib.request.urlopen(req, timeout=timeout) as r:
                            bridge_res = json.loads(r.read().decode("utf-8"))
                    except OSError as exc:
                        bridge_res = {"ok": False, "errors": [str(exc)]}
                    bridge_nodes = (((bridge_res.get("result") or {})
                                     .get("final_state") or {}).get("nodes")) or {}
                    bridge_ok = (bool(bridge_res.get("ok"))
                                 and new_id in bridge_nodes
                                 and (bridge_res.get("result") or {}).get("summary")
                                 == res1.get("summary"))
                    rec("bridge_execute_draft", bridge_ok,
                        f"ok={bridge_res.get('ok')} stage={bridge_res.get('stage')} "
                        f"summary_match={(bridge_res.get('result') or {}).get('summary') == res1.get('summary')}")
                    out["bridge_server_ok"] = bridge_ok
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

        # ---- 원본 replay 불변 (temp copy 내에서도 실행이 replay를 덮어쓰지 않았는지)
        replay_hash_after = _hash_dir(tmp_final / "replay")
        unchanged = replay_hash_before == replay_hash_after
        rec("replay_unchanged_after_execution", unchanged,
            f"files={len(replay_hash_after)}")
        out["original_replay_unchanged"] = unchanged

        out["can_execute_input"] = out["adapter_ok"] and out["runner_execution_ok"]
        out["can_see_result_from_created_input"] = (
            out["bridge_server_ok"] and out["result_reflects_edit"]
            and out["viewer_served_ok"])
        out["product_loop_closed"] = (
            out["can_execute_input"] and out["can_see_result_from_created_input"]
            and out["revise_cycle_changes_result"] and out["original_replay_unchanged"])
        out["execution_smoke_pass"] = out["product_loop_closed"] and not out["failures"]
        return out
    except Exception as exc:  # noqa: BLE001 — 스모크 예외는 정직하게 실패로 기록
        rec("execution_smoke_exception", False, str(exc))
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- adapter 정적 검사

def check_adapter(final_dir: Path) -> dict:
    """어댑터 파일 존재 + 금지 사항(골든/replay 접근, 하드코딩 결과) 정적 검사."""
    p = Path(final_dir) / ADAPTER_REL
    out = {"exists": p.is_file(), "path": ADAPTER_REL, "problems": [], "status": "FAIL"}
    if not p.is_file():
        out["problems"].append("adapter 파일 없음")
        return out
    src = p.read_text(encoding="utf-8", errors="replace")
    if "draft_to_scenario" not in src:
        out["problems"].append("draft_to_scenario 함수 없음")
    for banned, why in (("golden", "golden 접근 금지"), ("replay_scenario", "replay 파일 접근 금지"),
                        ("open(", "어댑터는 파일 IO 없이 순수 변환만")):
        if banned in src:
            out["problems"].append(f"금지 패턴 '{banned}': {why}")
    out["status"] = "PASS" if not out["problems"] else "FAIL"
    return out


# ---------------------------------------------------------------- 사전 조건 (auto_order §7)

def _user_decision_ok(run_dir: Path) -> tuple[bool, str | None]:
    """user_review_decision.md에서 Phase 2C-3 진행 결정 확인."""
    for rel in ("user_review_decision.md", "review/phase2d0/user_review_decision.md",
                "review/phase2c2/user_review_decision.md"):
        p = run_dir / rel
        if p.is_file():
            txt = p.read_text(encoding="utf-8", errors="replace")
            if re.search(r"\[x\]\s*Phase\s*2C-3", txt, re.I) or "Phase 2C-3 진행" in txt:
                return True, str(rel)
    return False, None


def check_execution_preconditions(run_dir: Path, gate: dict) -> list[str]:
    """2C-2 draft editor candidate + REVIEW_READY + green_base + 사용자 승인 + 주입 앵커."""
    problems: list[str] = []
    editor_report = _load_json(run_dir / "review" / "phase2c2" / "phase2c2_editor_report.json")
    if editor_report is None:
        problems.append("Phase 2C-2 editor report 없음 (2C-2 먼저 필요)")
    elif not editor_report.get("draft_editor_candidate"):
        problems.append("2C-2 draft_editor_candidate가 true 아님")
    if gate.get("verdict") != "REVIEW_READY":
        problems.append(f"current verdict가 REVIEW_READY 아님: {gate.get('verdict')}")
    if not gate.get("green_base"):
        problems.append("green_base가 true 아님")
    ok, _src = _user_decision_ok(run_dir)
    if not ok:
        problems.append("user_review_decision.md에서 Phase 2C-3 진행 결정을 찾지 못함")
    viewer = _find_product_viewer(run_dir / "final_artifact")
    if viewer is None:
        problems.append("product viewer 없음")
    elif _EDITOR_END_MARKER not in viewer.read_text(encoding="utf-8", errors="replace"):
        problems.append("viewer에 2C-2 editor 마커 없음 (주입 앵커 부재)")
    return problems


# ---------------------------------------------------------------- fitness 마무리 (auto_order §14)

def finalize_execution_fitness(base_fitness: dict, exec_smoke: dict, ui_pass: bool,
                               js_status: str, gate: dict, hash_status: str,
                               prior_editor_report: dict | None) -> dict:
    """runner-backed 실행 실증 조건으로 PRODUCT_CANDIDATE를 보수적으로 판정한다."""
    es = exec_smoke
    conditions = {
        "adapter_ok": es["adapter_ok"],
        "runner_execution_ok": es["runner_execution_ok"],
        "result_reflects_edit": es["result_reflects_edit"],
        "revise_cycle_changes_result": es["revise_cycle_changes_result"],
        "bridge_server_ok": es["bridge_server_ok"],
        "viewer_served_ok": es["viewer_served_ok"],
        "execution_smoke_pass": es["execution_smoke_pass"],
        "product_loop_closed": es["product_loop_closed"],
        "original_replay_unchanged": es["original_replay_unchanged"],
        "execution_ui_binding_pass": ui_pass,
        "js_syntax_pass": js_status == "PASS",
        "protected_hash_pass": hash_status == "PASS",
        "prior_draft_editor_candidate": bool((prior_editor_report or {})
                                             .get("draft_editor_candidate")),
        "green_base": bool(gate.get("green_base")),
        "no_gate_fail": not gate.get("gate_fail"),
    }
    all_ok = all(conditions.values())
    rec = base_fitness["recommended_fitness"]
    if rec == "PRODUCT_CANDIDATE" and not all_ok:
        rec = "NEEDS_PRODUCT_POLISH"  # §14: 실행 실증 없이 candidate 금지 — 정직 하향
    included = es["can_execute_input"] and es["can_see_result_from_created_input"]
    limitations = [
        "실행은 로컬 브리지 서버(product/draft_server.py) 필요 — 정적 파일 서빙만으로는 실행 불가",
        "draft 실행 결과는 화면 표시 전용 — 원본 replay/golden/contract 불변",
        "입력 노드 시작값은 단일 숫자로 단순화 (노드별 개별 입력은 미지원)",
    ]
    return {
        "recommended_fitness": rec,
        "runner_backed_execution_included": bool(included),
        "product_loop_closed": bool(es["product_loop_closed"]),
        "execution_candidate_conditions": conditions,
        "all_execution_conditions_met": all_ok,
        "limitations": limitations,
    }


# ---------------------------------------------------------------- 문서 렌더링

def _plan_md(plan: dict) -> str:
    L = ["# Phase 2C-3 Runner-backed Draft Execution Plan", "",
         f"- run_dir: {plan['run_dir']} / challenge_id: {plan['challenge_id']}",
         f"- status: {plan['status']}",
         "", "## planned changes"] + [f"- {f}" for f in plan["planned_changes"]]
    L += ["", "## allowed scopes"] + [f"- {s}" for s in plan["allowed_scopes"]]
    L += ["", "## protected scopes"] + [f"- {s}" for s in plan["protected_scopes"]]
    if plan.get("blocked_reasons"):
        L += ["", "## Blocked"] + [f"- {b}" for b in plan["blocked_reasons"]]
    return "\n".join(L) + "\n"


def _smoke_md(es: dict) -> str:
    L = ["# Phase 2C-3 Execution Smoke (edit -> validate -> execute -> result -> revise)", "",
         f"- execution_smoke_pass: **{es['execution_smoke_pass']}**",
         f"- product_loop_closed: {es['product_loop_closed']}",
         f"- can_execute_input: {es['can_execute_input']}",
         f"- can_see_result_from_created_input: {es['can_see_result_from_created_input']}",
         f"- revise cycle changes result: {es['revise_cycle_changes_result']}",
         f"- original replay unchanged: {es['original_replay_unchanged']}",
         "", "## steps"]
    for s in es["steps"]:
        L.append(f"- [{'x' if s['ok'] else ' '}] {s['step']} — {s['detail']}")
    if es["failures"]:
        L += ["", "## failures"] + [f"- {f}" for f in es["failures"]]
    return "\n".join(L) + "\n"


def _report_md(report: dict) -> str:
    es = report["execution_smoke"]
    L = ["# Phase 2C-3 Runner-backed Draft Execution Report", "",
         f"- run_dir: {report['run_dir']} / challenge_id: {report['challenge_id']}",
         f"- applied: {report['applied']} / 보호 대상 hash: {report['hash_status']}",
         f"- patched files: {', '.join(report['patched_files']) or '-'}",
         "", "## execution smoke",
         f"- adapter: {es['adapter_ok']} / runner: {es['runner_execution_ok']} "
         f"(exit {es['runner_exit_code']})",
         f"- result reflects edit: {es['result_reflects_edit']} (added node {es['added_node_id']})",
         f"- revise cycle: {es['revise_cycle_changes_result']}",
         f"- bridge server: {es['bridge_server_ok']} / viewer served: {es['viewer_served_ok']}",
         f"- product loop closed: {es['product_loop_closed']}",
         "", "## product fitness after execution",
         f"- recommended_fitness: {report['recommended_fitness']}",
         f"- runner_backed_execution_included: {report['runner_backed_execution_included']}",
         f"- product_loop_closed: {report['product_loop_closed']}"]
    return "\n".join(L) + "\n"


def _fitness_md(fit: dict, base: dict) -> str:
    L = ["# Product Fitness Report (After Phase 2C-3 Execution)", "",
         f"- recommended_fitness: **{fit['recommended_fitness']}** · 평균 {base['average_score']}/5",
         f"- runner_backed_execution_included: {fit['runner_backed_execution_included']}",
         f"- product_loop_closed: {fit['product_loop_closed']}",
         "", "## 점수"]
    for c in base["criteria"]:
        L.append(f"- {c['criterion']}: {c['score']} — {c['reason']}")
    L += ["", "## limitations"] + [f"- {x}" for x in fit["limitations"]]
    L += ["", "## execution candidate 조건"]
    for k, v in fit["execution_candidate_conditions"].items():
        L.append(f"- [{'x' if v else ' '}] {k}")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- 오케스트레이터

def resolve_execution_target(run_dir=None, run_id=None, db_conn=None):
    info = {"challenge_id": None, "resolved_run_dir": None}
    if run_dir is None and run_id is not None:
        if db_conn is None:
            return None, "--run-id는 DB가 필요합니다.", info
        from repo_idea_miner.factory_db import get_product_run

        row = get_product_run(db_conn, run_id)
        if row is None:
            return None, f"run_id {run_id} 없음", info
        run_dir = Path(row["workspace_dir"]).parent
        info["challenge_id"] = row.get("challenge_id")
    if run_dir is None:
        return None, "--run-dir 또는 --run-id가 필요합니다.", info
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        return None, f"run_dir 없음: {run_dir}", info
    info["resolved_run_dir"] = str(run_dir)
    return run_dir, None, info


def _adapter_bridge_paths(run_dir: Path) -> list[tuple[Path, str]]:
    """양 루트(final_artifact/workspace)에 기록할 (경로, 종류) 목록."""
    out: list[tuple[Path, str]] = []
    for root_name in ("final_artifact", "workspace"):
        root = run_dir / root_name
        if not root.is_dir():
            continue
        out.append((root / ADAPTER_REL, "adapter"))
        if (root / "product").is_dir():
            out.append((root / BRIDGE_REL, "bridge"))
    return out


def _viewer_paths(run_dir: Path) -> list[Path]:
    out: list[Path] = []
    for root_name in ("final_artifact", "workspace"):
        prod = run_dir / root_name / "product"
        if prod.is_dir():
            out.extend(sorted(prod.rglob("*.html")))
    return out


def run_draft_execution(run_dir=None, run_id=None, apply=False, db_conn=None,
                        timeout: float = 60.0) -> dict:
    """#47 draft editor에 runner-backed 실행을 dry-run/apply한다 (auto_order 기반).

    core/golden/fixtures/contract/replay/phase2c0·2c1·2c2 미변경, product/+src/adapters/만 수정.
    """
    result: dict = {
        "ok": False, "status": None, "resolved_run_dir": None, "challenge_id": None,
        "applied": False, "patched_files": [], "hash_status": None,
        "recommended_fitness": None, "review_dir": None, "problems": [], "error": None,
    }
    tgt, err, info = resolve_execution_target(run_dir, run_id, db_conn)
    result["resolved_run_dir"] = info.get("resolved_run_dir")
    if err:
        result["error"] = err
        return result
    run_dir = tgt
    review_dir = run_dir / EXEC_SUBDIR
    result["review_dir"] = review_dir.as_posix()
    final_dir = run_dir / "final_artifact"

    gate = read_gate_context(run_dir)
    result["challenge_id"] = info.get("challenge_id") or _challenge_id(run_dir)
    problems = check_execution_preconditions(run_dir, gate)

    plan = {
        "run_dir": f"runs/{run_dir.name}", "challenge_id": result["challenge_id"],
        "planned_changes": [
            f"{ADAPTER_REL} — draft를 runner 시나리오로 변환하는 어댑터 (신규)",
            f"{BRIDGE_REL} — 정적 서빙 + POST /api/execute-draft 브리지 서버 (신규)",
            "product viewer — Execute Draft 패널 주입 (2C-2 editor 블록 뒤, idempotent)",
        ],
        "allowed_scopes": list(ALLOWED_SCOPE_PREFIXES),
        "protected_scopes": [f"{r}/{p}" for r in _PROTECTED_ROOTS
                             for p in _PROTECTED_DIR_PREFIXES + _PROTECTED_CONTRACTS
                             + _PROTECTED_FILES] + list(_PROTECTED_REVIEW_DIRS),
        "blocked_reasons": problems,
        "status": "DRY_RUN_BLOCKED" if problems else "DRY_RUN_PASS",
    }
    _write_json(review_dir / "phase2c3_execution_plan.json", plan)
    _write_text(review_dir / "phase2c3_execution_plan.md", _plan_md(plan))

    if not apply:
        result["ok"] = not problems
        result["status"] = plan["status"]
        result["plan"] = plan
        result["problems"] = problems
        if problems:
            result["error"] = "; ".join(problems)
        return result

    if problems:
        result["status"] = "CANNOT_EXECUTE"
        result["problems"] = problems
        result["error"] = "; ".join(problems)
        return result

    # ---- Apply
    hash_before = compute_execution_protected_hashes(run_dir)
    _write_json(review_dir / "phase2c3_hash_before.json", hash_before)

    patched: list[str] = []
    for path, kind in _adapter_bridge_paths(run_dir):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(ADAPTER_SOURCE if kind == "adapter" else BRIDGE_SOURCE,
                        encoding="utf-8")
        patched.append(path.relative_to(run_dir).as_posix())
    for vp in _viewer_paths(run_dir):
        if inject_execution_panel(vp):
            patched.append(vp.relative_to(run_dir).as_posix())
    result["patched_files"] = patched

    hash_after = compute_execution_protected_hashes(run_dir)
    hash_check = _compare(hash_before, hash_after)
    hash_check["note"] = ("Phase 2C-3는 product/ + src/adapters/만 수정 — "
                          "golden/fixtures/replay/src/core/runner/contract/phase2c0·2c1·2c2 불변")
    _write_json(review_dir / "phase2c3_hash_after.json", hash_after)
    _write_json(review_dir / "phase2c3_hash_check.json", hash_check)
    result["hash_status"] = hash_check["status"]

    out_of_scope = [f for f in patched
                    if not any(f.startswith(p) for p in ALLOWED_SCOPE_PREFIXES)]
    _write_json(review_dir / "phase2c3_diff_summary.json", {
        "run_dir": f"runs/{run_dir.name}", "challenge_id": result["challenge_id"],
        "patched_files": patched,
        "out_of_scope_changes": out_of_scope,
        "protected_files_changed": hash_check["changed"] + hash_check["added"]
        + hash_check["removed"],
    })

    # ---- 정적 검사들
    adapter_check = check_adapter(final_dir)
    _write_json(review_dir / "adapter_check.json", adapter_check)

    viewer = _find_product_viewer(final_dir)
    viewer_html = viewer.read_text(encoding="utf-8", errors="replace") if viewer else ""
    js_syntax = (check_js_syntax(viewer, review_dir / "js_check")
                 if viewer else {"status": "FAIL", "errors": ["viewer 없음"]})
    static_dom = check_static_dom(viewer_html)
    handler = check_handler_binding(viewer_html)
    _write_json(review_dir / "viewer_js_syntax_check.json", js_syntax)
    _write_json(review_dir / "viewer_static_dom_check.json", static_dom)
    _write_json(review_dir / "viewer_handler_binding_check.json", handler)
    ui_pass = static_dom["status"] == "PASS" and handler["status"] == "PASS"

    # ---- viewer smoke (temp copy) + 실행 스모크
    viewer_smoke = smoke_review(run_dir, review_dir, timeout=timeout)
    _write_json(review_dir / "viewer_smoke_after_execution.json", viewer_smoke)

    exec_smoke = run_execution_smoke(run_dir, timeout=timeout)
    _write_json(review_dir / "execution_smoke.json", exec_smoke)
    _write_text(review_dir / "execution_smoke.md", _smoke_md(exec_smoke))

    # ---- fitness 재평가
    prior_editor = _load_json(run_dir / "review" / "phase2c2" / "phase2c2_editor_report.json")
    base_fitness = build_fitness(viewer_smoke, gate)
    fit = finalize_execution_fitness(base_fitness, exec_smoke, ui_pass,
                                     js_syntax["status"], gate, hash_check["status"],
                                     prior_editor)
    result["recommended_fitness"] = fit["recommended_fitness"]

    fitness_json = {
        "recommended_fitness": fit["recommended_fitness"],
        "runner_backed_execution_included": fit["runner_backed_execution_included"],
        "product_loop_closed": fit["product_loop_closed"],
        "review_status": ("사용자 최종 승인 필요"
                          if fit["recommended_fitness"] == "PRODUCT_CANDIDATE"
                          else "사용자 최종 결정 대기"),
        "final_decision": "PENDING_USER_REVIEW",
        "average_score": base_fitness["average_score"], "scores": base_fitness["scores"],
        "criteria": base_fitness["criteria"],
        "critical_red_flags": base_fitness["critical_red_flags"],
        "execution_candidate_conditions": fit["execution_candidate_conditions"],
        "all_execution_conditions_met": fit["all_execution_conditions_met"],
        "limitations": fit["limitations"],
        "green_base": gate.get("green_base"), "gate_fail": gate.get("gate_fail"),
        "viewer_mismatches": viewer_smoke.get("mismatches"),
        "runner_viewer_consistent": viewer_smoke.get("runner_viewer_consistent"),
    }
    _write_json(review_dir / "product_fitness_report_after_execution.json", fitness_json)
    _write_text(review_dir / "product_fitness_report_after_execution.md",
                _fitness_md(fit, base_fitness))

    # ---- report + dashboard summary
    report = {
        "run_dir": f"runs/{run_dir.name}", "challenge_id": result["challenge_id"],
        "applied": True, "patched_files": patched, "hash_status": hash_check["status"],
        "execution_smoke": exec_smoke,
        "recommended_fitness": fit["recommended_fitness"],
        "runner_backed_execution_included": fit["runner_backed_execution_included"],
        "product_loop_closed": fit["product_loop_closed"],
    }
    _write_json(review_dir / "phase2c3_execution_report.json", report)
    _write_text(review_dir / "phase2c3_execution_report.md", _report_md(report))

    _write_json(review_dir / "phase2c3_dashboard_summary.json", {
        "phase": "2c3", "challenge_id": result["challenge_id"],
        "run_dir": f"runs/{run_dir.name}",
        "verdict": gate.get("verdict"), "green_base": gate.get("green_base"),
        "recommended_fitness": fit["recommended_fitness"],
        "runner_backed_execution_included": fit["runner_backed_execution_included"],
        "product_loop_closed": fit["product_loop_closed"],
        "execution_smoke_pass": exec_smoke["execution_smoke_pass"],
        "revise_cycle_changes_result": exec_smoke["revise_cycle_changes_result"],
        "bridge_server_ok": exec_smoke["bridge_server_ok"],
        "original_replay_unchanged": exec_smoke["original_replay_unchanged"],
        "hash_status": hash_check["status"],
        "review_status": fitness_json["review_status"],
        "execution_status": ("runner-backed execution available"
                             if exec_smoke["product_loop_closed"]
                             else "execution partial (loop 미완결)"),
        "user_next_action": ("draft 실행/revise 확인 후 최종 승인"
                             if fit["recommended_fitness"] == "PRODUCT_CANDIDATE"
                             else "execute/result/revise 사이클 확인"),
        "average_score": base_fitness["average_score"], "scores": base_fitness["scores"],
        "critical_red_flags": base_fitness["critical_red_flags"],
        "limitations": fit["limitations"],
        "bridge_command": f"python {BRIDGE_REL} --port {DEFAULT_BRIDGE_PORT}",
    })

    result["applied"] = True
    result["ok"] = (hash_check["status"] == "PASS" and not out_of_scope)
    result["status"] = ("EXECUTION_ADDED" if exec_smoke["product_loop_closed"]
                        else "EXECUTION_PARTIAL")
    result["execution_smoke"] = exec_smoke
    result["fitness"] = fitness_json
    return result


def _challenge_id(run_dir: Path):
    for rel in ("review/phase2c2/phase2c2_dashboard_summary.json",
                "review/phase2c1/phase2c1_dashboard_summary.json",
                "review/phase2c0/review_package.json",
                "final_artifact/product_summary.json"):
        d = _load_json(run_dir / rel) or {}
        if d.get("challenge_id") is not None:
            return d["challenge_id"]
    return None
