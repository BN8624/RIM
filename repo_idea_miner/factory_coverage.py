# 이슈 #9: requirement coverage 판정을 결정론적 probe와 구조화 matrix로 만드는 모듈 (LLM 감상 없음).
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from repo_idea_miner.factory_run_layout import resolve_artifact_root

COVERAGE_SUBDIR = "review/coverage"
PROBE_SPEC_NAME = "coverage_probe_spec.json"
PROBE_RESULTS_NAME = "coverage_probe_results.json"
ADJUDICATION_NAME = "coverage_adjudication.json"
MATRIX_NAME = "coverage_matrix.json"

# §6.2 정본 enum — 이 목록 밖 값은 거부한다 (unknown classification 거부)
REQUIREMENT_KINDS = (
    "CRITICAL_REQUIREMENT",
    "DIFFICULTY_ANCHOR",
    "SUPPORTING_REQUIREMENT",
)
COVERAGE_STATUSES = (
    "COVERED",
    "PARTIALLY_COVERED",
    "NOT_COVERED",
    "AMBIGUOUS",
    "NOT_APPLICABLE",
)
FAILURE_CLASSES = (
    "TRUE_CORE_GAP",
    "EVIDENCE_GAP",
    "VALIDATOR_DEFECT",
    "SPEC_OVERREACH",
    "NONE",
)
PROBE_CHECK_KINDS = (
    "final_state_path",
    "queued_events",
    "distinct_paths",
    "ordered_paths",
    "errors",
    "static_substring_count",
)


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
                    encoding="utf-8")


def artifact_fingerprint(artifact_root: Path) -> str:
    """probe evidence가 '이 구현'에 대한 것임을 고정한다 — 다른 run에서 복사한 과거
    evidence는 fingerprint 불일치로 거부된다 (§17.3 과거 evidence 복사 거부)."""
    artifact_root = Path(artifact_root)
    h = hashlib.sha256()
    files = sorted(artifact_root.glob("src/**/*.py")) + [artifact_root / "runner_contract.json"]
    for f in files:
        if f.is_file():
            h.update(f.relative_to(artifact_root).as_posix().encode("utf-8"))
            h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


# ---------------------------------------------------------------- 결정론적 probe 실행 (§6.3-1)

def _dig(obj, path: str):
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None, False
        cur = cur[part]
    return cur, True


def _eval_check(check: dict, output: dict | None, root: Path) -> dict:
    kind = check.get("kind")
    res = {"kind": kind, "pass": False, "detail": None}
    if kind == "final_state_path":
        val, found = _dig((output or {}).get("final_state") or {}, check["path"])
        op = check.get("op", "eq")
        if op == "eq":
            res["pass"] = found and val == check.get("value")
        elif op == "is_int":
            res["pass"] = found and isinstance(val, int) and not isinstance(val, bool)
        elif op == "exists":
            res["pass"] = found
        elif op == "absent":
            res["pass"] = not found
        res["detail"] = {"path": check["path"], "found": found, "value": val}
    elif kind == "queued_events":
        id_key = check.get("id_key", "target_id")
        ids = [e.get(id_key) for e in (output or {}).get("events") or []
               if e.get("type") == check.get("event_type")]
        ok = True
        if "expected_target_ids" in check:
            ok = ok and ids == list(check["expected_target_ids"])
        for forbidden in check.get("forbidden_target_ids", []):
            ok = ok and forbidden not in ids
        res["pass"] = ok
        res["detail"] = {"observed_ids": ids}
    elif kind == "distinct_paths":
        vals = [_dig((output or {}).get("final_state") or {}, p)[0] for p in check["paths"]]
        res["pass"] = len(set(map(repr, vals))) == len(vals)
        res["detail"] = {"values": vals}
    elif kind == "ordered_paths":
        vals = [_dig((output or {}).get("final_state") or {}, p)[0] for p in check["paths"]]
        res["pass"] = all(isinstance(v, (int, float)) for v in vals) \
            and all(a < b for a, b in zip(vals, vals[1:]))
        res["detail"] = {"values": vals}
    elif kind == "errors":
        errs = (output or {}).get("errors") or []
        res["pass"] = bool(errs) if check.get("expect") == "nonempty" else not errs
        res["detail"] = {"errors": errs}
    elif kind == "static_substring_count":
        count = 0
        for p in sorted(root.glob(check.get("glob", "product/**/*.html"))):
            if p.is_file():
                count += p.read_text(encoding="utf-8", errors="ignore").count(check["needle"])
        res["pass"] = count > 0 if check.get("op", "gt0") == "gt0" else count == 0
        res["detail"] = {"count": count}
    else:
        res["detail"] = f"알 수 없는 check kind: {kind}"
    return res


