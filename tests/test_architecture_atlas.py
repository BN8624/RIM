# Architecture Atlas 테스트 — 결정론/지문/검사/AI-only 계약 (HTML 없음).
import json
from pathlib import Path

from repo_idea_miner.architecture_atlas import (
    ROOT_MD_WHITELIST,
    _canon_ids,
    build_atlas,
    compute_fingerprint,
    load_manifest,
    module_component_map,
    run_architecture_check,
)
from repo_idea_miner.architecture_scanner import (
    extract_cli_details,
    find_import_cycles,
    find_private_imports,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _atlas():
    if not hasattr(_atlas, "cache"):
        _atlas.cache = build_atlas(REPO_ROOT)
    return _atlas.cache


# ---------------------------------------------------------------- 결정론/지문

def test_build_deterministic():
    """같은 HEAD·manifest에서 두 번 빌드하면 동일하다."""
    a1 = build_atlas(REPO_ROOT)
    a2 = build_atlas(REPO_ROOT)
    assert a1 == a2


def test_fingerprint_ignores_internal_only_change():
    """LOC/라인 이동 등 구현 내부 변화는 지문을 바꾸지 않고, 공개 심볼 변화는 바꾼다."""
    a = _atlas()
    fp = a["repository"]["structural_fingerprint"]
    mutated = json.loads(json.dumps(a))
    mutated["modules"][0]["loc"] += 100
    mutated["symbols"][0]["start_line"] += 7  # 심볼 라인 이동도 내부 변화
    assert compute_fingerprint(mutated) == fp
    mutated["modules"][0]["public_symbols"] = ["__added_symbol__"]
    assert compute_fingerprint(mutated) != fp


def test_committed_atlas_not_stale():
    """커밋된 atlas.json 지문이 현재 구조와 일치한다."""
    committed = json.loads((REPO_ROOT / "architecture/atlas.json").read_text(encoding="utf-8"))
    assert committed["repository"]["structural_fingerprint"] \
        == _atlas()["repository"]["structural_fingerprint"]


# ---------------------------------------------------------------- 추출 정확성

def test_module_discovery_and_components():
    a = _atlas()
    names = {m["module"] for m in a["modules"]}
    assert "repo_idea_miner.factory_continue" in names
    assert a["health"]["unknown_component"] == []


def test_import_edges_and_imported_by():
    a = _atlas()
    dash = next(m for m in a["modules"] if m["module"].endswith(".challenge_dashboard"))
    assert any(i["from"].endswith("challenge_dashboard_data") for i in dash["imports"])
    data = next(m for m in a["modules"] if m["module"].endswith(".challenge_dashboard_data"))
    assert "repo_idea_miner.challenge_dashboard" in data["imported_by"]


def test_cli_extraction_matches_handlers():
    from repo_idea_miner.cli_handlers import HANDLERS

    a = _atlas()
    assert {c["command"] for c in a["cli"]} == set(HANDLERS)
    details = {d["command"]: d["options"] for d in extract_cli_details(REPO_ROOT)}
    assert "--execute" in details["factory-product-loop"]


def test_validator_and_test_mapping():
    a = _atlas()
    assert "CONTINUATION_RUN" in a["validators"]["run_kinds"]
    assert any(c.startswith("validate_") for c in a["validators"]["checks"])
    assert "architecture_atlas" in a["tests"].get("test_architecture_atlas", [])


def test_cycle_and_private_import_detection_synthetic():
    mods = [
        {"module": "repo_idea_miner.a", "imports": [{"from": "repo_idea_miner.b", "names": ["_x"]}]},
        {"module": "repo_idea_miner.b", "imports": [{"from": "repo_idea_miner.a", "names": []}]},
    ]
    assert find_import_cycles(mods) == [["repo_idea_miner.a", "repo_idea_miner.b"]]
    priv = find_private_imports(mods)
    assert priv == [{"module": "repo_idea_miner.a", "from": "repo_idea_miner.b", "names": ["_x"]}]


def test_health_targets():
    """§19 정량 목표: cycle 0, allowlist 밖 private import 0, unknown 0."""
    h = _atlas()["health"]
    assert h["import_cycles"] == []
    assert h["private_cross_imports_outside_allowlist"] == []
    assert len(h["private_cross_imports"]) == 3  # miner 예외 3건 (CANON-11)


# ---------------------------------------------------------------- 문서/거버넌스

def test_architecture_check_passes():
    assert run_architecture_check(REPO_ROOT) == []


def test_canon_index_ids_match():
    canon, index = _canon_ids(REPO_ROOT)
    assert canon == index
    assert "CANON-12" in canon


def test_manifest_covers_all_modules():
    comp_map = module_component_map(load_manifest(REPO_ROOT))
    actual = {p.stem for p in (REPO_ROOT / "repo_idea_miner").glob("*.py")}
    assert actual <= set(comp_map), sorted(actual - set(comp_map))


def test_root_markdown_whitelist_constant():
    assert set(ROOT_MD_WHITELIST) == {
        "AI_INDEX.md", "PROJECT_CANON.md", "README.md", "REENTRY.md"}


# ---------------------------------------------------------------- Schema V2 (§10~§14)

def test_schema_v2_top_level():
    a = _atlas()
    assert a["schema_version"] == 2
    for key in ("repository", "components", "modules", "symbols", "routes", "artifacts",
                "contracts", "invariants", "validators", "tests", "document_routes", "health"):
        assert key in a, key
    rep = a["repository"]
    assert set(rep) == {"head", "structure_snapshot", "structural_fingerprint", "structural_diff"}


def test_symbols_are_canonical_and_resolved():
    """§11: 핵심 symbol만 수집, 라인 범위·signature·component·test 연결. private helper 미수집."""
    a = _atlas()
    assert a["health"]["unresolved_symbols"] == []
    by_id = {s["symbol_id"]: s for s in a["symbols"]}
    loop = by_id["repo_idea_miner.factory_loop_executor.run_closed_product_loop"]
    assert loop["kind"] == "function"
    assert 0 < loop["start_line"] < loop["end_line"]
    assert loop["signature"].startswith("def run_closed_product_loop(")
    assert loop["component_id"] == "autopilot"
    assert "CANON-07" in loop["canon_ids"]
    assert loop["related_tests"]
    # cli handler는 registry 지정이므로 수집되지만, 임의 private helper는 수집되지 않는다
    assert "repo_idea_miner.factory_loop_executor._write_hold_packet" not in by_id


def test_routes_declared_and_linked():
    """§12: 필수 17 route, cli/steps 실재는 check가 보증."""
    a = _atlas()
    ids = {r["route_id"] for r in a["routes"]}
    assert len(a["routes"]) == 17
    for rid in ("miner_direct", "core_factory_build", "continuation", "spec_repair",
                "anti_hardcode_repair", "productization_chain", "factory_judge_only",
                "factory_closed_loop", "factory_validate", "dashboard_read",
                "architecture_build", "architecture_check", "architecture_context"):
        assert rid in ids, rid
    closed = next(r for r in a["routes"] if r["route_id"] == "factory_closed_loop")
    assert closed["cli"] == "factory-product-loop"
    assert closed["steps"][0] == "repo_idea_miner.cli_handlers._cmd_factory_product_loop"


def test_artifacts_have_role_and_provenance():
    """§13: role/provenance 필수, 문자열 스캔은 LITERAL_REFERENCE로 강등."""
    from repo_idea_miner.architecture_atlas import ARTIFACT_PROVENANCES, ARTIFACT_ROLES

    a = _atlas()
    roles = {x["role"] for x in a["artifacts"]}
    provs = {x["provenance"] for x in a["artifacts"]}
    assert roles <= set(ARTIFACT_ROLES)
    assert provs <= set(ARTIFACT_PROVENANCES)
    # manifest 선언 producer는 PRODUCES/MANIFEST로 수록된다
    assert any(x["role"] == "PRODUCES" and x["provenance"] == "MANIFEST"
               and x["path_pattern"] == "phase2d1_dashboard_summary.json"
               for x in a["artifacts"])
    # LITERAL_REFERENCE는 IO 실증 없는 문자열 — AST_IO_CALL과 짝이 되지 않는다
    for x in a["artifacts"]:
        if x["role"] == "LITERAL_REFERENCE":
            assert x["provenance"] == "AST_STRING_LITERAL"


def test_contracts_and_invariants_declared():
    """§14: contract 10종 + invariant 11종이 manifest에서 atlas로 들어온다."""
    a = _atlas()
    assert {c["contract_id"] for c in a["contracts"]} == {
        "core_contract", "output_representation", "golden_representation", "runner_result",
        "continuation_summary", "repair_execution_result", "product_evidence",
        "product_decision", "closed_loop_iteration", "closed_loop_summary"}
    assert {i["invariant_id"] for i in a["invariants"]} == {
        "INV-MINER-CORE-PRESERVED", "INV-BASE-RUN-IMMUTABLE", "INV-FRESH-VERIFICATION",
        "INV-HARD-RUNG-DETERMINISTIC", "INV-SPEC-REPAIR-PROTECTION", "INV-SUMMARY-STRING",
        "INV-PROTECTED-HASH", "INV-MOCK-FALLBACK-NOT-PRODUCT", "INV-SECRET-NONDISCLOSURE",
        "INV-PRESENTATION-NO-JUDGMENT", "INV-AI-DOCUMENTS-ONLY"}
    for c in a["contracts"]:
        assert c["owner_symbol"] and c["risk"] in ("high", "medium", "low")
    for i in a["invariants"]:
        assert i["applies_to"] and i["tests"]


def test_document_routes_parsed_from_ai_index():
    """AI_INDEX 라우팅 표가 document_routes로 기계 판독된다."""
    a = _atlas()
    by_id = {r["route_id"]: r for r in a["document_routes"]}
    assert "CLOSED_LOOP" in by_id
    assert "CANON-07" in by_id["CLOSED_LOOP"]["canon_ids"]
    assert by_id["CLOSED_LOOP"]["atlas_query"].startswith("--route")
    assert all(r["selectors"] for r in a["document_routes"])


def test_scanner_io_call_extraction(tmp_path):
    """§13 AST_IO_CALL: write/read 계열 호출의 파일명 리터럴만 role과 함께 기록한다."""
    from repo_idea_miner.architecture_scanner import scan_module

    root = tmp_path / "repo"
    (root / "repo_idea_miner").mkdir(parents=True)
    src = (
        "from pathlib import Path\n"
        "def f(d: Path):\n"
        "    x = open(d / 'in.json').read()\n"
        "    with open(d / 'out.json', 'w') as fh:\n"
        "        fh.write(x)\n"
        "    y = 'mentioned_only.json'\n"
        "    return y\n"
    )
    p = root / "repo_idea_miner" / "m.py"
    p.write_text(src, encoding="utf-8")
    info = scan_module(root, p)
    calls = {(c["name"], c["role"]) for c in info["artifact_io_calls"]}
    assert ("in.json", "CONSUMES") in calls
    assert ("out.json", "PRODUCES") in calls
    assert not any(n == "mentioned_only.json" for n, _ in calls)
    assert "mentioned_only.json" in info["artifact_refs"]


# ---------------------------------------------------------------- AI-only 계약 (HTML 없음)

def test_no_human_atlas_surface():
    """AI-only Atlas: HTML/renderer/serve·summary CLI가 존재하지 않는다."""
    from repo_idea_miner.cli_handlers import HANDLERS

    assert not (REPO_ROOT / "architecture/index.html").exists()
    assert not (REPO_ROOT / "repo_idea_miner/architecture_render.py").exists()
    assert "architecture-serve" not in HANDLERS
    assert "architecture-summary" not in HANDLERS


def test_atlas_outputs_no_secret_values():
    from repo_idea_miner.config import load_settings

    secrets = [s for s in load_settings().secret_values() if s]
    for name in ("architecture/atlas.json", "architecture/manifest.toml"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        for s in secrets:
            assert s not in text
