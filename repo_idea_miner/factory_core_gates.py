# Phase 1.6 Core Verification 게이트: contract/runner/replay/golden/invariant/determinism/anti-hardcode 코드 검증 모듈 (§8).
from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

from repo_idea_miner.factory_core_schemas import RUNNER_REQUIRED_OUTPUT_FIELDS
from repo_idea_miner.factory_gates import GateResult, write_gate_report
from repo_idea_miner.factory_sandbox import docker_available, run_in_sandbox

# ---------------------------------------------------------------- runner 실행 유틸


def _resolve_docker(use_docker: bool | None) -> bool:
    return docker_available() if use_docker is None else use_docker


def runner_command_for(runner_contract: dict, scenario_rel: str) -> str:
    """runner_command에서 scenario 경로를 대상 fixture로 치환한 실행 명령을 만든다."""
    cmd = runner_contract.get("runner_command") or ""
    if "{scenario}" in cmd:
        return cmd.replace("{scenario}", scenario_rel)
    if re.search(r"fixtures/[\w./\\-]+", cmd):
        return re.sub(r"fixtures/[\w./\\-]+", scenario_rel, cmd, count=1)
    return f"{cmd} {scenario_rel}"


def _localize_python(cmd: str, use_docker: bool) -> str:
    """로컬 실행 시 'python'을 현재 인터프리터 경로로 바꿔 PATH 문제를 피한다.

    경로에 공백이 있으면 cmd /c 중첩 따옴표 문제가 생기므로 원래 명령을 그대로 둔다.
    """
    if use_docker or " " in sys.executable:
        return cmd
    stripped = cmd.strip()
    for prefix in ("python3 ", "python "):
        if stripped.startswith(prefix):
            return f"{sys.executable} " + stripped[len(prefix):]
    return cmd


def run_scenario_once(
    workspace: Path,
    runner_contract: dict,
    scenario_rel: str,
    timeout_seconds: float,
    use_docker: bool | None,
    secrets: list[str],
) -> dict:
    """scenario 하나를 runner로 실행하고 실행/파싱 결과를 dict로 반환한다."""
    use_docker = _resolve_docker(use_docker)
    cmd = _localize_python(runner_command_for(runner_contract, scenario_rel), use_docker)
    res = run_in_sandbox(
        workspace, cmd, phase="execute", project_type="python_cli",
        timeout_seconds=timeout_seconds, use_docker=use_docker, secrets=secrets,
    )
    out: dict = {
        "scenario": scenario_rel,
        "command": cmd,
        "exit_code": res.returncode,
        "ok": res.ok,
        "timed_out": res.timed_out,
        "stdout": res.stdout,
        "stderr": res.stderr,
        "error": res.error,
        "parsed": None,
        "missing_fields": [],
    }
    if res.stdout.strip():
        try:
            parsed = json.loads(res.stdout.strip().splitlines()[-1])
            if isinstance(parsed, dict):
                out["parsed"] = parsed
        except json.JSONDecodeError:
            pass
    if out["parsed"] is None:
        out["ok"] = False
        out["error"] = out["error"] or "runner 출력이 JSON이 아님"
    else:
        required = runner_contract.get("required_output_fields") or list(RUNNER_REQUIRED_OUTPUT_FIELDS)
        out["missing_fields"] = [f for f in required if f not in out["parsed"]]
        if out["missing_fields"]:
            out["ok"] = False
            out["error"] = out["error"] or f"필수 출력 필드 누락: {out['missing_fields']}"
    return out


def list_scenario_files(workspace: Path) -> list[str]:
    fixtures = workspace / "fixtures"
    if not fixtures.is_dir():
        return []
    return sorted(
        p.relative_to(workspace).as_posix()
        for p in fixtures.glob("scenario_*.json")
        if p.is_file()
    )


def _scenario_id(workspace: Path, scenario_rel: str) -> str:
    try:
        data = json.loads((workspace / scenario_rel).read_text(encoding="utf-8"))
        return data.get("id") or Path(scenario_rel).stem
    except (OSError, json.JSONDecodeError):
        return Path(scenario_rel).stem


def src_code_files(workspace: Path, roots: tuple[str, ...] = ("src",)) -> dict[str, str]:
    out: dict[str, str] = {}
    for root in roots:
        base = workspace / root
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.suffix.lower() in (".py", ".js", ".mjs", ".html", ".htm", ".css"):
                out[p.relative_to(workspace).as_posix()] = p.read_text(encoding="utf-8", errors="replace")
    return out


# ---------------------------------------------------------------- 정적 코드 분석 (Phase 1.6b §4)

_C_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def strip_comments(text: str, suffix: str) -> str:
    """주석만 제거한다(문자열 리터럴은 보존). '주석에만 등장'과 'dispatch 문자열'을 구분하기 위함 (§4.4)."""
    suffix = suffix.lower()
    if suffix == ".py":
        return re.sub(r"(^|\s)#.*", r"\1", text, flags=re.MULTILINE)
    if suffix in (".js", ".mjs", ".css"):
        text = _C_BLOCK_COMMENT.sub(" ", text)
        return re.sub(r"(^|\s)//.*", r"\1", text, flags=re.MULTILINE)
    if suffix in (".html", ".htm"):
        return _HTML_COMMENT.sub(" ", text)
    return text


def _stripped_blob(code: dict[str, str]) -> str:
    return "\n".join(strip_comments(text, Path(rel).suffix) for rel, text in code.items())


def action_wiring(stripped_blob: str, full_blob: str, name: str) -> str:
    """action name이 코드에서 어떻게 나타나는지 분류한다.

    반환: 'callable'(정의) | 'dispatch'(문자열 키/비교) | 'weak'(장식용 문자열) | 'comment_only' | 'absent'.
    """
    if not name or name not in full_blob:
        return "absent"
    if name not in stripped_blob:
        return "comment_only"
    esc = re.escape(name)
    if (re.search(rf"\b(def|function|class)\s+{esc}\b", stripped_blob)
            or re.search(rf"\b{esc}\s*[:=]\s*(function|\(|lambda|async)", stripped_blob)
            or re.search(rf"\b{esc}\s*\([^\n)]*\)\s*(=>|\{{|:)", stripped_blob)):
        return "callable"
    if (re.search(rf"""(==|===|=>|case|:)\s*["']{esc}["']""", stripped_blob)
            or re.search(rf"""["']{esc}["']\s*(==|===|=>|:|\])""", stripped_blob)
            or re.search(rf"""\[\s*["']{esc}["']\s*\]""", stripped_blob)):
        return "dispatch"
    return "weak"


