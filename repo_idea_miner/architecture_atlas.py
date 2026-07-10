# Architecture Atlas 빌더/검사기 — scanner 사실 + manifest 의미를 결정론적 atlas.json(schema V2)으로 만들고 구조 규칙을 검사한다.
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from repo_idea_miner.architecture_scanner import (
    ATLAS_DIR,
    ATLAS_JSON,
    MANIFEST_NAME,
    PACKAGE,
    build_baseline,
    extract_cli_details,
    load_manifest,
    resolve_symbols,
)

ATLAS_SCHEMA = "atlas.schema.json"

ROOT_MD_WHITELIST = ("AI_INDEX.md", "PROJECT_CANON.md", "README.md", "REENTRY.md")

ARTIFACT_ROLES = ("PRODUCES", "CONSUMES", "VALIDATES", "LITERAL_REFERENCE")
ARTIFACT_PROVENANCES = ("AST_IMPORT", "AST_IO_CALL", "REGISTRY", "MANIFEST", "AST_STRING_LITERAL")

_CANON_ID_RE = re.compile(r"^## (CANON-\d{2})\b", re.M)
_CANON_SECTION_RE = re.compile(r"^## (CANON-\d{2})[^\n]*$", re.M)
_INDEX_ID_RE = re.compile(r"\b(CANON-\d{2})\b")
_INV_ID_RE = re.compile(r"\b(INV-[A-Z0-9-]+)\b")
_MD_LINK_RE = re.compile(r"\]\(([^)#`\s]+\.md)\)")


# ---------------------------------------------------------------- manifest

def module_component_map(manifest: dict) -> dict[str, str]:
    """짧은 모듈명(stem) → component id."""
    out: dict[str, str] = {}
    for cid, comp in manifest.get("components", {}).items():
        for mod in comp.get("modules", []):
            out[mod] = cid
    return out


# ---------------------------------------------------------------- atlas build

