# 이슈 #8 §19: 도메인 중립 UX_POLISH — contract/diagnosis/operations/runtime/loop/validator 검증.
import hashlib
import json
import re
from pathlib import Path

import pytest

from repo_idea_miner.factory_autopilot_desks import derive_primary_gap
from repo_idea_miner.factory_autopilot_schemas import GAP_TO_LANE
from repo_idea_miner.factory_lane_executors import (
    LANE_EXECUTOR_ROUTES,
    LANE_EXECUTORS,
    execute_lane,
)
from repo_idea_miner.factory_product_capabilities import _contract_mediated_replay_read
from repo_idea_miner.factory_product_loop import extract_artifact_evidence
from repo_idea_miner.factory_ux_polish import (
    DIAGNOSIS_STATUSES,
    DIAGNOSIS_TO_OPERATION,
    FORBIDDEN_OPERATION_IDS,
    MAX_OPERATIONS_PER_PRODUCT,
    MAX_TARGET_SURFACES,
    OPERATION_IDS,
    UX_STATUSES,
    VIEWPORT_DESKTOP,
    VIEWPORT_NARROW,
    apply_operation,
    build_ux_contract,
    build_ux_diagnosis,
    check_surface_scripts,
    collect_surfaces,
    diagnose_surface,
    run_ux_polish,
)
from repo_idea_miner.factory_validate import _check_ux_polish_lane


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _node_available() -> bool:
    return check_surface_scripts("<script>var a = 1;</script>")["status"] == "PASS"


# 도메인 중립 합성 표면 — 결함을 의도적으로 심는다 (§19.2). 특정 challenge/제품 이름 없음.
_GOOD_CONSOLE = """<!doctype html><html><head><style>
body { margin: 8px; }
</style></head><body>
<div id="state-view"></div><div id="error-view"></div>
<select id="action-select"></select>
<button id="run">실행</button>
<script>
"use strict";
const CONTRACT = {"initial_state": {"Entity": {"v": 1}}};
document.getElementById("run").addEventListener("click", function () {});
</script>
</body></html>"""

_BROKEN_VIEWER = """<!doctype html><html><head><style>
.layout { display: flex; gap: 10px; }
.side { width: 260px; flex: none; }
.main { flex: 1; }
</style></head><body>
<div class="layout"><div class="side" id="frame-list"></div>
<div class="main"><button data-action="next">다음</button>
<span id="frame-position"></span>
<pre id="before-state"></pre><div id="validation-area"></div>
<div id="error-area"></div></div></div>
<script>
"use strict";
function render() {
  var list = document.getElementById("frame-list");
  var div = document.createElement("div");
  div.setAttribute("data-action", "select-frame");
  list.appendChild(div);
}
fetch("viewer_contract.json").then(function (r) { return r.json(); }).then(render);
</script>
</body></html>"""


def _make_ux_run(tmp_path: Path, name: str = "run_ux") -> Path:
    """UX 결함 2종(narrow viewport/keyboard)을 가진 도메인 중립 합성 run."""
    run = tmp_path / name
    ws = run / "workspace"
    replay = {"ok": True, "errors": [], "summary": "1 executed",
              "final_state": {"Entity": {"v": 2}},
              "events": [{"type": "VALUE_SET", "target_id": "e1"}]}
    _dump(ws / "replay" / "replay_scenario_001.json", replay)
    digest = hashlib.sha256(
        (ws / "replay" / "replay_scenario_001.json").read_bytes()).hexdigest()
    _dump(ws / "runner_contract.json",
          {"required_output_fields": ["ok", "final_state", "events", "summary"]})
    _dump(ws / "product" / "interaction" / "contract.json", {
        "available_actions": [{"name": "set_value", "input": ["target_id", "value"]}],
        "validation_rules": [{"action": "set_value", "rule": "value >= 0"}],
    })
    _write(ws / "product" / "interaction" / "index.html", _GOOD_CONSOLE)
    _write(ws / "product" / "viewer" / "index.html", _BROKEN_VIEWER)
    _dump(ws / "product" / "viewer" / "viewer_contract.json", {
        "viewer_kind": "standard_typed_event",
        "replays": [{"replay_id": "scenario_001", "ok": True, "errors": [], "frames": []}],
        "source_artifact_refs": [
            {"ref": "replay/replay_scenario_001.json", "sha256": digest}],
    })
    # runtime action 실증(§10) — 기존 runner-backed evidence 참조
    _dump(run / "review" / "draft_execution" / "draft_execution_report.json", {
        "applied": True, "runner_backed_execution_included": True,
        "execution_evidence": {"can_execute_input": True, "state_change_observed": True,
                               "invalid_action_rejected": True},
    })
    return run


# ---------------------------------------------------------------- §19.1 UX Contract