def _runner_wiring_problem(script: str | None, code: dict[str, str]) -> str | None:
    """runner가 별도 core 모듈을 import/require하는지 검사한다 (§4.2-2, §4.4). 단일파일 runner는 면제."""
    if not script:
        return None
    runner_text = code.get(script)
    if runner_text is None:
        return None
    other_stems: set[str] = set()
    for rel in code:
        if rel == script:
            continue
        stem = Path(rel).stem
        other_stems.add(Path(rel).parent.name if stem == "__init__" else stem)
    other_stems.discard("")
    if not other_stems:
        return None  # core 로직이 runner 한 파일에 들어있는 경우 import 요구 불가
    import_lines = re.findall(
        r"^\s*(?:from\s|import\s|const\s|let\s|var\s|require\b|importScripts).*$",
        runner_text, re.MULTILINE,
    )
    import_blob = "\n".join(import_lines)
    if any(re.search(rf"\b{re.escape(stem)}\b", import_blob) for stem in other_stems):
        return None
    if re.search(r"require\s*\(", runner_text) and any(stem in runner_text for stem in other_stems):
        return None
    return f"runner가 core 모듈을 import/require하지 않음 (dead core 의심): {script}"


# ---------------------------------------------------------------- Core Contract Gate (§8.5, §4 보강)

def run_core_contract_gate(workspace: Path, core_contract: dict, runner_contract: dict) -> GateResult:
    """계약이 실제 실행 코드와 연결되는지 정적으로 검사한다.

    단순 문자열 포함이 아니라 (1) action이 정의/dispatch로 연결, (2) runner가 core를 import,
    (3) state entity가 코드에 반영되는지를 본다 (§4.2). 런타임 반영은 augment_core_contract_runtime.
    """
    r = GateResult(name="Core Contract Gate", ok=True)
    for required in ("core_contract.json", "state_contract.json", "action_contract.json", "runner_contract.json"):
        if not (workspace / required).is_file():
            r.problems.append(f"contract 파일 없음: {required}")

    # runner 스크립트 존재
    cmd = runner_contract.get("runner_command") or ""
    script = next(
        (tok for tok in shlex.split(cmd, posix=True) if tok.endswith((".py", ".js", ".mjs"))), None
    )
    if script is None:
        r.problems.append(f"runner_command에서 실행 스크립트를 찾을 수 없음: {cmd or '(없음)'}")
    elif not (workspace / script).is_file():
        r.problems.append(f"runner 스크립트 없음: {script}")

    code = src_code_files(workspace)
    if not code:
        r.problems.append("src/ 코드 파일 없음")
    full_blob = "\n".join(code.values())
    stripped_blob = _stripped_blob(code)

    # §4.2-1: action이 실제 callable/dispatch로 존재 (주석·장식용 문자열만이면 실패)
    for action in core_contract.get("actions") or []:
        name = action.get("name") or ""
        if not name:
            continue
        kind = action_wiring(stripped_blob, full_blob, name)
        if kind == "absent":
            r.problems.append(f"contract action이 코드에 없음: {name}")
        elif kind == "comment_only":
            r.problems.append(f"contract action이 주석에만 있음(정의/dispatch 없음): {name}")
        elif kind == "weak":
            r.problems.append(f"contract action이 dispatch/정의로 연결되지 않음(장식용 문자열만): {name}")

    # §4.2-2: runner가 core 모듈을 import/require
    wiring = _runner_wiring_problem(script, code)
    if wiring:
        r.problems.append(wiring)

    # §4.2-4: state entity가 코드(주석 제외)에 반영
    for entity in core_contract.get("state_entities") or []:
        name = entity.get("name") or ""
        fields = entity.get("fields") or []
        if name and name not in stripped_blob and not any(f in stripped_blob for f in fields):
            r.problems.append(f"contract state entity가 코드에 없음: {name}")

    r.notes.append(f"src 코드 파일 {len(code)}개 검사 (정적 wiring)")
    r.ok = not r.problems
    return r


def _collect_keys(node, acc: set) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            acc.add(k)
            _collect_keys(v, acc)
    elif isinstance(node, list):
        for item in node:
            _collect_keys(item, acc)


def augment_core_contract_runtime(result: GateResult, core_contract: dict, replay_outputs: dict[str, dict]) -> None:
    """replay 출력의 final_state에 contract state entity가 실제 반영됐는지 검사한다 (§4.2-3,4).

    정적 wiring만으로는 dead code가 통과할 수 있어, runner 실행 결과로 반영 여부를 확인한다.
    """
    final_states = [
        (run.get("parsed") or {}).get("final_state")
        for run in replay_outputs.values()
    ]
    final_states = [fs for fs in final_states if isinstance(fs, dict)]
    if not final_states:
        return  # runner 실패 → 별도 gate가 처리
    present: set = set()
    for fs in final_states:
        _collect_keys(fs, present)
    for entity in core_contract.get("state_entities") or []:
        name = entity.get("name") or ""
        fields = entity.get("fields") or []
        if name and name not in present and not any(f in present for f in fields):
            result.problems.append(f"state entity가 runner 출력 final_state에 반영되지 않음: {name}")
    result.ok = not result.problems


# ---------------------------------------------------------------- Product Layer 소비 검사 (Phase 1.6b §5)

# product 파일은 CSS 뒤 <script>에 replay fetch가 오는 경우가 많아 넉넉히 읽어야 한다
# (짧게 자르면 fetch/필드 사용을 놓쳐 false-negative 발생, live #47에서 관측됨).
PRODUCT_READ_LIMIT = 20000


def product_layer_consumes_core(
    product_files: dict[str, str], core_contract: dict | None = None
) -> list[str]:
    """Product Layer가 core output(replay/runner 결과)을 실제로 소비하는지 정적 검사한다 (§5.2~5.4)."""
    if not product_files:
        return ["product/ 파일 없음 (Product Layer는 필수, §2.3)"]
    problems: list[str] = []
    stripped = "\n".join(
        strip_comments(text, Path(rel).suffix) for rel, text in product_files.items()
    )
    # §5.2-1: replay/runner artifact를 실제로 읽는다 (경로 문자열 + 읽기 동작)
    accesses = bool(
        re.search(r"replay/(?:index\.json|[\w./-]*\.json)", stripped)
        or re.search(r"(?:fetch|open|read|require|import|XMLHttpRequest|loadJSON)\b[^\n]*replay", stripped)
    )
    if not accesses:
        problems.append("product layer가 replay/ 산출물을 실제로 읽지 않음(문자열 흔적만) (§5.4)")
    # §5.2-2: final_state/events/summary 중 2개 이상 표시
    used = [f for f in ("final_state", "events", "summary") if f in stripped]
    if len(used) < 2:
        problems.append(
            f"core output 필드 사용 {len(used)}개({used or '없음'}) < 2 "
            "(final_state/events/summary 중 2개 이상 필요, §5.2)"
        )
    # §5.2-4: core action 로직을 product 안에 복제하지 않는다
    for action in (core_contract or {}).get("actions") or []:
        name = action.get("name") or ""
        if name and re.search(rf"\b(?:def|function)\s+{re.escape(name)}\b", stripped):
            problems.append(f"product layer가 core action 로직을 복제함: {name} (§5.4)")
    return problems


