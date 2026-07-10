# R0 baseline scanner 테스트 — 결정론/사이클/private import/CLI 추출 검증.
import json
from pathlib import Path

from repo_idea_miner.architecture_scanner import (
    build_baseline,
    extract_cli_commands,
    find_import_cycles,
    find_private_imports,
    scan_module,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _fake_pkg(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    (root / "repo_idea_miner").mkdir(parents=True)
    (root / "tests").mkdir()
    for rel, src in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src, encoding="utf-8")
    return root


def test_baseline_deterministic_on_real_repo():
    a = build_baseline(REPO_ROOT, known_flaky=["x"])
    b = build_baseline(REPO_ROOT, known_flaky=["x"])
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_cli_commands_extracted_from_real_repo():
    cmds = extract_cli_commands(REPO_ROOT)
    for expected in ("run", "factory-build", "factory-continue", "factory-product-loop",
                     "factory-validate", "dashboard"):
        assert expected in cmds


def test_private_cross_import_detected(tmp_path):
    root = _fake_pkg(tmp_path, {
        "repo_idea_miner/a.py": "def _hidden():\n    pass\n",
        "repo_idea_miner/b.py": "from repo_idea_miner.a import _hidden\n",
    })
    mods = [scan_module(root, root / "repo_idea_miner" / n) for n in ("a.py", "b.py")]
    found = find_private_imports(mods)
    assert found == [{"module": "repo_idea_miner.b", "from": "repo_idea_miner.a",
                      "names": ["_hidden"]}]


def test_import_cycle_detected(tmp_path):
    root = _fake_pkg(tmp_path, {
        "repo_idea_miner/a.py": "from repo_idea_miner.b import x\ny = 1\n",
        "repo_idea_miner/b.py": "from repo_idea_miner.a import y\nx = 1\n",
        "repo_idea_miner/c.py": "z = 1\n",
    })
    mods = [scan_module(root, root / "repo_idea_miner" / n) for n in ("a.py", "b.py", "c.py")]
    cycles = find_import_cycles(mods)
    assert cycles == [["repo_idea_miner.a", "repo_idea_miner.b"]]


def test_product_chain_private_imports_removed():
    """§8.1/§8.2 회귀 가드(R3): product judgment/closed loop/제품화 체인에
    private cross-import가 다시 생기면 FAIL. (감지 능력 자체는 위 합성 fixture 테스트가 증명)"""
    base = build_baseline(REPO_ROOT)
    pairs = {(d["module"], d["from"]) for d in base["private_cross_imports"]}
    assert ("repo_idea_miner.factory_loop_executor",
            "repo_idea_miner.factory_product_loop") not in pairs
    chain = ("factory_product_loop", "factory_loop_executor", "factory_review",
             "factory_product_polish", "factory_product_editor", "factory_draft_execution",
             "factory_product_evidence", "factory_lane_executors", "factory_product_acceptance")
    offenders = [d for d in base["private_cross_imports"]
                 if d["module"].split(".")[-1] in chain or d["from"].split(".")[-1] in chain]
    assert offenders == []


def test_baseline_counts_sane():
    base = build_baseline(REPO_ROOT)
    assert base["python_module_count"] > 20
    assert base["factory_module_count"] >= 15
    assert base["test_count"] > 900
    assert any(c.startswith("_check_") for c in base["validator_checks"])
    assert base["root_markdown"]  # 루트 md 목록 존재