def test_valid_ux_contract_from_existing_contracts(tmp_path):
    run = _make_ux_run(tmp_path)
    built = build_ux_contract(run / "workspace")
    c = built["contract"]
    assert c["primary_actions"] == ["set_value"]
    assert c["surfaces"] == ["product/interaction/index.html", "product/viewer/index.html"]
    assert any("replay" not in r["ref"] and r["sha256"] for r in c["source_artifact_refs"])
    assert c["viewport_requirements"]["desktop"] == list(VIEWPORT_DESKTOP)
    assert c["viewport_requirements"]["narrow"] == list(VIEWPORT_NARROW)
    assert c["allowed_operations"] == list(OPERATION_IDS)
    assert c["forbidden_changes"]
    assert c["state_indicators"] and c["feedback_channels"] and c["error_channels"]


def test_contract_without_interaction_contract_has_no_primary_actions(tmp_path):
    run = _make_ux_run(tmp_path)
    (run / "workspace" / "product" / "interaction" / "contract.json").unlink()
    built = build_ux_contract(run / "workspace")
    c = built["contract"]
    assert c["primary_actions"] == []
    assert all(rc["kind"] != "primary_action" for rc in c["required_controls"])
    assert c["primary_task"]  # 목적 문구는 유지 — 빈 문서로 두지 않는다


def test_contract_deterministic_serialization(tmp_path):
    run = _make_ux_run(tmp_path)
    a = build_ux_contract(run / "workspace")["contract"]
    b = build_ux_contract(run / "workspace")["contract"]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["ux_target_id"] == b["ux_target_id"]


def test_contract_unsupported_without_surfaces(tmp_path):
    run = tmp_path / "empty"
    (run / "workspace").mkdir(parents=True)
    built = build_ux_contract(run / "workspace")
    assert built["surfaces"] == []
    assert built["problems"]
    diags = build_ux_diagnosis(built, run / "workspace")
    assert [d["status"] for d in diags] == ["UNSUPPORTED"]


def test_executor_source_has_no_task_hardcode():
    src = Path("repo_idea_miner/factory_ux_polish.py").read_text(encoding="utf-8")
    for token in ("SRS", "flashcard", "filesystem", "explorer", "palette",
                  "factory_2026", "challenge_id", "run_id ="):
        assert token not in src, token
    # 금지된 자유 형식 operation은 문자열 상수 선언(FORBIDDEN_OPERATION_IDS)에만 존재
    assert src.count("MAKE_BEAUTIFUL") == 1


def test_operation_catalog_is_closed():
    assert len(OPERATION_IDS) == 12
    assert set(DIAGNOSIS_TO_OPERATION.values()) <= set(OPERATION_IDS)
    assert not set(OPERATION_IDS) & set(FORBIDDEN_OPERATION_IDS)
    assert set(DIAGNOSIS_TO_OPERATION) <= set(DIAGNOSIS_STATUSES)


# ---------------------------------------------------------------- §19.2 Diagnosis

def _diag_statuses(html: str, contract: dict | None = None, tmp_path: Path | None = None):
    surface = {"rel": "product/x/index.html", "text": html}
    out = diagnose_surface(surface, contract or {}, tmp_path or Path("."))
    return {d["status"]: d for d in out}


def test_diagnosis_action_not_discoverable_no_controls():
    d = _diag_statuses("<html><body><div>결과</div></body></html>")
    assert d["ACTION_NOT_DISCOVERABLE"]["category"] == "PRODUCT_REQUIREMENT"
    assert not d["ACTION_NOT_DISCOVERABLE"]["machine_fixable"]


def test_diagnosis_unnamed_button_is_machine_fixable():
    d = _diag_statuses('<html><body><div id="state-x"></div><div id="error-x"></div>'
                       "<button></button></body></html>")
    rec = d["ACTION_NOT_DISCOVERABLE"]
    assert rec["machine_fixable"] and rec["operation"] == "CLARIFY_LABEL"


def test_diagnosis_state_not_visible():
    d = _diag_statuses('<html><body><div id="error-x"></div><button>go</button>'
                       "<script>var CONTRACT = {\"initial_state\": {}};</script></body></html>")
    assert d["STATE_NOT_VISIBLE"]["operation"] == "EXPOSE_STATE"


def test_diagnosis_feedback_missing():
    d = _diag_statuses('<html><body><div id="state-x"></div><button>go</button></body></html>')
    assert d["FEEDBACK_MISSING"]["operation"] == "ADD_ACTION_FEEDBACK"


def test_diagnosis_error_hidden():
    d = _diag_statuses('<html><body><div id="state-x"></div><button>go</button>'
                       "<script>try {} catch (e) { console.error(e); }</script></body></html>")
    assert d["ERROR_HIDDEN"]["operation"] == "EXPOSE_ERROR"


