# Phase 2C-1: #47 product viewer가 실제 replay schema를 맞춰 읽도록 field mapping/deterministic layout만 좁게 고치는 모듈.
from __future__ import annotations

import re
from pathlib import Path

from repo_idea_miner.factory_run_layout import resolve_run_target

from repo_idea_miner.factory_review import (
    _find_product_viewer,
    _first_replay_file,
    _load_json,
    _sha256,
    _viewer_field_mismatches,
    _write_json,
    _write_text,
    build_fitness,
    read_gate_context,
    smoke_review,
)

# ---------------------------------------------------------------- 상수 (§4, §9)

POLISH_SUBDIR = "review/phase2c1"
DEFAULT_TARGET = "viewer-field-mapping"

# review/phase2c1/ 아래 필수 산출물 (§9, §13.1)
REQUIRED_OUTPUTS = (
    "phase2c1_polish_plan.json", "phase2c1_polish_plan.md",
    "phase2c1_polish_report.json", "phase2c1_polish_report.md",
    "phase2c1_diff_summary.json",
    "phase2c1_hash_before.json", "phase2c1_hash_after.json", "phase2c1_hash_check.json",
    "artifact_smoke_review_after_polish.json", "artifact_smoke_review_after_polish.md",
    "product_fitness_report_after_polish.json", "product_fitness_report_after_polish.md",
    "phase2c1_dashboard_summary.json",
)

# no-code-change 보호 대상 (§4.1) — product/는 제외(수정 허용), replay는 보호 포함
_PROTECTED_CONTRACTS = (
    "core_contract.json", "state_contract.json", "action_contract.json", "runner_contract.json",
)
_PROTECTED_DIR_PREFIXES = ("src/", "golden/", "fixtures/", "replay/")
_PROTECTED_ROOTS = ("workspace", "final_artifact")