def _git_head(root: Path) -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def _committed_structural_fingerprint(root: Path) -> str | None:
    """git HEAD에 커밋된 atlas.json의 구조 지문 (structural_diff 기준선 — 같은 HEAD면 결정론)."""
    try:
        r = subprocess.run(["git", "show", f"HEAD:{ATLAS_DIR}/{ATLAS_JSON}"], cwd=root,
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout:
            data = json.loads(r.stdout)
            return data.get("repository", {}).get("structural_fingerprint") \
                or data.get("fingerprint")
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _test_mapping(modules: list[dict]) -> dict[str, list[str]]:
    """test 모듈 → import하는 production 모듈 (짧은 이름)."""
    out: dict[str, list[str]] = {}
    for m in modules:
        if not m["module"].startswith("tests."):
            continue
        srcs = sorted({imp["from"].split(".")[-1] for imp in m["imports"]
                       if imp["from"].startswith(PACKAGE)})
        if srcs:
            out[m["module"].split(".")[-1]] = srcs
    return out


def _cli_handlers_map(root: Path) -> dict[str, str]:
    """cli_handlers.HANDLERS의 command → handler 함수명 (AST — 결정론)."""
    import ast
    tree = ast.parse((root / PACKAGE / "cli_handlers.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == "HANDLERS" and isinstance(node.value, ast.Dict):
            return {str(k.value): v.id for k, v in zip(node.value.keys, node.value.values)
                    if isinstance(k, ast.Constant) and isinstance(v, ast.Name)}
    return {}


def _document_routes(root: Path) -> list[dict]:
    """AI_INDEX.md 라우팅 표를 기계 구조로 파싱한다 (§10.1 document_routes)."""
    rows: list[dict] = []
    for line in (root / "AI_INDEX.md").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 4 or cells[0] == "ROUTE_ID" or set(cells[0]) <= {"-"}:
            continue
        rows.append({
            "route_id": cells[0],
            "selectors": [s.strip() for s in cells[1].split(",") if s.strip()],
            "canon_ids": [s.strip() for s in cells[2].split(",") if s.strip()],
            "atlas_query": cells[3],
        })
    return rows


def _collect_symbol_specs(manifest: dict, handlers: dict[str, str]) \
        -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """§11 수집 대상 symbol id → roles / canon_ids. private helper는 수집하지 않는다."""
    roles: dict[str, set[str]] = {}
    canon: dict[str, set[str]] = {}

    def add(sid: str, role: str, cids=()) -> None:
        roles.setdefault(sid, set()).add(role)
        canon.setdefault(sid, set()).update(cids)

    for _cmd, fn in sorted(handlers.items()):
        add(f"{PACKAGE}.cli_handlers.{fn}", "cli_handler")
    for r in manifest.get("routes", []):
        for i, step in enumerate(r.get("steps", [])):
            add(step, "entrypoint" if i == 0 else "orchestrator", r.get("canon_ids", []))
    for c in manifest.get("contracts", []):
        add(c["owner_symbol"], "contract_owner", c.get("canon_ids", []))
        for s in c.get("consumer_symbols", []):
            add(s, "contract_consumer", c.get("canon_ids", []))
        for s in c.get("validator_symbols", []):
            add(s, "validator", c.get("canon_ids", []))
    for inv in manifest.get("invariants", []):
        for s in inv.get("applies_to", []):
            add(s, "invariant_target", [inv["canon_id"]])
    return roles, canon


def _artifact_id(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()


def _build_artifacts(manifest: dict, prod: list[dict]) -> list[dict]:
    """§13 artifact 관계 — role + provenance. 애매한 문자열은 LITERAL_REFERENCE로만 남긴다."""
    entries: dict[tuple, dict] = {}

    def add(name: str, role: str, symbol_id: str, provenance: str,
            source_path: str, source_line: int) -> None:
        key = (_artifact_id(name), role, symbol_id, provenance)
        cur = entries.get(key)
        if cur is None or source_line < cur["source_line"]:
            entries[key] = {
                "artifact_id": _artifact_id(name),
                "path_pattern": name,
                "role": role,
                "symbol_id": symbol_id,
                "provenance": provenance,
                "source_path": source_path,
                "source_line": source_line,
            }

    for fname, mods in sorted(manifest.get("artifact_producers", {}).items()):
        for mod in mods:
            add(fname, "PRODUCES", f"{PACKAGE}.{mod}", "MANIFEST",
                f"{ATLAS_DIR}/{MANIFEST_NAME}", 0)
    for m in prod:
        io_names = {io["name"] for io in m["artifact_io_calls"]}
        for io in m["artifact_io_calls"]:
            add(io["name"], io["role"], m["module"], "AST_IO_CALL", m["path"], io["line"])
        for ref in m["artifact_refs"]:
            if ref not in io_names:
                add(ref, "LITERAL_REFERENCE", m["module"], "AST_STRING_LITERAL", m["path"], 0)
    return [entries[k] for k in sorted(entries)]


def compute_fingerprint(atlas: dict) -> str:
    """구조 지문 — 함수 내부 구현·라인 이동만으로는 변하지 않는다 (line 번호는 basis 제외)."""
    basis = {
        "components": atlas["components"],
        "modules": [
            {"module": m["module"], "public": m["public_symbols"],
             "imports": [(i["from"], tuple(i["names"])) for i in m["imports"]]}
            for m in atlas["modules"]
        ],
        "symbols": [
            {k: s[k] for k in ("symbol_id", "kind", "signature", "component_id",
                               "roles", "canon_ids")}
            for s in atlas["symbols"]
        ],
        "routes": atlas["routes"],
        "contracts": atlas["contracts"],
        "invariants": atlas["invariants"],
        "artifacts": [
            {k: a[k] for k in ("artifact_id", "path_pattern", "role", "symbol_id",
                               "provenance")}
            for a in atlas["artifacts"]
        ],
        "cli": atlas["cli"],
        "validators": atlas["validators"],
        "tests": atlas["tests"],
        "document_routes": atlas["document_routes"],
    }
    payload = json.dumps(basis, ensure_ascii=False, sort_keys=True, default=list)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_atlas(root: Path) -> dict:
    """scanner 사실 + manifest 의미 → atlas dict (schema V2 §10). 같은 HEAD·manifest면 결정론적으로 동일하다."""
    manifest = load_manifest(root)
    comp_map = module_component_map(manifest)
    base = build_baseline(root)
    handlers = _cli_handlers_map(root)
    cli_details = {d["command"]: d["options"] for d in extract_cli_details(root)}

    prod = [m for m in base["modules"] if m["module"].startswith(PACKAGE + ".")]
    imported_by: dict[str, list[str]] = {}
    for m in prod:
        for imp in m["imports"]:
            imported_by.setdefault(imp["from"], []).append(m["module"])
    tests = _test_mapping(base["modules"])
    tests_by_src: dict[str, list[str]] = {}
    for t, srcs in tests.items():
        for s in srcs:
            tests_by_src.setdefault(s, []).append(t)

    modules = []
    for m in prod:
        stem = m["module"].split(".")[-1]
        modules.append({
            "module": m["module"],
            "path": m["path"],
            "loc": m["loc"],
            "component": comp_map.get(stem, "unknown"),
            "public_symbols": m["public_symbols"],
            "private_symbols": m["private_symbols"],
            "imports": m["imports"],
            "imported_by": sorted(set(imported_by.get(m["module"], []))),
            "artifact_refs": m["artifact_refs"],
            "tests": sorted(set(tests_by_src.get(stem, []))),
        })

    # §11 core symbol index — manifest·HANDLERS가 지정한 canonical symbol만 AST로 해상한다.
    sym_roles, sym_canon = _collect_symbol_specs(manifest, handlers)
    resolved = resolve_symbols(root, sorted(sym_roles))
    symbols, unresolved = [], []
    for sid in sorted(sym_roles):
        info = resolved.get(sid)
        if info is None:
            unresolved.append(sid)
            continue
        stem = sid.rsplit(".", 2)[-2]
        comp = comp_map.get(stem, "unknown")
        cids = sym_canon.get(sid) or set()
        if not cids:
            comp_decl = manifest.get("components", {}).get(comp, {})
            cids = set(comp_decl.get("canon_ids", []))
        symbols.append({
            **info,
            "component_id": comp,
            "roles": sorted(sym_roles[sid]),
            "canon_ids": sorted(cids),
            "related_tests": sorted(set(tests_by_src.get(stem, []))),
        })

    routes = [
        {"route_id": r["id"], "canon_ids": r.get("canon_ids", []), "cli": r.get("cli", ""),
         "steps": r.get("steps", [])}
        for r in manifest.get("routes", [])
    ]
    contracts = [
        {"contract_id": c["id"], "owner_symbol": c["owner_symbol"],
         "consumer_symbols": c.get("consumer_symbols", []),
         "validator_symbols": c.get("validator_symbols", []),
         "canon_ids": c.get("canon_ids", []),
         "compatibility": c.get("compatibility", ""), "risk": c.get("risk", "")}
        for c in manifest.get("contracts", [])
    ]
    invariants = [
        {"invariant_id": i["id"], "canon_id": i["canon_id"],
         "applies_to": i.get("applies_to", []), "tests": i.get("tests", [])}
        for i in manifest.get("invariants", [])
    ]

    private_allow = set(manifest.get("rules", {}).get("private_import_allowlist", {}).get("entries", []))
    private_extra = [
        p for p in base["private_cross_imports"]
        if not all(f"{p['module']} <- {p['from']}:{n}" in private_allow for n in p["names"])
    ]
    orphans = sorted(
        m["module"] for m in modules
        if not m["imported_by"] and m["module"].split(".")[-1] not in
        ("__init__", "__main__", "cli", "architecture_atlas")  # 패키지/entry/도구는 orphan 아님
        and not m["tests"]
    )

    atlas = {
        "schema_version": 2,
        "components": {
            cid: {"component_id": cid, "status": c["status"],
                  "canon_ids": sorted(c["canon_ids"]), "modules": sorted(c["modules"])}
            for cid, c in sorted(manifest["components"].items())
        },
        "modules": modules,
        "symbols": symbols,
        "routes": routes,
        "artifacts": _build_artifacts(manifest, prod),
        "contracts": contracts,
        "invariants": invariants,
        "cli": [
            {"command": cmd, "handler": handlers.get(cmd, ""), "options": cli_details.get(cmd, []),
             "source": f"{PACKAGE}.cli_handlers"}
            for cmd in base["cli_commands"]
        ],
        "validators": {"checks": base["validator_checks"], "run_kinds": base["run_kinds"]},
        "tests": tests,
        "document_routes": _document_routes(root),
        "health": {
            "import_cycles": base["import_cycles"],
            "private_cross_imports": base["private_cross_imports"],
            "private_cross_imports_outside_allowlist": private_extra,
            "orphan_modules": orphans,
            "unknown_component": sorted(m["module"] for m in modules if m["component"] == "unknown"),
            "unresolved_symbols": unresolved,
            "over_500_loc": base["over_500_loc"],
            "over_800_loc": base["over_800_loc"],
            "module_count": base["python_module_count"],
            "test_count": base["test_count"],
        },
    }
    fp = compute_fingerprint(atlas)
    committed_fp = _committed_structural_fingerprint(root)
    atlas["repository"] = {
        "head": _git_head(root),
        "structure_snapshot": hashlib.sha256(
            json.dumps([m["path"] for m in modules], sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "structural_fingerprint": fp,
        "structural_diff": committed_fp is not None and committed_fp != fp,
    }
    return atlas


_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "RIM Architecture Atlas",
    "type": "object",
    "required": ["schema_version", "repository", "components", "modules", "symbols",
                 "routes", "artifacts", "contracts", "invariants", "validators",
                 "tests", "document_routes", "health"],
    "properties": {
        "schema_version": {"const": 2},
        "repository": {"type": "object", "required": [
            "head", "structure_snapshot", "structural_fingerprint", "structural_diff"]},
        "components": {"type": "object"},
        "modules": {"type": "array", "items": {"type": "object", "required": [
            "module", "path", "loc", "component", "public_symbols", "imports", "imported_by"]}},
        "symbols": {"type": "array", "items": {"type": "object", "required": [
            "symbol_id", "kind", "path", "start_line", "end_line", "signature",
            "component_id", "roles", "canon_ids", "related_tests"]}},
        "routes": {"type": "array", "items": {"type": "object", "required": [
            "route_id", "canon_ids", "cli", "steps"]}},
        "artifacts": {"type": "array", "items": {"type": "object", "required": [
            "artifact_id", "path_pattern", "role", "symbol_id", "provenance",
            "source_path", "source_line"],
            "properties": {"role": {"enum": list(ARTIFACT_ROLES)},
                           "provenance": {"enum": list(ARTIFACT_PROVENANCES)}}}},
        "contracts": {"type": "array", "items": {"type": "object", "required": [
            "contract_id", "owner_symbol", "consumer_symbols", "validator_symbols",
            "canon_ids", "compatibility", "risk"]}},
        "invariants": {"type": "array", "items": {"type": "object", "required": [
            "invariant_id", "canon_id", "applies_to", "tests"]}},
        "cli": {"type": "array", "items": {"type": "object", "required": ["command", "handler", "options"]}},
        "validators": {"type": "object"},
        "tests": {"type": "object"},
        "document_routes": {"type": "array", "items": {"type": "object", "required": [
            "route_id", "selectors", "canon_ids", "atlas_query"]}},
        "health": {"type": "object"},
    },
}


def write_atlas(root: Path) -> dict:
    """atlas.json / atlas.schema.json을 생성한다 (byte-deterministic, AI 전용 — HTML 없음)."""
    atlas = build_atlas(root)
    out_dir = root / ATLAS_DIR
    out_dir.mkdir(exist_ok=True)
    (out_dir / ATLAS_JSON).write_text(
        json.dumps(atlas, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    (out_dir / ATLAS_SCHEMA).write_text(
        json.dumps(_SCHEMA, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    return atlas


# ---------------------------------------------------------------- architecture-check

def _tracked_md(root: Path) -> list[str] | None:
    """git tracked *.md 전체 (repo-relative posix path). git 없으면 None."""
    try:
        r = subprocess.run(["git", "ls-files", "*.md"], cwd=root,
                           capture_output=True, text=True, timeout=30)
    except OSError:
        return None
    return sorted(x.replace("\\", "/") for x in r.stdout.splitlines() if x.strip())


def _canon_ids(root: Path) -> tuple[set[str], set[str]]:
    canon = _CANON_ID_RE.findall((root / "PROJECT_CANON.md").read_text(encoding="utf-8"))
    index = _INDEX_ID_RE.findall((root / "AI_INDEX.md").read_text(encoding="utf-8"))
    return set(canon), set(index)


def _canon_section_bodies(root: Path) -> dict[str, str]:
    """CANON-ID → 섹션 본문 (invariant 소속 검증용)."""
    text = (root / "PROJECT_CANON.md").read_text(encoding="utf-8")
    parts = _CANON_SECTION_RE.split(text)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def _last_commit_files(root: Path) -> set[str]:
    try:
        r = subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"], cwd=root,
                           capture_output=True, text=True, timeout=30)
        return {x.replace("\\", "/") for x in r.stdout.splitlines() if x.strip()}
    except OSError:
        return set()


README_REQUIRED_SECTIONS = ("## READ ORDER", "## REPOSITORY RULES", "## CONTEXT COMMAND",
                            "## VALIDATION COMMANDS", "## DO NOT")
REENTRY_REQUIRED_SECTIONS = ("HEAD:", "SYSTEM_STATUS:", "RECENT_SEMANTIC_CHANGES:",
                             "OPEN_BLOCKERS:", "NEXT_ACTIONS:", "DO_NOT_REPEAT:", "VERIFY:")
FORBIDDEN_HUMAN_ATLAS_TOKENS = ("architecture/index.html", "architecture-serve",
                                "architecture-summary", "모바일 Atlas")
DOC_SIZE_LIMITS = {"README.md": 4096, "AI_INDEX.md": 6144,
                   "PROJECT_CANON.md": 20480, "REENTRY.md": 8192}


def run_architecture_check(root: Path, secrets: list[str] | None = None,
                           warnings: list[str] | None = None) -> list[str]:
    """구조·문서 governance 검사 — 문제 목록을 돌려준다 (비면 PASS).
    warnings 리스트를 넘기면 §17.2 비차단 경고를 채운다."""
    problems: list[str] = []
    atlas = build_atlas(root)
    manifest = load_manifest(root)
    h = atlas["health"]

    # 1. root Markdown 정확히 4개 (git tracked 기준 — untracked 주문서와 충돌 방지)
    tracked_all = _tracked_md(root)
    tracked = {Path(x).name for x in tracked_all if "/" not in x} if tracked_all is not None else None
    if tracked is not None and tracked != set(ROOT_MD_WHITELIST):
        problems.append(f"root markdown whitelist 위반: {sorted(tracked)}")

    # 1b. 전체 tracked md는 root AI 문서 또는 manifest 선언 fixture여야 한다 (§5.3)
    declared = set(manifest.get("documents", {}).get("fixtures", []))
    if tracked_all is not None:
        for p in tracked_all:
            if ("/" not in p and p in ROOT_MD_WHITELIST) or p in declared:
                continue
            problems.append(f"선언되지 않은 tracked markdown: {p} (root AI 문서/선언 fixture만 허용)")

    # 2. AI_INDEX CANON-ID == PROJECT_CANON CANON-ID
    canon, index = _canon_ids(root)
    if canon != index:
        problems.append(f"CANON/AI_INDEX 불일치: canon만={sorted(canon - index)} index만={sorted(index - canon)}")

    # 3. manifest canon_ids 실재
    for cid, comp in atlas["components"].items():
        for c in comp["canon_ids"]:
            if c not in canon:
                problems.append(f"manifest component {cid}의 canon_id {c}가 PROJECT_CANON에 없음")

    # 4. 존재하지 않는 md 링크 (네 문서 안)
    for name in ROOT_MD_WHITELIST:
        text = (root / name).read_text(encoding="utf-8")
        for link in _MD_LINK_RE.findall(text):
            if link.startswith("http"):
                continue
            if not (root / link).exists():
                problems.append(f"{name}: 깨진 md 링크 {link}")

    # 5. component 미분류 모듈
    for mod in h["unknown_component"]:
        problems.append(f"component 미분류 모듈: {mod}")

    # 6. manifest가 없는 모듈(경로)을 참조
    actual = {p.stem for p in (root / PACKAGE).glob("*.py")}
    for cid, comp in atlas["components"].items():
        for mod in comp["modules"]:
            if mod not in actual:
                problems.append(f"manifest component {cid}가 없는 모듈 참조: {mod}")

    # 7. forbidden dependency
    comp_map = module_component_map(manifest)
    forbid = set(manifest.get("rules", {}).get("dependencies", {}).get("forbid", []))
    for m in atlas["modules"]:
        src_c = m["component"]
        for imp in m["imports"]:
            dst_c = comp_map.get(imp["from"].split(".")[-1], "unknown")
            if src_c != dst_c and f"{src_c} -> {dst_c}" in forbid:
                problems.append(f"금지 의존: {m['module']} → {imp['from']} ({src_c} -> {dst_c})")

    # 8. import cycle
    for cyc in h["import_cycles"]:
        problems.append(f"import cycle: {' ↔ '.join(cyc)}")

    # 9. allowlist 밖 private cross-import
    for p in h["private_cross_imports_outside_allowlist"]:
        problems.append(f"private cross-import: {p['module']} ← {p['from']}:{p['names']}")

    # 10. duplicate CLI command
    cmds = [c["command"] for c in atlas["cli"]]
    for dup in sorted({c for c in cmds if cmds.count(c) > 1}):
        problems.append(f"duplicate CLI command: {dup}")

    # 11. artifact producer 정합: 선언 producer 실재·파일명 참조, 미선언 summary 부재
    #     (writer는 정적으로 판별 불가 — manifest 선언이 사람 정의 진실, §13 과장 금지)
    producers = manifest.get("artifact_producers", {})
    refs_by_stem = {m["module"].split(".")[-1]: set(m["artifact_refs"]) for m in atlas["modules"]}
    for fname, mods in sorted(producers.items()):
        for mod in mods:
            if mod not in actual:
                problems.append(f"artifact producer 선언이 없는 모듈 참조: {fname} → {mod}")
            elif fname not in refs_by_stem.get(mod, set()):
                problems.append(f"선언된 producer {mod}가 {fname}을 참조하지 않음")
    summary_re = re.compile(r"^(phase\w+|product_loop)_dashboard_summary\.json$")
    for m in atlas["modules"]:
        if m["module"].split(".")[-1].startswith("architecture_"):
            continue
        for r in m["artifact_refs"]:
            if summary_re.match(r) and r not in producers:
                problems.append(f"producer 미선언 dashboard summary: {r} (참조: {m['module']})")

    # 12. validator 관련 test 존재 (factory_validate를 import하는 테스트가 최소 1개)
    if not any("factory_validate" in srcs for srcs in atlas["tests"].values()):
        problems.append("factory_validate 관련 테스트 없음")

    # 13. canonical → legacy 역의존 (manifest status 기반)
    status = {cid: c["status"] for cid, c in atlas["components"].items()}
    for m in atlas["modules"]:
        if status.get(m["component"]) != "canonical":
            continue
        for imp in m["imports"]:
            dst_c = comp_map.get(imp["from"].split(".")[-1])
            if dst_c and status.get(dst_c) == "legacy":
                problems.append(f"canonical→legacy 역의존: {m['module']} → {imp['from']}")

    # 14. presentation이 판정/조회 로직 소유 금지 (R5 규칙과 동일)
    dash_src = (root / PACKAGE / "challenge_dashboard.py").read_text(encoding="utf-8")
    if "conn.execute(" in dash_src or "json.loads(" in dash_src:
        problems.append("presentation(challenge_dashboard)이 SQL/JSON 파싱을 소유")

    # 15. committed Atlas stale (구조 지문 비교)
    committed = root / ATLAS_DIR / ATLAS_JSON
    current_fp = atlas["repository"]["structural_fingerprint"]
    if committed.is_file():
        try:
            old = json.loads(committed.read_text(encoding="utf-8"))
            old_fp = old.get("repository", {}).get("structural_fingerprint") or old.get("fingerprint")
            if old_fp != current_fp:
                problems.append("Atlas stale: committed atlas.json fingerprint가 현재 구조와 다름 — architecture-build 재실행 필요")
        except json.JSONDecodeError:
            problems.append("Atlas stale: atlas.json 파싱 불가")
    else:
        problems.append("Atlas 없음: architecture-build를 먼저 실행")

    # 16. 사람용 Atlas HTML/renderer 부재 (AI-only Atlas)
    if (root / ATLAS_DIR / "index.html").is_file():
        problems.append("architecture/index.html 존재 — AI-only Atlas는 HTML을 갖지 않음")
    if (root / PACKAGE / "architecture_render.py").is_file():
        problems.append("architecture_render.py 존재 — HTML renderer는 제거 대상")

    # 17. secret 미포함 (생성 산출물)
    if secrets:
        for name in (ATLAS_JSON, ATLAS_SCHEMA, MANIFEST_NAME):
            p = root / ATLAS_DIR / name
            if p.is_file():
                text = p.read_text(encoding="utf-8", errors="replace")
                if any(s and s in text for s in secrets):
                    problems.append(f"secret 노출: architecture/{name}")

    # 18. canonical routes 정합 (§12): 선언 존재, cli 실재, 첫 step=handler, symbol 해상,
    #     canon 실재, related test 존재
    if not atlas["routes"]:
        problems.append("canonical route 정의 없음 (manifest [[routes]])")
    handlers = _cli_handlers_map(root)
    known_cmds = set(cmds)
    resolved_ids = {s["symbol_id"] for s in atlas["symbols"]}
    tests_by_src: dict[str, set[str]] = {}
    for t, srcs in atlas["tests"].items():
        for s in srcs:
            tests_by_src.setdefault(s, set()).add(t)
    for r in atlas["routes"]:
        rid = r["route_id"]
        if r["cli"] not in known_cmds:
            problems.append(f"route {rid}: 존재하지 않는 CLI {r['cli']}")
        elif r["steps"]:
            expect = f"{PACKAGE}.cli_handlers.{handlers.get(r['cli'], '')}"
            if r["steps"][0] != expect:
                problems.append(f"route {rid}: 첫 step이 {r['cli']} handler({expect})가 아님")
        if not r["steps"]:
            problems.append(f"route {rid}: step 없음")
        for c in r["canon_ids"]:
            if c not in canon:
                problems.append(f"route {rid}: 없는 CANON {c}")
        step_stems = {s.rsplit(".", 2)[-2] for s in r["steps"]}
        if not any(tests_by_src.get(st) for st in step_stems):
            problems.append(f"route {rid}: 관련 테스트 없음")

    # 18b. 해상 실패 symbol (routes/contracts/invariants가 참조하는 canonical symbol 실재)
    for sid in h["unresolved_symbols"]:
        problems.append(f"manifest가 없는 symbol 참조: {sid}")

    # 18c. contracts 정합 (§14.1)
    for c in atlas["contracts"]:
        for cid2 in c["canon_ids"]:
            if cid2 not in canon:
                problems.append(f"contract {c['contract_id']}: 없는 CANON {cid2}")

    # 18d. invariants 정합 (§14.2): CANON 실재 + 해당 섹션 INVARIANTS에 등재 + test 실재
    bodies = _canon_section_bodies(root)
    for inv in atlas["invariants"]:
        iid, cid2 = inv["invariant_id"], inv["canon_id"]
        if cid2 not in canon:
            problems.append(f"invariant {iid}: 없는 CANON {cid2}")
        elif iid not in _INV_ID_RE.findall(bodies.get(cid2, "")):
            problems.append(f"invariant {iid}: PROJECT_CANON {cid2} 섹션에 등재되지 않음")
        for t in inv["tests"]:
            if not (root / "tests" / f"{t}.py").is_file():
                problems.append(f"invariant {iid}: 없는 테스트 {t}")

    # 19. README의 주요 CLI 실재
    readme = (root / "README.md").read_text(encoding="utf-8")
    for m in re.finditer(r"python -m repo_idea_miner\s+([a-z][a-z0-9-]*)", readme):
        if m.group(1) not in known_cmds:
            problems.append(f"README가 없는 CLI를 안내: {m.group(1)}")

    # 20. 삭제된 과거 문서로 가는 실제 md 링크 잔존
    for name in ROOT_MD_WHITELIST:
        text = (root / name).read_text(encoding="utf-8")
        for ghost in ("SCOPE.md", "VERIFICATION.md", "CURRENT_STATE.md", "ARCHITECTURE.md", "checklist.md"):
            if f"]({ghost}" in text:
                problems.append(f"{name}: 삭제된 문서 링크 {ghost}")

    # 21. README AI bootstrap 구조 (§17.1-3, §6)
    for sec in README_REQUIRED_SECTIONS:
        if sec not in readme:
            problems.append(f"README bootstrap 섹션 누락: {sec}")

    # 22. REENTRY 필수 섹션 (§17.1-6, §9)
    reentry = (root / "REENTRY.md").read_text(encoding="utf-8")
    for sec in REENTRY_REQUIRED_SECTIONS:
        if sec not in reentry:
            problems.append(f"REENTRY 필수 섹션 누락: {sec}")

    # 23. architecture-serve/summary CLI 부재 (§17.1-9/10)
    for gone in ("architecture-serve", "architecture-summary"):
        if gone in known_cmds:
            problems.append(f"제거 대상 CLI 존재: {gone}")

    # 24. README·CANON에 사람용 Atlas(HTML/serve/모바일) 설명 부재 (§17.1-22)
    for name in ("README.md", "PROJECT_CANON.md"):
        text = (root / name).read_text(encoding="utf-8")
        for tok in FORBIDDEN_HUMAN_ATLAS_TOKENS:
            if tok in text:
                problems.append(f"{name}: 사람용 Atlas 설명 토큰 잔존 — {tok}")

    # 25. AI_INDEX 라우팅 표 정합 (§17.1-4): CANON 실재 + ATLAS_QUERY selector 해석 가능
    valid_selector_values = {
        "canon": canon,
        "component": set(atlas["components"]),
        "route": {r["route_id"] for r in atlas["routes"]},
        "module": {m["module"].split(".")[-1] for m in atlas["modules"]},
        "symbol": {s["symbol_id"] for s in atlas["symbols"]}
        | {s["symbol_id"].split(".")[-1] for s in atlas["symbols"]},
        "cli": known_cmds,
        "artifact": {a["artifact_id"] for a in atlas["artifacts"]},
    }
    for row in atlas["document_routes"]:
        for c in row["canon_ids"]:
            if c not in canon:
                problems.append(f"AI_INDEX {row['route_id']}: 없는 CANON {c}")
        parts = row["atlas_query"].split()
        kind = parts[0].lstrip("-") if parts and parts[0].startswith("--") else None
        if kind not in valid_selector_values or len(parts) != 2:
            problems.append(f"AI_INDEX {row['route_id']}: 해석 불가 ATLAS_QUERY '{row['atlas_query']}'")
        elif parts[1] not in valid_selector_values[kind]:
            problems.append(f"AI_INDEX {row['route_id']}: 없는 {kind} '{parts[1]}'")

    # 26. contract owner 누락 (§17.1-13)
    for c in atlas["contracts"]:
        if not c["owner_symbol"]:
            problems.append(f"contract {c['contract_id']}: owner_symbol 없음")

    # 27. 같은 입력에서 비결정 atlas (§17.1-20) — 두 번 빌드해 비교
    if build_atlas(root) != atlas:
        problems.append("비결정 atlas: 같은 입력에서 두 빌드 결과가 다름")

    # §17.12 문서 정책: 구조 fingerprint가 바뀌었는데 마지막 commit에 PROJECT_CANON.md가 없으면 FAIL
    if committed.is_file():
        try:
            old = json.loads(committed.read_text(encoding="utf-8"))
            old_fp = old.get("repository", {}).get("structural_fingerprint") or old.get("fingerprint")
        except json.JSONDecodeError:
            old_fp = None
        if old_fp and old_fp != current_fp \
                and "PROJECT_CANON.md" not in _last_commit_files(root):
            problems.append("구조 변경이 커밋되지 않았거나 PROJECT_CANON.md가 같은 커밋에 없음 (§17.12)")

    if warnings is not None:
        warnings.extend(_collect_warnings(root, atlas))
    return problems


def _collect_warnings(root: Path, atlas: dict) -> list[str]:
    """§17.2 비차단 경고 7종 + §18 문서 크기."""
    out: list[str] = []

    # 1. canonical symbol에 test 없음
    for s in atlas["symbols"]:
        if not s["related_tests"]:
            out.append(f"symbol test 없음: {s['symbol_id']}")

    # 2. literal reference로만 존재하는 artifact (집계)
    ids_with_fact = {a["artifact_id"] for a in atlas["artifacts"]
                     if a["role"] != "LITERAL_REFERENCE"}
    literal_only = {a["artifact_id"] for a in atlas["artifacts"]
                    if a["role"] == "LITERAL_REFERENCE"} - ids_with_fact
    if literal_only:
        out.append(f"literal reference로만 존재하는 artifact {len(literal_only)}개 (IO/manifest 실증 없음)")

    # 3. route 밖 public entrypoint (route가 없는 CLI command)
    routed = {r["cli"] for r in atlas["routes"]}
    unrouted = sorted(c["command"] for c in atlas["cli"] if c["command"] not in routed)
    if unrouted:
        out.append(f"route 미선언 CLI: {', '.join(unrouted)}")

    # 4. AI_INDEX query의 Context primary file 제한 초과
    from repo_idea_miner.architecture_context import build_context

    for row in atlas["document_routes"]:
        parts = row["atlas_query"].split()
        if len(parts) != 2 or not parts[0].startswith("--"):
            continue
        try:
            ctx = build_context(root, {parts[0].lstrip("-"): [parts[1]]})
        except FileNotFoundError:
            break
        for w in ctx["warnings"]:
            if "primary file 제한 초과" in w:
                out.append(f"AI_INDEX {row['route_id']}: {w}")

    # 5. contract consumer 미등록
    for c in atlas["contracts"]:
        if not c["consumer_symbols"]:
            out.append(f"contract consumer 미등록: {c['contract_id']}")

    # 6. repository HEAD와 committed atlas HEAD 다름 — 커밋에 포함된 atlas는 필연적으로
    #    직전 HEAD에서 빌드되므로 HEAD~1까지는 정상, 그보다 오래되면 경고
    committed = root / ATLAS_DIR / ATLAS_JSON
    if committed.is_file():
        try:
            old_head = json.loads(committed.read_text(encoding="utf-8")) \
                .get("repository", {}).get("head")
        except json.JSONDecodeError:
            old_head = None
        allowed = {atlas["repository"]["head"]}
        try:
            r = subprocess.run(["git", "rev-parse", "HEAD^"], cwd=root,
                               capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                allowed.add(r.stdout.strip())
        except OSError:
            pass
        if old_head and old_head not in allowed:
            out.append("committed atlas.json의 head가 HEAD/HEAD~1보다 오래됨 (구조 지문은 동일 — 참고)")

    # 7. AI 문서 크기 상한 (§18)
    for name, limit in DOC_SIZE_LIMITS.items():
        size = (root / name).stat().st_size if (root / name).is_file() else 0
        if size > limit:
            out.append(f"문서 크기 초과: {name} {size}B > {limit}B")
    return out