def test_diagnosis_control_clipped():
    d = _diag_statuses('<html><head><style>.box { overflow: hidden; }</style></head>'
                       '<body><div class="box"><button>go</button></div>'
                       '<div id="state-x"></div><div id="error-x"></div></body></html>')
    assert d["CONTROL_CLIPPED"]["operation"] == "FIX_OVERFLOW"


def test_diagnosis_narrow_viewport_broken():
    d = _diag_statuses(_BROKEN_VIEWER)
    assert d["NARROW_VIEWPORT_BROKEN"]["operation"] == "STACK_FOR_NARROW_VIEWPORT"
    assert ".layout" in d["NARROW_VIEWPORT_BROKEN"]["target"]


def test_diagnosis_focus_not_visible():
    d = _diag_statuses('<html><head><style>button { outline: none; }</style></head>'
                       '<body><button>go</button><div id="state-x"></div>'
                       '<div id="error-x"></div></body></html>')
    assert d["FOCUS_NOT_VISIBLE"]["operation"] == "ADD_VISIBLE_FOCUS"


def test_diagnosis_focus_order_invalid_static_and_dynamic():
    static = _diag_statuses('<html><body><div data-action="next">다음</div>'
                            '<div id="state-x"></div><div id="error-x"></div></body></html>')
    assert static["FOCUS_ORDER_INVALID"]["operation"] == "FIX_FOCUS_ORDER"
    dynamic = _diag_statuses(_BROKEN_VIEWER)
    assert "FOCUS_ORDER_INVALID" in dynamic


def test_diagnosis_disabled_reason_missing():
    d = _diag_statuses('<html><body><button disabled>go</button>'
                       '<div id="state-x"></div><div id="error-x"></div></body></html>')
    assert d["DISABLED_REASON_MISSING"]["operation"] == "MARK_DISABLED_REASON"


def test_diagnosis_replay_position_unclear():
    d = _diag_statuses('<html><body><button data-action="next">다음</button>'
                       '<div id="state-x"></div><div id="error-x"></div></body></html>')
    assert d["REPLAY_POSITION_UNCLEAR"]["operation"] == "EXPOSE_REPLAY_POSITION"


def test_diagnosis_validation_feedback_disconnected():
    html = ('<html><body><button>go</button><div id="state-x"></div>'
            '<script>fetch("viewer_contract.json");</script></body></html>')
    d = _diag_statuses(html, contract={"validation_rules": [{"rule": "x >= 0"}]})
    assert d["VALIDATION_FEEDBACK_DISCONNECTED"]["operation"] == "CONNECT_VALIDATION_FEEDBACK"


def test_diagnosis_upstream_defect_not_covered(tmp_path):
    run = _make_ux_run(tmp_path)
    (run / "workspace" / "product" / "viewer" / "viewer_contract.json").write_text(
        "{broken", encoding="utf-8")
    built = build_ux_contract(run / "workspace")
    diags = build_ux_diagnosis(built, run / "workspace")
    assert any(d["status"] == "UPSTREAM_DEFECT" for d in diags)
    res = run_ux_polish(run_dir=run, apply=True)
    assert res["ux_status"] == "UPSTREAM_BLOCKED"
    assert res["applied"] is False and res["patched_files"] == []


def test_diagnosis_enum_covers_spec():
    assert "HUMAN_REVIEW_REQUIRED" in DIAGNOSIS_STATUSES
    assert "UNSUPPORTED" in DIAGNOSIS_STATUSES
    assert len(DIAGNOSIS_STATUSES) == 15


# ---------------------------------------------------------------- §19.3 Operations

def _apply_for(html: str, status: str, contract: dict | None = None):
    surface = {"rel": "product/x/index.html", "text": html}
    diags = {d["status"]: d for d in diagnose_surface(surface, contract or {}, Path("."))}
    assert status in diags, f"진단 미발화: {status}"
    return apply_operation(html, diags[status], contract or {})


