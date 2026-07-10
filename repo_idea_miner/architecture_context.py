# AI Context Pack — atlas.json에서 작업에 필요한 slice만 결정론적으로 조회한다 (AI-Only 주문서 §15~§16).
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from repo_idea_miner.architecture_atlas import (
    ATLAS_DIR,
    ATLAS_JSON,
    load_manifest,
)

DEFAULT_DEPTH = 1
DEFAULT_MAX_PRIMARY = 5
DEFAULT_MAX_SECONDARY = 8

SELECTOR_KEYS = ("canon", "route", "module", "symbol", "cli", "artifact", "component")


def load_atlas(root: Path) -> dict:
    path = root / ATLAS_DIR / ATLAS_JSON
    if not path.is_file():
        raise FileNotFoundError("architecture/atlas.json 없음 — architecture-build를 먼저 실행")
    return json.loads(path.read_text(encoding="utf-8"))


def _changed_py_stems(root: Path) -> tuple[list[str], list[str]]:
    """git diff --name-only HEAD 기반 변경 파일 → (패키지 모듈 stem, 비-파이썬 변경)."""
    try:
        r = subprocess.run(["git", "diff", "--name-only", "HEAD"], cwd=root,
                           capture_output=True, text=True, timeout=30)
        files = sorted(x.replace("\\", "/") for x in r.stdout.splitlines() if x.strip())
    except OSError:
        return [], []
    stems, other = [], []
    for f in files:
        p = Path(f)
        if f.endswith(".py") and p.parts and p.parts[0] == "repo_idea_miner":
            stems.append(p.stem)
        else:
            other.append(f)
    return stems, other


def _symbol_module_stem(symbol_id: str, module_stems: set[str]) -> str:
    parts = symbol_id.split(".")
    if parts[-1] in module_stems:
        return parts[-1]
    return parts[-2] if len(parts) >= 2 else parts[-1]


