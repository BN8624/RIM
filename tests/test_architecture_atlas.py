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
    warnings: list[str] = []
    assert run_architecture_check(REPO_ROOT, warnings=warnings) == []
    assert all(isinstance(w, str) for w in warnings)  # §17.2 경고는 비차단 채널로만


def _cf(path: str, status: str = "UNTRACKED") -> dict:
    return {"path": path, "old_path": None, "status": status,
            "tracked": status != "UNTRACKED",
            "is_python": path.endswith(".py"),
            "is_test": path.startswith("tests/") and path.endswith(".py"),
            "is_markdown": path.endswith(".md")}


def test_check_fails_on_untracked_markdown_and_missed_production_py(monkeypatch):
    """A7 §5.2/§17.1: untracked 루트 md = hard fail, --changed가 untracked production py를
    누락하면 hard fail. atlas 쪽 collect만 fake로 바꿔 실제 workspace와 무관하게 검증한다."""
    import repo_idea_miner.architecture_atlas as aa
    import repo_idea_miner.architecture_context as ac

    fake = [_cf("NEW_ORDER.md"), _cf("repo_idea_miner/new_validator.py")]
    monkeypatch.setattr(aa, "collect_workspace_changes", lambda root: fake)
    monkeypatch.setattr(ac, "collect_workspace_changes", lambda root: [])
    problems = run_architecture_check(REPO_ROOT)
    assert any("untracked root markdown: NEW_ORDER.md" in p for p in problems)
    assert any("untracked production 파일 누락: repo_idea_miner/new_validator.py" in p
               for p in problems)


def test_check_fails_when_clean_workspace_has_changed_files(monkeypatch):
    """A7 §17.1-11: porcelain이 clean인데 context changed_files가 비어 있지 않으면 hard fail."""
    import repo_idea_miner.architecture_atlas as aa
    import repo_idea_miner.architecture_context as ac

    monkeypatch.setattr(aa, "collect_workspace_changes", lambda root: [])
    monkeypatch.setattr(ac, "collect_workspace_changes",
                        lambda root: [_cf("repo_idea_miner/ghost.py", "MODIFIED")])
    problems = run_architecture_check(REPO_ROOT)
    assert any("clean workspace인데" in p for p in problems)


def test_reentry_head_source_policy():
    """A7 §6: REENTRY는 Git 명령이 정본, 정적 현재-HEAD 필드(commit:) 금지."""
    from repo_idea_miner.architecture_atlas import (
        _REENTRY_STATIC_HEAD_RE,
        REENTRY_REQUIRED_COMMANDS,
        REENTRY_REQUIRED_SECTIONS,
    )

    reentry = (REPO_ROOT / "REENTRY.md").read_text(encoding="utf-8")
    assert "HEAD_SOURCE:" in REENTRY_REQUIRED_SECTIONS
    for cmd in REENTRY_REQUIRED_COMMANDS:
        assert cmd in reentry
    assert not _REENTRY_STATIC_HEAD_RE.search(reentry)
    # regex 자체: 현재-HEAD 필드는 잡고, 과거 evidence 속 hash 언급은 잡지 않는다
    assert _REENTRY_STATIC_HEAD_RE.search("HEAD:\n- commit: 98cd9ad (A7)\n")
    assert _REENTRY_STATIC_HEAD_RE.search("commit: abcdef1234567890\n")
    assert not _REENTRY_STATIC_HEAD_RE.search("- evidence: run at commit 98cd9ad\n")


def _usage_contract_inputs():
    from repo_idea_miner.architecture_atlas import usage_contract_problems

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    canon = (REPO_ROOT / "PROJECT_CANON.md").read_text(encoding="utf-8")
    a = _atlas()
    opts = {o for c in a["cli"] if c["command"] == "architecture-context"
            for o in c["options"]}
    cmds = {c["command"] for c in a["cli"]}
    return usage_contract_problems, readme, canon, opts, cmds


def test_atlas_usage_contract_current_documents_pass():
    """usage-contract §8.1-1/9/10: 실제 README·CANON-12가 사용 계약을 만족하고,
    required workflow의 CLI·옵션이 실제 parser와 일치한다."""
    check, readme, canon, opts, cmds = _usage_contract_inputs()
    assert check(readme, canon, opts, cmds) == []


def test_usage_contract_fails_on_removed_readme_procedure():
    """usage-contract §8.1-2/3: read_first 절차·--changed --impact 절차 삭제 시 FAIL."""
    check, readme, canon, opts, cmds = _usage_contract_inputs()
    no_read_first = readme.replace("read_first", "primary")
    assert any("read_first" in p for p in check(no_read_first, canon, opts, cmds))
    no_changed = readme.replace("--changed", "--diff")
    assert any("--changed" in p for p in check(no_changed, canon, opts, cmds))


def test_usage_contract_fails_on_oracle_wording():
    """usage-contract §8.1-4: Atlas를 최종 범위 결정기로 표현하면 FAIL (README·CANON 모두)."""
    check, readme, canon, opts, cmds = _usage_contract_inputs()
    bad_readme = readme + "\nAtlas determines the final edit scope.\n"
    assert any("권한 과장" in p for p in check(bad_readme, canon, opts, cmds))
    bad_canon = canon + "\nAtlas가 최종 수정 범위를 확정한다.\n"
    assert any("권한 과장" in p for p in check(readme, bad_canon, opts, cmds))


def test_usage_contract_fails_on_removed_canon_keys():
    """usage-contract §8.1-5/6/7: ATLAS_AUTHORITY/IMPACT_LIMIT/VALIDATED_LIMIT 등
    stable key 삭제·빈 섹션 시 FAIL."""
    check, readme, canon, opts, cmds = _usage_contract_inputs()
    from repo_idea_miner.architecture_atlas import CANON12_REQUIRED_KEYS

    for key in CANON12_REQUIRED_KEYS:
        removed = canon.replace(key, "X_" + key)
        assert any(key in p for p in check(readme, removed, opts, cmds)), key
    # 빈 섹션(뒤따르는 '- ' 항목 없음)도 실패
    emptied = canon.replace("ATLAS_AUTHORITY:\n- ", "ATLAS_AUTHORITY:\n\n- x ")
    assert any("ATLAS_AUTHORITY:" in p for p in check(readme, emptied, opts, cmds))


def test_usage_contract_fails_on_unknown_cli_or_missing_option():
    """usage-contract §8.1-8 + §7.3: 없는 CLI 안내·문서가 요구하는 옵션의 parser 부재 시 FAIL."""
    check, readme, canon, opts, cmds = _usage_contract_inputs()
    ghost = readme + "\npython -m repo_idea_miner architecture-teleport\n"
    assert any("architecture-teleport" in p for p in check(ghost, canon, opts, cmds))
    problems = check(readme, canon, {"--route"}, cmds)
    assert any("--changed" in p for p in problems)
    assert any("--impact" in p for p in problems)


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