@pytest.mark.parametrize("status,html,contract", [
    ("ACTION_NOT_DISCOVERABLE",
     '<html><body><div id="state-x"></div><div id="error-x"></div>'
     "<button></button></body></html>", {"primary_actions": ["set_value"]}),
    ("STATE_NOT_VISIBLE",
     '<html><body><div id="error-x"></div><button>go</button>'
     "<script>var CONTRACT = {\"initial_state\": {}};</script></body></html>", None),
    ("FEEDBACK_MISSING",
     '<html><body><div id="state-x"></div><button>go</button></body></html>', None),
    ("ERROR_HIDDEN",
     '<html><body><div id="state-x"></div><button>go</button>'
     "<script>console.error(1);</script></body></html>", None),
    ("CONTROL_CLIPPED",
     '<html><head><style>.box { overflow: hidden; }</style></head>'
     '<body><div class="box"><button>go</button></div><div id="state-x"></div>'
     '<div id="error-x"></div></body></html>', None),
    ("NARROW_VIEWPORT_BROKEN", _BROKEN_VIEWER, None),
    ("FOCUS_NOT_VISIBLE",
     '<html><head><style>button { outline: none; }</style></head>'
     '<body><button>go</button><div id="state-x"></div>'
     '<div id="error-x"></div></body></html>', None),
    ("FOCUS_ORDER_INVALID",
     '<html><body><div data-action="next">다음</div><div id="state-x"></div>'
     '<div id="error-x"></div></body></html>', None),
    ("DISABLED_REASON_MISSING",
     '<html><body><button disabled>go</button><div id="state-x"></div>'
     '<div id="error-x"></div></body></html>', None),
    ("REPLAY_POSITION_UNCLEAR",
     '<html><body><button data-action="next">다음</button><div id="state-x"></div>'
     '<div id="error-x"></div></body></html>', None),
    ("VALIDATION_FEEDBACK_DISCONNECTED",
     '<html><body><button>go</button><div id="state-x"></div>'
     '<script>fetch("viewer_contract.json");</script></body></html>',
     {"validation_rules": [{"rule": "x >= 0"}]}),
])
def test_operation_fixes_its_diagnosis(status, html, contract):
    """각 operation: precondition(진단 발화) → minimal patch → 같은 진단 소멸 (§7.2)."""
    out = _apply_for(html, status, contract)
    assert out is not None
    new_text, rec = out
    assert rec["operation_id"] == DIAGNOSIS_TO_OPERATION[status]
    assert f'data-ux-op="{rec["operation_id"]}"' in new_text
    surface = {"rel": "product/x/index.html", "text": new_text}
    remaining = [d for d in diagnose_surface(surface, contract or {}, Path("."))
                 if d["status"] == status]
    assert remaining == [], f"{status} 잔존"


def test_expose_primary_action_unhides_hidden_control():
    html = ('<html><head><style>.controls { display: none; }</style></head>'
            '<body><div class="controls"><button>go</button></div>'
            '<div id="state-x"></div><div id="error-x"></div></body></html>')
    diag = {"status": "ACTION_NOT_DISCOVERABLE", "surface": "product/x/index.html",
            "target": ".controls", "target_kind": "control", "evidence": "hidden",
            "category": "MACHINE_FIXABLE", "operation": "EXPOSE_PRIMARY_ACTION",
            "machine_fixable": True}
    out = apply_operation(html, diag, {})
    assert out is not None
    new_text, rec = out
    assert rec["operation_id"] == "EXPOSE_PRIMARY_ACTION"
    assert "display: initial" in new_text


def test_operations_are_idempotent_marker_blocks():
    out1 = _apply_for(_BROKEN_VIEWER, "NARROW_VIEWPORT_BROKEN")
    text1, _ = out1
    surface = {"rel": "x", "text": text1}
    # 강제로 같은 op 재적용 — marker block(style+meta)이 교체되고 중복되지 않는다
    diag = {"status": "NARROW_VIEWPORT_BROKEN", "surface": "x", "target": ".layout",
            "target_kind": "component", "evidence": "", "category": "MACHINE_FIXABLE",
            "operation": "STACK_FOR_NARROW_VIEWPORT", "machine_fixable": True}
    out2 = apply_operation(text1, diag, {})
    if out2 is not None:  # 재진단이 사라져 precondition 미충족(None)이어도 정상
        assert out2[0].count('<style data-ux-op="STACK_FOR_NARROW_VIEWPORT"') == 1
        assert out2[0].count('<meta name="viewport"') == 1
    assert text1.count('<style data-ux-op="STACK_FOR_NARROW_VIEWPORT"') == 1
    assert text1.count('<meta name="viewport"') == 1


def test_media_query_without_meta_viewport_still_broken():
    """2026-07-11 runtime smoke 실측 회귀: stacking media query가 있어도 meta viewport가
    없으면 모바일(fallback ~980px)에서 발화하지 않으므로 해소로 인정하지 않는다."""
    html = _BROKEN_VIEWER.replace(
        "</style>",
        "@media (max-width: 700px) { .layout { flex-direction: column; } }\n</style>")
    surface = {"rel": "product/viewer/index.html", "text": html}
    statuses = [d["status"] for d in diagnose_surface(surface, {}, Path("."))]
    assert "NARROW_VIEWPORT_BROKEN" in statuses
    diag = next(d for d in diagnose_surface(surface, {}, Path("."))
                if d["status"] == "NARROW_VIEWPORT_BROKEN")
    assert "meta viewport" in diag["evidence"]