def _run_scenario(root: Path, initial_state: dict, actions: list, timeout: float) -> dict | None:
    scenario = {"id": "coverage_probe", "initial_state": initial_state, "actions": actions}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as fh:
        json.dump(scenario, fh, ensure_ascii=True)
        spath = fh.name
    try:
        out = subprocess.run(
            [sys.executable, str(Path("src") / "runner.py"), "--scenario", spath],
            capture_output=True, text=True, cwd=root, timeout=timeout)
        return json.loads(out.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return None
    finally:
        Path(spath).unlink(missing_ok=True)


def run_coverage_probes(run_dir: str | Path, timeout: float = 60.0) -> dict:
    """probe spec의 각 probe를 artifact temp copy에서 실행하고 결과를 기록한다.

    runner scenario 실행 + 결정론적 check 평가만 있다 — 사람 설명이나 과거 기록은
    evidence가 되지 못한다 (§9.1)."""
    run_dir = Path(run_dir)
    spec = _load_json(run_dir / COVERAGE_SUBDIR / PROBE_SPEC_NAME)
    result: dict = {"ok": False, "probes": {}, "problems": [],
                    "produced_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    root = resolve_artifact_root(run_dir)
    if spec is None or root is None:
        result["problems"].append("coverage_probe_spec.json 또는 artifact root 없음")
        return result
    result["artifact_fingerprint"] = artifact_fingerprint(Path(root))
    tmp = Path(tempfile.mkdtemp(prefix="coverage_probe_"))
    try:
        copy_root = tmp / "artifact"
        shutil.copytree(root, copy_root)
        for probe in spec.get("probes") or []:
            pid = str(probe.get("probe_id"))
            output = None
            if probe.get("actions") is not None:
                output = _run_scenario(copy_root, probe.get("initial_state") or {},
                                       probe["actions"], timeout)
                if output is None:
                    result["probes"][pid] = {"pass": False, "checks": [],
                                             "problem": "runner 실행/파싱 실패"}
                    continue
            checks = [_eval_check(c, output, copy_root) for c in probe.get("checks") or []]
            result["probes"][pid] = {
                "title": probe.get("title"),
                "pass": bool(checks) and all(c["pass"] for c in checks),
                "checks": checks,
                "runner_output_digest": hashlib.sha256(
                    json.dumps(output, sort_keys=True, ensure_ascii=True).encode()
                ).hexdigest() if output is not None else None,
            }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    result["ok"] = bool(result["probes"]) \
        and all(p.get("checks") for p in result["probes"].values())
    _write_json(run_dir / COVERAGE_SUBDIR / PROBE_RESULTS_NAME, result)
    return result


# ---------------------------------------------------------------- coverage matrix (§6.2)

_ROW_REQUIRED_FIELDS = (
    "requirement_id", "requirement_kind", "requirement_text_or_ref",
    "coverage_status", "failure_class", "reason_code", "recommended_action",
)


def _validate_rows(rows: list, normalized: dict, probe_results: dict,
                   current_fingerprint: str | None) -> list[str]:
    problems: list[str] = []
    seen_ids: set[str] = set()
    seen_text: set[str] = set()
    probes = (probe_results or {}).get("probes") or {}
    stored_fp = (probe_results or {}).get("artifact_fingerprint")
    if current_fingerprint and stored_fp and stored_fp != current_fingerprint:
        problems.append("probe evidence가 현재 artifact와 불일치 (과거/타 run 복사 의심)")
    for row in rows:
        rid = str(row.get("requirement_id"))
        for field in _ROW_REQUIRED_FIELDS:
            if row.get(field) in (None, ""):
                problems.append(f"{rid}: 필수 필드 {field} 없음")
        if rid in seen_ids:
            problems.append(f"중복 requirement_id: {rid}")
        seen_ids.add(rid)
        seen_text.add(str(row.get("requirement_text_or_ref")))
        if row.get("requirement_kind") not in REQUIREMENT_KINDS:
            problems.append(f"{rid}: 알 수 없는 requirement_kind {row.get('requirement_kind')!r}")
        if row.get("coverage_status") not in COVERAGE_STATUSES:
            problems.append(f"{rid}: 알 수 없는 coverage_status {row.get('coverage_status')!r}")
        if row.get("failure_class") not in FAILURE_CLASSES:
            problems.append(f"{rid}: 분류 불가 failure_class {row.get('failure_class')!r} — "
                            "unknown 분류는 거부한다")
        status = row.get("coverage_status")
        if status == "COVERED" and row.get("failure_class") != "NONE":
            problems.append(f"{rid}: COVERED인데 failure_class={row.get('failure_class')}")
        if status in ("PARTIALLY_COVERED", "NOT_COVERED") \
                and row.get("failure_class") == "NONE":
            problems.append(f"{rid}: {status}인데 failure_class=NONE — 원인 미분류 FAIL 금지")
        # 실증 요구: 충족 주장(COVERED)과 부분 충족은 PASS probe evidence가 필수
        if status in ("COVERED", "PARTIALLY_COVERED"):
            refs = row.get("runtime_evidence_refs") or []
            if not refs:
                problems.append(f"{rid}: {status} 판정에 runtime_evidence_refs 없음")
            for ref in refs:
                probe = probes.get(str(ref))
                if probe is None:
                    problems.append(f"{rid}: probe {ref!r} 결과 없음")
                elif status == "COVERED" and not probe.get("pass"):
                    problems.append(f"{rid}: COVERED인데 probe {ref!r} FAIL")
    # 전수 대조 — 정본의 모든 항목이 matrix에 있어야 한다 (누락 은폐 금지)
    for kind_key, label in (("success_conditions", "critical requirement"),
                            ("difficulty_anchors", "difficulty anchor"),
                            ("forbidden_simplifications", "forbidden simplification")):
        for item in normalized.get(kind_key) or []:
            if str(item) not in seen_text:
                problems.append(f"정본 {label} 누락: {str(item)[:60]!r}")
    return problems


def _aggregate(rows: list) -> dict:
    def _cov(kind: str) -> dict:
        sel = [r for r in rows if r.get("requirement_kind") == kind
               and not r.get("forbidden_simplification")]
        covered = sum(1 for r in sel if r.get("coverage_status") == "COVERED")
        return {"total": len(sel), "covered": covered,
                "coverage": round(covered / len(sel), 4) if sel else 1.0}
    violations = [str(r.get("requirement_text_or_ref")) for r in rows
                  if r.get("forbidden_simplification")
                  and r.get("coverage_status") == "NOT_COVERED"]
    classes: dict = {}
    for r in rows:
        c = r.get("failure_class")
        if c and c != "NONE":
            classes[c] = classes.get(c, 0) + 1
    return {"critical": _cov("CRITICAL_REQUIREMENT"),
            "difficulty_anchor": _cov("DIFFICULTY_ANCHOR"),
            "forbidden_violations": sorted(violations),
            "failure_class_counts": classes}


def build_coverage_matrix(run_dir: str | Path) -> dict:
    """adjudication rows + probe 결과 + 정본을 대조해 coverage matrix를 만든다.

    검증 실패가 하나라도 있으면 matrix를 쓰지 않는다 — 부분적으로 맞는 matrix가
    coverage 판정에 흘러들어 과대평가되는 것을 차단한다."""
    run_dir = Path(run_dir)
    adjudication = _load_json(run_dir / COVERAGE_SUBDIR / ADJUDICATION_NAME) or {}
    normalized = _load_json(run_dir / "normalized_challenge.json") or {}
    probe_results = _load_json(run_dir / COVERAGE_SUBDIR / PROBE_RESULTS_NAME) or {}
    rows = list(adjudication.get("rows") or [])
    root = resolve_artifact_root(run_dir)
    fp = artifact_fingerprint(Path(root)) if root else None
    problems = _validate_rows(rows, normalized, probe_results, fp)
    result = {"ok": not problems, "problems": problems, "row_count": len(rows)}
    if problems:
        return result
    matrix = {
        "rows": sorted(rows, key=lambda r: str(r.get("requirement_id"))),
        "aggregates": _aggregate(rows),
        "artifact_fingerprint": fp,
        "probe_results_ref": f"{COVERAGE_SUBDIR}/{PROBE_RESULTS_NAME}",
        "produced_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "produced_by": "factory_coverage",
    }
    _write_json(run_dir / COVERAGE_SUBDIR / MATRIX_NAME, matrix)
    result["matrix"] = matrix
    return result


def validate_coverage_artifacts(run_dir: str | Path) -> list[str]:
    """저장된 matrix를 재검증한다 (validator용). matrix가 없으면 빈 목록 (있으면-검사)."""
    run_dir = Path(run_dir)
    matrix = _load_json(run_dir / COVERAGE_SUBDIR / MATRIX_NAME)
    if matrix is None:
        return []
    normalized = _load_json(run_dir / "normalized_challenge.json") or {}
    probe_results = _load_json(run_dir / COVERAGE_SUBDIR / PROBE_RESULTS_NAME) or {}
    root = resolve_artifact_root(run_dir)
    fp = artifact_fingerprint(Path(root)) if root else None
    rows = list(matrix.get("rows") or [])
    problems = _validate_rows(rows, normalized, probe_results, fp)
    if matrix.get("artifact_fingerprint") != fp:
        problems.append("coverage matrix fingerprint가 현재 artifact와 다름")
    expected = _aggregate(rows)
    if matrix.get("aggregates") != expected:
        problems.append("coverage matrix aggregates가 row와 불일치 (결정론 집계 위반)")
    return [f"coverage_matrix: {p}" for p in problems]


# ---------------------------------------------------------------- 판정 소비 (§9.1 evidence 연결)

_STATUS_TO_JUDGE = {
    # 과대평가 금지: PARTIALLY/AMBIGUOUS/NOT_APPLICABLE은 절대 implemented로 매핑하지 않는다
    "COVERED": "implemented",
    "PARTIALLY_COVERED": "missing",
    "NOT_COVERED": "missing",
    "AMBIGUOUS": "unknown",
    "NOT_APPLICABLE": "unknown",
}


def load_matrix_judge_coverage(run_dir: str | Path) -> dict | None:
    """유효한 fresh coverage matrix가 있으면 judge_coverage 형태로 변환한다.

    없으면 None(기존 desk 경로 유지). 검증 실패한 matrix는 무시하고 problems만 돌려준다 —
    잘못된 matrix가 조용히 coverage를 올리는 일은 없다."""
    run_dir = Path(run_dir)
    if not (run_dir / COVERAGE_SUBDIR / MATRIX_NAME).is_file():
        return None
    problems = validate_coverage_artifacts(run_dir)
    if problems:
        return {"judge_coverage": {}, "problems": problems, "valid": False}
    matrix = _load_json(run_dir / COVERAGE_SUBDIR / MATRIX_NAME) or {}
    judged: dict = {}
    for row in matrix.get("rows") or []:
        status = _STATUS_TO_JUDGE.get(str(row.get("coverage_status")), "unknown")
        if row.get("forbidden_simplification"):
            status = "respected" if row.get("coverage_status") == "COVERED" \
                else ("violated" if row.get("coverage_status") == "NOT_COVERED" else "unknown")
        judged[str(row.get("requirement_text_or_ref"))] = {
            "status": status,
            "evidence_refs": [f"{COVERAGE_SUBDIR}/{PROBE_RESULTS_NAME}#" + str(r)
                              for r in (row.get("runtime_evidence_refs") or [])],
            "reason": f"coverage matrix {row.get('requirement_id')} "
                      f"({row.get('reason_code')})",
        }
    return {"judge_coverage": judged, "problems": [], "valid": True}
