# Phase 2C-2 테스트: #47 viewer 최소 node draft editor (schema 호환 draft state/validation/roundtrip, 주문서 §26).
import json
import shutil
from pathlib import Path

import pytest

from repo_idea_miner.cli import main
from repo_idea_miner.factory_product_editor import (
    EditorGraphModel,
    build_editor_block,
    check_draft_roundtrip,
    check_draft_schema_compatible,
    check_handler_binding,
    check_static_dom,
    compute_editor_protected_hashes,
    extract_supported_node_types,
    inject_editor,
    run_model_level_smoke,
    run_product_editor,
)
from repo_idea_miner.factory_product_polish import run_product_polish
from repo_idea_miner.factory_review import run_review_package
from repo_idea_miner.factory_validate import (
    _check_phase2c2,
    detect_phase2c2_run,
    validate_product_run_dir,
)

# 2C-0/2C-1 테스트의 합성 green run 빌더를 재사용한다
from test_factory_review_2c0 import (  # noqa: E402
    _REPLAY_001,
    _VIEWER_MISMATCH,
    _build_green_run,
    _dump,
)

FIXTURE_47 = Path("runs/factory_20260709_072220")
_TYPES = ["ADD_10", "INPUT", "OUTPUT"]


def _write_decision(run: Path):
    (run / "user_review_decision.md").write_text(
        "# 검수 결과\n## 최종 결정\n- [x] Phase 2C-2 진행\n", encoding="utf-8")


def _editor_ready_run(tmp_path) -> Path:
    """green run → 2C-0 review → 2C-1 polish(NEEDS_PRODUCT_POLISH) → 사용자 결정 기록."""
    run = _build_green_run(tmp_path, _VIEWER_MISMATCH)
    run_review_package(run_dir=run)
    out = run_product_polish(run_dir=run, apply=True)
    assert out["recommended_fitness"] == "NEEDS_PRODUCT_POLISH"
    _write_decision(run)
    return run


def _edited_run(tmp_path):
    run = _editor_ready_run(tmp_path)
    out = run_product_editor(run_dir=run, apply=True)
    return run, out


# ---------------------------------------------------------------- Group A: EditorGraphModel 단위 (§13)

def test_model_add_edit_delete_node():
    m = EditorGraphModel(_TYPES)
    m.load_from_replay(_REPLAY_001)
    assert len(m.nodes) == 2
    r = m.add_node("X", "ADD_10")
    assert r["ok"] and r["id"] not in ("a", "b")
    assert m.edit_node(r["id"], label="Y", type_="OUTPUT")["ok"]
    assert m.edit_node("ghost")["ok"] is False


def test_model_delete_node_removes_incident_edges():
    m = EditorGraphModel(_TYPES)
    m.load_from_replay(_REPLAY_001)  # edge a->b
    m.delete_node("b")
    assert all(e["source_id"] != "b" and e["target_id"] != "b" for e in m.edges)
    assert m.edges == []  # dangling 없음


def test_model_add_delete_edge():
    m = EditorGraphModel(_TYPES)
    m.load_from_replay(_REPLAY_001)
    n = m.add_node("c", "OUTPUT")["id"]
    assert m.add_edge("b", n)["ok"]
    idx = len(m.edges) - 1
    assert m.delete_edge(idx)["ok"]
    assert m.delete_edge(99)["ok"] is False


def test_model_unsupported_type_blocked():
    m = EditorGraphModel(_TYPES)
    r = m.add_node("x", "banana")
    assert r["ok"] is False and "unsupported" in r["error"]


def test_model_validation_duplicate_id():
    m = EditorGraphModel(_TYPES)
    m.nodes = [{"id": "n", "type": "INPUT", "label": "a"},
               {"id": "n", "type": "INPUT", "label": "b"}]
    assert any("duplicate" in e for e in m.validate()["errors"])