def test_stack_op_injects_meta_viewport_when_absent():
    out = _apply_for(_BROKEN_VIEWER, "NARROW_VIEWPORT_BROKEN")
    new_text, _ = out
    assert new_text.count('<meta name="viewport"') == 1
    assert 'data-ux-op="STACK_FOR_NARROW_VIEWPORT"' in new_text
    assert "width=device-width" in new_text


def test_stack_op_keeps_product_own_meta_viewport():
    html = _BROKEN_VIEWER.replace(
        "<head>",
        '<head><meta name="viewport" content="width=device-width, initial-scale=1">')
    out = _apply_for(html, "NARROW_VIEWPORT_BROKEN")
    new_text, _ = out
    # 제품 자체 meta는 유지하고 marker meta를 추가하지 않는다
    assert new_text.count('<meta name="viewport"') == 1
    assert '<meta name="viewport"' in new_text
    assert 'data-ux-op="STACK_FOR_NARROW_VIEWPORT">' in new_text  # style block은 주입


def test_media_query_with_meta_viewport_resolved():
    html = _BROKEN_VIEWER.replace(
        "<head>",
        '<head><meta name="viewport" content="width=device-width, initial-scale=1">'
    ).replace(
        "</style>",
        "@media (max-width: 700px) { .layout { flex-direction: column; } }\n</style>")
    surface = {"rel": "product/viewer/index.html", "text": html}
    statuses = [d["status"] for d in diagnose_surface(surface, {}, Path("."))]
    assert "NARROW_VIEWPORT_BROKEN" not in statuses


def test_operation_record_has_full_spec_fields():
    out = _apply_for(_BROKEN_VIEWER, "NARROW_VIEWPORT_BROKEN")
    _, rec = out
    for key in ("operation_id", "target", "precondition", "patch_scope",
                "expected_effect", "forbidden_effects", "rollback_condition"):
        assert rec.get(key), key


def test_operation_rollback_on_failed_validation(tmp_path, monkeypatch):
    """적용 후에도 진단이 남으면 rollback 기록 + patch 미유지 (§9.3)."""
    import repo_idea_miner.factory_ux_polish as ux
    run = _make_ux_run(tmp_path)
    real = ux.apply_operation

    def sabotage(text, diag, contract):
        out = real(text, diag, contract)
        if out is None or diag["status"] != "NARROW_VIEWPORT_BROKEN":
            return out
        # marker는 넣되 실제 수리는 하지 않는 patch를 흉내낸다
        broken = out[0].replace("flex-direction: column;", "")
        return broken, out[1]

    monkeypatch.setattr(ux, "apply_operation", sabotage)
    res = ux.run_ux_polish(run_dir=run, apply=True)
    report = _load(run / "review/ux_polish/ux_polish_report.json")
    rolled = [o for o in report["operations"] if o["rolled_back"]]
    assert rolled and rolled[0]["operation_id"] == "STACK_FOR_NARROW_VIEWPORT"
    assert res["ux_status"] in ("PARTIAL", "FAILED")
    assert res["ok"] is False


def test_operation_budget_limits_patches(tmp_path, monkeypatch):
    import repo_idea_miner.factory_ux_polish as ux
    run = _make_ux_run(tmp_path)
    monkeypatch.setattr(ux, "MAX_OPERATIONS_PER_PRODUCT", 1)
    res = ux.run_ux_polish(run_dir=run, apply=True)
    report = _load(run / "review/ux_polish/ux_polish_report.json")
    assert len([o for o in report["operations"] if o["validation"] == "PASS"]) == 1
    assert any("budget" in p for p in res["problems"])
    assert res["ux_status"] == "PARTIAL"
    assert res["ok"] is False  # machine-fixable 잔존 → included 금지


# ---------------------------------------------------------------- §19.4 Runtime (합성 run)

