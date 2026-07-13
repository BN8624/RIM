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
MATRIX_META_NAME = "coverage_matrix_meta.json"

# 이슈 #25: matrix/adjudication 계약 버전 — 규칙이 바뀌면 올리고, 다르면 재사용 금지 (§5.3)
MATRIX_SCHEMA_VERSION = 2
ADJUDICATION_RULE_VERSION = 1
FINGERPRINT_VERSION = 2

# 이슈 #25 §4.6: requirement adjudication 경계 — SEMANTIC_ADJUDICATION만 LLM 후보
ADJUDICATION_MODES = (
    "DETERMINISTIC_RUNTIME",
    "DETERMINISTIC_STATIC",
    "DETERMINISTIC_CONTRACT",
    "SEMANTIC_ADJUDICATION",
    "INVALID_REQUIREMENT",
)
_CLASSIFICATION_TO_MODE = {
    "DETERMINISTIC_RUNTIME": "DETERMINISTIC_RUNTIME",
    "DETERMINISTIC_STATIC": "DETERMINISTIC_STATIC",
    "DETERMINISTIC_CONTRACT": "DETERMINISTIC_CONTRACT",
    "SEMANTIC_ADJUDICATION_REQUIRED": "SEMANTIC_ADJUDICATION",
    "INVALID_OR_AMBIGUOUS_REQUIREMENT": "INVALID_REQUIREMENT",
}

# 이슈 #25 §5.8: coverage 실패 분류 — transient 인프라 결함과 제품 결함을 구분한다
COVERAGE_MATRIX_GENERATION_FAILED = "COVERAGE_MATRIX_GENERATION_FAILED"
COVERAGE_PROBE_FAILED = "COVERAGE_PROBE_FAILED"
COVERAGE_MATRIX_INVALID = "COVERAGE_MATRIX_INVALID"
COVERAGE_STALE_REBUILD_FAILED = "COVERAGE_STALE_REBUILD_FAILED"
COVERAGE_SEMANTIC_ADJUDICATION_REQUIRED = "COVERAGE_SEMANTIC_ADJUDICATION_REQUIRED"
COVERAGE_SEMANTIC_INFRA_FAIL = "COVERAGE_SEMANTIC_INFRA_FAIL"
COVERAGE_REQUIREMENT_INVALID = "COVERAGE_REQUIREMENT_INVALID"

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