def build_context(root: Path, selectors: dict, impact: bool = False,
                  depth: int = DEFAULT_DEPTH,
                  max_primary: int = DEFAULT_MAX_PRIMARY,
                  max_secondary: int = DEFAULT_MAX_SECONDARY) -> dict:
    """selector → AI Context Pack (§15.3). 같은 atlas.json·같은 query면 byte-identical."""
    atlas = load_atlas(root)
    manifest = load_manifest(root)
    warnings: list[str] = []

    modules = atlas["modules"]
    mod_by_stem = {m["module"].split(".")[-1]: m for m in modules}
    module_stems = set(mod_by_stem)
    routes_by_id = {r["route_id"]: r for r in atlas["routes"]}
    symbols_by_id = {s["symbol_id"]: s for s in atlas["symbols"]}

    sel_canons: set[str] = set()
    sel_routes: list[str] = []       # 선언 순서 유지 (read_first 랭킹)
    sel_stems: list[str] = []        # 선택 순서 유지
    sel_symbol_ids: set[str] = set()
    sel_artifacts: list[dict] = []

    def add_route(rid: str) -> None:
        if rid not in sel_routes:
            sel_routes.append(rid)
        r = routes_by_id[rid]
        sel_canons.update(r["canon_ids"])
        for step in r["steps"]:
            sel_symbol_ids.add(step)
            add_stem(_symbol_module_stem(step, module_stems))

    def add_stem(stem: str) -> None:
        if stem in module_stems and stem not in sel_stems:
            sel_stems.append(stem)

    # ---- selector 해석 (결정론: 입력 순서 → 정렬된 확장)
    for c in selectors.get("canon", []):
        if not any(c == rc for rc in _all_canon_ids(atlas)):
            warnings.append(f"selector 불일치: canon {c}")
            continue
        sel_canons.add(c)
        for r in atlas["routes"]:
            if c in r["canon_ids"]:
                add_route(r["route_id"])
    for rid in selectors.get("route", []):
        if rid in routes_by_id:
            add_route(rid)
        else:
            warnings.append(f"selector 불일치: route {rid}")
    for comp_id in selectors.get("component", []):
        comp = atlas["components"].get(comp_id)
        if comp is None:
            warnings.append(f"selector 불일치: component {comp_id}")
            continue
        sel_canons.update(comp["canon_ids"])
        for stem in sorted(comp["modules"]):
            add_stem(stem)
    for mod in selectors.get("module", []):
        stem = mod.split(".")[-1]
        if stem in module_stems:
            add_stem(stem)
        else:
            warnings.append(f"selector 불일치: module {mod}")
    for sym in selectors.get("symbol", []):
        matches = [sid for sid in sorted(symbols_by_id)
                   if sid == sym or sid.endswith("." + sym)]
        if not matches:
            warnings.append(f"selector 불일치: symbol {sym}")
        for sid in matches:
            sel_symbol_ids.add(sid)
            add_stem(_symbol_module_stem(sid, module_stems))
    for cli in selectors.get("cli", []):
        hit = False
        for r in atlas["routes"]:
            if r["cli"] == cli:
                add_route(r["route_id"])
                hit = True
        for c in atlas["cli"]:
            if c["command"] == cli and c["handler"]:
                sel_symbol_ids.add(f"repo_idea_miner.cli_handlers.{c['handler']}")
                add_stem("cli_handlers")
                hit = True
        if not hit:
            warnings.append(f"selector 불일치: cli {cli}")
    for art in selectors.get("artifact", []):
        matches = [a for a in atlas["artifacts"]
                   if a["artifact_id"] == art or art in a["path_pattern"]]
        if not matches:
            warnings.append(f"selector 불일치: artifact {art}")
        for a in matches:
            sel_artifacts.append(a)
            add_stem(_symbol_module_stem(a["symbol_id"], module_stems))
    changed_other: list[str] = []
    if selectors.get("changed"):
        stems, changed_other = _changed_py_stems(root)
        if not stems and not changed_other:
            warnings.append("--changed: HEAD 대비 변경 파일 없음")
        for s in stems:
            if s in module_stems:
                add_stem(s)
            else:
                warnings.append(f"--changed: manifest 밖 파이썬 파일 {s}")

    # ---- 확장: component canon, 모듈 내 canonical symbol
    for stem in sel_stems:
        comp_id = mod_by_stem[stem]["component"]
        comp = atlas["components"].get(comp_id, {})
        sel_canons.update(comp.get("canon_ids", []))
    for sid, s in symbols_by_id.items():
        if _symbol_module_stem(sid, module_stems) in sel_stems:
            sel_symbol_ids.add(sid)

    # ---- contracts / invariants in scope
    contracts = [
        c for c in atlas["contracts"]
        if set(c["canon_ids"]) & sel_canons
        or _symbol_module_stem(c["owner_symbol"], module_stems) in sel_stems
        or any(_symbol_module_stem(s, module_stems) in sel_stems
               for s in c["consumer_symbols"] + c["validator_symbols"])
    ]
    invariants = [
        i for i in atlas["invariants"]
        if i["canon_id"] in sel_canons
        or any(_symbol_module_stem(s, module_stems) in sel_stems for s in i["applies_to"])
    ]

    # ---- read_first / read_if_needed (§15.4)
    def _is_hub(stem: str) -> bool:
        """dispatch 허브(cli component)는 orchestrator 뒤로 미룬다 — 모든 모듈을 import해 노이즈."""
        return mod_by_stem.get(stem, {}).get("component") == "cli"

    ordered_paths: list[str] = []
    deferred_paths: list[str] = []

    def push(stem: str) -> None:
        m = mod_by_stem.get(stem)
        if not m:
            return
        target = deferred_paths if _is_hub(stem) else ordered_paths
        if m["path"] not in ordered_paths and m["path"] not in deferred_paths:
            target.append(m["path"])

    for rid in sel_routes:
        for step in routes_by_id[rid]["steps"]:
            push(_symbol_module_stem(step, module_stems))
    for stem in sel_stems:
        push(stem)
    for c in contracts:
        push(_symbol_module_stem(c["owner_symbol"], module_stems))
    ordered_paths += deferred_paths

    def _entry(path: str) -> dict:
        syms = sorted(
            ({"symbol_id": s["symbol_id"], "start_line": s["start_line"],
              "end_line": s["end_line"], "signature": s["signature"]}
             for s in symbols_by_id.values()
             if s["path"] == path and s["symbol_id"] in sel_symbol_ids),
            key=lambda d: d["start_line"])
        return {"path": path, "symbols": syms}

    read_first = [_entry(p) for p in ordered_paths[:max_primary]]
    overflow = ordered_paths[max_primary:]
    if overflow:
        warnings.append(f"primary file 제한 초과: {len(ordered_paths)} > {max_primary} — 초과분은 read_if_needed로")

    secondary: list[str] = list(overflow)
    if depth >= 1:
        primary_stems = {Path(p).stem for p in ordered_paths[:max_primary]}
        neighbor_mods: set[str] = set()
        for stem in sorted(primary_stems):
            m = mod_by_stem.get(stem)
            if not m or _is_hub(stem):  # dispatch 허브의 이웃(=전 모듈)은 확장하지 않는다
                continue
            neighbor_mods.update(i["from"] for i in m["imports"])
            neighbor_mods.update(nb for nb in m["imported_by"]
                                 if not _is_hub(nb.split(".")[-1]))
        for nm in sorted(neighbor_mods):
            p = mod_by_stem.get(nm.split(".")[-1], {}).get("path")
            if p and p not in ordered_paths[:max_primary] and p not in secondary:
                secondary.append(p)
    read_if_needed = secondary[:max_secondary]
    if len(secondary) > max_secondary:
        warnings.append(f"secondary file 제한 초과: {len(secondary)} > {max_secondary} — 목록 절단")

    # ---- artifacts (LITERAL_REFERENCE는 기본 제외 §13)
    scoped_artifacts = sorted(
        (a for a in atlas["artifacts"]
         if a["role"] != "LITERAL_REFERENCE"
         and (a in sel_artifacts
              or _symbol_module_stem(a["symbol_id"], module_stems) in sel_stems)),
        key=lambda a: (a["artifact_id"], a["role"], a["symbol_id"], a["provenance"]))

    # ---- tests / verification / do_not_modify
    tests = set()
    for stem in sel_stems:
        tests.update(mod_by_stem[stem]["tests"])
    for i in invariants:
        tests.update(i["tests"])
    tests_to_run = sorted(tests)
    verification_commands = []
    if tests_to_run:
        verification_commands.append(
            "python -m pytest " + " ".join(f"tests/{t}.py" for t in tests_to_run) + " -q")
    verification_commands.append("python -m repo_idea_miner architecture-check")
    do_not_modify = sorted(
        manifest.get("rules", {}).get("do_not_modify", {}).get("entries", []))

    out = {
        "selectors": {k: sorted(selectors.get(k, [])) for k in SELECTOR_KEYS}
        | {"changed": bool(selectors.get("changed"))},
        "canon_ids": sorted(sel_canons),
        "routes": sel_routes,
        "read_first": read_first,
        "read_if_needed": read_if_needed,
        "contracts": contracts,
        "invariants": invariants,
        "artifacts": scoped_artifacts,
        "tests_to_run": tests_to_run,
        "verification_commands": verification_commands,
        "do_not_modify": do_not_modify,
        "warnings": sorted(set(warnings)),
    }
    if impact:
        out["direct_static_impact"] = _direct_static_impact(
            root, atlas, sel_stems, mod_by_stem, module_stems, contracts, invariants,
            changed=bool(selectors.get("changed")), changed_other=changed_other)
    return out