@pytest.mark.skipif(not _node_available(), reason="node 없음")
def test_apply_fixes_synthetic_run_end_to_end(tmp_path):
    run = _make_ux_run(tmp_path)
    plan = run_ux_polish(run_dir=run, apply=False)
    assert plan["status"] == "PLAN_ONLY"
    fix_statuses = {f["status"] for f in plan["plan"]["machine_fixable"]}
    assert fix_statuses == {"NARROW_VIEWPORT_BROKEN", "FOCUS_ORDER_INVALID"}

    res = run_ux_polish(run_dir=run, apply=True)
    assert res["status"] == "APPLIED" and res["ux_status"] == "APPLIED"
    assert res["ok"] is True and res["applied"] is True
    assert res["patched_files"] == ["product/viewer/index.html"]

    evidence = _load(run / "review/ux_polish/ux_evidence.json")
    assert evidence["primary_action_visible"] is True
    assert evidence["state_indicator_visible"] is True
    assert evidence["feedback_channel_visible"] is True
    assert evidence["error_channel_visible"] is True
    assert all(v["narrow"]["pass"] for v in evidence["viewport_results"].values())
    assert all(k["pass"] for k in evidence["keyboard_results"].values())
    assert all(c["status"] == "PASS" for c in evidence["js_syntax"].values())
    assert evidence["runtime_action_refs"]  # 기존 runner-backed 실증 참조
    assert evidence["ux_provenance"]["fresh"] is True

    patched = (run / "workspace/product/viewer/index.html").read_text(encoding="utf-8")
    assert 'data-ux-op="STACK_FOR_NARROW_VIEWPORT"' in patched
    assert 'data-ux-op="FIX_FOCUS_ORDER"' in patched
    assert "@media (max-width" in patched
    # 금지 리터럴 없음 (mock/fallback·비결정 소스·viewer raw key)
    for lit in ("Math.random", "Date.now", "edge.from", "ev.type"):
        assert lit not in patched.split('data-ux-op')[1], lit


@pytest.mark.skipif(not _node_available(), reason="node 없음")
def test_ux_ready_when_no_machine_fixable_defects(tmp_path):
    run = _make_ux_run(tmp_path)
    # 결함 viewer를 건강한 콘솔형 표면으로 교체 → machine-fixable 0
    _write(run / "workspace/product/viewer/index.html", _GOOD_CONSOLE)
    res = run_ux_polish(run_dir=run, apply=True)
    assert res["status"] == "UX_READY" and res["ux_status"] == "UX_READY"
    assert res["applied"] is False and res["patched_files"] == []
    assert res["ok"] is True  # 진단·검증 완료 = 실증 (patch 유무가 기준이 아님)
    report = _load(run / "review/ux_polish/ux_polish_report.json")
    assert report["ux_polish_included"] is True


def test_no_silent_success_without_runtime_refs(tmp_path):
    run = _make_ux_run(tmp_path)
    (run / "review/draft_execution/draft_execution_report.json").unlink()
    res = run_ux_polish(run_dir=run, apply=True)
    assert res["ok"] is False  # HTML 생성만으로 성공 처리하지 않는다 (§11)
    report = _load(run / "review/ux_polish/ux_polish_report.json")
    assert report["ux_polish_included"] is False
    assert any("runtime action" in p for p in res["problems"])


def test_unsupported_run_without_surfaces(tmp_path):
    run = tmp_path / "nosurface"
    (run / "workspace").mkdir(parents=True)
    res = run_ux_polish(run_dir=run, apply=True)
    assert res["ux_status"] == "UNSUPPORTED"
    assert res["status"] == "PRECONDITION_UNSUPPORTED"
    assert res["applied"] is False


# ---------------------------------------------------------------- §19.5 Product Loop

def test_lane_selection_and_registry():
    assert GAP_TO_LANE["UX_POLISH_REQUIRED"] == "UX_POLISH"
    assert "factory_ux_polish" in LANE_EXECUTOR_ROUTES["UX_POLISH"]
    assert LANE_EXECUTORS["UX_POLISH"].__name__ == "_exec_ux_polish"


@pytest.mark.skipif(not _node_available(), reason="node 없음")
def test_execute_lane_applied_creates_child_and_keeps_parent(tmp_path):
    run = _make_ux_run(tmp_path)
    before = (run / "workspace/product/viewer/index.html").read_bytes()
    res = execute_lane("UX_POLISH", {
        "parent_run_dir": run, "children_root": tmp_path / "children",
        "iteration_dir": tmp_path / "iter", "mode": "mock", "timeout": 60.0})
    assert res["status"] == "APPLIED"
    assert res["allowed_scope_check"] == "PASS"
    assert res["protected_hash_check"] == "PASS"
    assert (run / "workspace/product/viewer/index.html").read_bytes() == before
    child = Path(res["child_run_dir"])
    assert 'data-ux-op="FIX_FOCUS_ORDER"' in \
        (child / "workspace/product/viewer/index.html").read_text(encoding="utf-8")


def test_execute_lane_blocked_on_upstream_defect(tmp_path):
    run = _make_ux_run(tmp_path)
    (run / "workspace/product/viewer/viewer_contract.json").write_text(
        "{broken", encoding="utf-8")
    res = execute_lane("UX_POLISH", {
        "parent_run_dir": run, "children_root": tmp_path / "children",
        "iteration_dir": tmp_path / "iter", "mode": "mock", "timeout": 60.0})
    assert res["status"] == "BLOCKED"
    assert res["failure_signature"]  # §10 반복 시 중단 신호