# 폴리시된 viewer script — 실제 replay schema(source_id/target_id, event/node_id, 좌표 없음)를
# normalize 단계에서 맞춰 읽고 deterministic layout을 생성한다. edge.from/ev.type/node.x 같은
# raw-access 리터럴을 쓰지 않는다(smoke schema-mismatch 감지가 [] 이어야 함).
_POLISHED_SCRIPT = r"""
// Phase 2C-1 field mapping polish: raw replay schema -> display model -> render
function normalizeEdge(e) {
    var a = (e.source_id !== undefined) ? e.source_id : e["from"];
    var b = (e.target_id !== undefined) ? e.target_id : e["to"];
    return { from: a, to: b, sourcePort: e.source_port, targetPort: e.target_port };
}

function normalizeEvent(evt) {
    var kind = (evt.event !== undefined) ? evt.event : (evt.kind || "event");
    var nodeId = (evt.node_id !== undefined) ? evt.node_id : null;
    var linked = evt.edge || null;
    var label = evt.message;
    if (label === undefined || label === null) {
        if (linked) {
            var s = (linked.source_id !== undefined) ? linked.source_id : linked["from"];
            var t = (linked.target_id !== undefined) ? linked.target_id : linked["to"];
            label = s + " → " + t;
        } else if (nodeId) {
            label = nodeId;
        } else {
            label = "";
        }
    }
    return { kind: kind, nodeId: nodeId, label: label };
}

// 좌표가 없으면 execution_order / topological 기반 deterministic layout 생성 (random/시간 금지)
function computeLayout(rawNodes, dispEdges) {
    var ids = Object.keys(rawNodes).sort();
    var indeg = {}, adj = {};
    ids.forEach(function (id) { indeg[id] = 0; adj[id] = []; });
    dispEdges.forEach(function (de) {
        if (adj[de.from] !== undefined && indeg[de.to] !== undefined) {
            adj[de.from].push(de.to); indeg[de.to] += 1;
        }
    });
    var level = {}, remaining = {};
    ids.forEach(function (id) { level[id] = 0; remaining[id] = indeg[id]; });
    var frontier = ids.filter(function (id) { return indeg[id] === 0; }).sort();
    var lvl = 0;
    while (frontier.length) {
        frontier.forEach(function (id) { if (level[id] < lvl) level[id] = lvl; });
        var nxt = [];
        frontier.forEach(function (id) {
            adj[id].sort().forEach(function (t) {
                remaining[t] -= 1;
                if (remaining[t] === 0) nxt.push(t);
            });
        });
        frontier = nxt.sort(); lvl += 1;
    }
    var byLevel = {};
    ids.forEach(function (id) { (byLevel[level[id]] = byLevel[level[id]] || []).push(id); });
    var coords = {};
    Object.keys(byLevel).sort(function (p, q) { return p - q; }).forEach(function (l) {
        byLevel[l].sort().forEach(function (id, i) {
            coords[id] = { px: 40 + Number(l) * 200, py: 40 + i * 120 };
        });
    });
    return coords;
}

function normalizeReplayForViewer(data) {
    var state = data.final_state || {};
    var rawNodes = state.nodes || {};
    var rawEdges = state.edges || [];
    var dispEdges = rawEdges.map(normalizeEdge);
    var coords = computeLayout(rawNodes, dispEdges);
    var dispNodes = {};
    Object.keys(rawNodes).forEach(function (id) {
        var node = rawNodes[id];
        var pos = coords[id] || { px: 40, py: 40 };
        dispNodes[id] = {
            id: id, kind: node["type"], status: node.status,
            outputs: node.output_values, px: pos.px, py: pos.py
        };
    });
    var dispEvents = (data.events || []).map(normalizeEvent);
    return {
        nodes: dispNodes, edges: dispEdges, events: dispEvents,
        summary: data.summary, execution_order: state.execution_order || []
    };
}

async function init() {
    try {
        var response = await fetch('../../replay/index.json');
        var data = await response.json();
        var select = document.getElementById('scenario-select');
        select.innerHTML = '';
        data.replays.forEach(function (r) {
            var opt = document.createElement('option');
            opt.value = r.file;
            opt.textContent = r.id + ' (' + (r.ok ? 'OK' : 'FAIL') + ')';
            select.appendChild(opt);
        });
    } catch (e) {
        alert('replay/index.json을 로드할 수 없습니다.');
    }
}

async function loadSelectedScenario() {
    var file = document.getElementById('scenario-select').value;
    var graphArea = document.getElementById('graph-area');
    var detailsContent = document.getElementById('details-content');
    graphArea.innerHTML = '';
    detailsContent.innerHTML = 'Loading...';
    try {
        var response = await fetch('../../replay/' + file);
        var data = await response.json();
        var model = normalizeReplayForViewer(data);

        var html = '<div class="summary-card"><strong>Execution Summary</strong><br>';
        html += '<pre>' + JSON.stringify(data.summary, null, 2) + '</pre></div>';
        html += '<h4>Event Log</h4><div class="event-log">';
        model.events.forEach(function (evt) {
            html += '<div class="event-item"><strong>' + evt.kind + '</strong>: ' + evt.label + '</div>';
        });
        html += '</div>';
        detailsContent.innerHTML = html;

        var nodes = model.nodes;
        model.edges.forEach(function (de) {
            var fromNode = nodes[de.from];
            var toNode = nodes[de.to];
            if (fromNode && toNode) {
                var edgeEl = document.createElement('div');
                edgeEl.className = 'edge';
                var x1 = fromNode.px + 70, y1 = fromNode.py + 35;
                var x2 = toNode.px + 70, y2 = toNode.py + 35;
                var length = Math.sqrt(Math.pow(x2 - x1, 2) + Math.pow(y2 - y1, 2));
                var angle = Math.atan2(y2 - y1, x2 - x1) * 180 / Math.PI;
                edgeEl.style.width = length + 'px';
                edgeEl.style.left = x1 + 'px';
                edgeEl.style.top = y1 + 'px';
                edgeEl.style.transform = 'rotate(' + angle + 'deg)';
                graphArea.appendChild(edgeEl);
            }
        });
        Object.keys(nodes).forEach(function (id) {
            var node = nodes[id];
            var cls = node.status === 'COMPLETED' ? 'success'
                : (node.status === 'FAILED' || node.status === 'ERROR' ? 'error' : 'pending');
            var nodeEl = document.createElement('div');
            nodeEl.className = 'node ' + cls;
            nodeEl.style.left = node.px + 'px';
            nodeEl.style.top = node.py + 'px';
            nodeEl.innerHTML = '<div class="status-tag">' + (node.status || 'UNKNOWN') + '</div>'
                + '<strong>' + id + '</strong><br><span>' + (node.kind || '') + '</span>';
            nodeEl.onclick = function () {
                alert('Node: ' + id + '\nType: ' + (node.kind || '') + '\nStatus: ' + node.status
                    + '\nOutputs: ' + JSON.stringify(node.outputs || []));
            };
            graphArea.appendChild(nodeEl);
        });
    } catch (e) {
        detailsContent.innerHTML = '데이터 로드 오류: ' + e.message;
    }
}
window.onload = init;
"""

