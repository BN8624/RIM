# 제품 evidence 공통 정본 — viewer/replay 탐색, viewer field evidence, protected hash, gate context를 한 곳에서만 구현한다 (Structural Reset R3, §8.2).
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

# ---------------------------------------------------------------- 공통 IO

def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- Protected hash 정본 (§3.4, §13.3)

_PROTECTED_CONTRACTS = (
    "core_contract.json",
    "state_contract.json",
    "action_contract.json",
    "runner_contract.json",
)
_PROTECTED_DIR_PREFIXES = ("src/", "product/", "golden/", "fixtures/")
_PROTECTED_ROOTS = ("workspace", "final_artifact")


def compute_protected_hashes(run_dir: Path) -> dict[str, str]:
    """보호 대상 artifact logic(src/product/golden/fixtures/contract/oracle)의 sha256 map을 만든다.

    review 산출물/smoke temp/logs/__pycache__는 대상에서 제외한다(§3.4).
    """
    run_dir = Path(run_dir)
    out: dict[str, str] = {}
    for root_name in _PROTECTED_ROOTS:
        base = run_dir / root_name
        if not base.is_dir():
            continue
        for rel in _PROTECTED_CONTRACTS:
            p = base / rel
            if p.is_file():
                out[f"{root_name}/{rel}"] = sha256_file(p)
        for prefix in _PROTECTED_DIR_PREFIXES:
            d = base / prefix.rstrip("/")
            if not d.is_dir():
                continue
            for p in sorted(d.rglob("*")):
                if not p.is_file() or "__pycache__" in p.parts:
                    continue
                out[f"{root_name}/{p.relative_to(base).as_posix()}"] = sha256_file(p)
    orr = run_dir / "oracle_risk_report.json"
    if orr.is_file():
        out["oracle_risk_report.json"] = sha256_file(orr)
    return out


def compare_protected_hashes(before: dict[str, str], after: dict[str, str]) -> dict:
    changed = sorted(k for k in before if k in after and before[k] != after[k])
    removed = sorted(k for k in before if k not in after)
    added = sorted(k for k in after if k not in before)
    ok = not (changed or removed or added)
    return {
        "status": "PASS" if ok else "FAIL",
        "files_checked": len(before),
        "changed": changed,
        "added": added,
        "removed": removed,
        "note": "Phase 2C-0는 no-code-change review — 보호 대상 artifact가 바뀌면 FAIL (§3.4)",
    }


# ---------------------------------------------------------------- Gate context (§5)

def read_gate_context(run_dir: Path) -> dict:
    """green_base / gate 재검증 / phase2b1b 요약에서 하네스 상태를 읽는다 (§5)."""
    gb = load_json(run_dir / "green_base.json") or {}
    p2b1b = load_json(run_dir / "phase2b1b_dashboard_summary.json") or {}
    gr = load_json(run_dir / "gate_rerun_after_anti_hardcode_patch.json") or {}
    gates = gr.get("gates") or p2b1b.get("gates") or {}
    green_base = (gb.get("base_type") == "green_base") or bool(p2b1b.get("promoted_to_green_base"))
    verdict = gb.get("verdict") or p2b1b.get("verdict")
    passed = sum(1 for v in gates.values() if v)
    return {
        "green_base": bool(green_base),
        "green_base_path": gb.get("green_base_path"),
        "verdict": verdict,
        "gates": gates,
        "gates_passed": passed,
        "gates_total": len(gates),
        "gate_fail": bool(gates) and not all(gates.values()),
        "anti_hardcode": bool(gates.get("anti_hardcode")),
        "summary_source": gr.get("summary_source") or p2b1b.get("summary_source"),
        "summary_hardcode_risk": gr.get("summary_hardcode_risk") or p2b1b.get("summary_hardcode_risk"),
        "next_goal": gb.get("next_goal"),
    }


# ---------------------------------------------------------------- Viewer / Replay 탐색 (§6)

def find_product_viewer(final_dir: Path) -> Path | None:
    """product/ 아래 첫 viewer html을 찾는다 (index.html 우선)."""
    product = final_dir / "product"
    if not product.is_dir():
        return None
    htmls = sorted(product.rglob("*.html"))
    for p in htmls:
        if p.name == "index.html":
            return p
    return htmls[0] if htmls else None


