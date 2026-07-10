# AI Context Pack 테스트 — selector/read_first/impact/결정론 (AI-Only 주문서 §15~§16).
import json
from pathlib import Path

import repo_idea_miner.architecture_context as ac
from repo_idea_miner.architecture_context import (
    build_context,
    classify_changes,
    render_compact,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _ctx(selectors, **kw):
    return build_context(REPO_ROOT, selectors, **kw)


def test_context_deterministic_byte_identical():
    """같은 atlas·같은 query → byte-identical (§15.3/§20)."""
    a = json.dumps(_ctx({"canon": ["CANON-07"]}, impact=True), sort_keys=True)
    b = json.dumps(_ctx({"canon": ["CANON-07"]}, impact=True), sort_keys=True)
    assert a == b


def test_context_output_shape():
    c = _ctx({"canon": ["CANON-07"]})
    for key in ("selectors", "canon_ids", "routes", "read_first", "read_if_needed",
                "contracts", "invariants", "artifacts", "tests_to_run",
                "verification_commands", "do_not_modify", "warnings"):
        assert key in c, key
    assert "direct_static_impact" not in c  # --impact 없으면 미포함


def test_canon_selector_builds_closed_loop_slice():
    c = _ctx({"canon": ["CANON-07"]})
    assert "CANON-07" in c["canon_ids"]
    assert c["routes"] == ["factory_judge_only", "factory_closed_loop"]
    paths = [e["path"] for e in c["read_first"]]
    assert paths[0] == "repo_idea_miner/factory_product_loop.py"
    assert "repo_idea_miner/factory_loop_executor.py" in paths
    assert len(paths) <= 5  # 기본 primary 제한 (§15.4)
    assert len(c["read_if_needed"]) <= 8
    assert {x["contract_id"] for x in c["contracts"]} >= {
        "product_evidence", "product_decision", "closed_loop_iteration"}
    assert any(i["invariant_id"] == "INV-BASE-RUN-IMMUTABLE" for i in c["invariants"])
    assert "tests/test_factory_phase2d1_loop.py" in c["tests_to_run"]  # §10 실제 path
    assert any("architecture-check" in v for v in c["verification_commands"])
    assert any("pipeline.py" in d for d in c["do_not_modify"])


def test_symbol_selector_gives_line_ranges():
    c = _ctx({"symbol": ["run_closed_product_loop"]})
    entry = next(e for e in c["read_first"]
                 if e["path"] == "repo_idea_miner/factory_loop_executor.py")
    sym = next(s for s in entry["symbols"]
               if s["symbol_id"].endswith(".run_closed_product_loop"))
    assert 0 < sym["start_line"] < sym["end_line"]
    assert sym["signature"].startswith("def run_closed_product_loop(")


def test_impact_is_named_direct_static_impact():
    """§16: 반드시 direct_static_impact로 명명, runtime 영향이라 주장하지 않는다."""
    c = _ctx({"module": ["factory_product_evidence"]}, impact=True)
    imp = c["direct_static_impact"]
    assert "runtime 영향이 아님" in imp["note"]
    assert "repo_idea_miner.factory_product_loop" in imp["direct_import_consumers"]
    assert "product_evidence" in imp["contracts"]
    assert imp["related_tests"]


def test_artifacts_exclude_literal_reference_by_default():
    c = _ctx({"module": ["factory_loop_executor"]})
    assert c["artifacts"], "IO 실증/manifest artifact가 있어야 한다"
    assert all(a["role"] != "LITERAL_REFERENCE" for a in c["artifacts"])


def test_unknown_selector_warns_instead_of_failing():
    c = _ctx({"route": ["no_such_route"], "canon": ["CANON-99"]})
    assert any("no_such_route" in w for w in c["warnings"])
    assert any("CANON-99" in w for w in c["warnings"])
    assert c["read_first"] == []


def test_compact_render_deterministic_lines():
    c = _ctx({"route": ["factory_closed_loop"]})
    text = render_compact(c)
    assert text == render_compact(c)
    lines = text.splitlines()
    assert any(line.startswith("READ_FIRST repo_idea_miner/factory_loop_executor.py")
               for line in lines)
    assert any(line.startswith("INVARIANT INV-BASE-RUN-IMMUTABLE") for line in lines)
    assert any(line.startswith("DO_NOT_MODIFY") for line in lines)


def test_component_selector_and_ai_index_queries():
    """AI_INDEX의 모든 ATLAS_QUERY가 유효한 selector로 해석된다 (§7 라우팅 표 정합)."""
    c = _ctx({"component": ["atlas"]})
    paths = [e["path"] for e in c["read_first"]]
    assert "repo_idea_miner/architecture_atlas.py" in paths
    assert "CANON-12" in c["canon_ids"]

    atlas = json.loads(
        (REPO_ROOT / "architecture/atlas.json").read_text(encoding="utf-8"))
    for row in atlas["document_routes"]:
        parts = row["atlas_query"].split()
        assert len(parts) == 2 and parts[0].startswith("--"), row
        cc = _ctx({parts[0].lstrip("-"): [parts[1]]})
        assert not any("selector 불일치" in w for w in cc["warnings"]), row
        assert cc["read_first"], row


def test_ambiguous_module_selector_returns_deterministic_error(monkeypatch):
    """A7 §9.3 — duplicate stem에서 short selector는 자동 선택 금지, stable sort candidates."""
    real = ac.load_atlas(REPO_ROOT)
    fake = json.loads(json.dumps(real))
    base = next(m for m in fake["modules"]
                if m["module"] == "repo_idea_miner.factory_validate")
    dup = json.loads(json.dumps(base))
    dup["module"] = "repo_idea_miner.subpkg.factory_validate"
    fake["modules"].append(dup)
    monkeypatch.setattr(ac, "load_atlas", lambda root: fake)

    err = build_context(REPO_ROOT, {"module": ["factory_validate"]})
    assert err == {
        "error": "AMBIGUOUS_MODULE_SELECTOR",
        "selector": "factory_validate",
        "candidates": ["repo_idea_miner.factory_validate",
                       "repo_idea_miner.subpkg.factory_validate"],
    }
    # full module ID는 정본이므로 그대로 동작한다 (§9.2)
    ok = build_context(REPO_ROOT, {"module": ["repo_idea_miner.factory_validate"]})
    assert "error" not in ok
    assert any(e["path"].endswith("factory_validate.py") for e in ok["read_first"])


def test_ambiguous_symbol_selector_returns_candidates(monkeypatch):
    """A7 §9.5 — 짧은 symbol 이름이 여러 개와 일치하면 자동 선택 금지."""
    real = ac.load_atlas(REPO_ROOT)
    fake = json.loads(json.dumps(real))
    dup = json.loads(json.dumps(fake["symbols"][0]))
    orig_id = dup["symbol_id"]
    short = orig_id.split(".")[-1]
    dup["symbol_id"] = f"repo_idea_miner.other_module.{short}"
    fake["symbols"].append(dup)
    monkeypatch.setattr(ac, "load_atlas", lambda root: fake)

    err = build_context(REPO_ROOT, {"symbol": [short]})
    assert err["error"] == "AMBIGUOUS_SYMBOL_SELECTOR"
    assert err["candidates"] == sorted([orig_id, dup["symbol_id"]])
    # full symbol ID는 정확 일치로 통과
    ok = build_context(REPO_ROOT, {"symbol": [orig_id]})
    assert "error" not in ok


def test_tests_to_run_are_real_paths():
    """A7 §10 — tests_to_run/verification_commands는 실제 repo-relative path."""
    c = _ctx({"canon": ["CANON-07"]})
    assert c["tests_to_run"]
    for t in c["tests_to_run"]:
        assert t.startswith("tests/") and t.endswith(".py"), t
        assert (REPO_ROOT / t).is_file(), t
    assert c["verification_commands"][0].startswith("python -m pytest tests/")


def _cf(path: str, status: str = "MODIFIED", old: str | None = None) -> dict:
    return {"path": path, "old_path": old, "status": status,
            "tracked": status != "UNTRACKED",
            "is_python": path.endswith(".py"),
            "is_test": path.startswith("tests/") and path.endswith(".py"),
            "is_markdown": path.endswith(".md")}


def test_classify_changes_pure():
    """A7 §7.3 — ChangedFile 분류: known/pending_build/deleted/rename/test/governance."""
    stems = {"architecture_context", "factory_review"}
    info = classify_changes([
        _cf("repo_idea_miner/architecture_context.py"),
        _cf("repo_idea_miner/brand_new.py", status="UNTRACKED"),
        _cf("repo_idea_miner/factory_review.py", status="DELETED"),
        _cf("repo_idea_miner/new_name.py", status="RENAMED",
            old="repo_idea_miner/old_name.py"),
        _cf("tests/test_x.py", status="UNTRACKED"),
        _cf("PLAN.md", status="UNTRACKED"),
    ], stems)
    assert info["known_stems"] == ["architecture_context", "factory_review"]
    assert info["pending_build"] == [
        "repo_idea_miner/brand_new.py", "repo_idea_miner/new_name.py"]
    assert info["deleted_module_stems"] == ["factory_review", "old_name"]
    assert info["test_changes"] == ["tests/test_x.py"]
    assert any("PLAN.md" in p for p in info["governance_problems"])


def test_changed_selector_impact_block(monkeypatch):
    """A7 — --changed --impact: UNKNOWN_PENDING_BUILD, deleted_modules,
    governance → document_update_required, pending/deleted → atlas_rebuild_required."""
    fake = [
        _cf("repo_idea_miner/factory_product_evidence.py"),
        _cf("repo_idea_miner/brand_new.py", status="UNTRACKED"),
        _cf("repo_idea_miner/factory_review.py", status="DELETED"),
        _cf("NOTES.md", status="UNTRACKED"),
        _cf("tests/test_factory_review.py"),
    ]
    monkeypatch.setattr(ac, "collect_workspace_changes", lambda root: fake)
    c = ac.build_context(REPO_ROOT, {"changed": True}, impact=True,
                         live_fingerprint="not-the-committed-fp")
    assert any("UNKNOWN_PENDING_BUILD" in w for w in c["warnings"])
    ch = c["direct_static_impact"]["changed"]
    assert ch["changed_files"] == fake
    assert "UNKNOWN_PENDING_BUILD" in ch["changed_components"]
    assert ch["pending_build_files"] == ["repo_idea_miner/brand_new.py"]
    dm = next(d for d in ch["deleted_modules"] if d["module_stem"] == "factory_review")
    assert dm["previous_component"] != "unknown"  # 아직 atlas에 있으므로 실제 component
    assert dm["importers"] or dm["possible_broken_routes"]
    assert ch["changed_tests"] == ["tests/test_factory_review.py"]
    assert ch["structure_fingerprint_changed"] is True
    assert ch["atlas_rebuild_required"] is True
    assert ch["document_update_required"] is True
    assert any("NOTES.md" in p for p in ch["workspace_governance_problems"])


def test_changed_selector_clean_workspace_warns(monkeypatch):
    monkeypatch.setattr(ac, "collect_workspace_changes", lambda root: [])
    c = ac.build_context(REPO_ROOT, {"changed": True})
    assert any("workspace clean" in w for w in c["warnings"])


def test_cli_end_to_end(capsys):
    from repo_idea_miner.cli import main

    assert main(["architecture-context", "--canon", "CANON-12"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "architecture_context" in out["routes"]
    assert main(["architecture-context"]) == 1  # selector 없으면 오류