def test_execute_lane_blocked_on_unsupported(tmp_path):
    run = tmp_path / "nosurface"
    (run / "workspace").mkdir(parents=True)
    res = execute_lane("UX_POLISH", {
        "parent_run_dir": run, "children_root": tmp_path / "children",
        "iteration_dir": tmp_path / "iter", "mode": "mock", "timeout": 60.0})
    assert res["status"] == "BLOCKED"


def _gap_inputs(has_report: bool, loop_closed: bool = True, sixty: bool = True):
    evidence = {
        "facts": {"evidence_sufficient": True, "viewer_exists": True,
                  "viewer_reads_replay": True, "mismatches": [], "authoring_ui": True,
                  "has_interaction_report": True, "has_execution_report": True,
                  "has_ux_polish_report": has_report, "gate_fail": False},
        "product_loop": {"can_execute_primary_action": True,
                         "product_loop_closed": loop_closed},
    }
    quality = {"fields": {"user_can_understand_value_in_60s": sixty}}
    stage_label = {"stage": "EXECUTION_CANDIDATE"}
    return evidence, quality, stage_label


def test_gap_stays_without_ux_evidence():
    ev, q, st = _gap_inputs(has_report=False)
    assert derive_primary_gap(ev, q, st) == "UX_POLISH_REQUIRED"


def test_gap_removed_with_ux_evidence():
    ev, q, st = _gap_inputs(has_report=True)
    assert derive_primary_gap(ev, q, st) is None


def test_gap_stays_when_loop_open_even_with_report():
    ev, q, st = _gap_inputs(has_report=True, loop_closed=False)
    assert derive_primary_gap(ev, q, st) == "UX_POLISH_REQUIRED"


def test_evidence_reads_ux_report_only_when_included(tmp_path):
    run = _make_ux_run(tmp_path)
    facts = extract_artifact_evidence(run)["facts"]
    assert facts["has_ux_polish_report"] is False
    _dump(run / "review/ux_polish/ux_polish_report.json",
          {"applied": True, "ux_status": "APPLIED", "ux_polish_included": True})
    assert extract_artifact_evidence(run)["facts"]["has_ux_polish_report"] is True
    _dump(run / "review/ux_polish/ux_polish_report.json",
          {"applied": True, "ux_status": "APPLIED", "ux_polish_included": False})
    assert extract_artifact_evidence(run)["facts"]["has_ux_polish_report"] is False
    # UX_READY도 실증이다 — patch 없이 검증만으로 included면 인정
    _dump(run / "review/ux_polish/ux_polish_report.json",
          {"applied": False, "ux_status": "UX_READY", "ux_polish_included": True})
    assert extract_artifact_evidence(run)["facts"]["has_ux_polish_report"] is True


def test_executor_never_sets_product_status():
    src = Path("repo_idea_miner/factory_ux_polish.py").read_text(encoding="utf-8")
    for token in ("product_reviews", "PRODUCT_CANDIDATE", "recommended_fitness",
                  "set_owner_review", "green_base"):
        assert token not in src, token


# ---------------------------------------------------------------- §19.5 Validator

def _valid_report(run: Path, **over) -> dict:
    report = {
        "applied": True, "ux_status": "APPLIED", "ux_polish_included": True,
        "diagnosis_before": [{"status": "NARROW_VIEWPORT_BROKEN"}],
        "operations": [{"operation_id": "STACK_FOR_NARROW_VIEWPORT",
                        "validation": "PASS", "rolled_back": False}],
        "patched_files": ["product/viewer/index.html"],
    }
    report.update(over)
    _dump(run / "review/ux_polish/ux_polish_report.json", report)
    return report


def _valid_evidence(run: Path, **over) -> dict:
    evidence = {
        "viewport_results": {"product/viewer/index.html": {"narrow": {"pass": True}}},
        "keyboard_results": {"product/viewer/index.html": {"pass": True}},
        "js_syntax": {"product/viewer/index.html": {"status": "PASS"}},
        "runtime_action_refs": {"draft_execution": {"ref": "review/..."}},
        "ux_provenance": {"fresh": True, "started_at": "2026-07-11T00:00:00"},
    }
    evidence.update(over)
    _dump(run / "review/ux_polish/ux_evidence.json", evidence)
    _dump(run / "review/ux_polish/ux_contract.json", {"ux_target_id": "x"})
    _dump(run / "review/ux_polish/ux_diagnosis.json", [])
    return evidence


def test_validator_passes_honest_report(tmp_path):
    _valid_report(tmp_path)
    _valid_evidence(tmp_path)
    assert _check_ux_polish_lane(tmp_path) == []