def first_replay_file(final_dir: Path) -> tuple[str | None, dict | None]:
    idx = load_json(final_dir / "replay" / "index.json") or {}
    replays = idx.get("replays") or []
    if replays and replays[0].get("file"):
        f = replays[0]["file"]
        return f, load_json(final_dir / "replay" / f)
    # index가 없으면 replay dir에서 직접 첫 파일
    rdir = final_dir / "replay"
    if rdir.is_dir():
        for p in sorted(rdir.glob("replay_*.json")):
            return p.name, load_json(p)
    return None, None


# ---------------------------------------------------------------- Replay node collection 정본 (이슈 #19 §5)

NODE_MAP = "NODE_MAP"
NODE_LIST = "NODE_LIST"
NODE_COLLECTION_EMPTY = "NODE_COLLECTION_EMPTY"
NODE_COLLECTION_MISSING = "NODE_COLLECTION_MISSING"
NODE_COLLECTION_MALFORMED = "NODE_COLLECTION_MALFORMED"
# NODE_COLLECTION_AMBIGUOUS: canonical 경로가 final_state["nodes"] 하나뿐이라 이 evaluator에서는
# 발생하지 않는다 — 다른 키를 crawl하지 않는다(정의만 예약, 이슈 #19 §5.2).
NODE_COLLECTION_AMBIGUOUS = "NODE_COLLECTION_AMBIGUOUS"


def classify_node_collection(final_state) -> dict:
    """replay final_state의 node collection을 shape-safe로 정본 분류한다 (이슈 #19 §5).

    dict(NODE_MAP)와 list(NODE_LIST)는 모두 정상 canonical collection이다. 빈 collection
    (EMPTY)·경로 부재(MISSING)·scalar/null 등 비collection(MALFORMED)을 분리하고,
    canonical node object(dict)가 아닌 entry는 버리지 않고 malformed_entries로 센다 —
    malformed evidence를 빈 evidence로 조용히 처리하지 않는다. 순서는 입력 순서를
    보존한다(결정론). 어떤 입력 shape에서도 예외를 던지지 않는다."""
    if not isinstance(final_state, dict) or "nodes" not in final_state:
        return {"shape": NODE_COLLECTION_MISSING, "nodes": [], "identities": [],
                "malformed_entries": 0}
    raw = final_state["nodes"]
    if isinstance(raw, dict):
        if not raw:
            return {"shape": NODE_COLLECTION_EMPTY, "nodes": [], "identities": [],
                    "malformed_entries": 0}
        nodes = [v for v in raw.values() if isinstance(v, dict)]
        identities = [str(k) for k, v in raw.items() if isinstance(v, dict)]
        return {"shape": NODE_MAP, "nodes": nodes, "identities": identities,
                "malformed_entries": len(raw) - len(nodes)}
    if isinstance(raw, list):
        if not raw:
            return {"shape": NODE_COLLECTION_EMPTY, "nodes": [], "identities": [],
                    "malformed_entries": 0}
        nodes = [e for e in raw if isinstance(e, dict)]
        identities = [str(i) for i, e in enumerate(raw) if isinstance(e, dict)]
        return {"shape": NODE_LIST, "nodes": nodes, "identities": identities,
                "malformed_entries": len(raw) - len(nodes)}
    return {"shape": NODE_COLLECTION_MALFORMED, "nodes": [], "identities": [],
            "malformed_entries": 1}


# ---------------------------------------------------------------- Viewer field evidence (§6.2)

def viewer_reads_replay_evidence(viewer_src: str, replay: dict | None) -> list[str]:
    """viewer가 replay를 읽는다는 근거를 모은다. 단순 fetch 문자열 하나만으로는 부족 (§6.2)."""
    ev: list[str] = []
    if re.search(r"replay/index\.json", viewer_src):
        ev.append("viewer가 replay/index.json을 fetch함 (source)")
    if re.search(r"replay/[`'\"]?\s*\+|replay/\$\{|replay/\$\{?file", viewer_src) or \
            re.search(r"replay/`?\$\{file\}`?", viewer_src):
        ev.append("viewer가 replay/<scenario> 파일을 fetch함 (source)")
    if isinstance(replay, dict):
        # replay 실제 필드를 viewer가 참조하는지 (data.<field> / 하위 status 등)
        for field in ("summary", "events", "final_state"):
            if field in replay and re.search(rf"\bdata\.{field}\b", viewer_src):
                sval = replay.get(field)
                shown = sval if isinstance(sval, str) else f"<{type(sval).__name__}>"
                ev.append(f"smoke가 replay 필드 '{field}'(={shown})를 읽고 viewer가 data.{field}를 표시함")
        # node collection은 dict(NODE_MAP)/list(NODE_LIST) 모두 canonical — shape-safe 추출 (이슈 #19)
        info = classify_node_collection(replay.get("final_state"))
        if info["nodes"] and re.search(r"\bnode\.status\b", viewer_src):
            statuses = sorted({n.get("status") for n in info["nodes"]
                               if n.get("status") is not None})
            # status 값이 하나도 없으면 vacuous — 빈 evidence를 성공 근거로 세지 않는다 (이슈 #19 INV-7)
            if statuses:
                ev.append(f"replay 노드 status({','.join(s for s in statuses if s)})를 viewer가 node.status로 표시함")
    return ev


