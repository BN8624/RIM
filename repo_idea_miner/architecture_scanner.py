# 저장소 구조를 AST로 결정론적으로 추출하는 scanner — R0 baseline이자 Architecture Atlas의 코어.
from __future__ import annotations

import ast
import re
from pathlib import Path

PACKAGE = "repo_idea_miner"

_ARTIFACT_RE = re.compile(r"^[\w./-]+\.(json|md|html|toml|jsonl)$")
_RUN_KIND_RE = re.compile(r"^[A-Z][A-Z0-9_]*_RUN$")


def _iter_py(root: Path) -> list[Path]:
    """패키지와 tests의 .py를 정렬된 순서로 돌려준다 (filesystem 순서 비의존)."""
    out = []
    for base in (root / PACKAGE, root / "tests"):
        if base.is_dir():
            out += [p for p in base.rglob("*.py") if "__pycache__" not in p.parts]
    return sorted(out, key=lambda p: p.relative_to(root).as_posix())


def _module_name(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    return ".".join(rel.parts)


def scan_module(root: Path, path: Path) -> dict:
    """모듈 1개의 구조 사실을 추출한다. 구문 오류 파일도 기록은 남긴다."""
    src = path.read_text(encoding="utf-8", errors="replace")
    loc = src.count("\n") + (0 if src.endswith("\n") or not src else 1)
    info: dict = {
        "module": _module_name(root, path),
        "path": path.relative_to(root).as_posix(),
        "loc": loc,
        "public_symbols": [],
        "private_symbols": [],
        "imports": [],           # 패키지 내부 from-import: {"from": module, "names": [...]}
        "artifact_refs": [],
        "parse_error": None,
    }
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        info["parse_error"] = str(exc)
        return info

    for node in tree.body:
        name = None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        if name:
            key = "private_symbols" if name.startswith("_") else "public_symbols"
            info[key].append(name)

    artifacts: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module \
                and node.module.split(".")[0] == PACKAGE:
            info["imports"].append({
                "from": node.module,
                "names": sorted(a.name for a in node.names),
            })
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] == PACKAGE:
                    info["imports"].append({"from": a.name, "names": []})
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and _ARTIFACT_RE.match(node.value):
            artifacts.add(node.value)
    info["imports"].sort(key=lambda d: (d["from"], ",".join(d["names"])))
    info["public_symbols"].sort()
    info["private_symbols"].sort()
    info["artifact_refs"] = sorted(artifacts)
    return info


def find_private_imports(modules: list[dict]) -> list[dict]:
    """production 모듈 간 `from X import _private` 사용을 찾는다 (tests 제외)."""
    out = []
    for m in modules:
        if not m["module"].startswith(PACKAGE + "."):
            continue
        for imp in m["imports"]:
            if imp["from"] == m["module"]:
                continue
            privates = sorted(n for n in imp["names"] if n.startswith("_"))
            if privates:
                out.append({"module": m["module"], "from": imp["from"],
                            "names": privates})
    return sorted(out, key=lambda d: (d["module"], d["from"]))