_SCRIPT_BLOCK_RE = re.compile(r"<script>.*?</script>", re.DOTALL)


# ---------------------------------------------------------------- 대상/사전 조건

def resolve_polish_target(run_dir=None, run_id=None, db_conn=None):
    return resolve_run_target(run_dir, run_id, db_conn)


def check_polish_preconditions(run_dir: Path, gate: dict) -> list[str]:
    """§8: Phase 2C-0 fitness=NEEDS_PRODUCT_POLISH + verdict REVIEW_READY + green_base true."""
    problems: list[str] = []
    fitness = _load_json(run_dir / "review" / "phase2c0" / "product_fitness_report.json")
    if fitness is None:
        problems.append("Phase 2C-0 product_fitness_report.json 없음 (2C-0 review 먼저 필요)")
    elif fitness.get("recommended_fitness") != "NEEDS_PRODUCT_POLISH":
        problems.append(f"2C-0 recommended_fitness가 NEEDS_PRODUCT_POLISH 아님: {fitness.get('recommended_fitness')}")
    if gate.get("verdict") != "REVIEW_READY":
        problems.append(f"current verdict가 REVIEW_READY 아님: {gate.get('verdict')}")
    if not gate.get("green_base"):
        problems.append("green_base가 true 아님")
    return problems


# ---------------------------------------------------------------- 보호 대상 hash (§4)

def compute_polish_protected_hashes(run_dir: Path) -> dict[str, str]:
    """src/golden/fixtures/contract/oracle/replay를 보호(product/ 제외)한 sha256 map (§4.1)."""
    run_dir = Path(run_dir)
    out: dict[str, str] = {}
    for root_name in _PROTECTED_ROOTS:
        base = run_dir / root_name
        if not base.is_dir():
            continue
        for rel in _PROTECTED_CONTRACTS:
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
    return out


def _compare(before: dict, after: dict) -> dict:
    changed = sorted(k for k in before if k in after and before[k] != after[k])
    removed = sorted(k for k in before if k not in after)
    added = sorted(k for k in after if k not in before)
    return {"status": "PASS" if not (changed or removed or added) else "FAIL",
            "files_checked": len(before), "changed": changed, "added": added, "removed": removed}


def _product_viewer_paths(run_dir: Path) -> list[Path]:
    """final_artifact/product 와 workspace/product 아래 viewer html을 모두 찾는다."""
    out: list[Path] = []
    for root_name in ("final_artifact", "workspace"):
        prod = run_dir / root_name / "product"
        if prod.is_dir():
            for p in sorted(prod.rglob("*.html")):
                out.append(p)
    return out


def _product_hashes(paths: list[Path], run_dir: Path) -> dict[str, str]:
    return {str(p.relative_to(run_dir).as_posix()): _sha256(p) for p in paths if p.is_file()}


# ---------------------------------------------------------------- 진단 / patch