def _all_canon_ids(atlas: dict) -> set[str]:
    out: set[str] = set()
    for c in atlas["components"].values():
        out.update(c["canon_ids"])
    for r in atlas["routes"]:
        out.update(r["canon_ids"])
    return out


def _direct_static_impact(root: Path, atlas: dict, sel_stems: list[str],
                          mod_by_stem: dict, module_stems: set[str],
                          contracts: list[dict], invariants: list[dict],
                          changed: bool, changed_other: list[str]) -> dict:
    """§16 direct static impact — 완전한 runtime 영향이 아니라 정적 1-hop 사실만."""
    sel_full = {mod_by_stem[s]["module"] for s in sel_stems}
    consumers = sorted({
        m["module"] for m in atlas["modules"]
        if any(i["from"] in sel_full for i in m["imports"])
    })
    affected_routes = sorted({
        r["route_id"] for r in atlas["routes"]
        if any(_symbol_module_stem(s, module_stems) in sel_stems for s in r["steps"])
    })
    producers = sorted({
        a["artifact_id"] for a in atlas["artifacts"]
        if a["role"] == "PRODUCES"
        and _symbol_module_stem(a["symbol_id"], module_stems) in sel_stems})
    consumes = sorted({
        a["artifact_id"] for a in atlas["artifacts"]
        if a["role"] == "CONSUMES"
        and _symbol_module_stem(a["symbol_id"], module_stems) in sel_stems})
    validators = sorted({v for c in contracts for v in c["validator_symbols"]})
    related_tests = set()
    for stem in sel_stems:
        related_tests.update(mod_by_stem[stem]["tests"])
    for m in atlas["modules"]:
        if m["module"] in consumers:
            related_tests.update(m["tests"])
    if "cli_handlers" in sel_stems:  # 모든 handler가 한 모듈에 있으므로 전체 command가 정적 영향권
        clis = sorted(c["command"] for c in atlas["cli"])
    else:
        clis = sorted({r["cli"] for r in atlas["routes"] if r["route_id"] in affected_routes})
    presentation = sorted(
        m for m in consumers
        if mod_by_stem.get(m.split(".")[-1], {}).get("component") == "dashboard")

    impact = {
        "note": "direct_static_impact — 정적 1-hop 사실. 완전한 runtime 영향이 아님",
        "direct_import_consumers": consumers,
        "canonical_routes": affected_routes,
        "artifact_producers": producers,
        "artifact_consumers": consumes,
        "validators": validators,
        "contracts": sorted(c["contract_id"] for c in contracts),
        "invariants": sorted(i["invariant_id"] for i in invariants),
        "related_tests": sorted(related_tests),
        "cli": clis,
        "presentation_consumers": presentation,
    }
    if changed:
        from repo_idea_miner.architecture_atlas import build_atlas

        live_fp = build_atlas(root)["repository"]["structural_fingerprint"]
        committed_fp = atlas["repository"]["structural_fingerprint"]
        fp_changed = live_fp != committed_fp
        impact["changed"] = {
            "changed_components": sorted({mod_by_stem[s]["component"] for s in sel_stems}),
            "affected_routes": affected_routes,
            "canon_sections_to_review": sorted(
                {c for s in sel_stems
                 for c in atlas["components"][mod_by_stem[s]["component"]]["canon_ids"]}),
            "targeted_tests": sorted(related_tests),
            "changed_non_python": changed_other,
            "structure_fingerprint_changed": fp_changed,
            "atlas_rebuild_required": fp_changed,
            "project_markdown_update_required": fp_changed,
        }
    return impact