# ---------------------------------------------------------------- Runner Gate (§8.5)

def run_runner_gate(
    workspace: Path,
    runner_contract: dict,
    timeout_seconds: float,
    use_docker: bool | None,
    secrets: list[str],
) -> tuple[GateResult, dict | None]:
    r = GateResult(name="Runner Gate", ok=True)
    scenarios = list_scenario_files(workspace)
    if not scenarios:
        r.problems.append("fixtures/scenario_*.json 없음 → runner 실행 불가")
        r.ok = False
        return r, None
    run = run_scenario_once(workspace, runner_contract, scenarios[0], timeout_seconds, use_docker, secrets)
    r.sandbox_runs.append(run)
    if run["timed_out"]:
        r.problems.append(f"runner timeout: {run['command']}")
    elif run["exit_code"] not in (0,):
        r.problems.append(f"runner exit code {run['exit_code']}: {(run['stderr'] or '')[:300]}")
    if run["parsed"] is None:
        r.problems.append("runner 출력이 JSON이 아님")
    elif run["missing_fields"]:
        r.problems.append(f"required_output_fields 누락: {run['missing_fields']}")
    r.notes.append(f"command: {run['command']}")
    r.ok = not r.problems
    return r, run


# ---------------------------------------------------------------- Scenario Replay Gate (§8.5)