def detect_viewer_mismatches(final_dir: Path) -> tuple[list[str], dict | None, Path | None]:
    viewer = _find_product_viewer(final_dir)
    _f, replay = _first_replay_file(final_dir)
    if viewer is None:
        return ["product viewer 없음"], replay, None
    mism = _viewer_field_mismatches(replay, viewer.read_text(encoding="utf-8", errors="replace"))
    return mism, replay, viewer


def patch_viewer(viewer_path: Path) -> bool:
    """viewer의 <script> 블록만 폴리시된 스크립트로 교체한다. CSS/구조는 보존.

    치환은 lambda로 넘긴다. re.sub의 문자열 replacement는 백슬래시 이스케이프(\\n 등)를
    해석하므로, 스크립트의 JS `\\n` 이스케이프가 실제 개행으로 바뀌어 구문이 깨진다.
    함수 replacement는 반환값을 그대로 삽입한다.
    """
    text = viewer_path.read_text(encoding="utf-8", errors="replace")
    if not _SCRIPT_BLOCK_RE.search(text):
        return False
    replacement = "<script>\n" + _POLISHED_SCRIPT + "\n    </script>"
    new_text = _SCRIPT_BLOCK_RE.sub(lambda _m: replacement, text, count=1)
    if new_text == text:
        return False
    viewer_path.write_text(new_text, encoding="utf-8")
    return True


def analyze_polish(viewer_src: str, replay: dict | None) -> dict:
    """폴리시된 viewer가 edge/event/layout을 제대로 처리하는지 판정한다 (§10.2)."""
    mism = _viewer_field_mismatches(replay, viewer_src)
    edge_left = any("엣지" in m for m in mism)
    event_left = any("이벤트" in m for m in mism)
    pos_left = any("겹침" in m or "좌표" in m for m in mism)
    reads_source = bool(re.search(r"source_id|target_id", viewer_src))
    reads_event = bool(re.search(r"\.event\b|node_id", viewer_src))
    has_layout = bool(re.search(r"computeLayout|normalizeReplayForViewer|execution_order", viewer_src))
    no_raw_xy = not re.search(r"node\.x|node\.y", viewer_src)
    nondeterministic = bool(re.search(r"Math\.random|Date\.now|new Date|performance\.now", viewer_src))
    return {
        "edge_mapping_fixed": reads_source and not edge_left,
        "event_mapping_fixed": reads_event and not event_left,
        "node_layout_generated": has_layout and no_raw_xy and not pos_left,
        "layout_deterministic": has_layout and no_raw_xy and not nondeterministic,
        "viewer_schema_mismatches_remaining": mism,
    }


# ---------------------------------------------------------------- 문서 렌더링

def _plan_md(plan: dict) -> str:
    L = ["# Phase 2C-1 Viewer Field Mapping Polish Plan", "",
         f"- run_dir: {plan['run_dir']} / challenge_id: {plan['challenge_id']}",
         f"- target: {plan['target']} / status: {plan['status']}",
         "", "## 감지된 viewer schema mismatch"]
    L += [f"- {m}" for m in plan["detected_mismatches"]] or ["- (없음)"]
    L += ["", "## 수정 예정 파일(product viewer)"] + ([f"- {f}" for f in plan["planned_files"]] or ["- (없음)"])
    L += ["", "## 보호 대상(변경 금지)"] + [f"- {f}" for f in plan["protected_files"]]
    L += ["", "## 기대 매핑 변경"] + [f"- {c}" for c in plan["expected_mapping_changes"]]
    L += ["", f"## risk: {plan['risk']}"]
    if plan.get("blocked_reasons"):
        L += ["", "## Blocked"] + [f"- {b}" for b in plan["blocked_reasons"]]
    return "\n".join(L) + "\n"


