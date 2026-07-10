# AI Context Pack 테스트 — selector/read_first/impact/결정론 (AI-Only 주문서 §15~§16).
import json
from pathlib import Path

from repo_idea_miner.architecture_context import build_context, render_compact

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
    assert "test_factory_phase2d1_loop" in c["tests_to_run"]
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


def test_cli_end_to_end(capsys):
    from repo_idea_miner.cli import main

    assert main(["architecture-context", "--canon", "CANON-12"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "architecture_context" in out["routes"]
    assert main(["architecture-context"]) == 1  # selector 없으면 오류
