# 도메인 중립 VIEWER_POLISH lane executor — replay artifact를 정본 ref로 발견하고 domain adapter로 canonical viewer contract를 만들어 generic viewer core가 실제 replay navigation을 제공하게 한다 (이슈 #7).
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

from repo_idea_miner.factory_run_layout import resolve_artifact_root

# ---------------------------------------------------------------- 산출물 위치 (evidence ownership §8)

VIEWER_SUBDIR = "review/viewer_polish"
CONTRACT_JSON = "viewer_contract.json"
DISCOVERY_JSON = "viewer_discovery.json"
EVIDENCE_JSON = "viewer_evidence.json"
REPORT_JSON = "viewer_polish_report.json"
DASHBOARD_JSON = "viewer_polish_dashboard_summary.json"

VIEWER_HTML_REL = "product/viewer/index.html"
VIEWER_CONTRACT_REL = "product/viewer/viewer_contract.json"

# discovery 상태 (§5.4) — 어느 것도 빈/mock viewer로 대체하지 않는다
DISCOVERY_STATUSES = ("FOUND", "MISSING", "AMBIGUOUS", "INVALID", "UNSUPPORTED")

# viewer 상태 (§7.3) — REPLAY_COMPLETE는 끝까지 탐색 가능하다는 뜻일 뿐 제품 성공이 아니다
VIEWER_STATUSES = (
    "REPLAY_READY",
    "REPLAY_COMPLETE",
    "REPLAY_MISSING",
    "REPLAY_INVALID",
    "REPLAY_AMBIGUOUS",
    "REPLAY_UNSUPPORTED",
    "REPLAY_VALIDATION_FAILED",
)

# domain adapter identity (§6) — 선택은 replay event 스키마 shape로만 한다.
# SRS/table/filesystem 등 표준 harness replay(events[].type)는 한 adapter가 담당하고,
# 과거 graph replay(events[].event)만 legacy adapter로 읽는다. 도메인 이름 분기 없음.
ADAPTER_STANDARD = "standard_typed_event"
ADAPTER_GRAPH_LEGACY = "graph_legacy_event"