def _report_md(report: dict) -> str:
    a = report["after"]
    L = ["# Phase 2C-1 Viewer Field Mapping Polish Report", "",
         f"- run_dir: {report['run_dir']} / challenge_id: {report['challenge_id']}",
         f"- applied: {report['applied']} / patched files: {', '.join(report['patched_files']) or '-'}",
         f"- 보호 대상 hash: {report['hash_status']}",
         "", "## viewer 수정 결과",
         f"- edge mapping fixed: {a['edge_mapping_fixed']}",
         f"- event mapping fixed: {a['event_mapping_fixed']}",
         f"- node layout generated: {a['node_layout_generated']}",
         f"- layout deterministic: {a['layout_deterministic']}",
         f"- 남은 schema mismatch: {a['viewer_schema_mismatches_remaining'] or '없음'}",
         "", "## smoke review after polish",
         f"- runner executable: {report['smoke']['runner_executable']}",
         f"- viewer reads replay: {report['smoke']['product_viewer_reads_replay']}",
         f"- runner/viewer consistency: {report['smoke']['runner_viewer_consistent']} "
         f"{report['smoke']['runner_viewer_consistency_fields']}",
         "", "## product fitness after polish",
         f"- recommended_fitness: {report['recommended_fitness']}",
         f"- 평균 점수: {report['average_score']}/5",
         f"- red flags: {report['critical_red_flags'] or '없음'}"]
    return "\n".join(L) + "\n"


def _smoke_md(smoke: dict, extra: dict) -> str:
    return "\n".join([
        "# Artifact Smoke Review (After Phase 2C-1 Polish)", "",
        f"- runner executable: {smoke['runner_executable']} (exit={smoke['runner_exit_code']})",
        f"- product viewer reads replay: {smoke['product_viewer_reads_replay']}",
        f"- runner/viewer consistency: {smoke['runner_viewer_consistent']} {smoke['runner_viewer_consistency_fields']}",
        f"- edge mapping fixed: {extra['edge_mapping_fixed']}",
        f"- event mapping fixed: {extra['event_mapping_fixed']}",
        f"- node layout generated: {extra['node_layout_generated']} (deterministic: {extra['layout_deterministic']})",
        f"- 남은 schema mismatch: {extra['viewer_schema_mismatches_remaining'] or '없음'}",
        f"- critical failures: {smoke['critical_failures'] or '없음'}",
        f"- unknowns: {smoke['unknowns'] or '없음'}",
    ]) + "\n"


def _fitness_md(fitness: dict) -> str:
    L = ["# Product Fitness Report (After Phase 2C-1 Polish)", "",
         f"- recommended_fitness: **{fitness['recommended_fitness']}** · 평균 {fitness['average_score']}/5",
         "", "## 점수"]
    for c in fitness["criteria"]:
        L.append(f"- {c['criterion']}: {c['score']} — {c['reason']}")
    L += ["", "## red flags"] + [f"- {r}" for r in fitness["critical_red_flags"]] or ["- 없음"]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- 오케스트레이터 (§7, §8)