def test_model_validation_missing_endpoint():
    m = EditorGraphModel(_TYPES)
    m.nodes = [{"id": "n1", "type": "INPUT", "label": "a"}]
    m.edges = [{"source_id": "n1", "target_id": "ghost"}]
    assert any("does not exist" in e for e in m.validate()["errors"])


def test_model_validation_cycle():
    m = EditorGraphModel(_TYPES)
    m.nodes = [{"id": "a", "type": "INPUT", "label": "a"},
               {"id": "b", "type": "OUTPUT", "label": "b"}]
    m.edges = [{"source_id": "a", "target_id": "b"}, {"source_id": "b", "target_id": "a"}]
    assert "cycle detected" in m.validate()["errors"]


def test_model_validation_self_loop():
    m = EditorGraphModel(_TYPES)
    m.nodes = [{"id": "a", "type": "INPUT", "label": "a"}]
    m.edges = [{"source_id": "a", "target_id": "a"}]
    assert any("self-loop" in e for e in m.validate()["errors"])


def test_model_validation_isolated_warning():
    m = EditorGraphModel(_TYPES)
    m.nodes = [{"id": "a", "type": "INPUT", "label": "a"},
               {"id": "b", "type": "OUTPUT", "label": "b"}]
    assert any("isolated" in w for w in m.validate()["warnings"])


def test_model_empty_graph_invalid():
    m = EditorGraphModel(_TYPES)
    assert any("no nodes" in e for e in m.validate()["errors"])


# ---------------------------------------------------------------- Group B: draft 호환/roundtrip (§11, §12)

def test_draft_schema_compatible_pass():
    m = EditorGraphModel(_TYPES)
    m.load_from_replay(_REPLAY_001)
    draft = m.build_draft("runs/x", 47)
    res = check_draft_schema_compatible(draft, _TYPES)
    assert res["compatible"] is True, res["reasons"]
    assert draft["metadata"]["source"] == "phase2c2_editor_draft"


def test_draft_from_to_only_edge_incompatible():
    draft = {"nodes": [{"id": "a", "type": "INPUT", "label": "a"}],
             "edges": [{"from": "a", "to": "a"}],
             "metadata": {"source": "phase2c2_editor_draft"}}
    res = check_draft_schema_compatible(draft, _TYPES)
    assert res["compatible"] is False
    assert any("from/to" in r for r in res["reasons"])


def test_draft_missing_source_id_incompatible():
    draft = {"nodes": [{"id": "a", "type": "INPUT", "label": "a"}],
             "edges": [{"target_id": "a"}], "metadata": {}}
    res = check_draft_schema_compatible(draft, _TYPES)
    assert res["compatible"] is False
    assert any("missing source_id" in r for r in res["reasons"])


def test_draft_dangling_ref_incompatible():
    draft = {"nodes": [{"id": "a", "type": "INPUT", "label": "a"}],
             "edges": [{"source_id": "a", "target_id": "ghost"}], "metadata": {}}
    res = check_draft_schema_compatible(draft, _TYPES)
    assert res["compatible"] is False


def test_draft_unsupported_type_incompatible():
    draft = {"nodes": [{"id": "a", "type": "banana", "label": "a"}], "edges": [], "metadata": {}}
    assert check_draft_schema_compatible(draft, _TYPES)["compatible"] is False


def test_draft_label_not_string_incompatible():
    draft = {"nodes": [{"id": "a", "type": "INPUT", "label": 5}], "edges": [], "metadata": {}}
    assert check_draft_schema_compatible(draft, _TYPES)["compatible"] is False


def test_draft_roundtrip_preserves_and_regenerates():
    m = EditorGraphModel(_TYPES)
    m.load_from_replay(_REPLAY_001)
    draft = m.build_draft("runs/x", 47)
    rt = check_draft_roundtrip(draft)
    assert rt["pass"] is True
    assert rt["nodes_preserved"] and rt["display_model_regenerated"]