def artifact_fingerprint(artifact_root: Path, version: int = FINGERPRINT_VERSION) -> str:
    """probe evidence가 '이 구현'에 대한 것임을 고정한다 — 다른 run에서 복사한 과거
    evidence는 fingerprint 불일치로 거부된다 (§17.3 과거 evidence 복사 거부).

    v2(이슈 #25)는 product/ surface도 포함한다 — viewer/UX lane 수정이 fingerprint를
    바꿔 stale matrix 재사용을 차단한다. v1은 기존 matrix 재검증 호환용으로만 남긴다."""
    artifact_root = Path(artifact_root)
    h = hashlib.sha256()
    files = sorted(artifact_root.glob("src/**/*.py")) + [artifact_root / "runner_contract.json"]
    if version >= 2:
        files += sorted(p for p in artifact_root.glob("product/**/*") if p.is_file())
    for f in files:
        if f.is_file():
            h.update(f.relative_to(artifact_root).as_posix().encode("utf-8"))
            h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def _canonical_digest(data) -> str:
    return hashlib.sha256(
        json.dumps(data, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()


def normalized_challenge_digest(normalized: dict) -> str:
    """requirement 정본(성공 조건/anchor/금지 단순화)의 canonical digest (이슈 #25 §5.4).

    목록 순서는 challenge 계약이므로 보존한다. digest가 다르면 기존 coverage artifact는
    전부 stale이다 — artifact fingerprint만으로는 challenge 변경을 감지하지 못한다."""
    return _canonical_digest({
        "success_conditions": [str(x) for x in normalized.get("success_conditions") or []],
        "difficulty_anchors": [str(x) for x in normalized.get("difficulty_anchors") or []],
        "forbidden_simplifications":
            [str(x) for x in normalized.get("forbidden_simplifications") or []],
    })


def probe_spec_digest(spec: dict) -> str:
    """probe spec의 의미 digest — 비본질 metadata(produced_*)는 제외한다."""
    return _canonical_digest({k: v for k, v in (spec or {}).items()
                              if not str(k).startswith("produced_")})


def probe_results_semantic_digest(results: dict) -> str:
    """probe 결과의 의미 digest — produced_at 같은 시각 metadata는 제외한다 (§4.2)."""
    return _canonical_digest({
        "probes": (results or {}).get("probes") or {},
        "artifact_fingerprint": (results or {}).get("artifact_fingerprint"),
        "challenge_digest": (results or {}).get("challenge_digest"),
    })


def matrix_semantic_digest(matrix: dict) -> str:
    """matrix의 의미 digest — canonical matrix 파일에는 시각 metadata가 없으므로 전체가 정본."""
    return _canonical_digest(matrix or {})


_REQUIREMENT_SECTIONS = (
    ("success_conditions", "SC", "CRITICAL_REQUIREMENT", False),
    ("difficulty_anchors", "DA", "DIFFICULTY_ANCHOR", False),
    ("forbidden_simplifications", "FS", "SUPPORTING_REQUIREMENT", True),
)


def enumerate_requirements(normalized: dict) -> list[dict]:
    """normalized challenge에서 requirement row 뼈대를 결정론적 ID/순서로 만든다."""
    entries: list[dict] = []
    for key, prefix, kind, forbidden in _REQUIREMENT_SECTIONS:
        for i, text in enumerate(normalized.get(key) or [], start=1):
            entry = {"requirement_id": f"{prefix}{i}", "requirement_kind": kind,
                     "requirement_text_or_ref": str(text)}
            if forbidden:
                entry["forbidden_simplification"] = True
            entries.append(entry)
    return entries


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
    result["fingerprint_version"] = FINGERPRINT_VERSION
    result["probe_spec_digest"] = probe_spec_digest(spec)
    normalized = _load_json(run_dir / "normalized_challenge.json")
    if normalized is not None:
        result["challenge_digest"] = normalized_challenge_digest(normalized)
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
    # probe 0개(전 requirement semantic)는 실행할 것이 없는 정상 상태다 — check 없는 probe만 결함
    result["ok"] = all(p.get("checks") for p in result["probes"].values())
    _write_json(run_dir / COVERAGE_SUBDIR / PROBE_RESULTS_NAME, result)
    return result


# ---------------------------------------------------------------- coverage matrix (§6.2)

_ROW_REQUIRED_FIELDS = (
    "requirement_id", "requirement_kind", "requirement_text_or_ref",
    "coverage_status", "failure_class", "reason_code", "recommended_action",
)


def _validate_rows(rows: list, normalized: dict, probe_results: dict,
                   current_fingerprint: str | None, run_dir: Path | None = None) -> list[str]:
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
        mode = row.get("adjudication_mode")
        if mode is not None and mode not in ADJUDICATION_MODES:
            problems.append(f"{rid}: 알 수 없는 adjudication_mode {mode!r}")
        status = row.get("coverage_status")
        if status == "COVERED" and row.get("failure_class") != "NONE":
            problems.append(f"{rid}: COVERED인데 failure_class={row.get('failure_class')}")
        if status in ("PARTIALLY_COVERED", "NOT_COVERED") \
                and row.get("failure_class") == "NONE":
            problems.append(f"{rid}: {status}인데 failure_class=NONE — 원인 미분류 FAIL 금지")
        # 실증 요구: 충족 주장(COVERED)과 부분 충족은 실제 evidence가 필수.
        # semantic row(이슈 #25 §5.7)는 존재하는 static/contract evidence ref로 실증하고,
        # 그 외(deterministic·legacy)는 기존과 동일하게 PASS probe evidence가 필수다.
        if status in ("COVERED", "PARTIALLY_COVERED"):
            refs = row.get("runtime_evidence_refs") or []
            if mode == "SEMANTIC_ADJUDICATION" and not refs:
                srefs = [str(r) for r in (row.get("static_evidence_refs") or [])
                         + (row.get("contract_evidence_refs") or [])]
                if not srefs:
                    problems.append(f"{rid}: {status} semantic 판정에 evidence ref 없음")
                for ref in srefs:
                    if run_dir is None:
                        continue
                    if ".." in ref or Path(ref).is_absolute() \
                            or not (Path(run_dir) / ref).is_file():
                        problems.append(f"{rid}: evidence ref {ref!r}가 존재하지 않음")
            else:
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
    spec = _load_json(run_dir / COVERAGE_SUBDIR / PROBE_SPEC_NAME)
    rows = list(adjudication.get("rows") or [])
    root = resolve_artifact_root(run_dir)
    fp = artifact_fingerprint(Path(root)) if root else None
    problems = _validate_rows(rows, normalized, probe_results, fp, run_dir)
    result = {"ok": not problems, "problems": problems, "row_count": len(rows)}
    if problems:
        return result
    # canonical matrix에는 시각/경로 metadata를 넣지 않는다 — 동일 입력이면 byte-identical (§4.2)
    matrix = {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "adjudication_rule_version": ADJUDICATION_RULE_VERSION,
        "rows": sorted(rows, key=lambda r: str(r.get("requirement_id"))),
        "aggregates": _aggregate(rows),
        "artifact_fingerprint": fp,
        "fingerprint_version": FINGERPRINT_VERSION,
        "challenge_digest": normalized_challenge_digest(normalized),
        "probe_spec_digest": probe_spec_digest(spec) if spec is not None else None,
        "probe_results_digest": probe_results_semantic_digest(probe_results)
        if probe_results else None,
        "semantic_adjudication_state": adjudication.get(
            "semantic_adjudication_state", "NONE_REQUIRED"),
        "probe_results_ref": f"{COVERAGE_SUBDIR}/{PROBE_RESULTS_NAME}",
        "produced_by": "factory_coverage",
    }
    _write_json(run_dir / COVERAGE_SUBDIR / MATRIX_NAME, matrix)
    _write_json(run_dir / COVERAGE_SUBDIR / MATRIX_META_NAME, {
        "produced_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "matrix_semantic_digest": matrix_semantic_digest(matrix),
    })
    result["matrix"] = matrix
    result["matrix_semantic_digest"] = matrix_semantic_digest(matrix)
    return result


def validate_coverage_artifacts(run_dir: str | Path) -> list[str]:
    """저장된 matrix를 재검증한다 (validator용). matrix가 없으면 빈 목록 (있으면-검사)."""
    run_dir = Path(run_dir)
    matrix = _load_json(run_dir / COVERAGE_SUBDIR / MATRIX_NAME)
    if matrix is None:
        return []
    normalized = _load_json(run_dir / "normalized_challenge.json") or {}
    probe_results = _load_json(run_dir / COVERAGE_SUBDIR / PROBE_RESULTS_NAME) or {}
    spec = _load_json(run_dir / COVERAGE_SUBDIR / PROBE_SPEC_NAME)
    root = resolve_artifact_root(run_dir)
    # 기존(v1) matrix는 v1 규칙으로 재검증한다 — 정본 run의 과거 matrix를 소급 파괴하지 않되,
    # 새 matrix(v2)는 product surface 변경도 stale로 잡는다 (이슈 #25).
    fpv = int(matrix.get("fingerprint_version") or 1)
    fp = artifact_fingerprint(Path(root), version=fpv) if root else None
    rows = list(matrix.get("rows") or [])
    problems = _validate_rows(rows, normalized, probe_results, fp, run_dir)
    if matrix.get("artifact_fingerprint") != fp:
        problems.append("coverage matrix fingerprint가 현재 artifact와 다름")
    if matrix.get("challenge_digest") is not None \
            and matrix["challenge_digest"] != normalized_challenge_digest(normalized):
        problems.append("coverage matrix challenge digest가 현재 normalized challenge와 다름")
    if matrix.get("probe_spec_digest") is not None and spec is not None \
            and matrix["probe_spec_digest"] != probe_spec_digest(spec):
        problems.append("coverage matrix가 현재 probe spec과 불일치 (spec 변경 후 미재생성)")
    if matrix.get("probe_results_digest") is not None and probe_results \
            and matrix["probe_results_digest"] != probe_results_semantic_digest(probe_results):
        problems.append("coverage matrix가 현재 probe result보다 오래됨 (재생성 필요)")
    expected = _aggregate(rows)
    if matrix.get("aggregates") != expected:
        problems.append("coverage matrix aggregates가 row와 불일치 (결정론 집계 위반)")
    return [f"coverage_matrix: {p}" for p in problems]


# ---------------------------------------------------------------- coverage automation (이슈 #25)

_DETERMINISTIC_MODES = ("DETERMINISTIC_RUNTIME", "DETERMINISTIC_STATIC",
                        "DETERMINISTIC_CONTRACT")
_FINAL_STATE_OPS = ("eq", "is_int", "exists", "absent")


def _bad_glob(pattern: str) -> bool:
    return ".." in pattern or Path(pattern).is_absolute() or pattern.startswith("\\")


def _validate_check(pid: str, check: dict) -> list[str]:
    kind = check.get("kind")
    if kind not in PROBE_CHECK_KINDS:
        return [f"probe {pid}: 허용 밖 check kind {kind!r}"]
    p: list[str] = []
    if kind == "final_state_path":
        if not str(check.get("path") or ""):
            p.append(f"probe {pid}: final_state_path에 path 없음")
        if check.get("op", "eq") not in _FINAL_STATE_OPS:
            p.append(f"probe {pid}: 허용 밖 op {check.get('op')!r}")
    elif kind == "queued_events":
        if not str(check.get("event_type") or ""):
            p.append(f"probe {pid}: queued_events에 event_type 없음")
    elif kind in ("distinct_paths", "ordered_paths"):
        paths = check.get("paths")
        if not isinstance(paths, list) or len(paths) < 2 \
                or not all(isinstance(x, str) and x for x in paths):
            p.append(f"probe {pid}: {kind}에 paths(2개 이상 문자열) 필요")
    elif kind == "errors":
        if check.get("expect") not in ("empty", "nonempty"):
            p.append(f"probe {pid}: errors check의 expect는 empty|nonempty")
    elif kind == "static_substring_count":
        if not str(check.get("needle") or ""):
            p.append(f"probe {pid}: static_substring_count에 needle 없음")
        if _bad_glob(str(check.get("glob", "product/**/*.html"))):
            p.append(f"probe {pid}: 허용 밖 glob {check.get('glob')!r}")
        if check.get("op", "gt0") not in ("gt0", "eq0"):
            p.append(f"probe {pid}: 허용 밖 op {check.get('op')!r}")
    return p


def _validate_spec_proposal(raw: dict, requirement_texts: set[str]) -> list[str]:
    """LLM probe spec 제안의 결정론적 재검증 (§5.5) — 하나라도 어기면 제안 전체를 거부한다."""
    problems: list[str] = []
    seen_ids: set[str] = set()
    probe_has_actions: dict[str, bool] = {}
    covers_by_text: dict[str, list[str]] = {}
    for probe in raw.get("probes") or []:
        pid = str(probe.get("probe_id"))
        if pid in seen_ids:
            problems.append(f"probe {pid}: 중복 probe_id")
        seen_ids.add(pid)
        checks = probe.get("checks") or []
        if not checks:
            problems.append(f"probe {pid}: check 0개 — PASS 불가 (§5.5)")
        for check in checks:
            if not isinstance(check, dict):
                problems.append(f"probe {pid}: check가 객체가 아님")
                continue
            problems += _validate_check(pid, check)
        actions = probe.get("actions")
        if actions is not None:
            if not isinstance(actions, list) or not all(
                    isinstance(a, dict) and str(a.get("type") or "") for a in actions):
                problems.append(f"probe {pid}: actions는 type 있는 객체 목록이어야 함")
        if not isinstance(probe.get("initial_state", {}), dict):
            problems.append(f"probe {pid}: initial_state는 객체여야 함")
        probe_has_actions[pid] = actions is not None
        for text in probe.get("covers") or []:
            if str(text) not in requirement_texts:
                problems.append(f"probe {pid}: covers가 정본 밖 requirement {str(text)[:40]!r}")
            covers_by_text.setdefault(str(text), []).append(pid)
    classified: dict[str, str] = {}
    for item in raw.get("requirements") or []:
        text = str(item.get("requirement"))
        mode = item.get("adjudication_mode")
        if text not in requirement_texts:
            problems.append(f"분류가 정본 밖 requirement {text[:40]!r}")
            continue
        if text in classified:
            problems.append(f"requirement 중복 분류: {text[:40]!r}")
        if mode not in _CLASSIFICATION_TO_MODE:
            problems.append(f"알 수 없는 adjudication 분류 {mode!r}")
            continue
        classified[text] = _CLASSIFICATION_TO_MODE[mode]
    for text in requirement_texts:
        if text not in classified:
            problems.append(f"requirement 분류 누락: {text[:40]!r}")
    for text, mode in classified.items():
        pids = covers_by_text.get(text) or []
        if mode in _DETERMINISTIC_MODES and not pids:
            problems.append(f"{mode} 분류인데 covering probe 없음: {text[:40]!r}")
        if mode == "DETERMINISTIC_RUNTIME" and pids \
                and not any(probe_has_actions.get(p) for p in pids):
            problems.append(f"DETERMINISTIC_RUNTIME인데 runner probe 없음: {text[:40]!r}")
    return problems


def _artifact_context_for_prompt(run_dir: Path) -> dict:
    root = resolve_artifact_root(run_dir)
    ctx: dict = {}
    for name in ("action_contract.json", "state_contract.json", "runner_contract.json"):
        data = _load_json(Path(root) / name)
        if data is not None:
            ctx[name] = data
    ctx["product_files"] = sorted(
        p.relative_to(root).as_posix() for p in Path(root).glob("product/**/*")
        if p.is_file())[:40]
    return ctx


def _build_probe_spec_prompt(run_dir: Path, entries: list[dict]) -> str:
    ctx = _artifact_context_for_prompt(run_dir)
    dsl = {
        "probe": {"probe_id": "고유 ID", "title": "설명",
                  "initial_state": "runner scenario initial_state (runner probe일 때)",
                  "actions": "[{type, payload}] — runner 실행 probe만. 정적 probe는 생략",
                  "checks": "아래 kind 중 1개 이상", "covers": ["판정하는 requirement 원문"]},
        "check_kinds": {
            "final_state_path": {"path": "a.b.c", "op": "eq|is_int|exists|absent", "value": "eq일 때"},
            "queued_events": {"event_type": "...", "expected_target_ids": "선택",
                              "forbidden_target_ids": "선택", "id_key": "선택(기본 target_id)"},
            "distinct_paths": {"paths": ["a.b", "c.d"]},
            "ordered_paths": {"paths": ["a.b", "c.d"]},
            "errors": {"expect": "empty|nonempty"},
            "static_substring_count": {"glob": "product/**/*.html", "needle": "...", "op": "gt0|eq0"},
        },
    }
    reqs = [{"requirement": e["requirement_text_or_ref"], "kind": e["requirement_kind"],
             "forbidden_simplification": bool(e.get("forbidden_simplification"))}
            for e in entries]
    return f"""너는 Product Factory의 Coverage Probe Spec 제안자다.
각 requirement를 결정론적 probe DSL로 판정할 probe를 제안하고, 전 requirement를 분류한다.

규칙:
- probe는 후보 제안일 뿐이다. 실제 실행 결과만 정본이며, 네 설명은 근거가 아니다.
- runner probe는 runner.py --scenario 계약을 따른다: 입력 {{initial_state, actions:[{{type,payload}}]}},
  출력 {{ok, final_state, events, errors}}. action type은 아래 계약의 action만 사용.
- DSL로 참·거짓을 기계 판정할 수 없는 requirement는 SEMANTIC_ADJUDICATION_REQUIRED로 분류하고 probe를 만들지 마라.
- 판정 가능한 형태가 아닌 requirement는 INVALID_OR_AMBIGUOUS_REQUIREMENT.
- forbidden simplification은 '그 단순화가 없음'을 증명하는 probe(정적 eq0 또는 runtime 거부)로 판정한다.
- 모든 requirement를 정확히 한 번씩 분류한다. 분류: DETERMINISTIC_RUNTIME | DETERMINISTIC_STATIC |
  DETERMINISTIC_CONTRACT | SEMANTIC_ADJUDICATION_REQUIRED | INVALID_OR_AMBIGUOUS_REQUIREMENT.
- DETERMINISTIC_* 분류는 covering probe 최소 1개 필수. check 0개 probe 금지. 낙관적 substring PASS 금지.

JSON만 출력. Schema: {{"probes": [...], "requirements": [{{"requirement": "...", "adjudication_mode": "...", "reason": "..."}}]}}

=== PROBE DSL ===
{json.dumps(dsl, ensure_ascii=False, indent=1)}

=== REQUIREMENTS ===
{json.dumps(reqs, ensure_ascii=False, indent=1)}

=== ARTIFACT CONTRACTS ===
{json.dumps(ctx, ensure_ascii=False, indent=1)[:6000]}
"""


def generate_probe_spec(run_dir: str | Path, *, executor=None) -> dict:
    """probe spec이 없거나 stale일 때 생성한다 (§5.5).

    executor가 있으면 LLM이 probe 후보를 제안하되 결정론적 재검증을 통과해야만 채택한다 —
    무효 제안은 전면 semantic 강등(fail-closed), transient 인프라 실패는 spec을 쓰지 않고
    infra로 보고한다 (약화된 spec을 transient 때문에 영속화하지 않는다)."""
    run_dir = Path(run_dir)
    normalized = _load_json(run_dir / "normalized_challenge.json") or {}
    entries = enumerate_requirements(normalized)
    out: dict = {"ok": True, "desk_called": False, "infra_failure": False,
                 "problems": [], "spec": None}
    if not entries:
        out["ok"] = False
        out["problems"].append("normalized challenge에 requirement 없음")
        return out
    by_text = {e["requirement_text_or_ref"]: e for e in entries}
    probes: list = []
    modes = {t: "SEMANTIC_ADJUDICATION" for t in by_text}
    refs: dict[str, list[str]] = {t: [] for t in by_text}
    if executor is not None:
        from repo_idea_miner.factory_autopilot_desks import execute_desk
        from repo_idea_miner.factory_autopilot_schemas import (
            AUTOPILOT_INFRA_FAIL,
            CoverageProbeSpecProposal,
        )
        res = execute_desk(executor, "coverage_probe_spec",
                           _build_probe_spec_prompt(run_dir, entries),
                           CoverageProbeSpecProposal)
        out["desk_called"] = True
        if res["status"] == "PASS":
            raw = res["raw"] or {}
            proposal_problems = _validate_spec_proposal(raw, set(by_text))
            if proposal_problems:
                out["problems"] += [f"probe spec 제안 거부 → semantic 강등: {p}"
                                    for p in proposal_problems[:10]]
            else:
                probes = list(raw.get("probes") or [])
                for item in raw.get("requirements") or []:
                    modes[str(item["requirement"])] = \
                        _CLASSIFICATION_TO_MODE[item["adjudication_mode"]]
                for probe in probes:
                    for text in probe.get("covers") or []:
                        refs[str(text)].append(str(probe.get("probe_id")))
        elif res.get("failure_type") == AUTOPILOT_INFRA_FAIL:
            out["ok"] = False
            out["infra_failure"] = True
            out["problems"] += list(res.get("problems") or [])
            return out
        else:
            out["problems"] += [f"probe spec 제안 무효 → semantic 강등: {p}"
                                for p in (res.get("problems") or [])[:10]]
    spec = {
        "schema_version": 2,
        "challenge_digest": normalized_challenge_digest(normalized),
        "probes": probes,
        "requirements": [
            {**e, "adjudication_mode": modes[e["requirement_text_or_ref"]],
             "probe_refs": sorted(set(refs[e["requirement_text_or_ref"]]))}
            for e in entries
        ],
        "produced_by": "factory_coverage_automation",
    }
    _write_json(run_dir / COVERAGE_SUBDIR / PROBE_SPEC_NAME, spec)
    out["spec"] = spec
    return out


def _semantic_evidence_catalog(run_dir: Path) -> list[str]:
    """semantic adjudication이 인용할 수 있는 실존 파일 카탈로그 (run 상대 경로)."""
    run_dir = Path(run_dir)
    root = resolve_artifact_root(run_dir)
    rel_root = Path(root).name
    catalog: list[str] = []
    for pattern in ("product/**/*", "src/**/*.py"):
        for p in sorted(Path(root).glob(pattern)):
            if p.is_file():
                catalog.append(f"{rel_root}/{p.relative_to(root).as_posix()}")
    for name in ("runner_contract.json", "core_contract.json", "state_contract.json",
                 "action_contract.json"):
        if (Path(root) / name).is_file():
            catalog.append(f"{rel_root}/{name}")
    for p in sorted(run_dir.glob("review/*/*.json")):
        catalog.append(p.relative_to(run_dir).as_posix())
    return catalog[:120]


def _build_semantic_prompt(semantic_entries: list[dict], catalog: list[str]) -> str:
    reqs = [{"requirement": e["requirement_text_or_ref"], "kind": e["requirement_kind"],
             "forbidden_simplification": bool(e.get("forbidden_simplification"))}
            for e in semantic_entries]
    return f"""너는 Product Factory의 Semantic Coverage Adjudicator다.
결정론적 probe로 판정 불가한 requirement만 아래 evidence 카탈로그의 실존 파일 근거로 판정한다.

규칙:
- coverage_status: COVERED | PARTIALLY_COVERED | NOT_COVERED | AMBIGUOUS | NOT_APPLICABLE.
- failure_class: TRUE_CORE_GAP | EVIDENCE_GAP | VALIDATOR_DEFECT | SPEC_OVERREACH | NONE.
- COVERED/PARTIALLY_COVERED는 카탈로그의 evidence_refs 최소 1개 필수. COVERED는 failure_class=NONE.
- 근거 없는 낙관 판정 금지 — 불확실하면 AMBIGUOUS. 카탈로그 밖 ref를 만들지 마라.
- reason_code는 짧은 대문자 코드.

JSON만 출력. Schema: {{"items": [{{"requirement": "...", "coverage_status": "...", "failure_class": "...", "reason_code": "...", "evidence_refs": ["..."]}}]}}

=== SEMANTIC REQUIREMENTS ===
{json.dumps(reqs, ensure_ascii=False, indent=1)}

=== EVIDENCE CATALOG ===
{json.dumps(catalog, ensure_ascii=False, indent=1)}
"""


def _ambiguous_row(reason_code: str) -> dict:
    return {"coverage_status": "AMBIGUOUS", "failure_class": "EVIDENCE_GAP",
            "reason_code": reason_code, "recommended_action": "SEMANTIC_REVIEW",
            "runtime_evidence_refs": [], "static_evidence_refs": [],
            "contract_evidence_refs": []}


def _adjudicate_semantic_rows(run_dir: Path, semantic_entries: list[dict],
                              executor) -> dict:
    """semantic requirement만 제한적으로 LLM adjudication 한다 (§5.7).

    transient 인프라 실패는 NOT_COVERED로 바꾸지 않고 infra로 보고한다 (§6.12).
    무효 판정(카탈로그 밖 ref, enum 밖 값, 근거 없는 COVERED)은 AMBIGUOUS로 강등한다 —
    위로 승격되는 강등은 없다."""
    out: dict = {"ok": True, "rows_by_text": {}, "infra_failure": False,
                 "desk_called": False, "problems": [], "state": "NOT_ATTEMPTED"}
    if not semantic_entries:
        out["state"] = "NONE_REQUIRED"
        return out
    if executor is None:
        return out
    from repo_idea_miner.factory_autopilot_desks import execute_desk
    from repo_idea_miner.factory_autopilot_schemas import (
        AUTOPILOT_INFRA_FAIL,
        SemanticCoverageAdjudication,
    )
    catalog = _semantic_evidence_catalog(run_dir)
    res = execute_desk(executor, "coverage_semantic_adjudication",
                       _build_semantic_prompt(semantic_entries, catalog),
                       SemanticCoverageAdjudication)
    out["desk_called"] = True
    if res["status"] != "PASS":
        if res.get("failure_type") == AUTOPILOT_INFRA_FAIL:
            out["ok"] = False
            out["infra_failure"] = True
            out["problems"] += list(res.get("problems") or [])
        else:
            out["state"] = "ADJUDICATION_INVALID"
            out["problems"] += [f"semantic adjudication 무효 → AMBIGUOUS 강등: {p}"
                                for p in (res.get("problems") or [])[:10]]
        return out
    catalog_set = set(catalog)
    items = {str(i.get("requirement")): i for i in (res["raw"] or {}).get("items") or []}
    for entry in semantic_entries:
        text = entry["requirement_text_or_ref"]
        item = items.get(text)
        if item is None:
            out["problems"].append(f"semantic 판정 누락 → AMBIGUOUS: {text[:40]!r}")
            continue
        status = item.get("coverage_status")
        fclass = item.get("failure_class")
        refs = [str(r) for r in item.get("evidence_refs") or []]
        valid_refs = [r for r in refs
                      if r in catalog_set and (run_dir / r).is_file()]
        row = {"coverage_status": status, "failure_class": fclass,
               "reason_code": str(item.get("reason_code") or "SEMANTIC_JUDGED"),
               "recommended_action": "없음" if status == "COVERED" else "SEMANTIC_REVIEW",
               "runtime_evidence_refs": [], "static_evidence_refs": valid_refs,
               "contract_evidence_refs": []}
        demote = None
        if status not in COVERAGE_STATUSES or fclass not in FAILURE_CLASSES:
            demote = "enum 밖 판정"
        elif status in ("COVERED", "PARTIALLY_COVERED") and not valid_refs:
            demote = "실존 evidence ref 없는 충족 주장"
        elif status == "COVERED" and fclass != "NONE":
            demote = "COVERED인데 failure_class!=NONE"
        elif status in ("PARTIALLY_COVERED", "NOT_COVERED") and fclass == "NONE":
            demote = "원인 미분류 FAIL"
        if demote:
            out["problems"].append(f"semantic 판정 강등({demote}): {text[:40]!r}")
            row = _ambiguous_row("SEMANTIC_JUDGMENT_REJECTED")
        out["rows_by_text"][text] = row
    out["state"] = "ADJUDICATED"
    return out


def _build_adjudication_rows(spec: dict, probe_results: dict,
                             semantic_rows_by_text: dict) -> tuple[list[dict], list[str]]:
    """spec의 requirement 분류 + fresh probe 결과에서 adjudication row를 결정론적으로 만든다."""
    probes = (probe_results or {}).get("probes") or {}
    rows: list[dict] = []
    problems: list[str] = []
    for req in spec.get("requirements") or []:
        text = str(req.get("requirement_text_or_ref"))
        mode = req.get("adjudication_mode")
        row = {"requirement_id": req.get("requirement_id"),
               "requirement_kind": req.get("requirement_kind"),
               "requirement_text_or_ref": text,
               "adjudication_mode": mode}
        if req.get("forbidden_simplification"):
            row["forbidden_simplification"] = True
        if mode in _DETERMINISTIC_MODES:
            refs = [str(r) for r in req.get("probe_refs") or []]
            results = [probes.get(r) for r in refs]
            if not refs or any(r is None for r in results):
                problems.append(f"{row['requirement_id']}: probe 결과 없음 — 재실행 필요")
                row.update(_ambiguous_row("PROBE_RESULT_MISSING"))
            elif all(r.get("pass") and r.get("checks") for r in results):
                row.update(coverage_status="COVERED", failure_class="NONE",
                           reason_code="PROBE_PROVEN", recommended_action="없음",
                           runtime_evidence_refs=refs)
            else:
                row.update(coverage_status="NOT_COVERED", failure_class="TRUE_CORE_GAP",
                           reason_code="PROBE_FAILED", recommended_action="REPAIR_REQUIRED",
                           runtime_evidence_refs=[], probe_refs=refs)
        elif mode == "SEMANTIC_ADJUDICATION":
            row.update(semantic_rows_by_text.get(text)
                       or _ambiguous_row("SEMANTIC_ADJUDICATION_NOT_ATTEMPTED"))
        elif mode == "INVALID_REQUIREMENT":
            row.update(coverage_status="AMBIGUOUS", failure_class="SPEC_OVERREACH",
                       reason_code="INVALID_OR_AMBIGUOUS_REQUIREMENT",
                       recommended_action="SPEC_REVIEW",
                       runtime_evidence_refs=[])
        else:
            problems.append(f"{row['requirement_id']}: 알 수 없는 adjudication_mode {mode!r}")
            row.update(_ambiguous_row("UNKNOWN_MODE"))
        rows.append(row)
    return rows, problems


def _matrix_reuse_problems(run_dir: Path, matrix: dict, fp: str, cdig: str,
                           executor) -> list[str]:
    """기존 matrix 재사용 조건 (§5.3) — 전부 일치할 때만 재사용한다."""
    problems = list(validate_coverage_artifacts(run_dir))
    if matrix.get("schema_version") != MATRIX_SCHEMA_VERSION:
        problems.append("matrix schema_version 불일치 (legacy matrix — 재생성)")
    if matrix.get("adjudication_rule_version") != ADJUDICATION_RULE_VERSION:
        problems.append("adjudication rule version 불일치")
    if matrix.get("artifact_fingerprint") != fp:
        problems.append("artifact fingerprint 불일치")
    if matrix.get("challenge_digest") != cdig:
        problems.append("challenge digest 불일치")
    if executor is not None \
            and matrix.get("semantic_adjudication_state") == "NOT_ATTEMPTED":
        problems.append("semantic rows 미판정 상태 — executor로 승급 재생성")
    return problems


def ensure_deterministic_coverage_matrix(
    run_dir: str | Path,
    *,
    executor=None,
    timeout: float = 60.0,
    force_rebuild: bool = False,
) -> dict:
    """closed loop가 호출하는 coverage 정본 자동화 진입점 (이슈 #25 §5.1).

    유효·fresh matrix는 재사용하고, 없거나 stale이면 spec 확보→probe 실행→adjudication→
    matrix 생성→재검증까지 수행한다. 'matrix 없음'은 LLM fallback 사유가 아니라 생성
    사유다 (§4.5). transient 인프라 실패는 절대 NOT_COVERED로 변환하지 않는다."""
    run_dir = Path(run_dir)
    result: dict = {
        "status": "FAILED", "action": "NONE", "artifact_fingerprint": None,
        "challenge_digest": None, "matrix_path": f"{COVERAGE_SUBDIR}/{MATRIX_NAME}",
        "matrix_semantic_digest": None, "deterministic_row_count": 0,
        "semantic_row_count": 0, "validation_problems": [], "problems": [],
        "fallback_allowed": False, "failure_type": None, "infra_failure": False,
        "desk_calls": {"probe_spec": 0, "semantic": 0},
        "invalid_requirement_count": 0,
    }
    normalized = _load_json(run_dir / "normalized_challenge.json")
    entries = enumerate_requirements(normalized or {})
    if not entries:
        result["status"] = "SKIPPED"
        result["problems"].append("normalized challenge requirement 없음")
        return result
    root = resolve_artifact_root(run_dir)
    if root is None or not Path(root).is_dir():
        # 구조적 불가 — probe를 실행할 artifact 자체가 없다. 이때만 desk fallback 허용.
        result["failure_type"] = COVERAGE_MATRIX_GENERATION_FAILED
        result["fallback_allowed"] = True
        result["problems"].append("artifact root 없음 — deterministic probe 구조적 불가")
        return result
    fp = artifact_fingerprint(Path(root))
    cdig = normalized_challenge_digest(normalized)
    result["artifact_fingerprint"] = fp
    result["challenge_digest"] = cdig

    matrix = _load_json(run_dir / COVERAGE_SUBDIR / MATRIX_NAME)
    stale_rebuild = False
    if matrix is not None:
        reuse_problems = _matrix_reuse_problems(run_dir, matrix, fp, cdig, executor)
        if not force_rebuild and not reuse_problems:
            result.update(status="OK", action="REUSED",
                          matrix_semantic_digest=matrix_semantic_digest(matrix))
            rows = matrix.get("rows") or []
            result["deterministic_row_count"] = sum(
                1 for r in rows if r.get("adjudication_mode") in _DETERMINISTIC_MODES)
            result["semantic_row_count"] = sum(
                1 for r in rows if r.get("adjudication_mode") == "SEMANTIC_ADJUDICATION")
            return result
        stale_rebuild = True
        result["problems"] += [f"기존 matrix 재사용 불가: {p}" for p in reuse_problems[:8]]

    # ---- spec 확보 (없음/stale → 생성. 있음 → 재사용)
    spec = _load_json(run_dir / COVERAGE_SUBDIR / PROBE_SPEC_NAME)
    spec_texts = {str(r.get("requirement_text_or_ref"))
                  for r in (spec or {}).get("requirements") or []}
    spec_stale = spec is not None and (
        (spec.get("challenge_digest") not in (None, cdig))
        or (spec_texts and spec_texts != {e["requirement_text_or_ref"] for e in entries}))
    if spec is None or spec_stale or force_rebuild:
        gen = generate_probe_spec(run_dir, executor=executor)
        result["desk_calls"]["probe_spec"] += 1 if gen["desk_called"] else 0
        result["problems"] += gen["problems"]
        if not gen["ok"]:
            result["failure_type"] = COVERAGE_STALE_REBUILD_FAILED if stale_rebuild \
                else COVERAGE_MATRIX_GENERATION_FAILED
            result["infra_failure"] = gen["infra_failure"]
            return result
        spec = gen["spec"]

    # ---- fresh probe 실행 (재사용이 아닌 모든 경로에서 재실행 — 과거 결과 소비 금지)
    probe_results = run_coverage_probes(run_dir, timeout=timeout)
    if probe_results.get("problems") or not probe_results.get("ok"):
        result["failure_type"] = COVERAGE_PROBE_FAILED
        result["problems"] += list(probe_results.get("problems") or [])
        result["problems"] += [f"probe {pid}: {p.get('problem')}" for pid, p in
                               (probe_results.get("probes") or {}).items()
                               if p.get("problem")]
        return result

    # ---- adjudication (deterministic rows + 제한적 semantic fallback)
    if spec.get("requirements"):
        semantic_entries = [r for r in spec["requirements"]
                            if r.get("adjudication_mode") == "SEMANTIC_ADJUDICATION"]
        sem = _adjudicate_semantic_rows(run_dir, semantic_entries, executor)
        result["desk_calls"]["semantic"] += 1 if sem["desk_called"] else 0
        result["problems"] += sem["problems"]
        if not sem["ok"]:
            result["failure_type"] = COVERAGE_SEMANTIC_INFRA_FAIL
            result["infra_failure"] = sem["infra_failure"]
            return result
        rows, adj_problems = _build_adjudication_rows(spec, probe_results,
                                                      sem["rows_by_text"])
        result["problems"] += adj_problems
        _write_json(run_dir / COVERAGE_SUBDIR / ADJUDICATION_NAME, {
            "produced_by": "factory_coverage_automation",
            "rule_version": ADJUDICATION_RULE_VERSION,
            "challenge_digest": cdig,
            "semantic_adjudication_state": sem["state"],
            "rows": rows,
        })
    # spec에 requirement 분류가 없는 legacy run은 기존 adjudication을 그대로 재검증한다

    # ---- matrix 생성 + 재검증 (fail-closed)
    build = build_coverage_matrix(run_dir)
    if not build.get("ok"):
        result["failure_type"] = COVERAGE_MATRIX_INVALID
        result["validation_problems"] = list(build.get("problems") or [])
        return result
    leftover = validate_coverage_artifacts(run_dir)
    if leftover:
        result["failure_type"] = COVERAGE_MATRIX_INVALID
        result["validation_problems"] = leftover
        return result
    built = build["matrix"]
    rows = built.get("rows") or []
    result["deterministic_row_count"] = sum(
        1 for r in rows if r.get("adjudication_mode") in _DETERMINISTIC_MODES)
    result["semantic_row_count"] = sum(
        1 for r in rows if r.get("adjudication_mode") == "SEMANTIC_ADJUDICATION")
    result["invalid_requirement_count"] = sum(
        1 for r in rows if r.get("adjudication_mode") == "INVALID_REQUIREMENT")
    result["matrix_semantic_digest"] = build["matrix_semantic_digest"]
    semantic_pending = built.get("semantic_adjudication_state") == "NOT_ATTEMPTED" \
        and result["semantic_row_count"] > 0
    result["status"] = "OK"
    result["action"] = ("REBUILT_STALE" if stale_rebuild
                        else "SEMANTIC_FALLBACK_REQUIRED" if semantic_pending
                        else "GENERATED")
    return result


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
        refs = [f"{COVERAGE_SUBDIR}/{PROBE_RESULTS_NAME}#" + str(r)
                for r in (row.get("runtime_evidence_refs") or [])]
        # semantic row(이슈 #25)는 실존 파일 evidence를 그대로 노출한다
        refs += [str(r) for r in (row.get("static_evidence_refs") or [])
                 + (row.get("contract_evidence_refs") or [])]
        judged[str(row.get("requirement_text_or_ref"))] = {
            "status": status,
            "evidence_refs": refs,
            "reason": f"coverage matrix {row.get('requirement_id')} "
                      f"({row.get('reason_code')})",
        }
    return {"judge_coverage": judged, "problems": [], "valid": True}
