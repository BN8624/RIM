# R0 baseline scanner 테스트 — 결정론/사이클/private import/CLI 추출 검증.
import json
import subprocess
from pathlib import Path

from repo_idea_miner.architecture_scanner import (
    build_baseline,
    collect_workspace_changes,
    extract_cli_commands,
    find_import_cycles,
    find_private_imports,
    scan_module,
    workspace_markdown_problems,
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


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   cwd=root, check=True, capture_output=True)


def test_collect_workspace_changes_on_temp_git_repo(tmp_path):
    """A7 §7/§8 — porcelain 파싱 매트릭스: staged/unstaged/DELETED/UNTRACKED/RENAMED
    (old_path 소비), 공백·한글 path, ignored 제외, untracked test 분류, 10회 반복 결정론."""
    root = tmp_path / "repo"
    (root / "repo_idea_miner").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "runs").mkdir()
    (root / ".gitignore").write_text(".env\nruns/\n", encoding="utf-8")
    (root / "keep.py").write_text("x = 1\n", encoding="utf-8")
    (root / "staged.py").write_text("s = 1\n", encoding="utf-8")
    (root / "gone.py").write_text("y = 1\n", encoding="utf-8")
    (root / "old_name.py").write_text("z = 1\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    assert collect_workspace_changes(root) == []  # §8.2 clean workspace

    (root / "keep.py").write_text("x = 2\n", encoding="utf-8")          # unstaged modified
    (root / "staged.py").write_text("s = 2\n", encoding="utf-8")        # staged modified
    _git(root, "add", "staged.py")
    (root / "gone.py").unlink()                                          # deleted
    (root / "new file.md").write_text("hi\n", encoding="utf-8")          # 공백 path
    (root / "한글모듈.py").write_text("k = 1\n", encoding="utf-8")       # 한글 path
    (root / "repo_idea_miner" / "new_validator.py").write_text("v = 1\n", encoding="utf-8")
    (root / "tests" / "test_new_validator.py").write_text("t = 1\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=1\n", encoding="utf-8")           # ignored
    (root / "runs" / "out.json").write_text("{}\n", encoding="utf-8")    # ignored
    _git(root, "mv", "old_name.py", "new_name.py")                       # staged rename

    changes = collect_workspace_changes(root)
    for _ in range(10):  # §8.3 반복 결정론
        assert collect_workspace_changes(root) == changes
    by_path = {c["path"]: c for c in changes}
    assert by_path["keep.py"]["status"] == "MODIFIED"
    assert by_path["staged.py"]["status"] == "MODIFIED" and by_path["staged.py"]["tracked"]
    assert by_path["gone.py"]["status"] == "DELETED"
    md = by_path["new file.md"]
    assert md["status"] == "UNTRACKED" and not md["tracked"] and md["is_markdown"]
    assert by_path["한글모듈.py"]["is_python"]
    prod = by_path["repo_idea_miner/new_validator.py"]
    assert prod["status"] == "UNTRACKED" and prod["is_python"] and not prod["is_test"]
    tst = by_path["tests/test_new_validator.py"]
    assert tst["is_test"] and tst["is_python"]
    ren = by_path["new_name.py"]
    assert ren["status"] == "RENAMED" and ren["old_path"] == "old_name.py"
    assert ren["is_python"]
    # §8.2 ignored는 출력에 아예 나오지 않는다 (.env/runs/)
    assert ".env" not in by_path
    assert not any(p.startswith("runs/") for p in by_path)
    assert ".gitignore" not in by_path  # 커밋됨


def test_collect_workspace_changes_outside_git_repo(tmp_path):
    assert collect_workspace_changes(tmp_path) == []


def _cf(path: str, status: str = "UNTRACKED", old: str | None = None) -> dict:
    return {"path": path, "old_path": old, "status": status,
            "tracked": status != "UNTRACKED",
            "is_python": path.endswith(".py"),
            "is_test": path.startswith("tests/") and path.endswith(".py"),
            "is_markdown": path.endswith(".md")}


def test_workspace_markdown_problems():
    """A7 §5.2 — untracked md가 루트/소스 경로에 있으면 문맥 오염, 그 외는 침묵."""
    probs = workspace_markdown_problems([
        _cf("NOTES.md"),                        # 루트 untracked → 문제
        _cf("repo_idea_miner/plan.md"),         # 소스 경로 untracked → 문제
        _cf("README.md", status="MODIFIED"),    # tracked 수정 → 문제 아님
        _cf("samples/foo.md"),                  # 비관리 경로 → 문제 아님
    ])
    assert len(probs) == 2
    assert any("NOTES.md" in p for p in probs)
    assert any("repo_idea_miner/plan.md" in p for p in probs)


def test_baseline_counts_sane():
    base = build_baseline(REPO_ROOT)
    assert base["python_module_count"] > 20
    assert base["factory_module_count"] >= 15
    assert base["test_count"] > 900
    assert any(c.startswith("_check_") for c in base["validator_checks"])
    assert base["root_markdown"]  # 루트 md 목록 존재