def viewer_field_mismatches(replay: dict | None, viewer_src: str) -> list[str]:
    """viewer가 참조하지만 replay 스키마에 없는 필드(렌더링 결함)를 찾는다 (제품성 감점 근거).

    malformed node collection/entry는 빈 evidence로 조용히 처리하지 않고 명시적 결함으로
    반환한다 — fail-closed (이슈 #19 §8.2)."""
    out: list[str] = []
    if replay is None:
        return out
    if not isinstance(replay, dict):
        out.append(f"replay 문서가 object가 아님({type(replay).__name__}) → evidence 판정 불가 (fail-closed)")
        return out
    fs = replay.get("final_state")
    if fs is not None and not isinstance(fs, dict):
        out.append(f"replay final_state가 object가 아님({type(fs).__name__}) → evidence 판정 불가 (fail-closed)")
        return out
    fs = fs or {}
    info = classify_node_collection(fs)
    if info["shape"] == NODE_COLLECTION_MALFORMED:
        out.append(
            f"replay final_state.nodes가 node collection(dict/list)이 아님"
            f"({type(fs.get('nodes')).__name__}) → node evidence 판정 불가 (fail-closed)")
    elif info["malformed_entries"]:
        out.append(
            f"replay nodes에 canonical node object가 아닌 entry {info['malformed_entries']}개 "
            f"(valid {len(info['nodes'])}개) → malformed evidence")
    edges = fs.get("edges") or []
    events = replay.get("events") or []
    sample_node = info["nodes"][0] if info["nodes"] else {}
    sample_edge = edges[0] if isinstance(edges, list) and edges and isinstance(edges[0], dict) else {}
    sample_event = events[0] if isinstance(events, list) and events and isinstance(events[0], dict) else {}
    # edge from/to
    if re.search(r"edge\.from|edge\.to", viewer_src) and sample_edge and \
            ("from" not in sample_edge or "to" not in sample_edge):
        out.append(f"viewer는 edge.from/edge.to를 읽지만 replay edge 키는 {sorted(sample_edge)} → 엣지 미렌더링")
    # event type/message — viewer가 실제로 읽는 키만 replay에 요구한다 (이슈 #7 §11.1:
    # .type만 읽는 viewer에 message까지 요구하면 message 없는 도메인 전부 오탐)
    if sample_event:
        wanted = []
        if re.search(r"ev\.type|\.type\b", viewer_src) and "type" not in sample_event:
            wanted.append("type")
        if re.search(r"ev\.message", viewer_src) and "message" not in sample_event:
            wanted.append("message")
        if wanted:
            out.append(f"viewer는 event.{'/'.join(wanted)}를 읽지만 replay event 키는 "
                       f"{sorted(sample_event)} → 이벤트 로그 undefined")
    # node position x/y
    if re.search(r"node\.x|node\.y", viewer_src) and sample_node and \
            ("x" not in sample_node or "y" not in sample_node):
        out.append("viewer는 node.x/node.y로 좌표 배치하지만 replay 노드에 x/y 없음 → 노드 겹침 배치")
    # node status — viewer가 node.status를 읽는데 어떤 canonical node에도 status가 없으면
    # 상태 렌더링이 전부 fallback으로 빠진다 (x/y와 같은 원칙, 이슈 #19)
    if re.search(r"\bnode\.status\b", viewer_src) and info["nodes"] and \
            all(n.get("status") is None for n in info["nodes"]):
        out.append(f"viewer는 node.status를 읽지만 replay 노드 키는 {sorted(sample_node)} → 노드 상태 미렌더링")
    return out


# ---------------------------------------------------------------- Run 식별

def challenge_id_from_run(run_dir: Path) -> int | None:
    for name in ("phase2b1b_dashboard_summary.json", "green_base_promotion_after_anti_hardcode_patch.json",
                 "dashboard_summary.json"):
        d = load_json(run_dir / name) or {}
        if d.get("challenge_id") is not None:
            return d["challenge_id"]
    return None