def test_validator_blocks_forbidden_and_unknown_operations(tmp_path):
    _valid_report(tmp_path, operations=[
        {"operation_id": "MAKE_BEAUTIFUL", "validation": "PASS", "rolled_back": False}])
    _valid_evidence(tmp_path)
    problems = _check_ux_polish_lane(tmp_path)
    assert any("금지된 자유 형식" in p for p in problems)
    _valid_report(tmp_path, operations=[
        {"operation_id": "SOMETHING_ELSE", "validation": "PASS", "rolled_back": False}])
    assert any("catalog 밖" in p for p in _check_ux_polish_lane(tmp_path))


def test_validator_blocks_budget_overrun(tmp_path):
    ops = [{"operation_id": "CLARIFY_LABEL", "validation": "PASS", "rolled_back": False}
           for _ in range(MAX_OPERATIONS_PER_PRODUCT + 1)]
    _valid_report(tmp_path, operations=ops)
    _valid_evidence(tmp_path)
    assert any("budget 초과" in p for p in _check_ux_polish_lane(tmp_path))


def test_validator_blocks_patch_outside_product(tmp_path):
    _valid_report(tmp_path, patched_files=["src/core/engine.py"])
    _valid_evidence(tmp_path)
    assert any("product/ 밖" in p for p in _check_ux_polish_lane(tmp_path))


def test_validator_blocks_included_overclaims(tmp_path):
    _valid_report(tmp_path, applied=False, ux_status="FAILED")
    _valid_evidence(tmp_path)
    assert any("과장" in p for p in _check_ux_polish_lane(tmp_path))

    _valid_report(tmp_path)
    _valid_evidence(tmp_path, viewport_results={
        "product/viewer/index.html": {"narrow": {"pass": False}}})
    assert any("narrow viewport FAIL" in p for p in _check_ux_polish_lane(tmp_path))

    _valid_evidence(tmp_path, keyboard_results={
        "product/viewer/index.html": {"pass": False}})
    assert any("keyboard" in p for p in _check_ux_polish_lane(tmp_path))

    _valid_evidence(tmp_path, runtime_action_refs={})
    assert any("runtime action" in p for p in _check_ux_polish_lane(tmp_path))

    _valid_evidence(tmp_path, ux_provenance={"fresh": False})
    assert any("provenance" in p for p in _check_ux_polish_lane(tmp_path))


def test_validator_ignores_run_without_marker(tmp_path):
    assert _check_ux_polish_lane(tmp_path) == []


def test_validator_accepts_all_outcome_enum_values(tmp_path):
    for status in UX_STATUSES:
        _valid_report(tmp_path, ux_status=status, ux_polish_included=False, applied=False)
        problems = _check_ux_polish_lane(tmp_path)
        assert not any("알 수 없는" in p for p in problems), status


# ---------------------------------------------------------------- §19.6 Regression (probe07)

def _probe_ws(tmp_path: Path, *, digest_ok: bool = True, with_fetch: bool = True) -> Path:
    ws = tmp_path / "ws"
    _dump(ws / "replay" / "replay_scenario_001.json", {"ok": True, "events": []})
    digest = hashlib.sha256(
        (ws / "replay" / "replay_scenario_001.json").read_bytes()).hexdigest()
    if not digest_ok:
        digest = "0" * 64
    _dump(ws / "product" / "viewer" / "viewer_contract.json", {
        "source_artifact_refs": [
            {"ref": "replay/replay_scenario_001.json", "sha256": digest}]})
    html = ('<html><script>fetch("viewer_contract.json");</script></html>'
            if with_fetch else "<html></html>")
    _write(ws / "product" / "viewer" / "index.html", html)
    return ws


def test_probe07_contract_mediated_replay_read_accepted(tmp_path):
    ws = _probe_ws(tmp_path)
    srcs = {"product/viewer/index.html":
            (ws / "product/viewer/index.html").read_text(encoding="utf-8")}
    assert _contract_mediated_replay_read(ws, srcs) is True


def test_probe07_rejects_digest_mismatch(tmp_path):
    ws = _probe_ws(tmp_path, digest_ok=False)
    srcs = {"product/viewer/index.html":
            (ws / "product/viewer/index.html").read_text(encoding="utf-8")}
    assert _contract_mediated_replay_read(ws, srcs) is False


def test_probe07_requires_contract_fetch_in_surface(tmp_path):
    ws = _probe_ws(tmp_path, with_fetch=False)
    srcs = {"product/viewer/index.html":
            (ws / "product/viewer/index.html").read_text(encoding="utf-8")}
    assert _contract_mediated_replay_read(ws, srcs) is False


def test_probe07_requires_existing_replay_file(tmp_path):
    ws = _probe_ws(tmp_path)
    (ws / "replay" / "replay_scenario_001.json").unlink()
    srcs = {"product/viewer/index.html":
            (ws / "product/viewer/index.html").read_text(encoding="utf-8")}
    assert _contract_mediated_replay_read(ws, srcs) is False
