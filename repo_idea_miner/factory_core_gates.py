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


def _src_code_files(workspace: Path, roots: tuple[str, ...] = ("src",)) -> dict[str, str]:
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

    code = _src_code_files(workspace)
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


# ---------------------------------------------------------------- State Invariant Gate (§8.5)

_INV_CMP_RE = re.compile(r"^\s*([\w.]+)\s*(>=|<=|==|>|<)\s*(-?\d+(?:\.\d+)?)\s*$")


def _resolve_path(state, path: str):
    node = state
    for part in path.split("."):
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


def run_state_invariant_gate(
    core_contract: dict, replay_outputs: dict[str, dict]
) -> tuple[GateResult, dict]:
    r = GateResult(name="State Invariant Gate", ok=True)
    invariants: list[str] = []
    for entity in core_contract.get("state_entities") or []:
        invariants += entity.get("invariants") or []
    violations = []
    unevaluated = []
    checked = 0
    for sid, run in replay_outputs.items():
        parsed = run.get("parsed")
        if not parsed:
            continue
        final_state = parsed.get("final_state")
        if not isinstance(final_state, dict):
            violations.append({"scenario_id": sid, "invariant": "(구조)", "message": "final_state가 dict가 아님"})
            continue
        for inv in invariants:
            ok, msg = check_invariant(final_state, inv)
            if ok is None:
                if msg not in unevaluated:
                    unevaluated.append(msg)
                continue
            checked += 1
            if not ok:
                violations.append({"scenario_id": sid, "invariant": inv, "message": msg})
    for v in violations:
        r.problems.append(f"{v['scenario_id']}: {v['message']}")
    r.notes += unevaluated
    r.notes.append(f"invariant 평가 {checked}건")
    summary = {
        "status": "PASS" if not violations else "FAIL",
        "checked": checked,
        "violations": violations,
        "unevaluated": unevaluated,
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

    code = _src_code_files(workspace)
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

    code = _src_code_files(workspace, roots=("src", "product"))
    for rel, text in code.items():
        if _SCENARIO_ID_RE.search(text):
            level1.append(f"{rel}: fixture id 직접 분기 의심 ({_SCENARIO_ID_RE.search(text).group(0)})")
        if _TODO_RE.search(text):
            medium_only.append(f"{rel}: TODO/placeholder 흔적")
        for pattern in _SERIALIZED_OK_PATTERNS:
            if pattern in text:
                level1.append(f"{rel}: 미리 직렬화된 출력 문자열 의심 (hardcoded success)")
                break

    src_blob = "\n".join(v for k, v in code.items() if k.startswith("src/"))
    for golden in goldens:
        summary_text = (golden.get("expected_summary") or "").strip()
        if len(summary_text) >= 8 and summary_text in src_blob:
            level1.append(f"golden expected_summary 문자열이 코드에 직접 포함됨: {summary_text!r}")

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