# ---------------------------------------------------------------- Group C: supported_node_types (§8)

def test_extract_types_from_replay(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_MISMATCH)
    types, src = extract_supported_node_types(run / "final_artifact")
    assert types and src == "replay_node_types"
    assert "INPUT" in types and "ADD_10" in types


def test_extract_types_prefers_contract(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_MISMATCH)
    fd = run / "final_artifact"
    c = json.loads((fd / "core_contract.json").read_text("utf-8"))
    c["supported_node_types"] = ["FOO", "BAR"]
    _dump(fd / "core_contract.json", c)
    types, src = extract_supported_node_types(fd)
    assert types == ["BAR", "FOO"] and src.endswith("supported_node_types")


def test_extract_types_none_when_absent(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_MISMATCH)
    fd = run / "final_artifact"
    for p in (fd / "replay").glob("replay_*.json"):
        d = json.loads(p.read_text("utf-8"))
        for n in d["final_state"]["nodes"].values():
            n.pop("type", None)
        _dump(p, d)
    types, src = extract_supported_node_types(fd)
    assert types == [] and src == "none"


def test_add_node_disabled_when_no_supported_types():
    m = EditorGraphModel([])
    assert m.add_node("x", "INPUT")["ok"] is False


def test_types_absent_blocks_apply(tmp_path):
    run = _editor_ready_run(tmp_path)
    for p in (run / "final_artifact" / "replay").glob("replay_*.json"):
        d = json.loads(p.read_text("utf-8"))
        for n in d["final_state"]["nodes"].values():
            n.pop("type", None)
        _dump(p, d)
    out = run_product_editor(run_dir=run, apply=True)
    assert out["status"] == "CANNOT_EDIT"
    assert any("supported_node_types 추출 실패" in x for x in out["problems"])


# ---------------------------------------------------------------- Group D: 주입 / JS 구문 (§17)