def run_scenario_replay_gate(
    workspace: Path,
    runner_contract: dict,
    timeout_seconds: float,
    use_docker: bool | None,
    secrets: list[str],
) -> tuple[GateResult, dict[str, dict]]:
    """모든 scenario를 재생하고 replay/ 결과를 남긴다. 반환: (GateResult, scenario_id → run dict)."""
    r = GateResult(name="Scenario Replay Gate", ok=True)
    replay_dir = workspace / "replay"
    replay_dir.mkdir(parents=True, exist_ok=True)
    scenarios = list_scenario_files(workspace)
    if not scenarios:
        r.problems.append("fixtures/scenario_*.json 없음")
        r.ok = False
        return r, {}

    outputs: dict[str, dict] = {}
    index = []
    for rel in scenarios:
        sid = _scenario_id(workspace, rel)
        run = run_scenario_once(workspace, runner_contract, rel, timeout_seconds, use_docker, secrets)
        outputs[sid] = run
        if run["parsed"] is not None:
            (replay_dir / f"replay_{sid}.json").write_text(
                json.dumps(run["parsed"], ensure_ascii=False, indent=2), encoding="utf-8"
            )
        if not run["ok"]:
            r.problems.append(f"scenario 재생 실패: {sid}: {(run['error'] or run['stderr'] or '')[:200]}")
        index.append({"id": sid, "file": f"replay_{sid}.json", "ok": bool(run["ok"])})
    (replay_dir / "index.json").write_text(
        json.dumps({"replays": index}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    r.notes.append(f"재생 scenario 수: {len(scenarios)}")
    r.ok = not r.problems
    return r, outputs


# ---------------------------------------------------------------- Golden Output Gate (§8.5, §6.7)

def _diff_exact(expected, actual, path="") -> list[str]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        diffs = []
        for k in sorted(set(expected) | set(actual)):
            if k not in expected:
                diffs.append(f"{path}.{k}: golden에 없는 키")
            elif k not in actual:
                diffs.append(f"{path}.{k}: 출력에 없는 키")
            else:
                diffs += _diff_exact(expected[k], actual[k], f"{path}.{k}")
        return diffs
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return [f"{path}: 길이 다름 (기대 {len(expected)}, 실제 {len(actual)})"]
        diffs = []
        for i, (e, a) in enumerate(zip(expected, actual)):
            diffs += _diff_exact(e, a, f"{path}[{i}]")
        return diffs
    if expected != actual:
        return [f"{path}: 기대 {expected!r} ≠ 실제 {actual!r}"]
    return []


def _diff_partial(expected, actual, path="") -> list[str]:
    """expected에 있는 키/값만 검사한다 (부분 비교)."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: dict가 아님"]
        diffs = []
        for k, v in expected.items():
            if k not in actual:
                diffs.append(f"{path}.{k}: 출력에 없는 키")
            else:
                diffs += _diff_partial(v, actual[k], f"{path}.{k}")
        return diffs
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [f"{path}: list가 아님"]
        if len(actual) < len(expected):
            return [f"{path}: 길이 부족 (기대 ≥{len(expected)}, 실제 {len(actual)})"]
        diffs = []
        for i, e in enumerate(expected):
            diffs += _diff_partial(e, actual[i], f"{path}[{i}]")
        return diffs
    if expected != actual:
        return [f"{path}: 기대 {expected!r} ≠ 실제 {actual!r}"]
    return []


def _diff_invariant_keys(expected, actual, path="") -> list[str]:
    """값은 비교하지 않고 expected의 키 구조가 존재하는지만 검사한다."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: dict가 아님"]
        diffs = []
        for k, v in expected.items():
            if k not in actual:
                diffs.append(f"{path}.{k}: 출력에 없는 키")
            else:
                diffs += _diff_invariant_keys(v, actual[k], f"{path}.{k}")
        return diffs
    return []


def compare_golden(golden: dict, parsed: dict) -> tuple[str, list[str]]:
    """golden 1건을 runner 출력과 비교한다. 반환: (result, diffs). result: PASS|FAIL|REVIEW."""
    mode = golden.get("comparison_mode") or "exact"
    if mode == "review":
        return "REVIEW", []
    actual_state = parsed.get("final_state")
    diffs: list[str] = []
    if mode == "exact":
        diffs += _diff_exact(golden.get("expected_final_state") or {}, actual_state, "final_state")
        if golden.get("expected_events"):
            diffs += _diff_exact(golden["expected_events"], parsed.get("events"), "events")
        if golden.get("expected_summary"):
            if golden["expected_summary"] != parsed.get("summary"):
                diffs.append(f"summary: 기대 {golden['expected_summary']!r} ≠ 실제 {parsed.get('summary')!r}")
    elif mode == "partial":
        diffs += _diff_partial(golden.get("expected_final_state") or {}, actual_state, "final_state")
        if golden.get("expected_events"):
            diffs += _diff_partial(golden["expected_events"], parsed.get("events"), "events")
        if golden.get("expected_summary") and golden["expected_summary"] != parsed.get("summary"):
            diffs.append(f"summary: 기대 {golden['expected_summary']!r} ≠ 실제 {parsed.get('summary')!r}")
    elif mode == "invariant":
        diffs += _diff_invariant_keys(golden.get("expected_final_state") or {}, actual_state, "final_state")
    return ("PASS" if not diffs else "FAIL"), diffs


def run_golden_output_gate(
    workspace: Path, goldens: list[dict], replay_outputs: dict[str, dict]
) -> tuple[GateResult, dict]:
    """golden 비교 gate. review 모드는 자동 PASS 근거로 세지 않는다 (§6.7).

    반환: (GateResult, golden_diff_summary dict).
    """
    r = GateResult(name="Golden Output Gate", ok=True)
    diffs_out = []
    passed = failed = review_skipped = 0
    exact_total = exact_passed = 0
    failed_scenarios: list[str] = []
    for golden in goldens:
        sid = golden.get("scenario_id") or "(없음)"
        mode = golden.get("comparison_mode") or "exact"
        run = replay_outputs.get(sid)
        if run is None or run.get("parsed") is None:
            failed += 1
            failed_scenarios.append(sid)
            r.problems.append(f"golden {sid}: replay 출력 없음")
            diffs_out.append({"scenario_id": sid, "mode": mode, "result": "FAIL",
                              "diffs": ["replay 출력 없음"]})
            continue
        result, diffs = compare_golden(golden, run["parsed"])
        if mode == "exact":
            exact_total += 1
            if result == "PASS":
                exact_passed += 1
        if result == "REVIEW":
            review_skipped += 1
        elif result == "PASS":
            passed += 1
        else:
            failed += 1
            failed_scenarios.append(sid)
            r.problems.append(f"golden {sid} ({mode}) 불일치: " + "; ".join(diffs)[:300])
        diffs_out.append({"scenario_id": sid, "mode": mode, "result": result, "diffs": diffs[:20]})

    if not goldens:
        r.problems.append("golden expected 없음")
    elif passed + failed == 0:
        r.problems.append("자동 gate로 사용 가능한 golden 없음 (전부 review 모드)")
    summary = {
        "status": "PASS" if not r.problems else "FAIL",
        "total": len(goldens),
        "passed": passed,
        "failed": failed,
        "review_skipped": review_skipped,
        "exact_total": exact_total,
        "exact_passed": exact_passed,
        "failed_scenarios": failed_scenarios,
        "diffs": diffs_out,
    }
    r.notes.append(f"golden {len(goldens)}건: PASS {passed} / FAIL {failed} / REVIEW 제외 {review_skipped}")
    r.ok = not r.problems
    return r, summary


# ---------------------------------------------------------------- Golden Representation Lint (정답지 표현 계약)

def lint_golden_representation(core_contract: dict, goldens: list[dict]) -> dict:
    """golden이 contract의 output_representation(이벤트/summary 표현 계약)을 따르는지 기계 검사.

    구현이 없는 시점에 정답지↔구현 표현 드리프트를 막는 결정적 lint다.
    선언이 없으면 NOT_DECLARED (기존 run 호환 — 강제하지 않고 기록만).
    비어 있는 expected_events/expected_summary는 "기대 없음"으로 통과다.

    strict mode (Phase 2D-1 §2.3): core_contract.harness_schema_version >= 2인 run은
    output_representation 필수, event_item_type/event_required_keys/summary_format 필수,
    아무 기대값도 없는 golden(빈 정답지)은 FAIL로 강제한다.
    """
    try:
        strict = int((core_contract or {}).get("harness_schema_version") or 1) >= 2
    except (TypeError, ValueError):
        strict = False
    rep = (core_contract or {}).get("output_representation")
    if not isinstance(rep, dict) or not rep:
        if strict:
            return {"status": "FAIL", "declared": None, "strict": True,
                    "problems": ["output_representation 미선언 (harness_schema_version>=2 강제, §2.3)"],
                    "checked_goldens": len(goldens or [])}
        return {"status": "NOT_DECLARED", "declared": None, "strict": False, "problems": [],
                "checked_goldens": len(goldens or [])}
    problems: list[str] = []
    ev_type = rep.get("event_item_type")
    ev_keys = [k for k in (rep.get("event_required_keys") or []) if isinstance(k, str)]
    kind_key = rep.get("event_kind_key")
    kinds = [k for k in (rep.get("event_kinds") or []) if isinstance(k, str)]
    if strict:
        if ev_type not in ("object", "string"):
            problems.append(f"strict: event_item_type 미선언/무효 ({ev_type!r})")
        if ev_type == "object" and not ev_keys:
            problems.append("strict: event_item_type=object인데 event_required_keys 미선언")
        if not (rep.get("summary_format") or "").strip():
            problems.append("strict: summary_format 미선언")
        for g in goldens or []:
            if not (g.get("expected_events") or g.get("expected_final_state")
                    or (g.get("expected_summary") or "").strip()):
                problems.append(
                    f"{g.get('scenario_id') or '?'}: expected event/state/summary 모두 비어 있음 "
                    "(strict: 빈 정답지 금지)")
    for g in goldens or []:
        sid = g.get("scenario_id") or "?"
        for i, ev in enumerate(g.get("expected_events") or []):
            if ev_type == "object":
                if not isinstance(ev, dict):
                    problems.append(
                        f"{sid}: expected_events[{i}]가 object가 아님 "
                        f"(선언 object, 실제 {type(ev).__name__} {str(ev)[:40]!r} — 추상 라벨 금지)")
                    continue
                missing = [k for k in ev_keys if k not in ev]
                if missing:
                    problems.append(f"{sid}: expected_events[{i}]에 필수 키 없음: {missing}")
                if kinds and kind_key and ev.get(kind_key) not in kinds:
                    problems.append(
                        f"{sid}: expected_events[{i}].{kind_key}={ev.get(kind_key)!r}가 "
                        f"선언된 event_kinds에 없음: {kinds}")
            elif ev_type == "string":
                if not isinstance(ev, str):
                    problems.append(
                        f"{sid}: expected_events[{i}]가 string이 아님 "
                        f"(선언 string, 실제 {type(ev).__name__})")
                elif kinds and ev not in kinds:
                    problems.append(
                        f"{sid}: expected_events[{i}]={ev!r}가 선언된 event_kinds에 없음: {kinds}")
        summary = g.get("expected_summary")
        if summary not in (None, "") and not isinstance(summary, str):
            problems.append(
                f"{sid}: expected_summary가 string이 아님 "
                f"(하네스 표준: summary는 상태에서 파생된 문자열, 실제 {type(summary).__name__})")
    return {"status": "PASS" if not problems else "FAIL", "declared": rep, "strict": strict,
            "problems": problems, "checked_goldens": len(goldens or [])}


# ---------------------------------------------------------------- State Invariant Gate (§8.5)

_INV_CMP_RE = re.compile(r"^\s*([\w.]+)\s*(>=|<=|==|>|<)\s*(-?\d+(?:\.\d+)?)\s*$")


def _resolve_path(state, path: str):
    node = state
    for part in path.split("."):
        # Phase 2B-1 §9 최소 보강: dict/list의 단순 length 해석 (missing path와 empty는 구분 유지)
        if part == "length" and isinstance(node, (list, dict)):
            node = len(node)
            continue
        if not isinstance(node, dict) or part not in node:
            return None, False
        node = node[part]
    return node, True


def check_invariant(final_state: dict, invariant: str) -> tuple[bool | None, str]:
    """invariant 문자열 하나를 평가한다. 반환: (통과 여부 | None=평가불가, 메시지)."""
    inv = (invariant or "").strip()
    if inv.startswith("exists:"):
        path = inv[len("exists:"):].strip()
        _, found = _resolve_path(final_state, path)
        return (True, "") if found else (False, f"필수 필드 없음: {path}")
    m = _INV_CMP_RE.match(inv)
    if not m:
        return None, f"기계 평가 불가 invariant: {inv}"
    path, op, num = m.group(1), m.group(2), float(m.group(3))
    value, found = _resolve_path(final_state, path)
    if not found:
        return False, f"invariant 대상 필드 없음: {path}"
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False, f"invariant 대상이 숫자가 아님: {path}={value!r}"
    ok = {
        ">=": value >= num, "<=": value <= num, "==": value == num,
        ">": value > num, "<": value < num,
    }[op]
    return (True, "") if ok else (False, f"invariant 위반: {path}={value} (기대 {op} {num:g})")


def invariant_category(ok: bool | None, msg: str) -> str:
    """check_invariant 결과를 §15.2 카테고리로 분류한다.

    반환: INVARIANT_PASS | INVARIANT_FAIL | INVARIANT_NOT_EXPOSED | INVARIANT_UNCHECKABLE.
    """
    if ok is None:
        return "INVARIANT_UNCHECKABLE"
    if ok:
        return "INVARIANT_PASS"
    if "필드 없음" in msg or "dict가 아님" in msg:
        return "INVARIANT_NOT_EXPOSED"
    return "INVARIANT_FAIL"


def _entity_instances(entity: dict, final_state: dict) -> list[dict]:
    """entity 필드를 모두 가진 인스턴스를 final_state에서 찾는다 (Phase 2B-1 §9).

    entity 이름 키 singleton(final_state[name]이 필드를 모두 가진 dict), list-of-dicts,
    dict-of-dicts(id 키 컬렉션)만 최소 해석한다. 못 찾으면 빈 리스트
    (호출부가 INVARIANT_NOT_EXPOSED를 유지 — missing path 자동 PASS 금지).
    """
    fields = set(entity.get("fields") or [])
    if not fields:
        return []
    # entity 이름 키 singleton: golden expected_final_state와 같은 중첩 구조를 해석한다.
    # 필드가 하나라도 없으면 매칭하지 않는다 — NOT_EXPOSED 유지 (자동 PASS 금지).
    named = final_state.get(entity.get("name") or "")
    if isinstance(named, dict) and fields <= set(named.keys()):
        return [named]
    out: list[dict] = []
    for value in final_state.values():
        if isinstance(value, list):
            items = value
        elif isinstance(value, dict) and value and all(isinstance(v, dict) for v in value.values()):
            items = list(value.values())
        else:
            continue
        if items and all(isinstance(e, dict) and fields <= set(e.keys()) for e in items):
            out.extend(items)
    return out


def run_state_invariant_gate(
    core_contract: dict, replay_outputs: dict[str, dict]
) -> tuple[GateResult, dict]:
    r = GateResult(name="State Invariant Gate", ok=True)
    entities = core_contract.get("state_entities") or []
    violations = []
    not_exposed: list[dict] = []
    failed: list[dict] = []
    unevaluated = []
    checked = 0
    for sid, run in replay_outputs.items():
        parsed = run.get("parsed")
        if not parsed:
            continue
        final_state = parsed.get("final_state")
        if not isinstance(final_state, dict):
            v = {"scenario_id": sid, "invariant": "(구조)", "message": "final_state가 dict가 아님",
                 "category": "INVARIANT_NOT_EXPOSED"}
            violations.append(v)
            not_exposed.append(v)
            continue
        for entity in entities:
            for inv in entity.get("invariants") or []:
                ok, msg = check_invariant(final_state, inv)
                category = invariant_category(ok, msg)
                # Phase 2B-1 §9: top-level에 없으면 entity 인스턴스(컬렉션 원소) 기준으로 최소 해석.
                # 인스턴스도 못 찾으면 NOT_EXPOSED 유지 (자동 PASS 금지), 값 위반은 FAIL로 구분.
                if ok is False and category == "INVARIANT_NOT_EXPOSED":
                    instances = _entity_instances(entity, final_state)
                    if instances:
                        bad = None
                        for inst in instances:
                            i_ok, i_msg = check_invariant(inst, inv)
                            if i_ok is not True:
                                bad = (i_ok, i_msg)
                                break
                        ok, msg = (True, "") if bad is None else bad
                        category = invariant_category(ok, msg)
                if ok is None:
                    if msg not in unevaluated:
                        unevaluated.append(msg)
                    continue
                checked += 1
                if not ok:
                    v = {"scenario_id": sid, "invariant": inv, "message": msg, "category": category}
                    violations.append(v)
                    (not_exposed if category == "INVARIANT_NOT_EXPOSED" else failed).append(v)
    for v in violations:
        r.problems.append(f"{v['scenario_id']}: {v['message']}")
    r.notes += unevaluated
    r.notes.append(f"invariant 평가 {checked}건 (노출 안 됨 {len(not_exposed)} / 위반 {len(failed)})")
    summary = {
        "status": "PASS" if not violations else "FAIL",
        "checked": checked,
        "violations": violations,
        "not_exposed": not_exposed,
        "failed": failed,
        "unevaluated": unevaluated,
        "counts": {
            "not_exposed": len(not_exposed),
            "failed": len(failed),
            "uncheckable": len(unevaluated),
        },
    }
    r.ok = not r.problems
    return r, summary


# ---------------------------------------------------------------- Determinism Gate (§8.5)

_RANDOM_PATTERNS = (
    "Math.random", "Date.now", "random.random", "random.randint", "random.choice",
    "random.shuffle", "datetime.now", "time.time(", "uuid4", "uuid.uuid",
)


def run_determinism_gate(
    workspace: Path,
    core_contract: dict,
    runner_contract: dict,
    replay_outputs: dict[str, dict],
    timeout_seconds: float,
    use_docker: bool | None,
    secrets: list[str],
) -> tuple[GateResult, dict]:
    """같은 scenario를 역순으로 다시 실행해 출력 동일성을 검사하고 random/시간 의존 코드를 탐지한다.

    2차 실행을 역순으로 수행해 fixture 순서 변경 검사(§8.5 Level 2)도 함께 충족한다.
    """
    r = GateResult(name="Determinism Gate", ok=True)
    determinism = core_contract.get("determinism") or {}
    random_allowed = bool(determinism.get("random_allowed"))

    code = src_code_files(workspace)
    static_problems = []
    blob = "\n".join(code.values())
    for rel, text in code.items():
        for pattern in _RANDOM_PATTERNS:
            if pattern in text:
                if random_allowed and "seed" in blob:
                    continue
                static_problems.append(f"{rel}: 비결정 요소 사용 ({pattern})")
    r.problems += static_problems

    mismatches = []
    reran = 0
    scenarios = list(reversed(list_scenario_files(workspace)))
    for rel in scenarios:
        sid = _scenario_id(workspace, rel)
        first = replay_outputs.get(sid)
        if first is None or first.get("parsed") is None:
            continue
        second = run_scenario_once(workspace, runner_contract, rel, timeout_seconds, use_docker, secrets)
        reran += 1
        if second.get("parsed") != first.get("parsed"):
            mismatches.append(sid)
            r.problems.append(f"재실행 출력 불일치: {sid}")
    summary = {
        "status": "PASS" if not r.problems else "FAIL",
        "reran": reran,
        "rerun_order": "reversed",
        "mismatches": mismatches,
        "static_problems": static_problems,
        "random_allowed": random_allowed,
    }
    r.notes.append(f"역순 재실행 {reran}건, 불일치 {len(mismatches)}건")
    r.ok = not r.problems
    return r, summary


# ---------------------------------------------------------------- Anti-Hardcode Gate (§8.5 Level 1~2)

_SCENARIO_ID_RE = re.compile(r"scenario_\d+")
_TODO_RE = re.compile(r"\b(TODO|FIXME|PLACEHOLDER)\b|coming soon", re.IGNORECASE)
_SERIALIZED_OK_PATTERNS = ('\'{"ok"', '"{\\"ok\\"', "'{\\'ok\\'")

# summary 리터럴이 이 그래프-실행 상태 토큰들을 읽는 함수 안에서 나오면 state 파생으로 본다 (Phase 2B-1b §8).
# errors/len 단독은 파생 근거로 인정하지 않는다 — 실행 상태가 아니라 예외 개수일 뿐이다.
_SUMMARY_STATE_TOKENS = ("final_state", "execution_order", "executed_nodes", "failed_nodes",
                         "nodes", "edges", "status", "global_tick")
_SUMMARY_EVENT_TOKENS = ("events",)
_SUMMARY_ASSIGN_RE = re.compile(r"""["']summary["']\s*:|(?<![\w.])summary\s*=""")


def _enclosing_scope(text: str, lineno: int) -> str:
    """lineno(0-base)를 포함하는 def 블록 텍스트를 추출한다. 감싸는 def가 없으면 모듈 전체."""
    lines = text.splitlines()
    start, indent = None, None
    for i in range(min(lineno, len(lines) - 1), -1, -1):
        m = re.match(r"(\s*)def\s+\w+", lines[i])
        if m:
            start, indent = i, len(m.group(1))
            break
    if start is None:
        return text  # 모듈 스코프
    end = len(lines)
    for j in range(start + 1, len(lines)):
        stripped = lines[j].strip()
        if stripped and (len(lines[j]) - len(lines[j].lstrip())) <= indent \
                and re.match(r"\s*(def|class)\s", lines[j]):
            end = j
            break
    return "\n".join(lines[start:end])


def classify_summary_source(code: dict[str, str], goldens: list[dict]) -> dict:
    """golden expected_summary 리터럴이 코드에 어떻게 존재하는지 분류한다 (Phase 2B-1b §8).

    - summary 대입식에 리터럴이 직접 결합 → hardcoded(high)
    - 리터럴이 그래프-실행 상태/events를 읽는 formatter 함수 안의 결과 상수 → state/event_derived(low)
    - 그 외(모듈 상수 등 파생 근거 없음) → hardcoded(high)
    리터럴이 아예 없으면 n/a(low). anti_hardcode를 느슨하게 만들지 않고 오탐만 줄인다.
    """
    src = {k: v for k, v in code.items() if k.startswith("src/")}
    src_blob = "\n".join(src.values())
    literals = sorted({(g.get("expected_summary") or "").strip() for g in goldens})
    literals = [s for s in literals if len(s) >= 8]
    problems: list[str] = []
    evidence: list[str] = []
    source, risk = "n/a", "low"
    for lit in literals:
        if lit not in src_blob:
            continue
        direct, derived, derived_kind = False, False, "state_derived"
        for rel, text in src.items():
            if lit not in text:
                continue
            for i, line in enumerate(text.splitlines()):
                if lit not in line:
                    continue
                if _SUMMARY_ASSIGN_RE.search(line):
                    direct = True
                    evidence.append(f"{rel}:{i + 1}: summary 대입에 리터럴 직접 결합")
                scope = _enclosing_scope(text, i)
                has_state = any(t in scope for t in _SUMMARY_STATE_TOKENS)
                has_event = any(t in scope for t in _SUMMARY_EVENT_TOKENS)
                if (has_state or has_event) and not _SCENARIO_ID_RE.search(scope):
                    derived = True
                    derived_kind = "event_derived" if has_event and not has_state else "state_derived"
                    evidence.append(f"{rel}:{i + 1}: state/events 파생 formatter 결과 상수")
        if direct:
            problems.append(f"expected_summary 리터럴이 summary 대입에 직접 하드코딩됨: {lit!r}")
            source, risk = "hardcoded", "high"
        elif derived:
            source = derived_kind
        else:
            problems.append(f"expected_summary 리터럴이 코드에 하드코딩됨(state/events 파생 근거 없음): {lit!r}")
            source, risk = "hardcoded", "high"
    return {"problems": problems, "summary_source": source,
            "summary_hardcode_risk": risk, "summary_evidence": evidence}


# ---------------------------------------------------------------- Mock Fallback 검출 (Phase 2D-1 §2.2)

# fallback을 쓰려면 이 상태 중 하나를 화면에 명시해야 한다 — 실제 실행 결과 위장 금지.
FALLBACK_STATE_TOKENS = ("DEMO_ONLY", "NOT_EXECUTED", "RUNNER_UNAVAILABLE")
_FAKE_RESULT_RE = re.compile(r"Math\.random\s*\(|Date\.now\s*\(")
_SUCCESS_PAYLOAD_RE = re.compile(
    r"""(?:["']?(?:ok|success)["']?\s*:\s*true)"""
    r"""|(?:["']?status["']?\s*:\s*["'](?:ok|success|pass|passed|completed)["'])""",
    re.IGNORECASE,
)
_DEMO_NAME_RE = re.compile(r"\b(?:demo|mock|fake|sample)(?:Result|Data|Response|Payload|Replay)\b")
_CATCH_WINDOW = 600


def detect_mock_fallback(product_files: dict[str, str]) -> dict:
    """product/ 파일에서 mock/demo fallback을 실제 실행 결과처럼 표시하는 패턴을 정적 검출한다 (§2.2).

    검출 규칙 (결정적 static scan):
    - catch 블록 부근에서 성공 payload/demo 데이터를 만들면서 FALLBACK_STATE_TOKENS 미표시
    - Math.random / Date.now 기반 가짜 실행 결과 (2C-3 viewer smoke 규칙을 gate로 승격)
    - demo/mock/fake/sample 이름의 결과 데이터를 상태 표시 없이 사용
    """
    problems: list[str] = []
    for rel, text in sorted(product_files.items()):
        has_state_token = any(tok in text for tok in FALLBACK_STATE_TOKENS)
        for m in _FAKE_RESULT_RE.finditer(text):
            lineno = text.count("\n", 0, m.start()) + 1
            problems.append(f"{rel}:{lineno}: 가짜 실행 결과 의심 ({m.group(0).strip()} — 금지)")
        for m in re.finditer(r"\bcatch\b", text):
            window = text[m.start():m.start() + _CATCH_WINDOW]
            if any(tok in window for tok in FALLBACK_STATE_TOKENS):
                continue
            if _SUCCESS_PAYLOAD_RE.search(window) or _DEMO_NAME_RE.search(window):
                lineno = text.count("\n", 0, m.start()) + 1
                problems.append(
                    f"{rel}:{lineno}: 실패 catch에서 성공 mock/demo 결과 표시 의심 "
                    f"(DEMO_ONLY/NOT_EXECUTED/RUNNER_UNAVAILABLE 상태 미표시)")
        if not has_state_token:
            for m in _DEMO_NAME_RE.finditer(text):
                lineno = text.count("\n", 0, m.start()) + 1
                problems.append(
                    f"{rel}:{lineno}: 내장 demo 데이터({m.group(0)})를 상태 표시 없이 사용 의심")
    return {"problems": problems, "mock_fallback_count": len(problems),
            "checked_files": sorted(product_files)}


def run_anti_hardcode_gate(
    workspace: Path,
    goldens: list[dict],
    runner_contract: dict,
    replay_outputs: dict[str, dict],
    timeout_seconds: float,
    use_docker: bool | None,
    secrets: list[str],
    run_level2: bool = True,
) -> tuple[GateResult, dict]:
    r = GateResult(name="Anti-Hardcode Gate", ok=True)
    level1: list[str] = []
    level2: list[str] = []
    medium_only: list[str] = []

    code = src_code_files(workspace, roots=("src", "product"))
    for rel, text in code.items():
        if _SCENARIO_ID_RE.search(text):
            level1.append(f"{rel}: fixture id 직접 분기 의심 ({_SCENARIO_ID_RE.search(text).group(0)})")
        if _TODO_RE.search(text):
            medium_only.append(f"{rel}: TODO/placeholder 흔적")
        for pattern in _SERIALIZED_OK_PATTERNS:
            if pattern in text:
                level1.append(f"{rel}: 미리 직렬화된 출력 문자열 의심 (hardcoded success)")
                break

    # golden summary 리터럴이 하드코딩인지 state/events 파생인지 분류 (Phase 2B-1b §8)
    summary_class = classify_summary_source(code, goldens)
    level1 += summary_class["problems"]

    # mock/demo fallback을 실제 실행 결과처럼 표시하는 패턴 검출 (Phase 2D-1 §2.2)
    # product/가 아직 없으면(빌드 pre-product 시점) 검사 대상 0 — post-product 재실행에서 잡는다.
    mock_fb = detect_mock_fallback({rel: t for rel, t in code.items() if rel.startswith("product/")})
    level1 += mock_fb["problems"]

    # Level 2: scenario id/title 변형 후 재실행 → final_state가 달라지면 fixture 의존 (§8.5)
    variant_ran = False
    if run_level2 and not level1:
        scenarios = list_scenario_files(workspace)
        for rel in scenarios:
            try:
                data = json.loads((workspace / rel).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            sid = data.get("id") or Path(rel).stem
            first = replay_outputs.get(sid)
            if first is None or first.get("parsed") is None:
                continue
            variant = json.loads(json.dumps(data))
            variant["id"] = f"{sid}_variant"
            variant["title"] = f"variant of {sid}"
            variants_dir = workspace / "fixtures" / "_variants"
            variants_dir.mkdir(parents=True, exist_ok=True)
            variant_rel = f"fixtures/_variants/{sid}_variant.json"
            (workspace / variant_rel).write_text(
                json.dumps(variant, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            run = run_scenario_once(workspace, runner_contract, variant_rel, timeout_seconds, use_docker, secrets)
            variant_ran = True
            if run.get("parsed") is None:
                level2.append(f"{sid}: 변형 fixture 실행 실패")
            elif run["parsed"].get("final_state") != first["parsed"].get("final_state"):
                level2.append(f"{sid}: id/title 변형 후 final_state가 달라짐 (fixture 의존 의심)")
            break  # 간단한 Level 2 — 대표 scenario 1개만 변형 실행

    hardcode_risk = "low"
    if level1 or level2:
        hardcode_risk = "high"
    elif medium_only:
        hardcode_risk = "medium"

    r.problems += level1 + level2
    r.notes += medium_only
    r.notes.append(f"Level 2 변형 실행: {'수행' if variant_ran else '생략'}")
    summary = {
        "status": "PASS" if not r.problems else "FAIL",
        "level1_problems": level1,
        "level2_problems": level2,
        "medium_signals": medium_only,
        "hardcode_risk": hardcode_risk,
        "level2_ran": variant_ran,
        "summary_source": summary_class["summary_source"],
        "summary_hardcode_risk": summary_class["summary_hardcode_risk"],
        "summary_evidence": summary_class["summary_evidence"],
        "mock_fallback_count": mock_fb["mock_fallback_count"],
        "mock_fallback_problems": mock_fb["problems"],
        "product_files_scanned": mock_fb["checked_files"],
    }
    r.ok = not r.problems
    return r, summary


# ---------------------------------------------------------------- 전체 실행 (§8)

def run_core_gates(
    workspace: Path,
    core_contract: dict,
    runner_contract: dict,
    goldens: list[dict],
    timeout_seconds: float = 120.0,
    use_docker: bool | None = None,
    secrets: list[str] | None = None,
) -> dict:
    """core gate 전체를 순서대로 실행한다.

    반환 dict: summary(bool), problems, results(GateResult), artifacts(json용 요약), replay_outputs.
    """
    secrets = secrets or []
    use_docker = _resolve_docker(use_docker)
    results: dict[str, GateResult] = {}
    artifacts: dict[str, dict] = {}

    results["core_contract"] = run_core_contract_gate(workspace, core_contract, runner_contract)

    runner_result, runner_run = run_runner_gate(
        workspace, runner_contract, timeout_seconds, use_docker, secrets
    )
    results["runner"] = runner_result
    artifacts["runner_summary"] = {
        "status": "PASS" if runner_result.ok else "FAIL",
        "command": (runner_run or {}).get("command"),
        "exit_code": (runner_run or {}).get("exit_code"),
        "missing_fields": (runner_run or {}).get("missing_fields") or [],
        "timed_out": bool((runner_run or {}).get("timed_out")),
        "stdout_preview": ((runner_run or {}).get("stdout") or "")[:2000],
        "stderr_preview": ((runner_run or {}).get("stderr") or "")[:2000],
        "problems": runner_result.problems,
    }

    replay_outputs: dict[str, dict] = {}
    if runner_result.ok:
        replay_result, replay_outputs = run_scenario_replay_gate(
            workspace, runner_contract, timeout_seconds, use_docker, secrets
        )
    else:
        replay_result = GateResult(
            name="Scenario Replay Gate", ok=False,
            problems=["선행 runner gate 실패로 재생 생략"],
        )
    results["scenario_replay"] = replay_result
    replay_failed = [
        sid for sid, run in replay_outputs.items() if not run.get("ok")
    ] if replay_outputs else []
    artifacts["scenario_replay_summary"] = {
        "status": "PASS" if replay_result.ok else "FAIL",
        "total": len(replay_outputs),
        "passed": len(replay_outputs) - len(replay_failed),
        "failed_scenarios": replay_failed,
        "problems": replay_result.problems,
    }

    # Core Contract Gate 런타임 반영 검사 (§4.2-3,4): replay 이후에만 가능
    augment_core_contract_runtime(results["core_contract"], core_contract, replay_outputs)
    artifacts["core_contract_summary"] = {
        "status": "PASS" if results["core_contract"].ok else "FAIL",
        "problems": results["core_contract"].problems,
    }

    if runner_result.ok:
        golden_result, golden_summary = run_golden_output_gate(workspace, goldens, replay_outputs)
    else:
        golden_result = GateResult(name="Golden Output Gate", ok=False,
                                   problems=["선행 runner gate 실패로 비교 생략"])
        golden_summary = {"status": "FAIL", "total": len(goldens), "passed": 0, "failed": 0,
                          "review_skipped": 0, "exact_total": 0, "exact_passed": 0,
                          "failed_scenarios": [], "diffs": []}
    results["golden_output"] = golden_result
    artifacts["golden_diff_summary"] = golden_summary

    invariant_result, invariant_summary = run_state_invariant_gate(core_contract, replay_outputs)
    if not runner_result.ok:
        invariant_result.ok = False
        invariant_result.problems.append("선행 runner gate 실패로 검사 불충분")
        invariant_summary["status"] = "FAIL"
    results["state_invariant"] = invariant_result
    artifacts["state_invariant_summary"] = invariant_summary

    if runner_result.ok:
        det_result, det_summary = run_determinism_gate(
            workspace, core_contract, runner_contract, replay_outputs,
            timeout_seconds, use_docker, secrets,
        )
    else:
        det_result = GateResult(name="Determinism Gate", ok=False,
                                problems=["선행 runner gate 실패로 재실행 생략"])
        det_summary = {"status": "FAIL", "reran": 0, "mismatches": [], "static_problems": []}
    results["determinism"] = det_result
    artifacts["determinism_summary"] = det_summary

    anti_result, anti_summary = run_anti_hardcode_gate(
        workspace, goldens, runner_contract, replay_outputs,
        timeout_seconds, use_docker, secrets, run_level2=runner_result.ok,
    )
    results["anti_hardcode"] = anti_result
    artifacts["anti_hardcode_summary"] = anti_summary

    # gate report markdown (final_artifact/reports/)
    report_names = {
        "core_contract": "core_contract_report.md",
        "runner": "runner_report.md",
        "scenario_replay": "scenario_replay_report.md",
        "golden_output": "golden_output_report.md",
        "state_invariant": "state_invariant_report.md",
        "determinism": "determinism_report.md",
        "anti_hardcode": "anti_hardcode_report.md",
    }
    for key, fname in report_names.items():
        write_gate_report(workspace, fname, results[key])

    summary = {name: res.ok for name, res in results.items()}
    problems = {name: res.problems for name, res in results.items()}
    return {
        "summary": summary,
        "problems": problems,
        "results": results,
        "artifacts": artifacts,
        "replay_outputs": replay_outputs,
        "replay_failed": replay_failed,
    }