def find_import_cycles(modules: list[dict]) -> list[list[str]]:
    """패키지 내부 import 그래프의 SCC(크기≥2)를 cycle로 돌려준다."""
    graph: dict[str, set[str]] = {}
    names = {m["module"] for m in modules if m["module"].startswith(PACKAGE + ".")}
    for m in modules:
        if m["module"] not in names:
            continue
        deps = {i["from"] for i in m["imports"] if i["from"] in names and i["from"] != m["module"]}
        graph[m["module"]] = deps

    # Tarjan SCC (반복 구현 — 재귀 한도 회피)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    sccs: list[list[str]] = []
    counter = [0]

    def strongconnect(start: str) -> None:
        work = [(start, iter(sorted(graph[start])))]
        index[start] = low[start] = counter[0]
        counter[0] += 1
        stack.append(start)
        on_stack.add(start)
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter[0]
                    counter[0] += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(sorted(graph[w]))))
                    advanced = True
                    break
                if w in on_stack:
                    low[v] = min(low[v], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                pv = work[-1][0]
                low[pv] = min(low[pv], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1:
                    sccs.append(sorted(comp))

    for node in sorted(graph):
        if node not in index:
            strongconnect(node)
    return sorted(sccs)


def extract_cli_commands(root: Path) -> list[str]:
    """cli.py의 add_parser(\"name\") 호출에서 command 목록을 추출한다."""
    path = root / PACKAGE / "cli.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "add_parser" and node.args \
                and isinstance(node.args[0], ast.Constant):
            out.add(str(node.args[0].value))
    return sorted(out)


def extract_cli_details(root: Path) -> list[dict]:
    """cli.py AST에서 command별 option 목록을 추출한다 (Atlas §17.5 CLI)."""
    path = root / PACKAGE / "cli.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    var_to_cmd: dict[str, str] = {}
    options: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Call) \
                and isinstance(node.value.func, ast.Attribute) \
                and node.value.func.attr == "add_parser" \
                and node.value.args and isinstance(node.value.args[0], ast.Constant):
            cmd = str(node.value.args[0].value)
            var_to_cmd[node.targets[0].id] = cmd
            options.setdefault(cmd, set())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "add_argument" \
                and isinstance(node.func.value, ast.Name) \
                and node.func.value.id in var_to_cmd \
                and node.args and isinstance(node.args[0], ast.Constant):
            options[var_to_cmd[node.func.value.id]].add(str(node.args[0].value))
    return [{"command": c, "options": sorted(opts)} for c, opts in sorted(options.items())]


def extract_validator_ids(root: Path) -> dict:
    """factory_validate의 check/detect/validate 함수명과 run kind 리터럴을 추출한다.
    run kind 정본 리터럴은 R2 이후 factory_run_layout에 있으므로 둘 다 스캔한다."""
    checks, kinds = set(), set()
    for name in ("factory_validate.py", "factory_run_layout.py"):
        tree = ast.parse((root / PACKAGE / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if name == "factory_validate.py" \
                    and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name.startswith(("_check_", "detect_", "validate_")):
                checks.add(node.name)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and _RUN_KIND_RE.match(node.value):
                kinds.add(node.value)
    return {"checks": sorted(checks), "run_kinds": sorted(kinds)}


def count_tests(modules: list[dict]) -> int:
    return sum(1 for m in modules if m["module"].startswith("tests.")
               for s in m["public_symbols"] + m["private_symbols"]
               if s.startswith("test_"))


def build_baseline(root: Path, known_flaky: list[str] | None = None) -> dict:
    """§10.1 baseline — 같은 HEAD에서 두 번 실행하면 동일해야 한다."""
    modules = [scan_module(root, p) for p in _iter_py(root)]
    prod = [m for m in modules if m["module"].startswith(PACKAGE + ".")]
    factory = [m for m in prod if Path(m["path"]).name.startswith("factory_")]
    validators = extract_validator_ids(root)
    return {
        "schema_version": 1,
        "python_module_count": len(prod),
        "factory_module_count": len(factory),
        "test_count": count_tests(modules),
        "total_loc": sum(m["loc"] for m in prod),
        "factory_loc": sum(m["loc"] for m in factory),
        "over_500_loc": sorted(m["path"] for m in prod if m["loc"] > 500),
        "over_800_loc": sorted(m["path"] for m in prod if m["loc"] > 800),
        "import_cycles": find_import_cycles(modules),
        "private_cross_imports": find_private_imports(modules),
        "cli_commands": extract_cli_commands(root),
        "validator_checks": validators["checks"],
        "run_kinds": validators["run_kinds"],
        "artifact_refs_by_module": {m["module"]: m["artifact_refs"]
                                    for m in prod if m["artifact_refs"]},
        "root_markdown": sorted(p.name for p in root.glob("*.md")),
        "known_flaky": sorted(known_flaky or []),
        "modules": modules,
    }