def test_editor_block_no_forbidden_literals():
    block = build_editor_block(_TYPES, "runs/x", 47)
    for lit in ("edge.from", "edge.to", "ev.type", "ev.message", "node.x", "node.y",
                "Math.random", "Date.now", "new Date", "performance.now"):
        assert lit not in block, lit
    import re
    assert not re.search(r"\.type\b", block)  # bracket 표기만 사용
    for fn in ("p2c2LoadFromReplay", "p2c2AddNodeModel", "p2c2AddEdgeModel",
               "p2c2ValidateGraph", "p2c2BuildDraft", "p2c2DraftSchemaCompatible",
               "p2c2Roundtrip"):
        assert fn in block


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_injected_viewer_scripts_valid_js(tmp_path):
    import re
    import subprocess

    run = _editor_ready_run(tmp_path)
    v = run / "final_artifact" / "product" / "viewer" / "index.html"
    inject_editor(v, _TYPES, "runs/x", 47)
    html = v.read_text("utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    assert len(scripts) >= 2  # 폴리시 script 보존 + editor script
    for i, s in enumerate(scripts):
        js = tmp_path / f"s{i}.js"
        js.write_text(s, encoding="utf-8")
        r = subprocess.run([shutil.which("node"), "--check", str(js)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_inject_preserves_polish_script(tmp_path):
    run = _editor_ready_run(tmp_path)
    v = run / "final_artifact" / "product" / "viewer" / "index.html"
    inject_editor(v, _TYPES, "runs/x", 47)
    html = v.read_text("utf-8")
    assert "normalizeReplayForViewer" in html  # 폴리시 script 보존
    assert "PHASE2C2_EDITOR_START" in html


def test_inject_idempotent(tmp_path):
    run = _editor_ready_run(tmp_path)
    v = run / "final_artifact" / "product" / "viewer" / "index.html"
    inject_editor(v, _TYPES, "runs/x", 47)
    inject_editor(v, _TYPES, "runs/x", 47)
    html = v.read_text("utf-8")
    assert html.count("PHASE2C2_EDITOR_START") == 1  # 재주입 안전


# ---------------------------------------------------------------- Group E: static DOM + handler (§15)

def test_static_dom_and_handler_pass():
    block = build_editor_block(_TYPES, "runs/x", 47)
    assert check_static_dom(block)["status"] == "PASS"
    assert check_handler_binding(block)["status"] == "PASS"


def test_static_dom_detects_missing():
    assert check_static_dom("<html></html>")["status"] == "FAIL"


# ---------------------------------------------------------------- Group F: model smoke (§16, §21)

def test_model_smoke_pass_on_replay():
    m = run_model_level_smoke(_TYPES, _REPLAY_001, "runs/x", 47)
    assert m["model_level_smoke_pass"] is True, m["failures"]
    assert m["delete_node_removes_incident_edges"] is True
    assert m["from_to_only_edge_rejected"] is True
    assert m["original_replay_unchanged"] is True


# ---------------------------------------------------------------- Group G: dry-run / apply / hash

def test_dry_run_does_not_modify(tmp_path):
    run = _editor_ready_run(tmp_path)
    v = run / "final_artifact" / "product" / "viewer" / "index.html"
    before = v.read_text("utf-8")
    out = run_product_editor(run_dir=run, apply=False)
    assert out["status"] == "DRY_RUN_PASS"
    assert v.read_text("utf-8") == before
    assert not (run / "review" / "phase2c2" / "phase2c2_editor_report.json").is_file()


def test_dry_run_plan_has_features_and_rules(tmp_path):
    run = _editor_ready_run(tmp_path)
    out = run_product_editor(run_dir=run, apply=False)
    plan = out["plan"]
    assert plan["planned_editor_features"]
    assert plan["draft_compatibility_rules"] and plan["draft_roundtrip_rules"]
    assert plan["ui_binding_plan"]


def test_apply_requires_user_decision(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_MISMATCH)
    run_review_package(run_dir=run)
    run_product_polish(run_dir=run, apply=True)
    # 결정 파일 없음
    out = run_product_editor(run_dir=run, apply=True)
    assert out["status"] == "CANNOT_EDIT"
    assert any("Phase 2C-2 진행 결정" in p for p in out["problems"])


def test_apply_requires_prior_polish(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_MISMATCH)
    _write_decision(run)
    out = run_product_editor(run_dir=run, apply=True)
    assert out["status"] == "CANNOT_EDIT"
    assert any("2C-1" in p or "polish" in p for p in out["problems"])


def test_apply_protected_hash_unchanged(tmp_path):
    run = _editor_ready_run(tmp_path)
    before = compute_editor_protected_hashes(run)
    out = run_product_editor(run_dir=run, apply=True)
    after = compute_editor_protected_hashes(run)
    assert out["status"] == "EDITOR_ADDED"
    assert out["hash_status"] == "PASS"
    assert before == after  # src/golden/fixtures/contract/replay/phase2c0/2c1 불변


def test_apply_changes_only_product(tmp_path):
    run, out = _edited_run(tmp_path)
    diff = json.loads((run / "review" / "phase2c2" / "phase2c2_diff_summary.json").read_text("utf-8"))
    assert diff["core_golden_fixtures_contract_replay_changed"] is False
    assert all("/product/" in c for c in diff["product_files_changed"])


def test_apply_does_not_overwrite_phase2c0_2c1(tmp_path):
    run = _editor_ready_run(tmp_path)
    p2c1 = run / "review" / "phase2c1" / "product_fitness_report_after_polish.json"
    before = p2c1.read_text("utf-8")
    run_product_editor(run_dir=run, apply=True)
    assert p2c1.read_text("utf-8") == before  # 2C-1 산출물 불변


def test_apply_original_replay_unchanged(tmp_path):
    run, out = _edited_run(tmp_path)
    es = out["editor_smoke"]
    assert es["original_replay_unchanged"] is True
    replay = json.loads((run / "final_artifact" / "replay" / "replay_scenario_001.json").read_text("utf-8"))
    for n in replay["final_state"]["nodes"].values():
        assert "x" not in n  # 좌표 미추가


# ---------------------------------------------------------------- Group H: fitness + candidate (§22)

def test_apply_yields_draft_editor_candidate(tmp_path):
    """editor 주입으로 authoring 감지 → PRODUCT_CANDIDATE(draft editor candidate) + limitation 명시."""
    run, out = _edited_run(tmp_path)
    assert out["recommended_fitness"] == "PRODUCT_CANDIDATE"
    fit = out["fitness"]
    assert fit["draft_editor_candidate"] is True
    assert fit["runner_backed_execution_included"] is False
    fj = json.loads((run / "review" / "phase2c2"
                     / "product_fitness_report_after_editor.json").read_text("utf-8"))
    assert "runner-backed execution not included" in " ".join(fj["limitations"])


def test_all_required_outputs_generated(tmp_path):
    from repo_idea_miner.factory_product_editor import REQUIRED_OUTPUTS
    run, out = _edited_run(tmp_path)
    rd = run / "review" / "phase2c2"
    for rel in REQUIRED_OUTPUTS:
        assert (rd / rel).is_file(), rel


def test_editor_smoke_all_true(tmp_path):
    run, out = _edited_run(tmp_path)
    es = json.loads((run / "review" / "phase2c2" / "editor_smoke_review.json").read_text("utf-8"))
    for key in ("editor_mode_exists", "loads_replay_into_editor_state", "supported_node_types_loaded",
                "add_node_supported", "edit_node_supported", "delete_node_supported",
                "delete_node_removes_incident_edges", "add_edge_supported", "delete_edge_supported",
                "graph_validation_supported", "draft_schema_compatible", "draft_roundtrip_pass",
                "draft_export_supported", "model_level_smoke_pass", "ui_binding_evidence_pass",
                "original_replay_unchanged"):
        assert es[key] is True, key
    assert es["runner_backed_execution_included"] is False


# ---------------------------------------------------------------- Group I: validate 규칙 (§24)

def _write_min_editor(run_dir: Path, *, recommended="PRODUCT_CANDIDATE", hash_status="PASS",
                      protected_changed=False, product_changed=None, es_overrides=None,
                      js_status="PASS", dom_status="PASS", hb_status="PASS",
                      compat=True, roundtrip=True, runner_backed=False, replay_unchanged=True,
                      limitations=None, draft_candidate=None):
    rd = run_dir / "review" / "phase2c2"
    product_changed = product_changed if product_changed is not None else \
        ["final_artifact/product/viewer/index.html"]
    es = {
        "editor_mode_exists": True, "loads_replay_into_editor_state": True,
        "supported_node_types_loaded": True, "add_node_supported": True,
        "edit_node_supported": True, "delete_node_supported": True,
        "delete_node_removes_incident_edges": True, "add_edge_supported": True,
        "delete_edge_supported": True, "graph_validation_supported": True,
        "draft_schema_compatible": compat, "draft_roundtrip_pass": roundtrip,
        "draft_export_supported": True, "model_level_smoke_pass": True,
        "ui_binding_evidence_pass": True, "js_syntax_status": js_status,
        "original_replay_unchanged": replay_unchanged,
        "runner_backed_execution_included": runner_backed, "critical_failures": [],
    }
    if es_overrides:
        es.update(es_overrides)
    if draft_candidate is None:
        draft_candidate = recommended == "PRODUCT_CANDIDATE"
    if limitations is None:
        limitations = ["runner-backed execution not included", "editor validation only"]
    scores = {"Core usefulness": 5, "Interaction clarity": 4, "Product layer usefulness": 4,
              "Demo understandability": 4, "Extension potential": 4, "Evidence quality": 5,
              "Anti-hardcode confidence": 4}
    for rel in ("phase2c2_editor_plan.md", "phase2c2_editor_report.md",
                "product_fitness_report_after_editor.md"):
        (rd / rel).parent.mkdir(parents=True, exist_ok=True)
        (rd / rel).write_text("# stub\n", encoding="utf-8")
    _dump(rd / "phase2c2_editor_plan.json", {})
    _dump(rd / "phase2c2_editor_report.json", {"applied": True})
    _dump(rd / "phase2c2_diff_summary.json", {
        "core_golden_fixtures_contract_replay_changed": protected_changed,
        "product_files_changed": product_changed})
    _dump(rd / "phase2c2_hash_check.json", {"status": hash_status, "changed": []})
    _dump(rd / "viewer_js_syntax_check.json", {"status": js_status})
    _dump(rd / "viewer_static_dom_check.json", {"status": dom_status})
    _dump(rd / "viewer_handler_binding_check.json", {"status": hb_status})
    _dump(rd / "viewer_smoke_after_editor.json", {"product_viewer_exists": True})
    _dump(rd / "editor_smoke_review.json", es)
    _dump(rd / "draft_schema_compatibility.json", {"compatible": compat})
    _dump(rd / "draft_roundtrip_check.json", {"pass": roundtrip})
    _dump(rd / "product_fitness_report_after_editor.json", {
        "recommended_fitness": recommended, "draft_editor_candidate": draft_candidate,
        "runner_backed_execution_included": runner_backed, "limitations": limitations,
        "scores": scores, "criteria": [{"criterion": k, "score": v, "evidence": ["x"]}
                                       for k, v in scores.items()], "critical_red_flags": []})
    _dump(rd / "phase2c2_dashboard_summary.json", {"recommended_fitness": recommended})
    return rd


def test_detect_marker(tmp_path):
    run = tmp_path / "r"
    run.mkdir()
    assert detect_phase2c2_run(run) is False
    _write_min_editor(run)
    assert detect_phase2c2_run(run) is True


def test_validate_clean_editor_passes(tmp_path):
    run = tmp_path / "r"
    _write_min_editor(run)
    assert _check_phase2c2(run) == []


def test_validate_no_marker_no_check(tmp_path):
    run = tmp_path / "r"
    run.mkdir()
    assert _check_phase2c2(run) == []


def test_validate_protected_changed_fails(tmp_path):
    run = tmp_path / "r"
    _write_min_editor(run, hash_status="FAIL")
    assert any("보호 대상" in p for p in _check_phase2c2(run))


def test_validate_replay_changed_fails(tmp_path):
    run = tmp_path / "r"
    _write_min_editor(run, protected_changed=True)
    assert any("golden/fixtures/contract/replay 변경" in p for p in _check_phase2c2(run))


def test_validate_change_outside_product_fails(tmp_path):
    run = tmp_path / "r"
    _write_min_editor(run, product_changed=["final_artifact/src/runner.py"])
    assert any("허용 범위 밖" in p for p in _check_phase2c2(run))


def test_validate_runner_backed_true_fails(tmp_path):
    run = tmp_path / "r"
    _write_min_editor(run, recommended="NEEDS_PRODUCT_POLISH", runner_backed=True)
    assert any("runner_backed_execution_included=true" in p for p in _check_phase2c2(run))


def test_validate_replay_changed_flag_fails(tmp_path):
    run = tmp_path / "r"
    _write_min_editor(run, recommended="NEEDS_PRODUCT_POLISH", replay_unchanged=False)
    assert any("original_replay_unchanged=false" in p for p in _check_phase2c2(run))


def test_validate_candidate_editor_mode_missing_fails(tmp_path):
    run = tmp_path / "r"
    _write_min_editor(run, es_overrides={"editor_mode_exists": False})
    assert any("editor_mode_exists != true" in p for p in _check_phase2c2(run))


def test_validate_candidate_no_add_node_fails(tmp_path):
    run = tmp_path / "r"
    _write_min_editor(run, es_overrides={"add_node_supported": False})
    assert any("add_node_supported != true" in p for p in _check_phase2c2(run))


def test_validate_candidate_no_validation_fails(tmp_path):
    run = tmp_path / "r"
    _write_min_editor(run, es_overrides={"graph_validation_supported": False})
    assert any("graph_validation_supported != true" in p for p in _check_phase2c2(run))


def test_validate_candidate_compat_fail(tmp_path):
    run = tmp_path / "r"
    _write_min_editor(run, compat=False, es_overrides={"draft_schema_compatible": False})
    assert any("draft schema compatibility FAIL" in p or "draft_schema_compatible != true" in p
               for p in _check_phase2c2(run))


def test_validate_candidate_roundtrip_fail(tmp_path):
    run = tmp_path / "r"
    _write_min_editor(run, roundtrip=False, es_overrides={"draft_roundtrip_pass": False})
    assert any("roundtrip" in p.lower() for p in _check_phase2c2(run))


def test_validate_candidate_js_fail(tmp_path):
    run = tmp_path / "r"
    _write_min_editor(run, js_status="FAIL", es_overrides={"js_syntax_status": "FAIL"})
    assert any("JS syntax check FAIL" in p for p in _check_phase2c2(run))


def test_validate_candidate_handler_fail(tmp_path):
    run = tmp_path / "r"
    _write_min_editor(run, hb_status="FAIL", es_overrides={"ui_binding_evidence_pass": False})
    assert any("handler binding evidence FAIL" in p or "ui_binding_evidence_pass != true" in p
               for p in _check_phase2c2(run))


def test_validate_candidate_missing_limitation_fails(tmp_path):
    run = tmp_path / "r"
    _write_min_editor(run, limitations=["editor validation only"])
    assert any("runner-backed execution not included" in p for p in _check_phase2c2(run))


def test_validate_missing_required_fails(tmp_path):
    run = tmp_path / "r"
    rd = _write_min_editor(run)
    (rd / "phase2c2_dashboard_summary.json").unlink()
    assert any("산출물 없음" in p for p in _check_phase2c2(run))


# ---------------------------------------------------------------- Group J: CLI

def test_cli_requires_target(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["factory-product-editor"]) == 1
    assert main(["factory-product-editor", "--run-dir", "x", "--dry-run", "--apply"]) == 1


def test_cli_apply_on_synthetic(tmp_path, monkeypatch):
    run = _editor_ready_run(tmp_path)
    monkeypatch.chdir(tmp_path)
    rc = main(["factory-product-editor", "--run-dir", str(run), "--apply"])
    assert rc == 0
    assert (run / "review" / "phase2c2" / "phase2c2_editor_report.md").is_file()


# ---------------------------------------------------------------- Group K: 실제 #47 E2E

@pytest.mark.skipif(not FIXTURE_47.is_dir(), reason="#47 runtime 산출물 없음")
def test_e2e_47_editor(tmp_path):
    run = tmp_path / FIXTURE_47.name
    shutil.copytree(FIXTURE_47, run)
    if (run / "review" / "phase2c2").is_dir():
        shutil.rmtree(run / "review" / "phase2c2")
    _write_decision(run)
    before = compute_editor_protected_hashes(run)
    out = run_product_editor(run_dir=run, apply=True)
    after = compute_editor_protected_hashes(run)
    assert out["status"] == "EDITOR_ADDED"
    assert out["hash_status"] == "PASS"
    assert before == after  # 보호 대상 불변
    es = out["editor_smoke"]
    assert es["model_level_smoke_pass"] is True
    assert es["ui_binding_evidence_pass"] is True
    assert es["js_syntax_status"] == "PASS"
    assert es["original_replay_unchanged"] is True
    assert _check_phase2c2(run) == []
