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
    """LOC 등 구현 내부 변화는 지문을 바꾸지 않고, 공개 심볼 변화는 바꾼다 (§17.10)."""
    a = _atlas()
    fp = a["fingerprint"]
    mutated = json.loads(json.dumps(a))
    mutated["modules"][0]["loc"] += 100
    assert compute_fingerprint(mutated) == fp
    mutated["modules"][0]["public_symbols"] = ["__added_symbol__"]
    assert compute_fingerprint(mutated) != fp


def test_committed_atlas_not_stale():
    """커밋된 atlas.json 지문이 현재 구조와 일치한다 (§17.11-15)."""
    committed = json.loads((REPO_ROOT / "architecture/atlas.json").read_text(encoding="utf-8"))
    assert committed["fingerprint"] == _atlas()["fingerprint"]


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
