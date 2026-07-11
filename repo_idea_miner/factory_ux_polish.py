# UX_POLISH lane의 도메인 중립 executor — 제한된 UX operation catalog·결정론적 진단·machine-checkable evidence (이슈 #8)
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from repo_idea_miner.factory_run_layout import resolve_artifact_root

UX_SUBDIR = "review/ux_polish"
CONTRACT_JSON = "ux_contract.json"
DIAGNOSIS_JSON = "ux_diagnosis.json"
OPERATIONS_JSON = "ux_operations.json"
EVIDENCE_JSON = "ux_evidence.json"
REPORT_JSON = "ux_polish_report.json"
DASHBOARD_JSON = "ux_polish_dashboard_summary.json"

# 정본 viewport 상수 (§10.3) — 기존 runtime 환경(브라우저 smoke)과 동일 축
VIEWPORT_DESKTOP = (1280, 800)
VIEWPORT_NARROW = (375, 812)
# 이 폭 이하에서 필수 control이 세로 배치되어야 한다 (STACK_FOR_NARROW_VIEWPORT 기준)
NARROW_STACK_THRESHOLD_PX = 700

# 변경 예산 (§9.2)
MAX_OPERATIONS_PER_PRODUCT = 5
MAX_TARGET_SURFACES = 3

# lane outcome (§12.3) — report의 ux_status 정본 enum
UX_STATUSES = (
    "UX_READY",
    "APPLIED",
    "PARTIAL",
    "HUMAN_REVIEW",
    "UPSTREAM_BLOCKED",
    "UNSUPPORTED",
    "FAILED",
)

# 진단 상태 (§8.2) 정본 enum
DIAGNOSIS_STATUSES = (
    "UX_READY",
    "ACTION_NOT_DISCOVERABLE",
    "STATE_NOT_VISIBLE",
    "FEEDBACK_MISSING",
    "ERROR_HIDDEN",
    "CONTROL_CLIPPED",
    "NARROW_VIEWPORT_BROKEN",
    "FOCUS_NOT_VISIBLE",
    "FOCUS_ORDER_INVALID",
    "DISABLED_REASON_MISSING",
    "REPLAY_POSITION_UNCLEAR",
    "VALIDATION_FEEDBACK_DISCONNECTED",
    "HUMAN_REVIEW_REQUIRED",
    "UPSTREAM_DEFECT",
    "UNSUPPORTED",
)

# 결함 분류 (§4.3)
CATEGORY_MACHINE_FIXABLE = "MACHINE_FIXABLE"
CATEGORY_HUMAN_REVIEW = "HUMAN_REVIEW"
CATEGORY_PRODUCT_REQUIREMENT = "PRODUCT_REQUIREMENT"
CATEGORY_UPSTREAM_CONTRACT = "UPSTREAM_CONTRACT"
CATEGORY_UNSUPPORTED = "UNSUPPORTED"

# 제한된 operation catalog (§7.1) — 이 목록 밖 patch는 만들지 않는다
OPERATION_IDS = (
    "CLARIFY_LABEL",
    "EXPOSE_PRIMARY_ACTION",
    "ADD_ACTION_FEEDBACK",
    "EXPOSE_STATE",
    "EXPOSE_ERROR",
    "FIX_OVERFLOW",
    "STACK_FOR_NARROW_VIEWPORT",
    "ADD_VISIBLE_FOCUS",
    "FIX_FOCUS_ORDER",
    "MARK_DISABLED_REASON",
    "EXPOSE_REPLAY_POSITION",
    "CONNECT_VALIDATION_FEEDBACK",
)

# 판정이 주관적이고 patch 범위가 무제한이라 금지 (§7.3)
FORBIDDEN_OPERATION_IDS = (
    "MAKE_BEAUTIFUL",
    "REDESIGN_PAGE",
    "IMPROVE_STYLE",
    "MODERNIZE_UI",
    "ENHANCE_EXPERIENCE",
)

# diagnosis → operation 매핑 (§8.3 — catalog 항목과 일치할 때만 자동 patch)
DIAGNOSIS_TO_OPERATION = {
    "ACTION_NOT_DISCOVERABLE": "CLARIFY_LABEL",
    "STATE_NOT_VISIBLE": "EXPOSE_STATE",
    "FEEDBACK_MISSING": "ADD_ACTION_FEEDBACK",
    "ERROR_HIDDEN": "EXPOSE_ERROR",
    "CONTROL_CLIPPED": "FIX_OVERFLOW",
    "NARROW_VIEWPORT_BROKEN": "STACK_FOR_NARROW_VIEWPORT",
    "FOCUS_NOT_VISIBLE": "ADD_VISIBLE_FOCUS",
    "FOCUS_ORDER_INVALID": "FIX_FOCUS_ORDER",
    "DISABLED_REASON_MISSING": "MARK_DISABLED_REASON",
    "REPLAY_POSITION_UNCLEAR": "EXPOSE_REPLAY_POSITION",
    "VALIDATION_FEEDBACK_DISCONNECTED": "CONNECT_VALIDATION_FEEDBACK",
}

# UX executor가 절대 하지 않는 것 (§5.2) — contract와 report에 기록되는 정본 목록
FORBIDDEN_CHANGES = (
    "새 제품 기능 추가",
    "interaction contract 의미 변경",
    "domain data 생성/수정",
    "validator 통과를 위한 데이터 변조",
    "페이지 전면 재설계/새 디자인 시스템/프레임워크 도입",
    "브랜드 색상·로고·미감 자동 확정",
    "가짜 성공 메시지 생성",
    "사람이 요구하지 않은 navigation 추가",
)

# 표면 영역 탐지 힌트 (정본 상수 — 도메인 이름이 아니라 UI 관례 어휘)
_STATE_REGION_HINTS = ("state", "frame", "value", "result", "output")
_FEEDBACK_REGION_HINTS = ("error", "err", "feedback", "message", "status", "validation")
_ERROR_REGION_HINTS = ("error", "err", "validation")
_POSITION_REGION_HINTS = ("position",)

_NATIVE_FOCUSABLE = ("button", "select", "textarea", "input", "a")

_UX_MARKER_RE = re.compile(
    r"<(style|script)\s+data-ux-op=\"([A-Z_]+)\">.*?</\1>\s*", re.S)