def render_compact(ctx: dict) -> str:
    """--compact: AI용 결정론적 line format (사람용 리포트 아님)."""
    lines: list[str] = []
    for c in ctx["canon_ids"]:
        lines.append(f"CANON {c}")
    for r in ctx["routes"]:
        lines.append(f"ROUTE {r}")
    for e in ctx["read_first"]:
        syms = " ".join(f"{s['symbol_id'].split('.')[-1]}@{s['start_line']}-{s['end_line']}"
                        for s in e["symbols"])
        lines.append(f"READ_FIRST {e['path']}" + (f" {syms}" if syms else ""))
    for p in ctx["read_if_needed"]:
        lines.append(f"READ_IF {p}")
    for c in ctx["contracts"]:
        lines.append(f"CONTRACT {c['contract_id']} owner={c['owner_symbol']}")
    for i in ctx["invariants"]:
        lines.append(f"INVARIANT {i['invariant_id']} canon={i['canon_id']}")
    for a in ctx["artifacts"]:
        lines.append(f"ARTIFACT {a['role']} {a['path_pattern']} via={a['symbol_id']}")
    for t in ctx["tests_to_run"]:
        lines.append(f"TEST {t}")
    for v in ctx["verification_commands"]:
        lines.append(f"VERIFY {v}")
    for d in ctx["do_not_modify"]:
        lines.append(f"DO_NOT_MODIFY {d}")
    impact = ctx.get("direct_static_impact")
    if impact:
        for m in impact["direct_import_consumers"]:
            lines.append(f"IMPACT_IMPORT {m}")
        for r in impact["canonical_routes"]:
            lines.append(f"IMPACT_ROUTE {r}")
        ch = impact.get("changed")
        if ch:
            lines.append(f"IMPACT_FINGERPRINT_CHANGED {str(ch['structure_fingerprint_changed']).lower()}")
    for w in ctx["warnings"]:
        lines.append(f"WARN {w}")
    return "\n".join(lines)