_DISCOVERY_TO_VIEWER_STATUS = {
    "MISSING": "REPLAY_MISSING",
    "AMBIGUOUS": "REPLAY_AMBIGUOUS",
    "INVALID": "REPLAY_INVALID",
    "UNSUPPORTED": "REPLAY_UNSUPPORTED",
}


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def _digest(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- Replay Artifact Discovery (§5)

def discover_replay_sources(artifact_root: Path) -> dict:
    """replay artifact를 정본 ref 우선순위로 발견한다 (§5.2).

    1) replay/index.json의 replays[].file — producer가 선언한 명시적 ref
    2) index가 없을 때만 제한된 compatibility discovery(후보 정확히 1개, provenance 기록)
    directory glob을 정본으로 삼지 않고, filename 추측만으로 연결하지 않는다.
    """
    replay_dir = Path(artifact_root) / "replay"
    out: dict = {"status": "MISSING", "provenance": None, "sources": [],
                 "candidates": [], "problems": []}

    idx_path = replay_dir / "index.json"
    if idx_path.is_file():
        idx = _load_json(idx_path)
        if not isinstance(idx, dict) or not isinstance(idx.get("replays"), list):
            out["status"] = "INVALID"
            out["problems"].append("replay/index.json이 manifest schema가 아님")
            return out
        out["provenance"] = "explicit_index_ref"
        for entry in idx["replays"]:
            if not isinstance(entry, dict) or not entry.get("file"):
                out["problems"].append(f"index 항목에 file ref 없음: {entry}")
                continue
            rel = f"replay/{entry['file']}"
            out["sources"].append({
                "replay_id": str(entry.get("id") or entry["file"]),
                "ref": rel,
                "declared_ok": entry.get("ok"),
            })
        if not out["sources"]:
            out["status"] = "INVALID"
            out["problems"].append("replay/index.json에 유효한 file ref가 없음")
            return out
        out["status"] = "FOUND"
        return out

    # compatibility discovery (§5.3): index 없음 — deterministic, 후보 1개일 때만 자동 선택
    candidates = sorted(p.name for p in replay_dir.glob("*.json")) \
        if replay_dir.is_dir() else []
    out["candidates"] = candidates
    if not candidates:
        out["problems"].append("replay/index.json도 replay/*.json 후보도 없음")
        return out
    if len(candidates) > 1:
        out["status"] = "AMBIGUOUS"
        out["problems"].append(
            f"index 없이 replay 후보가 {len(candidates)}개 — 자동 선택하지 않음: {candidates}")
        return out
    out["status"] = "FOUND"
    out["provenance"] = "compatibility_single_candidate"
    out["sources"] = [{"replay_id": candidates[0].rsplit(".", 1)[0],
                       "ref": f"replay/{candidates[0]}", "declared_ok": None}]
    return out


# ---------------------------------------------------------------- Domain Adapter (§4.3, §6)

def select_adapter(replay_datas: list[dict]) -> tuple[str | None, list[str]]:
    """replay event 스키마 shape로 adapter를 고른다 — 과제 ID/run/파일명/제품명 분기 없음."""
    kinds: set[str] = set()
    problems: list[str] = []
    for data in replay_datas:
        for ev in data.get("events") or []:
            if not isinstance(ev, dict):
                return None, [f"event가 object가 아님: {type(ev).__name__} → UNSUPPORTED"]
            if "type" in ev:
                kinds.add(ADAPTER_STANDARD)
            elif "event" in ev:
                kinds.add(ADAPTER_GRAPH_LEGACY)
            else:
                return None, [f"event kind 키(type/event) 없음: {sorted(ev)} → UNSUPPORTED"]
    if len(kinds) > 1:
        return None, ["replay events가 서로 다른 스키마를 혼합 → UNSUPPORTED"]
    if not kinds:
        # 이벤트가 전부 비어 있으면 표준 adapter로 두고 frame 0개를 정직하게 표시한다
        return ADAPTER_STANDARD, ["events가 있는 replay가 없음 — frame 0개로 표시"]
    return kinds.pop(), problems


def _event_kind_key(adapter: str) -> str:
    return "event" if adapter == ADAPTER_GRAPH_LEGACY else "type"


def frames_from_replay(adapter: str, replay_id: str, data: dict,
                       initial_state: dict | None) -> list[dict]:
    """원시 replay event를 canonical frame으로 변환한다 (§4.2).

    값을 지어내지 않는다: before/after state는 파생 가능한 frame(첫/마지막)에만 있고
    나머지는 null(optional)이다. summary는 event_kind+target의 기계적 조합이다."""
    kind_key = _event_kind_key(adapter)
    events = data.get("events") or []
    final_state = data.get("final_state")
    frames: list[dict] = []
    for i, ev in enumerate(events, start=1):
        kind = ev.get(kind_key)
        targets = [f"{k}={ev[k]}" for k in sorted(ev)
                   if k != kind_key and isinstance(ev.get(k), (str, int))]
        frames.append({
            "frame_id": f"{replay_id}_f{i:03d}",
            "sequence": i,
            "event_kind": str(kind) if kind is not None else None,
            "summary": (str(kind) if kind is not None else "(kind 없음)")
            + (" → " + ", ".join(targets) if targets else ""),
            "payload": ev,
            "affected_targets": targets,
            "before_state": initial_state if i == 1 else None,
            "after_state": final_state if i == len(events) else None,
            "validation_refs": ["errors"] if data.get("errors") else [],
            "timestamp_or_step": i,
        })
    return frames


def _match_fixture_initial_state(artifact_root: Path, replay_id: str) -> tuple[dict | None, str | None]:
    """fixture의 내부 id 필드로 initial_state를 짝짓는다 — 파일명 추측이 아니라 선언된 id 매칭.

    정확히 1개일 때만 사용한다. 없으면 (None, 사유)로 명시한다."""
    fdir = Path(artifact_root) / "fixtures"
    if not fdir.is_dir():
        return None, "fixtures 디렉토리 없음"
    matches = []
    for p in sorted(fdir.glob("*.json")):
        data = _load_json(p)
        if isinstance(data, dict) and data.get("id") == replay_id \
                and isinstance(data.get("initial_state"), dict):
            matches.append(data)
    if len(matches) == 1:
        return matches[0]["initial_state"], None
    if not matches:
        return None, f"id={replay_id}인 fixture 없음"
    return None, f"id={replay_id}인 fixture가 {len(matches)}개 — ambiguous라 사용하지 않음"


# ---------------------------------------------------------------- Canonical Viewer Contract (§4)

def build_viewer_contract(artifact_root: Path) -> dict:
    """discovery + adapter로 canonical viewer contract를 만든다 (§4.1).

    반환: {"viewer_status", "discovery", "contract"(READY일 때만), "problems"}
    실패는 명시적 상태로 남긴다 — 빈/mock contract로 대체하지 않는다."""
    artifact_root = Path(artifact_root)
    problems: list[str] = []

    discovery = discover_replay_sources(artifact_root)
    problems += discovery["problems"]
    if discovery["status"] != "FOUND":
        return {"viewer_status": _DISCOVERY_TO_VIEWER_STATUS[discovery["status"]],
                "discovery": discovery, "contract": None, "problems": problems}

    loaded: list[tuple[dict, dict]] = []  # (source, data)
    for src in discovery["sources"]:
        path = artifact_root / src["ref"]
        if not path.is_file():
            problems.append(f"index가 가리키는 replay 파일 없음: {src['ref']}")
            src["load_status"] = "MISSING_FILE"
            continue
        data = _load_json(path)
        if not isinstance(data, dict) or not isinstance(data.get("events"), list):
            problems.append(f"replay 파일이 schema-valid하지 않음(events 목록 없음): {src['ref']}")
            src["load_status"] = "INVALID"
            continue
        src["load_status"] = "LOADED"
        src["sha256"] = _file_digest(path)
        loaded.append((src, data))
    if not loaded:
        discovery["status"] = "INVALID"
        return {"viewer_status": "REPLAY_INVALID", "discovery": discovery,
                "contract": None, "problems": problems}

    adapter, adapter_problems = select_adapter([d for _s, d in loaded])
    problems += adapter_problems
    if adapter is None:
        discovery["status"] = "UNSUPPORTED"
        return {"viewer_status": "REPLAY_UNSUPPORTED", "discovery": discovery,
                "contract": None, "problems": problems}

    state_contract = _load_json(artifact_root / "state_contract.json") or {}
    entities = [e.get("name") for e in state_contract.get("state_entities") or []
                if e.get("name")]

    replays: list[dict] = []
    for src, data in loaded:
        initial_state, why = _match_fixture_initial_state(artifact_root, src["replay_id"])
        if why:
            problems.append(f"{src['replay_id']}: initial_state 미확보 — {why}")
        frames = frames_from_replay(adapter, src["replay_id"], data, initial_state)
        replay_status = "REPLAY_READY" if frames else "REPLAY_VALIDATION_FAILED"
        replays.append({
            "replay_id": src["replay_id"],
            "source_ref": src["ref"],
            "source_sha256": src["sha256"],
            "ok": data.get("ok"),
            "errors": [str(e) for e in (data.get("errors") or [])],
            "result_summary": data.get("summary") if isinstance(data.get("summary"), str) else None,
            "event_count": len(data.get("events") or []),
            "initial_state": initial_state,
            "final_state": data.get("final_state"),
            "frames": frames,
            "replay_status": replay_status,
        })

    source_refs = [{"ref": r["source_ref"], "sha256": r["source_sha256"]} for r in replays]
    contract = {
        "schema_version": 1,
        "viewer_id": "viewer_" + _digest({"sources": source_refs, "adapter": adapter})[:16],
        "viewer_kind": adapter,
        "title": "Replay Viewer — " + (", ".join(entities) if entities else "state replay"),
        "source_artifact_refs": source_refs,
        "state_entities": entities,
        "replays": replays,
        "current_frame": 0,
        "capabilities": {
            "navigation": True, "frame_select": True, "reset": True,
            "replay_select": len(replays) > 1,
            "action_filter": False, "target_filter": False,
        },
        "validation_rules": [
            "frames.sequence는 1부터 강한 증가",
            "frame.event_kind 비어 있지 않음",
            "source_artifact_refs sha256 필수",
            "navigable replay(frames>0) 최소 1개",
        ],
        "evidence_requirements": [
            "visited_frames", "state_transitions_observed", "discovery_status",
            "render_status", "validation_failures",
        ],
        "viewer_status": "REPLAY_READY",
    }
    return {"viewer_status": "REPLAY_READY", "discovery": discovery,
            "contract": contract, "problems": problems}


def validate_viewer_contract(contract: dict) -> dict:
    """canonical contract 자체의 schema/결정론 검증 (§8) — HTML 생성 성공과 무관하다."""
    problems: list[str] = []
    replays = contract.get("replays") or []
    if not replays:
        problems.append("contract에 replay가 없음")
    navigable = [r for r in replays if r.get("frames")]
    if not navigable:
        problems.append("navigable replay(frames>0)가 하나도 없음")
    for r in replays:
        seqs = [f.get("sequence") for f in r.get("frames") or []]
        if seqs != list(range(1, len(seqs) + 1)):
            problems.append(f"{r.get('replay_id')}: frame sequence가 1..N 강한 증가가 아님")
        for f in r.get("frames") or []:
            if not f.get("event_kind"):
                problems.append(f"{r.get('replay_id')}/{f.get('frame_id')}: event_kind 비어 있음")
        if not r.get("source_sha256"):
            problems.append(f"{r.get('replay_id')}: source sha256 없음")
    if not contract.get("viewer_kind"):
        problems.append("viewer_kind(adapter identity) 없음")
    return {"pass": not problems, "problems": problems}


# ---------------------------------------------------------------- Viewer Model (§7 navigation smoke)

class ViewerModel:
    """generic viewer core의 Python 미러 — contract만 읽고 raw replay를 해석하지 않는다."""

    def __init__(self, contract: dict):
        self.contract = contract
        self.replays = contract.get("replays") or []
        self.replay_index = 0
        self.frame_index = 0  # 0-based

    def current_replay(self) -> dict:
        return self.replays[self.replay_index] if self.replays else {}

    def frames(self) -> list[dict]:
        return self.current_replay().get("frames") or []

    def current_frame(self) -> dict | None:
        frames = self.frames()
        return frames[self.frame_index] if 0 <= self.frame_index < len(frames) else None

    def select_replay(self, replay_id: str) -> bool:
        for i, r in enumerate(self.replays):
            if r.get("replay_id") == replay_id:
                self.replay_index, self.frame_index = i, 0
                return True
        return False

    def next(self) -> bool:
        if self.frame_index + 1 < len(self.frames()):
            self.frame_index += 1
            return True
        return False

    def previous(self) -> bool:
        if self.frame_index > 0:
            self.frame_index -= 1
            return True
        return False

    def reset(self) -> None:
        self.frame_index = 0

    def select_frame(self, sequence: int) -> bool:
        for i, f in enumerate(self.frames()):
            if f.get("sequence") == sequence:
                self.frame_index = i
                return True
        return False

    def status(self) -> str:
        frames = self.frames()
        if not frames:
            return "REPLAY_VALIDATION_FAILED"
        if self.frame_index == len(frames) - 1:
            return "REPLAY_COMPLETE"
        return "REPLAY_READY"


def run_navigation_smoke(contract: dict) -> dict:
    """initial → next(변화) → previous → reset → frame select를 model 수준에서 실증한다 (§7.2).

    정적 JSON dump가 아니라 frame 이동으로 표시 내용이 실제로 바뀌는 것을 기록한다."""
    model = ViewerModel(contract)
    visited: list[str] = []
    checks: dict[str, bool] = {}
    problems: list[str] = []

    navigable = next((r for r in model.replays if r.get("frames")), None)
    if navigable is None:
        return {"pass": False, "checks": {}, "visited_frames": [],
                "problems": ["navigable replay 없음 — navigation 실증 불가"],
                "state_transitions_observed": []}
    model.select_replay(navigable["replay_id"])

    first = model.current_frame()
    checks["initial_frame_visible"] = first is not None
    if first:
        visited.append(first["frame_id"])

    moved = model.next()
    second = model.current_frame()
    multi_frame = len(model.frames()) >= 2
    checks["next_changes_frame"] = (not multi_frame) or (
        moved and second is not None and second["frame_id"] != first["frame_id"]
        and (second["event_kind"], second["affected_targets"], second["sequence"])
        != (first["event_kind"], first["affected_targets"], first["sequence"]))
    if multi_frame and not checks["next_changes_frame"]:
        problems.append("next 이동 후에도 frame 표시 내용이 바뀌지 않음")
    if second and moved:
        visited.append(second["frame_id"])

    back = model.previous()
    checks["previous_returns"] = (not multi_frame) or (
        back and model.current_frame()["frame_id"] == first["frame_id"])

    model.select_frame(len(model.frames()))
    checks["frame_select_reaches_last"] = model.status() == "REPLAY_COMPLETE"
    last = model.current_frame()
    if last and last["frame_id"] not in visited:
        visited.append(last["frame_id"])

    model.reset()
    checks["reset_returns_to_initial"] = model.current_frame()["frame_id"] == first["frame_id"]

    transitions = []
    for r in model.replays:
        if isinstance(r.get("initial_state"), dict) and r.get("final_state") is not None:
            transitions.append({
                "replay_id": r["replay_id"],
                "initial_state_digest": _digest(r["initial_state"]),
                "final_state_digest": _digest(r["final_state"]),
                "state_changed": r["initial_state"] != r["final_state"],
            })
    checks["state_transition_observed"] = any(t["state_changed"] for t in transitions)
    if not transitions:
        problems.append("initial/final state 쌍이 있는 replay가 없어 state 전이를 관측하지 못함")

    problems += [name for name, ok in checks.items() if not ok and name not in
                 ("state_transition_observed",)]
    if not checks["state_transition_observed"]:
        problems.append("state 변화가 관측되지 않음 (initial==final 또는 initial 미확보)")
    return {"pass": all(checks.values()), "checks": checks,
            "visited_frames": visited, "state_transitions_observed": transitions,
            "problems": problems}


# ---------------------------------------------------------------- Generic Viewer Core (§7 HTML)

# 주의: 이 HTML/JS는 canonical contract만 읽는다. raw replay 키 리터럴(edge.from / ev.type /
# .type / node.x / Math.random / Date.now)을 쓰지 않는다 — 기존 mismatch/mock 검출기와 정합.
_VIEWER_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>Replay Viewer</title>
<style>
body { font-family: system-ui, sans-serif; margin: 0; background: #f5f6f8; color: #1c1e21; }
header { background: #232a36; color: #fff; padding: 10px 16px; }
header h1 { font-size: 16px; margin: 0 0 4px; }
.status-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px;
  background: #3b4a63; }
.status-badge.err { background: #8a2f2f; }
.layout { display: flex; gap: 12px; padding: 12px; align-items: flex-start; }
.panel { background: #fff; border: 1px solid #d9dde3; border-radius: 6px; padding: 10px; }
.side { width: 260px; flex: none; }
.main { flex: 1; min-width: 0; }
.replay-item, .frame-item { padding: 5px 8px; border-radius: 4px; cursor: pointer; font-size: 13px; }
.replay-item.active, .frame-item.active { background: #dce8ff; }
.frame-item .kind { font-weight: 600; }
.controls button { margin-right: 6px; padding: 4px 12px; }
pre { background: #f0f2f5; padding: 8px; overflow: auto; font-size: 12px; max-height: 260px; }
.meta { color: #5a6270; font-size: 12px; }
.error-box { background: #fdecec; border: 1px solid #e5b6b6; color: #7a2020; padding: 8px;
  border-radius: 4px; font-size: 13px; margin-bottom: 8px; }
.section-title { font-size: 13px; font-weight: 700; margin: 10px 0 4px; }
.validation-fail { color: #a02c2c; }
.validation-ok { color: #1d6f42; }
</style>
</head>
<body>
<header>
  <h1 id="viewer-title">Replay Viewer</h1>
  <span class="status-badge" id="viewer-status">LOADING</span>
  <span class="meta" id="viewer-source-refs"></span>
</header>
<div class="layout">
  <div class="panel side">
    <div class="section-title">Replay 목록</div>
    <div id="replay-list"></div>
    <div class="section-title">Frame 목록</div>
    <div id="frame-list"></div>
  </div>
  <div class="panel main">
    <div id="error-area"></div>
    <div class="controls">
      <button data-action="prev">이전 frame</button>
      <button data-action="next">다음 frame</button>
      <button data-action="reset">처음으로</button>
      <span class="meta" id="frame-position"></span>
    </div>
    <div class="section-title">현재 frame</div>
    <div id="frame-detail" class="meta">frame이 없습니다.</div>
    <div class="section-title">이전 상태 (before)</div>
    <pre id="before-state">(이 frame에는 before 상태 없음)</pre>
    <div class="section-title">이후 상태 (after)</div>
    <pre id="after-state">(이 frame에는 after 상태 없음)</pre>
    <div class="section-title">검증 결과</div>
    <div id="validation-area" class="meta"></div>
  </div>
</div>
<script>
"use strict";
var VP = {
  contract: null,
  replayIndex: 0,
  frameIndex: 0,
  el: function (id) { return document.getElementById(id); },

  currentReplay: function () {
    var rs = (this.contract && this.contract.replays) || [];
    return rs[this.replayIndex] || null;
  },
  frames: function () {
    var r = this.currentReplay();
    return (r && r.frames) || [];
  },
  currentFrame: function () {
    return this.frames()[this.frameIndex] || null;
  },

  setStatus: function (status, isError) {
    var badge = this.el("viewer-status");
    badge.textContent = status;
    badge.className = "status-badge" + (isError ? " err" : "");
  },

  showError: function (status, lines) {
    this.setStatus(status, true);
    var box = document.createElement("div");
    box.className = "error-box";
    var head = document.createElement("b");
    head.textContent = status;
    box.appendChild(head);
    (lines || []).forEach(function (line) {
      var p = document.createElement("div");
      p.textContent = line;
      box.appendChild(p);
    });
    this.el("error-area").appendChild(box);
  },

  renderReplayList: function () {
    var self = this;
    var list = this.el("replay-list");
    list.textContent = "";
    ((this.contract && this.contract.replays) || []).forEach(function (r, i) {
      var div = document.createElement("div");
      div.className = "replay-item" + (i === self.replayIndex ? " active" : "");
      div.setAttribute("data-action", "select-replay");
      div.setAttribute("data-index", String(i));
      var ok = r.ok === true ? "OK" : (r.ok === false ? "ERRORS" : "?");
      div.textContent = r.replay_id + " [" + r.replay_status + " / " + ok + "] frames=" +
        ((r.frames || []).length);
      list.appendChild(div);
    });
  },

  renderFrameList: function () {
    var self = this;
    var list = this.el("frame-list");
    list.textContent = "";
    this.frames().forEach(function (f, i) {
      var div = document.createElement("div");
      div.className = "frame-item" + (i === self.frameIndex ? " active" : "");
      div.setAttribute("data-action", "select-frame");
      div.setAttribute("data-index", String(i));
      var kind = document.createElement("span");
      kind.className = "kind";
      kind.textContent = "#" + f.sequence + " " + f.event_kind;
      div.appendChild(kind);
      list.appendChild(div);
    });
  },

  renderFrame: function () {
    var f = this.currentFrame();
    var detail = this.el("frame-detail");
    var frames = this.frames();
    this.el("frame-position").textContent =
      frames.length ? ("frame " + (this.frameIndex + 1) + " / " + frames.length) : "frame 없음";
    if (!f) {
      detail.textContent = "이 replay에는 frame이 없습니다 (event 0건).";
      this.el("before-state").textContent = "(없음)";
      this.el("after-state").textContent = "(없음)";
      return;
    }
    detail.textContent = "";
    var lines = [
      "frame_id: " + f.frame_id,
      "sequence: " + f.sequence,
      "event_kind: " + f.event_kind,
      "summary: " + f.summary,
      "affected_targets: " + (f.affected_targets.length ? f.affected_targets.join(", ") : "(없음)"),
      "payload: " + JSON.stringify(f.payload),
    ];
    lines.forEach(function (line) {
      var p = document.createElement("div");
      p.textContent = line;
      detail.appendChild(p);
    });
    this.el("before-state").textContent = f.before_state !== null && f.before_state !== undefined
      ? JSON.stringify(f.before_state, null, 2) : "(이 frame에는 before 상태 없음)";
    this.el("after-state").textContent = f.after_state !== null && f.after_state !== undefined
      ? JSON.stringify(f.after_state, null, 2) : "(이 frame에는 after 상태 없음)";
  },

  renderValidation: function () {
    var area = this.el("validation-area");
    area.textContent = "";
    var r = this.currentReplay();
    if (!r) { return; }
    var line = document.createElement("div");
    if (r.errors && r.errors.length) {
      line.className = "validation-fail";
      line.textContent = "scenario 검증 실패 " + r.errors.length + "건: " + r.errors.join(" | ");
    } else if (r.ok === true) {
      line.className = "validation-ok";
      line.textContent = "scenario 검증: 오류 없음 (replay 탐색 가능 ≠ 제품 성공)";
    } else {
      line.textContent = "scenario 검증 결과가 기록되어 있지 않습니다.";
    }
    area.appendChild(line);
    if (r.result_summary) {
      var s = document.createElement("div");
      s.textContent = "결과 요약: " + r.result_summary;
      area.appendChild(s);
    }
  },

  renderStatus: function () {
    var r = this.currentReplay();
    if (!r) { this.setStatus("REPLAY_MISSING", true); return; }
    if (r.replay_status !== "REPLAY_READY") { this.setStatus(r.replay_status, true); return; }
    var frames = this.frames();
    if (frames.length && this.frameIndex === frames.length - 1) {
      this.setStatus("REPLAY_COMPLETE", false);
    } else {
      this.setStatus("REPLAY_READY", false);
    }
  },

  renderAll: function () {
    this.renderReplayList();
    this.renderFrameList();
    this.renderFrame();
    this.renderValidation();
    this.renderStatus();
  },

  onAction: function (action, index) {
    if (action === "next") {
      if (this.frameIndex + 1 < this.frames().length) { this.frameIndex += 1; }
    } else if (action === "prev") {
      if (this.frameIndex > 0) { this.frameIndex -= 1; }
    } else if (action === "reset") {
      this.frameIndex = 0;
    } else if (action === "select-frame") {
      this.frameIndex = index;
    } else if (action === "select-replay") {
      this.replayIndex = index;
      this.frameIndex = 0;
    }
    this.renderAll();
  },

  init: function (contract) {
    this.contract = contract;
    this.el("viewer-title").textContent = contract.title || "Replay Viewer";
    this.el("viewer-source-refs").textContent = "sources: " +
      (contract.source_artifact_refs || []).map(function (s) { return s.ref; }).join(", ");
    if (contract.viewer_status && contract.viewer_status !== "REPLAY_READY") {
      this.showError(contract.viewer_status, contract.problems || []);
    }
    this.renderAll();
  }
};

document.addEventListener("click", function (e) {
  var node = e.target;
  while (node && node !== document.body) {
    var action = node.getAttribute && node.getAttribute("data-action");
    if (action) {
      VP.onAction(action, parseInt(node.getAttribute("data-index") || "0", 10));
      return;
    }
    node = node.parentNode;
  }
});

fetch("viewer_contract.json")
  .then(function (resp) {
    if (!resp.ok) { throw new Error("HTTP " + resp.status); }
    return resp.json();
  })
  .then(function (contract) { VP.init(contract); })
  .catch(function (err) {
    VP.showError("REPLAY_MISSING",
      ["viewer_contract.json을 불러올 수 없습니다: " + String(err),
       "NOT_EXECUTED — mock 데이터로 대체하지 않습니다."]);
  });
</script>
</body>
</html>
"""

# 기존 mismatch/mock 검출기와의 정합을 빌드 시점에 강제한다 (§7 금지 리터럴)
_FORBIDDEN_JS_LITERALS = ("edge.from", "edge.to", "ev.type", "ev.message",
                          "node.x", "node.y", "Math.random", "Date.now")


def generate_viewer_html() -> str:
    for lit in _FORBIDDEN_JS_LITERALS:
        if lit in _VIEWER_HTML:
            raise ValueError(f"generic viewer가 금지 리터럴을 포함: {lit}")
    if re.search(r"\.type\b", _VIEWER_HTML):
        raise ValueError("generic viewer가 raw .type 접근을 포함")
    return _VIEWER_HTML


def check_js_syntax(html: str) -> dict:
    """viewer <script> 블록을 node --check로 실제 파싱 검증한다 (2C-1 회귀 교훈)."""
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    if not scripts:
        return {"status": "FAIL", "detail": "script 블록 없음"}
    for i, script in enumerate(scripts):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(script)
            tmp_name = fh.name
        try:
            proc = subprocess.run(["node", "--check", tmp_name],
                                  capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"status": "NODE_UNAVAILABLE", "detail": str(exc)}
        finally:
            Path(tmp_name).unlink(missing_ok=True)
        if proc.returncode != 0:
            return {"status": "FAIL",
                    "detail": f"script #{i}: {(proc.stderr or '')[:400]}"}
    return {"status": "PASS", "detail": f"{len(scripts)} script block(s)"}


# ---------------------------------------------------------------- executor 본체 (lane 계약)

def _roots(run_dir: Path) -> list[Path]:
    return [run_dir / name for name in ("workspace", "final_artifact")
            if (run_dir / name).is_dir()]


def run_viewer_polish(run_dir=None, run_id=None, apply: bool = False,
                      db_conn=None, timeout: float = 60.0) -> dict:
    """도메인 중립 VIEWER_POLISH executor — graph 포함 전 도메인이 사용한다 (이슈 #23).

    adapter는 replay event schema shape로만 선택된다(events[].type=standard,
    events[].event=graph legacy event, mixed/unknown=UNSUPPORTED). 반환 계약은
    lane executor(_exec_apply_tool)와 동일: applied/patched_files/problems/
    error/ok/status. applied·ok=true는 discovery FOUND + contract valid + navigation
    실증 + JS 파싱 PASS일 때만이다 — HTML 생성/HTTP 200만으로 성공 처리하지 않는다."""
    result: dict = {"ok": False, "status": None, "applied": False, "patched_files": [],
                    "viewer_kind": None, "discovery_status": None, "viewer_status": None,
                    "problems": [], "error": None, "viewer_evidence": None}
    if run_dir is None:
        result["status"] = "PRECONDITION_NO_TARGET"
        result["error"] = "run_dir가 필요합니다"
        return result
    run_dir = Path(run_dir)
    artifact_root = resolve_artifact_root(run_dir)
    if artifact_root is None or not Path(artifact_root).is_dir():
        result["status"] = "PRECONDITION_NO_ARTIFACT_ROOT"
        result["error"] = "artifact root(workspace/final_artifact) 없음 — explicit missing state"
        return result
    artifact_root = Path(artifact_root)

    # 이슈 #23: graph kind 거부(PRECONDITION_GRAPH_DOMAIN) 제거 — kind 분기 없이
    # 전 도메인이 같은 canonical contract/viewer core를 쓴다.
    built = build_viewer_contract(artifact_root)
    result["discovery_status"] = built["discovery"]["status"]
    result["viewer_status"] = built["viewer_status"]
    result["problems"] = list(built["problems"])
    if built["contract"] is None:
        result["status"] = f"PRECONDITION_{built['viewer_status']}"
        result["error"] = "; ".join(built["problems"]) or built["viewer_status"]
        _write_outputs(run_dir, discovery=built["discovery"],
                       report=_report_dict(result, None))
        return result
    contract = built["contract"]
    result["viewer_kind"] = contract["viewer_kind"]

    if not apply:
        result["ok"] = True
        result["status"] = "PLAN_ONLY"
        result["plan"] = {
            "viewer_id": contract["viewer_id"],
            "viewer_kind": contract["viewer_kind"],
            "replay_count": len(contract["replays"]),
            "would_write": [VIEWER_HTML_REL, VIEWER_CONTRACT_REL],
        }
        _write_outputs(run_dir, discovery=built["discovery"], contract=contract,
                       report=_report_dict(result, None))
        return result

    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    contract_validation = validate_viewer_contract(contract)
    navigation = run_navigation_smoke(contract)
    html = generate_viewer_html()
    js_check = check_js_syntax(html)

    included = bool(contract_validation["pass"]) and bool(navigation["pass"]) \
        and js_check["status"] == "PASS" and built["discovery"]["status"] == "FOUND"
    problems = result["problems"] + \
        [f"contract: {p}" for p in contract_validation["problems"]] + \
        [f"navigation: {p}" for p in navigation["problems"]] + \
        ([f"js_syntax: {js_check['detail']}"] if js_check["status"] != "PASS" else [])

    patched: list[str] = []
    if included:
        # 검증 통과 시에만 artifact에 쓴다 — 깨진 viewer를 child에 남기지 않는다
        for root in _roots(run_dir):
            for rel, text in ((VIEWER_HTML_REL, html),
                              (VIEWER_CONTRACT_REL, _dump(contract) + "\n")):
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
        patched = [VIEWER_HTML_REL, VIEWER_CONTRACT_REL]
        result["viewer_status"] = "REPLAY_READY"
    else:
        result["viewer_status"] = "REPLAY_VALIDATION_FAILED"

    result["patched_files"] = patched
    result["applied"] = included
    result["ok"] = included
    result["problems"] = problems
    result["status"] = "APPLIED" if included else "VIEWER_VALIDATION_FAILED"
    if not included:
        result["error"] = "; ".join(problems) or "viewer 검증 실패"

    frames_total = sum(len(r["frames"]) for r in contract["replays"])
    first_navigable = next((r for r in contract["replays"] if r["frames"]), None)
    evidence = {
        "viewer_provenance": {
            "viewer_id": contract["viewer_id"],
            "produced_by": "factory_viewer_polish",
            "started_at": started_at,
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "fresh": True,
        },
        "viewer_contract_digest": _digest(contract),
        "source_replay_refs": contract["source_artifact_refs"],
        "adapter_identity": contract["viewer_kind"],
        "frame_count": frames_total,
        "initial_frame": (first_navigable["frames"][0]["frame_id"]
                          if first_navigable else None),
        "visited_frames": navigation["visited_frames"],
        "state_transitions_observed": navigation["state_transitions_observed"],
        "navigation": {"pass": navigation["pass"], "checks": navigation["checks"]},
        "contract_validation": contract_validation,
        "validation_failures": [
            {"replay_id": r["replay_id"], "errors": r["errors"]}
            for r in contract["replays"] if r["errors"]],
        "discovery_status": built["discovery"]["status"],
        "render_status": {"js_syntax": js_check["status"], "detail": js_check["detail"]},
        "error_status": None if included else result["status"],
    }
    result["viewer_evidence"] = {
        "viewer_navigation_works": bool(navigation["pass"]),
        "state_transition_observed": bool(
            navigation["checks"].get("state_transition_observed")),
        "frame_count": frames_total,
        "discovery_status": built["discovery"]["status"],
    }
    report = _report_dict(result, evidence)
    _write_outputs(run_dir, discovery=built["discovery"], contract=contract,
                   evidence=evidence, report=report)
    return result


def _report_dict(result: dict, evidence: dict | None) -> dict:
    included = bool(result.get("applied")) and bool(
        ((evidence or {}).get("navigation") or {}).get("pass"))
    return {
        "applied": bool(result.get("applied")),
        "viewer_kind": result.get("viewer_kind"),
        "discovery_status": result.get("discovery_status"),
        "viewer_status": result.get("viewer_status"),
        "viewer_polish_included": included,
        "patched_files": list(result.get("patched_files") or []),
        "viewer_evidence": result.get("viewer_evidence"),
        "viewer_id": (evidence or {}).get("viewer_contract_digest", "")[:16] or None,
        "problems": list(result.get("problems") or []),
        "error": result.get("error"),
    }


def _write_outputs(run_dir: Path, *, discovery=None, contract=None,
                   evidence=None, report=None) -> None:
    out_dir = Path(run_dir) / VIEWER_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    if discovery is not None:
        (out_dir / DISCOVERY_JSON).write_text(_dump(discovery) + "\n", encoding="utf-8")
    if contract is not None:
        (out_dir / CONTRACT_JSON).write_text(_dump(contract) + "\n", encoding="utf-8")
    if evidence is not None:
        (out_dir / EVIDENCE_JSON).write_text(_dump(evidence) + "\n", encoding="utf-8")
    if report is not None:
        (out_dir / REPORT_JSON).write_text(_dump(report) + "\n", encoding="utf-8")
        (out_dir / DASHBOARD_JSON).write_text(_dump({
            "phase": "viewer_polish",
            "viewer_status": report.get("viewer_status"),
            "discovery_status": report.get("discovery_status"),
            "viewer_kind": report.get("viewer_kind"),
            "viewer_polish_included": report.get("viewer_polish_included"),
            "frame_count": ((report.get("viewer_evidence") or {}).get("frame_count")),
            "problems": list(report.get("problems") or [])[:10],
        }) + "\n", encoding="utf-8")