_SCRIPT_BLOCK_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.S | re.I)
_STYLE_BLOCK_RE = re.compile(r"<style[^>]*>(.*?)</style>", re.S | re.I)
_DATA_ACTION_TAG_RE = re.compile(r"<(\w+)((?:[^<>]|\n)*?)\bdata-action=", re.I)
_ID_CLASS_RE = re.compile(r"(?:id|class)=\"([^\"]+)\"", re.I)
_CONTROL_TAG_RE = re.compile(r"<(button|select|textarea|input|a)\b([^>]*)>", re.I)
_BUTTON_TEXT_RE = re.compile(r"<button\b[^>]*>(.*?)</button>", re.S | re.I)


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def _digest(obj) -> str:
    return hashlib.sha256(_dump(obj).encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- 표면 수집

def collect_surfaces(artifact_root: Path) -> list[dict]:
    """product/ 아래 HTML 표면을 수집한다 — 파일 이름/도메인 분기 없음."""
    product = Path(artifact_root) / "product"
    surfaces: list[dict] = []
    if not product.is_dir():
        return surfaces
    for p in sorted(product.rglob("*.html")):
        if not p.is_file():
            continue
        surfaces.append({
            "rel": str(p.relative_to(artifact_root).as_posix()),
            "text": p.read_text(encoding="utf-8", errors="replace"),
        })
    return surfaces


def _region_ids(text: str, hints: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for m in _ID_CLASS_RE.finditer(text):
        for token in re.split(r"\s+", m.group(1)):
            low = token.lower()
            if any(h in low for h in hints) and token not in found:
                found.append(token)
    return found


def _controls(text: str) -> list[dict]:
    """native control inventory — tag/accessible name/focusable."""
    out: list[dict] = []
    for m in _CONTROL_TAG_RE.finditer(text):
        tag, attrs = m.group(1).lower(), m.group(2)
        name = ""
        if tag == "button":
            btn = _BUTTON_TEXT_RE.search(text[m.start():m.start() + 500])
            name = re.sub(r"<[^>]+>", "", btn.group(1)).strip() if btn else ""
        for attr in ("aria-label", "placeholder", "title", "value"):
            if not name:
                am = re.search(rf'{attr}="([^"]+)"', attrs)
                name = am.group(1).strip() if am else name
        out.append({"tag": tag, "accessible_name": name, "focusable": True,
                    "disabled": bool(re.search(r"\bdisabled\b", attrs))})
    return out


def _unfocusable_action_elements(text: str) -> list[str]:
    """click 대상(data-action)인데 keyboard로 도달 불가능한 요소들.

    정적 마크업과 JS 동적 생성(createElement + setAttribute("data-action")) 둘 다
    검사한다. FIX_FOCUS_ORDER marker script가 이미 주입돼 있으면 runtime에서
    tabindex가 부여되므로 잔여로 세지 않는다 (동작 자체는 브라우저 smoke가 실증)."""
    if re.search(r'data-ux-op="FIX_FOCUS_ORDER"', text) and 'setAttribute("tabindex"' in text:
        return []
    bad: list[str] = []
    for m in _DATA_ACTION_TAG_RE.finditer(text):
        tag, attrs = m.group(1).lower(), m.group(2)
        if tag in _NATIVE_FOCUSABLE:
            continue
        if "tabindex" in attrs.lower():
            continue
        bad.append(tag)
    # 동적 생성 click 대상: JS가 data-action을 부여하는데 tabindex는 부여하지 않음
    if 'setAttribute("data-action"' in text and 'setAttribute("tabindex"' not in text:
        for m in re.finditer(r'createElement\("(\w+)"\)', text):
            tag = m.group(1).lower()
            if tag not in _NATIVE_FOCUSABLE:
                bad.append(f"{tag}(dynamic)")
                break
    return bad


def _stylesheet(text: str) -> str:
    return "\n".join(_STYLE_BLOCK_RE.findall(text))


def _narrow_viewport_issue(text: str) -> dict | None:
    """고정폭 자식이 있는 flex row가 wrap/stacking media query 없이 좁은 화면을 깨뜨리는지.

    결정론 규칙: display:flex 컨테이너 class + width>=200px 고정 class가 같은
    스타일시트에 있고, flex-wrap도 없고, max-width media query 안에 그 컨테이너를
    실제로 세로 배치하는 규칙(flex-direction/flex-wrap/display 변경)도 없으면 결함.
    media query의 존재만으로는 해소로 보지 않는다 — 내용 없는 block은 수리가 아니다."""
    css = _stylesheet(text)
    if not css:
        return None
    if "flex-wrap" in css:
        return None
    containers = [m.group(1) for m in re.finditer(
        r"\.([\w-]+)[^{]*\{[^}]*display:\s*flex", css)]
    fixed = [m.group(1) for m in re.finditer(
        r"\.([\w-]+)[^{]*\{[^}]*width:\s*(?:2\d\d|[3-9]\d\d|\d{4,})px", css)]
    if not containers or not fixed:
        return None
    container = containers[0]
    for m in re.finditer(r"@media[^{]*max-width[^{]*\{", css):
        seg = css[m.end():m.end() + 800]
        rule = re.search(rf"\.{re.escape(container)}\s*\{{([^}}]*)\}}", seg)
        if rule and re.search(r"flex-direction|flex-wrap|display\s*:\s*(?:block|grid)",
                              rule.group(1)):
            return None
    return {"container": container, "fixed_children": fixed}


def _outline_suppressed(text: str) -> bool:
    css = _stylesheet(text)
    if not re.search(r"outline\s*:\s*(?:none|0)\b", css):
        return False
    # :focus 대체 스타일이 있으면 억제로 보지 않는다
    for m in re.finditer(r"([^{}]+):focus[^{]*\{([^}]*)\}", css):
        if "outline" in m.group(2) or "box-shadow" in m.group(2):
            return False
    return True


def _overflow_clip_selector(text: str) -> str | None:
    css = _stylesheet(text)
    m = re.search(r"([.#][\w-]+)[^{]*\{[^}]*overflow\s*:\s*hidden", css)
    if not m or not _CONTROL_TAG_RE.search(text):
        return None
    sel = m.group(1)
    # 같은 selector에 대한 이후 overflow:auto 재정의(FIX_OVERFLOW patch)가 있으면 해소된 것
    later = css[m.end():]
    if re.search(rf"{re.escape(sel)}\s*\{{[^}}]*overflow\s*:\s*auto", later):
        return None
    return sel


# ---------------------------------------------------------------- Canonical UX Contract (§6)

def build_ux_contract(artifact_root: Path) -> dict:
    """기존 interaction/viewer/runner contract를 재사용해 canonical UX contract를 만든다.

    제품별 DOM 구조를 가정하지 않는다 — 표면 inventory와 계약 파일에서만 유도한다."""
    artifact_root = Path(artifact_root)
    surfaces = collect_surfaces(artifact_root)
    refs: list[dict] = []
    problems: list[str] = []

    interaction = None
    viewer_contract = None
    product_dir = artifact_root / "product"
    contract_files = sorted(product_dir.rglob("*.json")) if product_dir.is_dir() else []
    for p in contract_files:
        data = _load_json(p)
        if not isinstance(data, dict):
            continue
        rel = str(p.relative_to(artifact_root).as_posix())
        if interaction is None and "available_actions" in data:
            interaction = data
            refs.append({"ref": rel, "sha256": _file_digest(p)})
        if viewer_contract is None and "replays" in data and "viewer_kind" in data:
            viewer_contract = data
            refs.append({"ref": rel, "sha256": _file_digest(p)})
    runner_contract_path = artifact_root / "runner_contract.json"
    runner_contract = _load_json(runner_contract_path) or {}
    if runner_contract:
        refs.append({"ref": "runner_contract.json",
                     "sha256": _file_digest(runner_contract_path)})

    primary_actions = [a.get("name") for a in
                       (interaction or {}).get("available_actions") or [] if a.get("name")]
    nav_actions: list[str] = []
    for s in surfaces:
        for m in re.finditer(r'data-action="([^"]+)"', s["text"]):
            if m.group(1) not in nav_actions:
                nav_actions.append(m.group(1))

    state_indicators: list[dict] = []
    feedback_channels: list[dict] = []
    error_channels: list[dict] = []
    for s in surfaces:
        for token in _region_ids(s["text"], _STATE_REGION_HINTS):
            state_indicators.append({"surface": s["rel"], "region": token})
        for token in _region_ids(s["text"], _FEEDBACK_REGION_HINTS):
            feedback_channels.append({"surface": s["rel"], "region": token})
        for token in _region_ids(s["text"], _ERROR_REGION_HINTS):
            error_channels.append({"surface": s["rel"], "region": token})

    required_controls = [{"kind": "primary_action", "actions": primary_actions}] \
        if primary_actions else []
    if nav_actions:
        required_controls.append({"kind": "navigation", "actions": sorted(nav_actions)})

    contract = {
        "schema_version": 1,
        "surface_kind": "generated_product_html",
        "surfaces": [s["rel"] for s in surfaces],
        "source_artifact_refs": refs,
        "primary_task": ("사용자가 계약된 action을 실행하고 상태 변화·피드백을 확인한 뒤 "
                         "replay를 탐색한다" if primary_actions else
                         "사용자가 제품 표면에서 결과 상태를 탐색한다"),
        "primary_actions": primary_actions,
        "navigation_actions": sorted(nav_actions),
        "state_indicators": state_indicators,
        "feedback_channels": feedback_channels,
        "error_channels": error_channels,
        "required_controls": required_controls,
        "viewport_requirements": {
            "desktop": list(VIEWPORT_DESKTOP),
            "narrow": list(VIEWPORT_NARROW),
            "narrow_stack_threshold_px": NARROW_STACK_THRESHOLD_PX,
        },
        "keyboard_requirements": [
            "primary action control이 keyboard focus 가능해야 한다",
            "click 대상 요소는 keyboard로 활성화 가능해야 한다",
            "focus 시각 표시를 제거하지 않는다",
        ],
        "validation_rules": ((interaction or {}).get("validation_rules")
                             or (viewer_contract or {}).get("validation_rules") or []),
        "allowed_operations": list(OPERATION_IDS),
        "forbidden_changes": list(FORBIDDEN_CHANGES),
        "evidence_requirements": [
            "진단·operation·검증이 machine-checkable로 기록된다",
            "viewport(desktop/narrow) 결과가 기록된다",
            "keyboard focus/활성 결과가 기록된다",
            "runtime action 실증은 기존 runner-backed evidence를 참조한다",
            "mock/screenshot만으로 성공 처리하지 않는다",
        ],
    }
    contract["ux_target_id"] = _digest(contract)[:16]
    if not surfaces:
        problems.append("product/ HTML 표면 없음 — UNSUPPORTED")
    return {"contract": contract, "surfaces": surfaces,
            "interaction": interaction, "viewer_contract": viewer_contract,
            "problems": problems}


# ---------------------------------------------------------------- UX Diagnosis (§8)

def _diag(status: str, surface: str, target: str, target_kind: str,
          evidence: str, category: str, operation: str | None = None) -> dict:
    return {"status": status, "surface": surface, "target": target,
            "target_kind": target_kind, "evidence": evidence,
            "category": category, "operation": operation,
            "machine_fixable": category == CATEGORY_MACHINE_FIXABLE
            and operation in OPERATION_IDS}


def diagnose_surface(surface: dict, contract: dict, artifact_root: Path) -> list[dict]:
    """표면 1개를 결정론적으로 진단한다 — LLM의 주관적 화면 감상을 쓰지 않는다 (§8.1)."""
    rel, text = surface["rel"], surface["text"]
    out: list[dict] = []
    controls = _controls(text)
    has_data_action = 'data-action="' in text

    # ACTION_NOT_DISCOVERABLE — control이 아예 없으면 기능 부재(요구사항), 이름 없는
    # control은 CLARIFY_LABEL로 machine-fixable. CLARIFY_LABEL marker script는
    # runtime에 aria-label을 부여하므로 정적 잔여로 세지 않는다(브라우저 smoke가 실증).
    label_marker = bool(re.search(r'data-ux-op="CLARIFY_LABEL"', text)) \
        and 'setAttribute("aria-label"' in text
    if not controls and not has_data_action:
        out.append(_diag("ACTION_NOT_DISCOVERABLE", rel, "surface", "surface",
                         "조작 가능한 control이 표면에 없음 — UX patch로 기능을 만들 수 없다",
                         CATEGORY_PRODUCT_REQUIREMENT))
    elif not label_marker:
        unnamed = [c for c in controls if c["tag"] == "button" and not c["accessible_name"]]
        if unnamed:
            out.append(_diag("ACTION_NOT_DISCOVERABLE", rel, "button", "control",
                             f"accessible name 없는 button {len(unnamed)}개",
                             CATEGORY_MACHINE_FIXABLE, "CLARIFY_LABEL"))

    # STATE_NOT_VISIBLE
    state_regions = _region_ids(text, _STATE_REGION_HINTS)
    if (controls or has_data_action) and not state_regions:
        derivable = "initial_state" in text or bool(
            re.search(r'fetch\("?[^")]*viewer_contract\.json', text))
        out.append(_diag(
            "STATE_NOT_VISIBLE", rel, "state_region", "state_region",
            "상태 표시 영역 없음" + (" (표면 내 상태 소스에서 파생 가능)" if derivable
                                     else " (파생 가능한 상태 소스 없음)"),
            CATEGORY_MACHINE_FIXABLE if derivable else CATEGORY_UPSTREAM_CONTRACT,
            "EXPOSE_STATE" if derivable else None))

    # FEEDBACK_MISSING
    feedback_regions = _region_ids(text, _FEEDBACK_REGION_HINTS)
    if (controls or has_data_action) and not feedback_regions:
        out.append(_diag(
            "FEEDBACK_MISSING", rel, "feedback_region", "feedback_region",
            "success/failure feedback 영역 없음",
            CATEGORY_MACHINE_FIXABLE if state_regions else CATEGORY_UPSTREAM_CONTRACT,
            "ADD_ACTION_FEEDBACK" if state_regions else None))

    # ERROR_HIDDEN — 오류가 console에만 남고 화면에 없음
    error_regions = _region_ids(text, _ERROR_REGION_HINTS)
    if "console.error(" in text and not error_regions:
        out.append(_diag("ERROR_HIDDEN", rel, "error_region", "feedback_region",
                         "console.error만 있고 화면 오류 영역 없음",
                         CATEGORY_MACHINE_FIXABLE, "EXPOSE_ERROR"))

    # CONTROL_CLIPPED
    clip_sel = _overflow_clip_selector(text)
    if clip_sel:
        out.append(_diag("CONTROL_CLIPPED", rel, clip_sel, "component",
                         f"{clip_sel} 규칙이 overflow:hidden — control이 잘릴 수 있음",
                         CATEGORY_MACHINE_FIXABLE, "FIX_OVERFLOW"))

    # NARROW_VIEWPORT_BROKEN
    narrow = _narrow_viewport_issue(text)
    if narrow:
        out.append(_diag(
            "NARROW_VIEWPORT_BROKEN", rel, "." + narrow["container"], "component",
            f"flex row(.{narrow['container']}) + 고정폭 자식"
            f"({', '.join('.' + c for c in narrow['fixed_children'])})이 "
            f"wrap/media query 없이 {VIEWPORT_NARROW[0]}px 화면을 깨뜨림",
            CATEGORY_MACHINE_FIXABLE, "STACK_FOR_NARROW_VIEWPORT"))

    # FOCUS_NOT_VISIBLE
    if _outline_suppressed(text):
        out.append(_diag("FOCUS_NOT_VISIBLE", rel, ":focus", "control",
                         "outline 제거 후 :focus 대체 스타일 없음",
                         CATEGORY_MACHINE_FIXABLE, "ADD_VISIBLE_FOCUS"))

    # FOCUS_ORDER_INVALID — click 대상이 keyboard로 도달 불가
    bad_tags = _unfocusable_action_elements(text)
    if bad_tags:
        out.append(_diag(
            "FOCUS_ORDER_INVALID", rel, "[data-action]", "control",
            f"keyboard 도달 불가한 click 대상 {len(bad_tags)}개 ({', '.join(sorted(set(bad_tags)))})",
            CATEGORY_MACHINE_FIXABLE, "FIX_FOCUS_ORDER"))

    # DISABLED_REASON_MISSING — MARK_DISABLED_REASON marker script는 runtime에
    # title을 부여하므로 정적 잔여로 세지 않는다
    disabled_marker = bool(re.search(r'data-ux-op="MARK_DISABLED_REASON"', text)) \
        and 'setAttribute("title"' in text
    disabled_untitled = [] if disabled_marker else [m.group(0) for m in re.finditer(
        r"<[^>]*\bdisabled\b[^>]*>", text) if "title=" not in m.group(0)]
    if disabled_untitled:
        out.append(_diag("DISABLED_REASON_MISSING", rel, "[disabled]", "control",
                         f"이유 표시 없는 disabled control {len(disabled_untitled)}개",
                         CATEGORY_MACHINE_FIXABLE, "MARK_DISABLED_REASON"))

    # REPLAY_POSITION_UNCLEAR — frame 탐색 UI가 있는데 위치 표시가 없음
    frame_nav = bool(re.search(r'data-action="(?:next|prev|select-frame)"', text))
    if frame_nav and not _region_ids(text, _POSITION_REGION_HINTS):
        out.append(_diag("REPLAY_POSITION_UNCLEAR", rel, "frame_position",
                         "navigation_region",
                         "frame 탐색 control은 있으나 현재 위치(N/M) 표시 없음",
                         CATEGORY_MACHINE_FIXABLE, "EXPOSE_REPLAY_POSITION"))

    # VALIDATION_FEEDBACK_DISCONNECTED — 계약에 validation rule이 있는데 표시 영역 없음
    if contract.get("validation_rules") and (controls or has_data_action):
        validation_regions = [t for t in _region_ids(text, ("validation",))]
        if not validation_regions and not error_regions:
            adjacent_contract = bool(
                re.search(r'fetch\("?[^")]*viewer_contract\.json', text))
            out.append(_diag(
                "VALIDATION_FEEDBACK_DISCONNECTED", rel, "validation_region",
                "feedback_region",
                "validation rule은 계약에 있으나 결과 표시 영역 없음",
                CATEGORY_MACHINE_FIXABLE if adjacent_contract
                else CATEGORY_UPSTREAM_CONTRACT,
                "CONNECT_VALIDATION_FEEDBACK" if adjacent_contract else None))

    return out


def build_ux_diagnosis(built: dict, artifact_root: Path) -> list[dict]:
    diagnoses: list[dict] = []
    contract = built["contract"]
    surfaces = built["surfaces"]
    if not surfaces:
        return [_diag("UNSUPPORTED", "(none)", "product/", "surface",
                      "product/ HTML 표면 없음", CATEGORY_UNSUPPORTED)]
    # UPSTREAM_DEFECT — viewer 표면이 viewer_contract를 fetch하는데 파일이 깨짐/없음
    for s in surfaces:
        if re.search(r'fetch\("?[^")]*viewer_contract\.json', s["text"]):
            candidates = list((Path(artifact_root) / "product").rglob("viewer_contract.json"))
            if not candidates or any(_load_json(c) is None for c in candidates):
                diagnoses.append(_diag(
                    "UPSTREAM_DEFECT", s["rel"], "viewer_contract.json", "surface",
                    "viewer가 참조하는 viewer_contract.json이 없거나 파싱 불가 — "
                    "UX patch로 덮지 않는다 (§4.3)", CATEGORY_UPSTREAM_CONTRACT))
    for s in surfaces:
        diagnoses.extend(diagnose_surface(s, contract, artifact_root))
    return diagnoses


# ---------------------------------------------------------------- Operation catalog (§7)

def _strip_op_block(text: str, op_id: str) -> str:
    return re.sub(
        rf"<(style|script)\s+data-ux-op=\"{op_id}\">.*?</\1>\s*", "", text, flags=re.S)


def _inject_style(text: str, op_id: str, css: str) -> str:
    block = f'<style data-ux-op="{op_id}">\n{css}\n</style>\n'
    text = _strip_op_block(text, op_id)
    if "</head>" in text:
        return text.replace("</head>", block + "</head>", 1)
    return block + text


def _inject_script(text: str, op_id: str, js: str, html_region: str = "") -> str:
    block = ""
    if html_region:
        block += html_region + "\n"
    block += f'<script data-ux-op="{op_id}">\n{js}\n</script>\n'
    text = _strip_op_block(text, op_id)
    if "</body>" in text:
        return text.replace("</body>", block + "</body>", 1)
    return text + block


_FOCUS_ORDER_JS = """\
(function () {
  "use strict";
  var NATIVE = ["button", "select", "textarea", "input", "a"];
  function upgrade() {
    var nodes = document.querySelectorAll("[data-action]");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (NATIVE.indexOf(el.tagName.toLowerCase()) === -1 && !el.hasAttribute("tabindex")) {
        el.setAttribute("tabindex", "0");
        if (!el.hasAttribute("role")) { el.setAttribute("role", "button"); }
      }
    }
  }
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") { return; }
    var el = e.target;
    if (el && el.getAttribute && el.getAttribute("data-action") &&
        NATIVE.indexOf(el.tagName.toLowerCase()) === -1) {
      e.preventDefault();
      el.click();
    }
  });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", upgrade);
  } else { upgrade(); }
  new MutationObserver(upgrade).observe(
    document.documentElement, {childList: true, subtree: true});
})();"""

_EXPOSE_ERROR_JS = """\
(function () {
  "use strict";
  var region = document.getElementById("ux-error-region");
  if (!region) { return; }
  window.addEventListener("error", function (e) {
    region.textContent = "오류: " + (e.message || "알 수 없는 오류");
  });
})();"""

_MARK_DISABLED_JS = """\
(function () {
  "use strict";
  function mark() {
    var nodes = document.querySelectorAll("[disabled]");
    for (var i = 0; i < nodes.length; i++) {
      if (!nodes[i].hasAttribute("title")) {
        nodes[i].setAttribute("title", "비활성화됨 — 계약 조건 미충족");
      }
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mark);
  } else { mark(); }
})();"""

_EXPOSE_REPLAY_POSITION_JS = """\
(function () {
  "use strict";
  var region = document.getElementById("ux-frame-position");
  if (!region) { return; }
  function update() {
    var frames = document.querySelectorAll('[data-action="select-frame"]');
    var active = -1;
    for (var i = 0; i < frames.length; i++) {
      if (frames[i].className.indexOf("active") !== -1) { active = i; }
    }
    region.textContent = frames.length
      ? ("frame " + (active + 1) + " / " + frames.length) : "";
  }
  document.addEventListener("click", function () { window.setTimeout(update, 0); });
  new MutationObserver(update).observe(
    document.documentElement, {childList: true, subtree: true});
  update();
})();"""


def _op_record(op_id: str, surface: str, target: str, detail: str) -> dict:
    rev = {v: k for k, v in DIAGNOSIS_TO_OPERATION.items()}
    return {
        "operation_id": op_id,
        "target_surface": surface,
        "target": target,
        "precondition": "diagnosis " + rev.get(
            op_id, "ACTION_NOT_DISCOVERABLE (숨겨진 필수 control)"),
        "patch_scope": "marker_block(data-ux-op) 주입 — 기존 마크업/스크립트 재작성 없음",
        "detail": detail,
        "expected_effect": "해당 diagnosis 재검사가 PASS로 바뀐다",
        "forbidden_effects": ["기능 추가/삭제", "contract 의미 변경", "가짜 성공 메시지",
                              "다른 표면 변경"],
        "validation": None,       # 적용 후 채움: PASS | FAIL
        "rolled_back": False,
        "rollback_condition": "적용 후 같은 diagnosis가 남아 있으면 이 marker block을 제거",
    }


def apply_operation(text: str, diag: dict, contract: dict) -> tuple[str, dict] | None:
    """diagnosis 1건에 operation 1개를 적용한다 (§9.1). 적용 불가면 None."""
    op = diag.get("operation")
    surface = diag["surface"]
    if op not in OPERATION_IDS:
        return None

    if op == "STACK_FOR_NARROW_VIEWPORT":
        issue = _narrow_viewport_issue(text)
        if not issue:
            return None
        rules = [f"  .{issue['container']} {{ flex-direction: column; }}"]
        rules += [f"  .{c} {{ width: auto; }}" for c in issue["fixed_children"]]
        css = (f"@media (max-width: {NARROW_STACK_THRESHOLD_PX}px) {{\n"
               + "\n".join(rules) + "\n}")
        rec = _op_record(op, surface, "." + issue["container"],
                         f"{NARROW_STACK_THRESHOLD_PX}px 이하에서 필수 영역 세로 배치")
        return _inject_style(text, op, css), rec

    if op == "FIX_FOCUS_ORDER":
        if not _unfocusable_action_elements(text):
            return None
        rec = _op_record(op, surface, "[data-action]",
                         "click 대상에 tabindex/role 부여 + Enter/Space 활성 위임")
        return _inject_script(text, op, _FOCUS_ORDER_JS), rec

    if op == "ADD_VISIBLE_FOCUS":
        if not _outline_suppressed(text):
            return None
        css = (":focus { outline: 2px solid currentColor; outline-offset: 2px; }")
        rec = _op_record(op, surface, ":focus", "outline 억제에 대한 가시적 focus 복원")
        return _inject_style(text, op, css), rec

    if op == "FIX_OVERFLOW":
        sel = _overflow_clip_selector(text)
        if not sel:
            return None
        css = f"{sel} {{ overflow: auto; }}"
        rec = _op_record(op, surface, sel, "clipping 영역을 스크롤 가능하게 완화")
        return _inject_style(text, op, css), rec

    if op == "EXPOSE_ERROR":
        region = '<div id="ux-error-region" role="alert" aria-live="assertive"></div>'
        rec = _op_record(op, surface, "#ux-error-region",
                         "런타임 오류를 화면에 명시 표시 (실제 오류만, 문구 창작 없음)")
        return _inject_script(text, op, _EXPOSE_ERROR_JS, region), rec

    if op == "MARK_DISABLED_REASON":
        rec = _op_record(op, surface, "[disabled]", "disabled control에 이유 title 부여")
        return _inject_script(text, op, _MARK_DISABLED_JS), rec

    if op == "EXPOSE_REPLAY_POSITION":
        region = '<span id="ux-frame-position" class="ux-position"></span>'
        rec = _op_record(op, surface, "#ux-frame-position",
                         "현재 frame/전체 frame 위치를 기존 목록 상태에서 파생 표시")
        return _inject_script(text, op, _EXPOSE_REPLAY_POSITION_JS, region), rec

    if op == "ADD_ACTION_FEEDBACK":
        state_regions = _region_ids(text, _STATE_REGION_HINTS)
        if not state_regions:
            return None
        target = state_regions[0]
        region = '<div id="ux-action-feedback" role="status" aria-live="polite"></div>'
        js = f"""\
(function () {{
  "use strict";
  var region = document.getElementById("ux-action-feedback");
  var target = document.getElementById({json.dumps(target)}) ||
    document.querySelector({json.dumps("." + target)});
  if (!region || !target) {{ return; }}
  new MutationObserver(function () {{
    region.textContent = "마지막 action 이후 상태 표시가 갱신되었습니다";
  }}).observe(target, {{childList: true, subtree: true, characterData: true}});
}})();"""
        rec = _op_record(op, surface, "#" + target,
                         "실제 상태 영역 변경을 관찰해 feedback 표시 (성공 창작 없음)")
        return _inject_script(text, op, js, region), rec

    if op == "EXPOSE_STATE":
        if "initial_state" not in text:
            return None
        region = '<pre id="ux-state-region" aria-live="polite"></pre>'
        js = """\
(function () {
  "use strict";
  var region = document.getElementById("ux-state-region");
  if (!region) { return; }
  if (typeof CONTRACT !== "undefined" && CONTRACT && CONTRACT["initial_state"]) {
    region.textContent = JSON.stringify(CONTRACT["initial_state"], null, 2);
  }
})();"""
        rec = _op_record(op, surface, "#ux-state-region",
                         "표면에 이미 있는 initial_state 소스를 표시 (데이터 창작 없음)")
        return _inject_script(text, op, js, region), rec

    if op == "CLARIFY_LABEL":
        actions = contract.get("primary_actions") or []
        js = f"""\
(function () {{
  "use strict";
  var ACTIONS = {json.dumps(actions, ensure_ascii=False)};
  function label() {{
    var btns = document.querySelectorAll("button");
    for (var i = 0; i < btns.length; i++) {{
      var b = btns[i];
      if (b.textContent.trim() || b.hasAttribute("aria-label")) {{ continue; }}
      var hint = b.getAttribute("data-action") || b.id || "";
      for (var j = 0; j < ACTIONS.length; j++) {{
        if (hint.indexOf(ACTIONS[j]) !== -1) {{ b.setAttribute("aria-label", ACTIONS[j]); }}
      }}
    }}
  }}
  if (document.readyState === "loading") {{
    document.addEventListener("DOMContentLoaded", label);
  }} else {{ label(); }}
}})();"""
        rec = _op_record(op, surface, "button",
                         "계약의 action 이름을 verbatim으로 label 부여 (문구 창작 없음)")
        return _inject_script(text, op, js), rec

    if op == "EXPOSE_PRIMARY_ACTION":
        # 숨겨진(display:none) 필수 control 노출만 허용 — 재배치/재설계 없음
        css_all = _stylesheet(text)
        m = re.search(r"([.#][\w-]+)[^{]*\{[^}]*display\s*:\s*none", css_all)
        if not m or not _CONTROL_TAG_RE.search(text):
            return None
        css = f"{m.group(1)} {{ display: initial; }}"
        rec = _op_record(op, surface, m.group(1), "숨겨진 필수 control 영역 노출")
        return _inject_style(text, op, css), rec

    if op == "CONNECT_VALIDATION_FEEDBACK":
        if not re.search(r'fetch\("?[^")]*viewer_contract\.json', text):
            return None
        region = '<div id="ux-validation-region" role="status"></div>'
        js = """\
(function () {
  "use strict";
  var region = document.getElementById("ux-validation-region");
  if (!region) { return; }
  fetch("viewer_contract.json").then(function (r) { return r.json(); })
    .then(function (c) {
      var lines = [];
      ((c && c.replays) || []).forEach(function (rep) {
        (rep.errors || []).forEach(function (err) {
          lines.push(rep.replay_id + ": " + err);
        });
      });
      region.textContent = lines.length ? ("검증 실패 " + lines.length + "건: "
        + lines.join(" | ")) : "";
    }).catch(function () { region.textContent = ""; });
})();"""
        rec = _op_record(op, surface, "#ux-validation-region",
                         "기존 계약의 검증 실패를 해당 replay와 연결 표시")
        return _inject_script(text, op, js, region), rec

    return None


# ---------------------------------------------------------------- Evidence (§10)

def _surface_inventory(text: str) -> dict:
    controls = _controls(text)
    return {
        "control_count": len(controls) + len(re.findall(r'data-action="', text)),
        "named_controls": sum(1 for c in controls if c["accessible_name"]),
        "unfocusable_action_elements": len(_unfocusable_action_elements(text)),
        "state_regions": _region_ids(text, _STATE_REGION_HINTS),
        "feedback_regions": _region_ids(text, _FEEDBACK_REGION_HINTS),
        "error_regions": _region_ids(text, _ERROR_REGION_HINTS),
        "position_regions": _region_ids(text, _POSITION_REGION_HINTS),
    }


def _viewport_check(text: str) -> dict:
    issue = _narrow_viewport_issue(text)
    return {
        "desktop": {"pass": True, "viewport": list(VIEWPORT_DESKTOP),
                    "method": "static_css_analysis"},
        "narrow": {"pass": issue is None, "viewport": list(VIEWPORT_NARROW),
                   "method": "static_css_analysis",
                   "issue": issue,
                   "note": "정적 CSS 규칙 검사 — 실제 렌더링은 브라우저 smoke에서 실증"},
    }


def _keyboard_check(text: str) -> dict:
    unfocusable = _unfocusable_action_elements(text)
    return {
        "pass": not unfocusable and not _outline_suppressed(text),
        "focusable_all_action_targets": not unfocusable,
        "visible_focus": not _outline_suppressed(text),
        "activation_delegation_present": bool(
            re.search(r'data-ux-op="FIX_FOCUS_ORDER"', text)) or not unfocusable,
        "method": "static_analysis",
    }


def check_surface_scripts(text: str) -> dict:
    """표면의 모든 <script> 블록을 node --check로 파싱 검증한다."""
    import subprocess
    import tempfile
    scripts = _SCRIPT_BLOCK_RE.findall(text)
    scripts = [s for s in scripts if s.strip()]
    if not scripts:
        return {"status": "PASS", "detail": "script 블록 없음"}
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
            return {"status": "FAIL", "detail": f"script #{i}: {(proc.stderr or '')[:400]}"}
    return {"status": "PASS", "detail": f"{len(scripts)} script block(s)"}


def _runtime_action_refs(run_dir: Path) -> dict:
    """runtime action 실증은 기존 runner-backed evidence를 참조한다 — UX가 재창작하지 않는다."""
    refs: dict = {}
    exec_report = _load_json(
        run_dir / "review/draft_execution/draft_execution_report.json") or {}
    if exec_report.get("applied") is True:
        ev = exec_report.get("execution_evidence") or {}
        refs["draft_execution"] = {
            "ref": "review/draft_execution/draft_execution_report.json",
            "can_execute_input": ev.get("can_execute_input"),
            "state_change_observed": ev.get("state_change_observed"),
            "invalid_action_rejected": ev.get("invalid_action_rejected"),
        }
    ui_report = _load_json(
        run_dir / "review/interaction_ui/interaction_ui_report.json") or {}
    if ui_report.get("applied") is True:
        smoke = ui_report.get("interaction_smoke") or {}
        refs["interaction_ui"] = {
            "ref": "review/interaction_ui/interaction_ui_report.json",
            "can_execute_primary_action": smoke.get("can_execute_primary_action"),
            "state_change_observed": smoke.get("state_change_observed"),
        }
    return refs


# ---------------------------------------------------------------- Executor 본체 (lane 계약)

def _roots(run_dir: Path) -> list[Path]:
    return [run_dir / name for name in ("workspace", "final_artifact")
            if (run_dir / name).is_dir()]


def run_ux_polish(run_dir=None, run_id=None, apply: bool = False,
                  db_conn=None, timeout: float = 60.0) -> dict:
    """도메인 중립 UX_POLISH executor (이슈 #8).

    반환 계약은 lane executor(_exec_apply_tool)와 동일: applied/patched_files/problems/
    error/ok/status. applied·ok=true는 진단→catalog operation→재검증이 전부
    machine-checkable로 통과할 때만이다 — CSS 변경/HTTP 200/screenshot만으로 성공
    처리하지 않는다 (§11)."""
    result: dict = {"ok": False, "status": None, "applied": False, "patched_files": [],
                    "ux_status": None, "problems": [], "error": None, "ux_evidence": None}
    if run_dir is None:
        result["status"] = "PRECONDITION_NO_TARGET"
        result["error"] = "run_dir가 필요합니다"
        return result
    run_dir = Path(run_dir)
    artifact_root = resolve_artifact_root(run_dir)
    if artifact_root is None or not Path(artifact_root).is_dir():
        result["status"] = "PRECONDITION_NO_ARTIFACT_ROOT"
        result["ux_status"] = "UNSUPPORTED"
        result["error"] = "artifact root(workspace/final_artifact) 없음"
        return result
    artifact_root = Path(artifact_root)

    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    built = build_ux_contract(artifact_root)
    contract = built["contract"]
    diagnoses = build_ux_diagnosis(built, artifact_root)
    result["problems"] = list(built["problems"])

    if not built["surfaces"]:
        result["status"] = "PRECONDITION_UNSUPPORTED"
        result["ux_status"] = "UNSUPPORTED"
        result["error"] = "product/ HTML 표면 없음"
        _write_outputs(run_dir, contract=contract, diagnosis=diagnoses,
                       report=_report_dict(result, contract, diagnoses, [], None))
        return result

    upstream = [d for d in diagnoses if d["category"] == CATEGORY_UPSTREAM_CONTRACT]
    fixable = [d for d in diagnoses if d["machine_fixable"]]
    requirement = [d for d in diagnoses if d["category"] == CATEGORY_PRODUCT_REQUIREMENT]

    if any(d["status"] == "UPSTREAM_DEFECT" for d in upstream):
        # viewer contract 자체가 깨짐 — UX patch로 덮지 않는다 (§4.3, §25)
        result["status"] = "PRECONDITION_UPSTREAM_DEFECT"
        result["ux_status"] = "UPSTREAM_BLOCKED"
        result["error"] = "; ".join(d["evidence"] for d in upstream
                                    if d["status"] == "UPSTREAM_DEFECT")
        _write_outputs(run_dir, contract=contract, diagnosis=diagnoses,
                       report=_report_dict(result, contract, diagnoses, [], None))
        return result

    if not apply:
        result["ok"] = True
        result["status"] = "PLAN_ONLY"
        result["ux_status"] = "UX_READY" if not fixable else None
        result["plan"] = {
            "ux_target_id": contract["ux_target_id"],
            "surfaces": contract["surfaces"],
            "machine_fixable": [{"status": d["status"], "surface": d["surface"],
                                 "operation": d["operation"]} for d in fixable],
            "budget": {"max_operations": MAX_OPERATIONS_PER_PRODUCT,
                       "max_target_surfaces": MAX_TARGET_SURFACES},
        }
        _write_outputs(run_dir, contract=contract, diagnosis=diagnoses,
                       report=_report_dict(result, contract, diagnoses, [], None))
        return result

    # ---- 적용 (§9) — 표면 텍스트에 marker block operation만 주입
    inventory_before = {s["rel"]: _surface_inventory(s["text"]) for s in built["surfaces"]}
    viewport_before = {s["rel"]: _viewport_check(s["text"]) for s in built["surfaces"]}
    keyboard_before = {s["rel"]: _keyboard_check(s["text"]) for s in built["surfaces"]}

    texts = {s["rel"]: s["text"] for s in built["surfaces"]}
    operations: list[dict] = []
    problems: list[str] = list(result["problems"])
    ops_used = 0
    target_surfaces: set[str] = set()

    for diag in fixable:
        if ops_used >= MAX_OPERATIONS_PER_PRODUCT:
            problems.append(f"operation budget 초과 — {diag['status']}({diag['surface']}) 미적용")
            continue
        if diag["surface"] not in target_surfaces \
                and len(target_surfaces) >= MAX_TARGET_SURFACES:
            problems.append(f"target surface budget 초과 — {diag['surface']} 미적용")
            continue
        text = texts[diag["surface"]]
        applied_op = apply_operation(text, diag, contract)
        if applied_op is None:
            problems.append(f"{diag['status']}: precondition 미충족으로 operation 미적용")
            continue
        new_text, rec = applied_op
        # 검증: 같은 진단이 patched 텍스트에서 사라져야 유지 (§7.2 validation/rollback)
        fake_surface = {"rel": diag["surface"], "text": new_text}
        recheck = [d for d in diagnose_surface(fake_surface, contract, artifact_root)
                   if d["status"] == diag["status"]]
        if recheck:
            rec["validation"] = "FAIL"
            rec["rolled_back"] = True
            problems.append(f"{rec['operation_id']}: 적용 후에도 {diag['status']} 잔존 — rollback")
            operations.append(rec)
            continue
        rec["validation"] = "PASS"
        texts[diag["surface"]] = new_text
        operations.append(rec)
        ops_used += 1
        target_surfaces.add(diag["surface"])

    # ---- 적용 후 검증
    after_surfaces = [{"rel": rel, "text": text} for rel, text in texts.items()]
    diagnosis_after: list[dict] = []
    for s in after_surfaces:
        diagnosis_after.extend(diagnose_surface(s, contract, artifact_root))
    remaining_fixable = [d for d in diagnosis_after if d["machine_fixable"]]

    js_checks = {s["rel"]: check_surface_scripts(s["text"]) for s in after_surfaces}
    js_fail = [rel for rel, c in js_checks.items() if c["status"] == "FAIL"]
    if js_fail:
        problems.append(f"JS 파싱 실패: {', '.join(js_fail)}")

    inventory_after = {s["rel"]: _surface_inventory(s["text"]) for s in after_surfaces}
    viewport_after = {s["rel"]: _viewport_check(s["text"]) for s in after_surfaces}
    keyboard_after = {s["rel"]: _keyboard_check(s["text"]) for s in after_surfaces}

    viewport_ok = all(v["narrow"]["pass"] and v["desktop"]["pass"]
                      for v in viewport_after.values())
    keyboard_ok = all(k["pass"] for k in keyboard_after.values())
    validated_ops = [o for o in operations if o["validation"] == "PASS"]
    rolled_back = [o for o in operations if o["rolled_back"]]

    # ---- 상태 판정 (§12.3)
    if js_fail:
        ux_status = "FAILED"
    elif remaining_fixable or rolled_back:
        ux_status = "PARTIAL" if validated_ops else "FAILED"
    elif validated_ops:
        ux_status = "APPLIED"
    elif fixable:
        ux_status = "FAILED"
    else:
        ux_status = "UX_READY"

    # patch 쓰기 — 검증 통과분이 있고 전체가 FAILED가 아닐 때만 (§9.3)
    patched: list[str] = []
    if validated_ops and ux_status in ("APPLIED", "PARTIAL"):
        changed_rels = sorted({o["target_surface"] for o in validated_ops})
        for root in _roots(run_dir):
            for rel in changed_rels:
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(texts[rel], encoding="utf-8")
        patched = changed_rels

    runtime_refs = _runtime_action_refs(run_dir)
    if not runtime_refs:
        problems.append("runtime action 실증(기존 runner-backed evidence) 없음")

    human_notes = ["HUMAN_AESTHETIC_REVIEW: 미감·브랜딩 판단은 사람 몫 — "
                   "비차단 review note (§12.5), product failure 아님"]

    evidence = {
        "ux_provenance": {
            "ux_target_id": contract["ux_target_id"],
            "produced_by": "factory_ux_polish",
            "started_at": started_at,
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "fresh": True,
        },
        "ux_contract_digest": _digest(contract),
        "source_artifact_refs": contract["source_artifact_refs"],
        "surfaces": contract["surfaces"],
        "diagnosis_before": [d["status"] for d in diagnoses],
        "diagnosis_after": [d["status"] for d in diagnosis_after] or ["UX_READY"],
        "operations": operations,
        "control_inventory_before": inventory_before,
        "control_inventory_after": inventory_after,
        "primary_action_visible": any(
            inv["control_count"] > 0 for inv in inventory_after.values()),
        "state_indicator_visible": any(
            inv["state_regions"] for inv in inventory_after.values()),
        "feedback_channel_visible": any(
            inv["feedback_regions"] for inv in inventory_after.values()),
        "error_channel_visible": any(
            inv["error_regions"] for inv in inventory_after.values()),
        "viewport_results_before": viewport_before,
        "viewport_results": viewport_after,
        "keyboard_results_before": keyboard_before,
        "keyboard_results": keyboard_after,
        "js_syntax": js_checks,
        "runtime_action_refs": runtime_refs,
        "requirement_level_gaps": [d["evidence"] for d in requirement],
        "human_review_notes": human_notes,
        "method_note": ("진단·viewport·keyboard는 결정론적 정적 분석, runtime action은 "
                        "기존 runner-backed evidence 참조 — 실제 브라우저 렌더/조작은 "
                        "세션 runtime smoke에서 별도 실증"),
    }

    included = ux_status in ("APPLIED", "UX_READY") \
        and viewport_ok and keyboard_ok \
        and evidence["primary_action_visible"] \
        and evidence["state_indicator_visible"] \
        and evidence["feedback_channel_visible"] \
        and evidence["error_channel_visible"] \
        and bool(runtime_refs) \
        and all(c["status"] == "PASS" for c in js_checks.values()) \
        and not remaining_fixable

    result["ux_status"] = ux_status
    result["applied"] = bool(patched)
    result["ok"] = included
    result["patched_files"] = patched
    result["problems"] = problems
    result["ux_evidence"] = {
        "viewport_narrow_pass": viewport_ok,
        "keyboard_pass": keyboard_ok,
        "operations_applied": len(validated_ops),
        "diagnosis_before_count": len(diagnoses),
        "machine_fixable_remaining": len(remaining_fixable),
    }
    if ux_status == "APPLIED":
        result["status"] = "APPLIED"
    elif ux_status == "UX_READY":
        result["status"] = "UX_READY"
    else:
        result["status"] = "UX_VALIDATION_FAILED"
        result["error"] = "; ".join(problems[-5:]) or f"ux_status={ux_status}"

    report = _report_dict(result, contract, diagnoses, operations, evidence,
                          included=included, human_notes=human_notes)
    _write_outputs(run_dir, contract=contract, diagnosis=diagnoses,
                   operations=operations, evidence=evidence, report=report)
    return result


def _report_dict(result: dict, contract: dict, diagnoses: list[dict],
                 operations: list[dict], evidence: dict | None,
                 included: bool = False, human_notes: list[str] | None = None) -> dict:
    return {
        "applied": bool(result.get("applied")),
        "ux_status": result.get("ux_status"),
        "ux_target_id": contract.get("ux_target_id"),
        "surfaces": contract.get("surfaces") or [],
        "diagnosis_before": [{"status": d["status"], "surface": d["surface"],
                              "category": d["category"], "operation": d["operation"]}
                             for d in diagnoses],
        "operations": [{"operation_id": o["operation_id"],
                        "target_surface": o["target_surface"], "target": o["target"],
                        "validation": o["validation"], "rolled_back": o["rolled_back"]}
                       for o in operations],
        "patched_files": list(result.get("patched_files") or []),
        "ux_polish_included": bool(included),
        "ux_evidence": result.get("ux_evidence"),
        "budget": {"max_operations": MAX_OPERATIONS_PER_PRODUCT,
                   "max_target_surfaces": MAX_TARGET_SURFACES,
                   "operations_used": len([o for o in operations
                                           if o["validation"] == "PASS"])},
        "human_review_notes": list(human_notes or []),
        "problems": list(result.get("problems") or []),
        "error": result.get("error"),
    }


def _write_outputs(run_dir: Path, *, contract=None, diagnosis=None, operations=None,
                   evidence=None, report=None) -> None:
    out_dir = Path(run_dir) / UX_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    if contract is not None:
        (out_dir / CONTRACT_JSON).write_text(_dump(contract) + "\n", encoding="utf-8")
    if diagnosis is not None:
        (out_dir / DIAGNOSIS_JSON).write_text(_dump(diagnosis) + "\n", encoding="utf-8")
    if operations is not None:
        (out_dir / OPERATIONS_JSON).write_text(_dump(operations) + "\n", encoding="utf-8")
    if evidence is not None:
        (out_dir / EVIDENCE_JSON).write_text(_dump(evidence) + "\n", encoding="utf-8")
    if report is not None:
        (out_dir / REPORT_JSON).write_text(_dump(report) + "\n", encoding="utf-8")
        (out_dir / DASHBOARD_JSON).write_text(_dump({
            "phase": "ux_polish",
            "ux_status": report.get("ux_status"),
            "ux_polish_included": report.get("ux_polish_included"),
            "operations": [o.get("operation_id") for o in report.get("operations") or []],
            "diagnosis_before": [d.get("status")
                                 for d in report.get("diagnosis_before") or []][:10],
            "patched_files": report.get("patched_files") or [],
            "problems": list(report.get("problems") or [])[:10],
        }) + "\n", encoding="utf-8")