def run_product_polish(run_dir=None, run_id=None, target=DEFAULT_TARGET, apply=False,
                       db_conn=None, timeout: float = 60.0) -> dict:
    """#47 viewer field mapping을 dry-run/apply한다 (§7, §8). core/golden/replay 미변경."""
    result: dict = {
        "ok": False, "status": None, "resolved_run_dir": None, "challenge_id": None,
        "applied": False, "patched_files": [], "hash_status": None,
        "recommended_fitness": None, "review_dir": None, "problems": [], "error": None,
    }
    tgt, err, info = resolve_polish_target(run_dir, run_id, db_conn)
    result["resolved_run_dir"] = info.get("resolved_run_dir")
    if err:
        result["error"] = err
        return result
    run_dir = tgt
    review_dir = run_dir / POLISH_SUBDIR
    result["review_dir"] = str(review_dir.as_posix())
    final_dir = run_dir / "final_artifact"

    gate = read_gate_context(run_dir)
    result["challenge_id"] = info.get("challenge_id") or _challenge_id(run_dir)

    if target != DEFAULT_TARGET:
        result["error"] = f"지원하지 않는 target: {target} (viewer-field-mapping만 지원)"
        return result

    problems = check_polish_preconditions(run_dir, gate)
    detected, replay, viewer = detect_viewer_mismatches(final_dir)

    plan = {
        "run_dir": f"runs/{run_dir.name}", "challenge_id": result["challenge_id"],
        "target": target, "detected_mismatches": detected,
        "planned_files": [str(p.relative_to(run_dir).as_posix()) for p in _product_viewer_paths(run_dir)],
        "protected_files": ["final_artifact/src/", "workspace/src/", "golden/", "fixtures/",
                            "core_contract.json", "state_contract.json", "action_contract.json",
                            "runner_contract.json", "oracle_risk_report.json",
                            "replay/index.json", "replay/replay_*.json"],
        "expected_mapping_changes": [
            "edge: source_id/target_id -> display from/to (normalizeEdge)",
            "event: event/node_id -> display kind/label (normalizeEvent)",
            "node: 좌표 없음 -> execution_order/topological deterministic layout (computeLayout)",
        ],
        "risk": "low (product viewer만 수정, core/golden/replay 불변)",
        "blocked_reasons": problems,
        "status": "DRY_RUN_BLOCKED" if problems else "DRY_RUN_PASS",
    }
    _write_json(review_dir / "phase2c1_polish_plan.json", plan)
    _write_text(review_dir / "phase2c1_polish_plan.md", _plan_md(plan))

    if not apply:
        result["ok"] = not problems
        result["status"] = plan["status"]
        result["plan"] = plan
        result["problems"] = problems
        if problems:
            result["error"] = "; ".join(problems)
        return result

    if problems:
        result["status"] = "CANNOT_POLISH"
        result["problems"] = problems
        result["error"] = "; ".join(problems)
        return result

    # ---- Apply (§8)
    hash_before = compute_polish_protected_hashes(run_dir)
    prod_before = _product_hashes(_product_viewer_paths(run_dir), run_dir)
    _write_json(review_dir / "phase2c1_hash_before.json", hash_before)

    patched: list[str] = []
    for vp in _product_viewer_paths(run_dir):
        if patch_viewer(vp):
            patched.append(str(vp.relative_to(run_dir).as_posix()))
    result["patched_files"] = patched

    hash_after = compute_polish_protected_hashes(run_dir)
    hash_check = _compare(hash_before, hash_after)
    hash_check["note"] = "Phase 2C-1은 product viewer만 수정 — src/golden/fixtures/contract/replay는 불변 (§4)"
    _write_json(review_dir / "phase2c1_hash_after.json", hash_after)
    _write_json(review_dir / "phase2c1_hash_check.json", hash_check)
    result["hash_status"] = hash_check["status"]

    prod_after = _product_hashes(_product_viewer_paths(run_dir), run_dir)
    prod_changed = sorted(k for k in prod_before if prod_before.get(k) != prod_after.get(k))
    _write_json(review_dir / "phase2c1_diff_summary.json", {
        "run_dir": f"runs/{run_dir.name}", "challenge_id": result["challenge_id"],
        "patched_files": patched,
        "product_files_changed": prod_changed,
        "protected_files_changed": hash_check["changed"] + hash_check["added"] + hash_check["removed"],
        "core_golden_fixtures_contract_replay_changed": bool(hash_check["changed"]
                                                              or hash_check["added"] or hash_check["removed"]),
        "mapping_changes": plan["expected_mapping_changes"],
    })

    # ---- Smoke review 재실행 (원본 오염 없이 temp copy) + polish 분석
    smoke = smoke_review(run_dir, review_dir, timeout=timeout)
    polished_src = viewer.read_text(encoding="utf-8", errors="replace") if viewer and viewer.is_file() else ""
    _f2, replay_after = _first_replay_file(final_dir)
    extra = analyze_polish(polished_src, replay_after)
    smoke_out = dict(smoke)
    smoke_out.update(extra)
    _write_json(review_dir / "artifact_smoke_review_after_polish.json", smoke_out)
    _write_text(review_dir / "artifact_smoke_review_after_polish.md", _smoke_md(smoke, extra))

    # ---- Product fitness 재평가
    fitness = build_fitness(smoke, gate)
    fitness_json = {
        "recommended_fitness": fitness["recommended_fitness"],
        "review_status": ("사용자 최종 승인 필요" if fitness["recommended_fitness"] == "PRODUCT_CANDIDATE"
                          else "사용자 최종 결정 대기"),
        "final_decision": "PENDING_USER_REVIEW",
        "average_score": fitness["average_score"], "scores": fitness["scores"],
        "criteria": fitness["criteria"], "critical_red_flags": fitness["critical_red_flags"],
        "candidate_conditions": fitness["candidate_conditions"],
        "green_base": gate.get("green_base"), "gate_fail": gate.get("gate_fail"),
        "runner_executable": smoke.get("runner_executable"),
        "product_viewer_reads_replay": smoke.get("product_viewer_reads_replay"),
        "runner_viewer_consistent": smoke.get("runner_viewer_consistent"),
        "edge_mapping_fixed": extra["edge_mapping_fixed"],
        "event_mapping_fixed": extra["event_mapping_fixed"],
        "node_layout_generated": extra["node_layout_generated"],
        "viewer_schema_mismatches_remaining": extra["viewer_schema_mismatches_remaining"],
    }
    _write_json(review_dir / "product_fitness_report_after_polish.json", fitness_json)
    _write_text(review_dir / "product_fitness_report_after_polish.md", _fitness_md(fitness))
    result["recommended_fitness"] = fitness["recommended_fitness"]

    # ---- Report + dashboard summary
    report = {
        "run_dir": f"runs/{run_dir.name}", "challenge_id": result["challenge_id"],
        "applied": True, "patched_files": patched, "hash_status": hash_check["status"],
        "after": extra, "smoke": smoke,
        "recommended_fitness": fitness["recommended_fitness"],
        "average_score": fitness["average_score"],
        "critical_red_flags": fitness["critical_red_flags"],
    }
    _write_json(review_dir / "phase2c1_polish_report.json", report)
    _write_text(review_dir / "phase2c1_polish_report.md", _report_md(report))

    _write_json(review_dir / "phase2c1_dashboard_summary.json", {
        "phase": "2c1", "challenge_id": result["challenge_id"], "run_dir": f"runs/{run_dir.name}",
        "verdict": gate.get("verdict"), "green_base": gate.get("green_base"),
        "recommended_fitness": fitness["recommended_fitness"],
        "review_status": fitness_json["review_status"],
        "viewer_polish_status": _polish_status_text(extra),
        "user_next_action": ("60초 검수 스크립트로 최종 승인" if fitness["recommended_fitness"] == "PRODUCT_CANDIDATE"
                             else "viewer에서 그래프/이벤트 렌더링 확인"),
        "edge_mapping_fixed": extra["edge_mapping_fixed"],
        "event_mapping_fixed": extra["event_mapping_fixed"],
        "node_layout_generated": extra["node_layout_generated"],
        "layout_deterministic": extra["layout_deterministic"],
        "viewer_schema_mismatches_remaining": extra["viewer_schema_mismatches_remaining"],
        "runner_viewer_consistent": smoke.get("runner_viewer_consistent"),
        "hash_status": hash_check["status"],
        "average_score": fitness["average_score"], "scores": fitness["scores"],
        "critical_red_flags": fitness["critical_red_flags"],
    })

    result["applied"] = True
    result["ok"] = True
    result["status"] = "POLISHED"
    result["smoke"] = smoke
    result["fitness"] = fitness
    result["extra"] = extra
    return result


def _polish_status_text(extra: dict) -> str:
    if extra["edge_mapping_fixed"] and extra["event_mapping_fixed"] and extra["node_layout_generated"]:
        return "field mapping fixed, interaction still limited"
    return "field mapping partially fixed"


def _challenge_id(run_dir: Path) -> int | None:
    for name in ("phase2b1b_dashboard_summary.json",
                 "green_base_promotion_after_anti_hardcode_patch.json"):
        d = _load_json(run_dir / name) or {}
        if d.get("challenge_id") is not None:
            return d["challenge_id"]
    d = _load_json(run_dir / "review" / "phase2c0" / "review_package.json") or {}
    return d.get("challenge_id")
