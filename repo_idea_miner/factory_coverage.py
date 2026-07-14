# 이슈 #9: requirement coverage 판정을 결정론적 probe와 구조화 matrix로 만드는 모듈 (LLM 감상 없음).
from __future__ import annotations

import ast
import hashlib
import json
import re
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
# 이슈 #26: semantic row가 validated claim 기반으로 바뀌어 schema 3/rule 2로 승급 —
# 기존(legacy) matrix는 저장된 버전 규칙으로만 재검증하고 새 automation에서는 rebuild한다.
MATRIX_SCHEMA_VERSION = 3
ADJUDICATION_RULE_VERSION = 2
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

# 이슈 #26: semantic coverage grounding — LLM은 claim proposer일 뿐이고 최종 COVERED는
# deterministic claim validator가 실제 artifact 내용을 재검사한 경우에만 허용된다 (§4.1).
CLAIM_VALIDATOR_VERSION = 1
EVIDENCE_BUNDLE_SELECTION_VERSION = 1
EVIDENCE_BUNDLE_NAME = "coverage_evidence_bundle.json"
CLAIM_PROPOSAL_NAME = "coverage_claim_proposal.json"
CLAIM_RESULTS_NAME = "coverage_claim_results.json"
# 제한 enum — 이 목록 밖 claim type은 UNSUPPORTED로 거부한다 (§4.5)
SEMANTIC_CLAIM_TYPES = (
    "FILE_CONTAINS",
    "PYTHON_SYMBOL_EXISTS",
    "PYTHON_SYMBOL_CONTAINS",
    "JSON_POINTER_EQUALS",
    "JSON_POINTER_TRUE",
    "HTML_ELEMENT_EXISTS",
    "HTML_CTA_WIRED",
)
CLAIM_STATUSES = ("PASS", "FAIL", "UNSUPPORTED", "STALE", "INVALID")
# 최종 row source enum (§5.10)
ROW_SOURCES = ("DETERMINISTIC_PROBE", "VALIDATED_SEMANTIC_CLAIMS", "AMBIGUOUS_SEMANTIC")


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
                   current_fingerprint: str | None, run_dir: Path | None = None,
                   rule_version: int = ADJUDICATION_RULE_VERSION) -> list[str]:
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
        # semantic row는 rule v2(이슈 #26)부터 validated claim이 필수 — plain file path
        # 인용만으로는 절대 승인되지 않는다 (§5.6). rule v1(legacy matrix 재검증)만
        # 기존 static/contract evidence ref 규칙을 유지한다. 그 외(deterministic·legacy)는
        # 기존과 동일하게 PASS probe evidence가 필수다.
        if status in ("COVERED", "PARTIALLY_COVERED"):
            refs = row.get("runtime_evidence_refs") or []
            if mode == "SEMANTIC_ADJUDICATION" and not refs:
                if rule_version >= 2:
                    if not row.get("claim_ids"):
                        problems.append(
                            f"{rid}: {status} semantic 판정에 validated claim 없음 — "
                            "plain file path 인용만으로는 금지")
                    if row.get("row_source") != "VALIDATED_SEMANTIC_CLAIMS":
                        problems.append(
                            f"{rid}: semantic {status}인데 "
                            f"row_source={row.get('row_source')!r}")
                    if not row.get("claim_pass_count"):
                        problems.append(f"{rid}: {status}인데 PASS claim 0개")
                    if status == "COVERED" and any(
                            row.get(k) for k in ("claim_fail_count", "claim_stale_count",
                                                 "claim_unsupported_count")):
                        problems.append(
                            f"{rid}: COVERED인데 FAIL/STALE/UNSUPPORTED claim 존재")
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
    # adjudication이 만들어진 rule 버전으로 row를 검증한다 — legacy(v1) adjudication을
    # v2 규칙으로 소급 파괴하지 않되, 새 automation은 항상 v2 rows를 생성한다 (이슈 #26).
    rule_version = int(adjudication.get("rule_version") or 1)
    problems = _validate_rows(rows, normalized, probe_results, fp, run_dir,
                              rule_version=rule_version)
    result = {"ok": not problems, "problems": problems, "row_count": len(rows)}
    if problems:
        return result
    # canonical matrix에는 시각/경로 metadata를 넣지 않는다 — 동일 입력이면 byte-identical (§4.2)
    matrix = {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "adjudication_rule_version": rule_version,
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
        # 이슈 #26 §5.8: reuse/stale 판정에 coverage 입력 전체와 validator version을 포함
        "coverage_context_digest": coverage_context_digest(run_dir),
        "evidence_bundle_digest": adjudication.get("evidence_bundle_digest"),
        "claim_validator_version": CLAIM_VALIDATOR_VERSION,
        "evidence_bundle_selection_version": EVIDENCE_BUNDLE_SELECTION_VERSION,
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


def _revalidate_semantic_claim_rows(run_dir: Path, rows: list) -> list[str]:
    """matrix의 claim 기반 semantic row를 실제 artifact 내용으로 재검증한다 (이슈 #26 §5.6).

    저장된 claim result를 믿지 않고 validate_semantic_claim을 다시 실행한다 — target
    파일이 바뀌었으면 STALE로 불일치가 드러나 matrix가 소비되지 못한다 (§6.4)."""
    claim_rows = [r for r in rows if r.get("adjudication_mode") == "SEMANTIC_ADJUDICATION"
                  and r.get("claim_ids")]
    if not claim_rows:
        return []
    problems: list[str] = []
    bundle = _load_json(Path(run_dir) / COVERAGE_SUBDIR / EVIDENCE_BUNDLE_NAME)
    stored = _load_json(Path(run_dir) / COVERAGE_SUBDIR / CLAIM_RESULTS_NAME)
    if bundle is None or stored is None:
        return ["semantic claim row가 있는데 evidence bundle/claim results 파일 없음"]
    bdig = evidence_bundle_digest(bundle)
    if stored.get("evidence_bundle_digest") != bdig:
        problems.append("claim results가 현재 evidence bundle과 불일치")
    by_req = stored.get("results") or {}
    for row in claim_rows:
        rid = str(row.get("requirement_id"))
        if row.get("evidence_bundle_digest") != bdig:
            problems.append(f"{rid}: row의 evidence bundle digest가 현재 bundle과 다름")
        entries = by_req.get(rid) or []
        ids = sorted(str(e.get("claim_id")) for e in entries)
        if ids != sorted(str(c) for c in row.get("claim_ids") or []):
            problems.append(f"{rid}: claim results와 row의 claim ID 불일치")
            continue
        for e in entries:
            fresh = validate_semantic_claim(run_dir, e.get("claim") or {}, bundle)
            stored_status = (e.get("result") or {}).get("status")
            if fresh["status"] != stored_status:
                problems.append(
                    f"{rid}: claim {e.get('claim_id')} 재검증 불일치 "
                    f"({stored_status} → {fresh['status']}) — stale evidence 소비 금지")
    return problems


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
    problems = _validate_rows(rows, normalized, probe_results, fp, run_dir,
                              rule_version=int(matrix.get("adjudication_rule_version")
                                               or 1))
    if matrix.get("artifact_fingerprint") != fp:
        problems.append("coverage matrix fingerprint가 현재 artifact와 다름")
    # 이슈 #26: context digest가 있으면(신규 matrix) coverage 입력 전체의 stale을 잡는다 —
    # contract/golden/fixture 변경은 fingerprint만으로는 놓친다 (§4.8). legacy matrix는
    # 필드가 없으므로 기존 규칙으로만 재검증한다.
    if matrix.get("coverage_context_digest") is not None \
            and matrix["coverage_context_digest"] != coverage_context_digest(run_dir):
        problems.append("coverage context digest가 현재 입력과 다름 "
                        "(contract/golden/fixture/spec 변경 — 재생성 필요)")
    problems += _revalidate_semantic_claim_rows(run_dir, rows)
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


# ---------------------------------------------------------------- semantic grounding (이슈 #26)

_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣_]{2,}")
_HTML_ID_RE = re.compile(r"\bid\s*=\s*[\"']([^\"']+)[\"']")
_BUNDLE_MAX_FILE_BYTES = 400_000
_BUNDLE_MAX_LINE_CHARS = 240


def _text_tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "")}


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _read_text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:4096]:
        return None
    return data.decode("utf-8", errors="ignore")


def _python_symbols(text: str) -> list[dict]:
    """AST 기반 symbol 카탈로그 (Class.method dotted, 최대 60) — 문자열 추측 없음."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    out: list[dict] = []

    def visit(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                out.append({"symbol": name, "line_start": child.lineno,
                            "line_end": int(getattr(child, "end_lineno", None)
                                            or child.lineno)})
                visit(child, prefix=f"{name}.")

    visit(tree)
    return sorted(out, key=lambda s: (s["line_start"], s["symbol"]))[:60]


def _json_pointers(data, prefix="", depth=0, out=None) -> list[dict]:
    """scalar 값 JSON pointer 카탈로그 (깊이 3, 최대 60) — 실제 값에만 claim을 걸 수 있다."""
    if out is None:
        out = []
    if len(out) >= 60 or depth > 3:
        return out
    if isinstance(data, dict):
        for k in sorted(data, key=str):
            token = str(k).replace("~", "~0").replace("/", "~1")
            _json_pointers(data[k], f"{prefix}/{token}", depth + 1, out)
    elif isinstance(data, list):
        for i, v in enumerate(data[:20]):
            _json_pointers(v, f"{prefix}/{i}", depth + 1, out)
    elif prefix and (isinstance(data, (str, int, float, bool)) or data is None):
        out.append({"pointer": prefix,
                    "value": data[:200] if isinstance(data, str) else data})
    return out


def _file_structure(path: Path, ref: str, text: str) -> dict:
    entry: dict = {"digest": _file_digest(path), "line_count": text.count("\n") + 1}
    if ref.endswith(".py"):
        entry["kind"] = "python"
        entry["python_symbols"] = _python_symbols(text)
    elif ref.endswith(".json"):
        entry["kind"] = "json"
        data = _load_json(path)
        entry["json_pointers"] = _json_pointers(data) if data is not None else []
    elif ref.endswith((".html", ".htm")):
        entry["kind"] = "html"
        entry["html_element_ids"] = sorted(set(_HTML_ID_RE.findall(text)))[:40]
    else:
        entry["kind"] = "text"
    return entry


def _bundle_candidate_pool(run_dir: Path) -> list[tuple[str, Path]]:
    """bundle 후보 파일 (run 상대 ref, 실제 경로) — 결정론적 순서.

    coverage 자기 산출물(review/coverage)은 제외한다 — 판정이 자기 출력을 근거로
    삼는 순환을 차단한다."""
    root = resolve_artifact_root(run_dir)
    rel_root = Path(root).name
    pool: list[tuple[str, Path]] = []
    seen: set[str] = set()

    def add(ref: str, path: Path) -> None:
        if ref not in seen and path.is_file() \
                and path.stat().st_size <= _BUNDLE_MAX_FILE_BYTES:
            seen.add(ref)
            pool.append((ref, path))

    for p in sorted(Path(root).glob("*_contract.json")):
        add(f"{rel_root}/{p.name}", p)
    for pattern in ("src/**/*.py", "product/**/*", "fixtures/**/*.json",
                    "golden/**/*.json"):
        for p in sorted(Path(root).glob(pattern)):
            add(f"{rel_root}/{p.relative_to(root).as_posix()}", p)
    for p in sorted(run_dir.glob("review/*/*.json")):
        ref = p.relative_to(run_dir).as_posix()
        if not ref.startswith(COVERAGE_SUBDIR):
            add(ref, p)
    return pool[:200]


def _bounded_excerpts(text: str, tokens: set[str], max_excerpts: int,
                      max_lines: int) -> list[dict]:
    lines = [ln[:_BUNDLE_MAX_LINE_CHARS] for ln in text.splitlines()]
    match_lines = [i + 1 for i, line in enumerate(lines) if tokens & _text_tokens(line)]
    windows: list[tuple[int, int]] = []
    for ln in match_lines:
        start = max(1, ln - max_lines // 4)
        end = min(len(lines), start + max_lines - 1)
        if windows and start <= windows[-1][1]:
            continue
        windows.append((start, end))
        if len(windows) >= max_excerpts:
            break
    if not windows and lines:
        windows = [(1, min(len(lines), max_lines))]
    return [{"line_start": s, "line_end": e, "text": "\n".join(lines[s - 1:e])}
            for s, e in windows]


def build_semantic_evidence_bundle(
    run_dir: str | Path,
    requirements: list[dict],
    *,
    max_files_per_requirement: int = 5,
    max_excerpts_per_file: int = 2,
    max_lines_per_excerpt: int = 80,
) -> dict:
    """semantic desk에 제공할 bounded evidence bundle (이슈 #26 §5.1).

    파일 선택·excerpt 추출은 전부 결정론적이다: requirement 토큰 겹침 점수(동률은 경로
    오름차순), 부족분은 contract→src→product 순의 pool 순서로 채운다. run ID/challenge
    title 하드코딩 없음. bundle에는 시각/절대경로 metadata가 없어 동일 입력이면
    canonical digest가 동일하다 (§4.7)."""
    run_dir = Path(run_dir)
    pool = _bundle_candidate_pool(run_dir)
    texts: dict[str, str] = {}
    token_cache: dict[str, set[str]] = {}
    for ref, path in pool:
        text = _read_text(path)
        if text is not None:
            texts[ref] = text
            token_cache[ref] = _text_tokens(text)
    req_entries: list[dict] = []
    used_refs: set[str] = set()
    for entry in requirements:
        rid = str(entry.get("requirement_id"))
        text = str(entry.get("requirement_text_or_ref")
                   or entry.get("requirement") or "")
        req_tokens = _text_tokens(text)
        scored = sorted(((len(req_tokens & token_cache[ref]), ref)
                         for ref, _ in pool if ref in texts),
                        key=lambda t: (-t[0], t[1]))
        chosen = [ref for score, ref in scored if score > 0][:max_files_per_requirement]
        if len(chosen) < max_files_per_requirement:
            for ref, _ in pool:
                if ref in texts and ref not in chosen:
                    chosen.append(ref)
                if len(chosen) >= max_files_per_requirement:
                    break
        files = [{"file": ref,
                  "excerpts": _bounded_excerpts(texts[ref], req_tokens,
                                                max_excerpts_per_file,
                                                max_lines_per_excerpt)}
                 for ref in chosen]
        used_refs.update(ref for ref in chosen)
        req_entries.append({"requirement_id": rid, "requirement": text, "files": files})
    path_by_ref = dict(pool)
    return {
        "schema_version": 1,
        "selection_version": EVIDENCE_BUNDLE_SELECTION_VERSION,
        "budget": {"max_files_per_requirement": max_files_per_requirement,
                   "max_excerpts_per_file": max_excerpts_per_file,
                   "max_lines_per_excerpt": max_lines_per_excerpt},
        "files": {ref: _file_structure(path_by_ref[ref], ref, texts[ref])
                  for ref in sorted(used_refs)},
        "requirements": req_entries,
        "produced_by": "factory_coverage_semantic_grounding",
    }


def evidence_bundle_digest(bundle: dict) -> str:
    """bundle의 canonical digest — bundle에는 비본질 metadata가 없으므로 전체가 정본."""
    return _canonical_digest(bundle or {})


def _resolve_json_pointer(data, pointer: str) -> tuple[object, bool]:
    cur = data
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, dict):
            if token not in cur:
                return None, False
            cur = cur[token]
        elif isinstance(cur, list):
            if not token.isdigit() or int(token) >= len(cur):
                return None, False
            cur = cur[int(token)]
        else:
            return None, False
    return cur, True


def _find_python_symbol(text: str, symbol: str) -> tuple[int, int] | None:
    for s in _python_symbols(text):
        if s["symbol"] == symbol:
            return s["line_start"], s["line_end"]
    return None


def _tokens_check(segment: str, expected: dict) -> tuple[bool, dict]:
    required = [str(t) for t in expected.get("required_tokens") or []]
    forbidden = [str(t) for t in expected.get("forbidden_tokens") or []]
    missing = [t for t in required if t not in segment]
    present_forbidden = [t for t in forbidden if t in segment]
    ok = bool(required) and not missing and not present_forbidden
    return ok, {"missing_tokens": missing, "forbidden_tokens_present": present_forbidden}


def validate_semantic_claim(run_dir: str | Path, claim: dict,
                            evidence_bundle: dict) -> dict:
    """claim 1건을 실제 artifact 내용에서 재검사한다 (이슈 #26 §5.4).

    파일이 존재한다는 사실만으로는 절대 PASS하지 않는다 — bundle 소속·digest 일치·
    위치(symbol/pointer/element) 실존·expected assertion 재검사를 전부 통과해야 PASS다.
    판정 불가는 UNSUPPORTED/INVALID/STALE로 정직하게 남는다."""
    run_dir = Path(run_dir)
    ct = str(claim.get("claim_type"))
    ref = str(claim.get("file") or "")
    out: dict = {"claim_id": claim.get("claim_id"), "claim_type": ct, "file": ref,
                 "status": "INVALID", "reason_code": None,
                 "observed": None, "expected": claim.get("expected") or {},
                 "file_digest_ok": False, "location_ok": False,
                 "validator_version": CLAIM_VALIDATOR_VERSION}
    if ct not in SEMANTIC_CLAIM_TYPES:
        out.update(status="UNSUPPORTED", reason_code="UNSUPPORTED_CLAIM_TYPE")
        return out
    norm = ref.replace("\\", "/")
    if not ref or ".." in norm.split("/") or norm.startswith("/") \
            or ":" in norm.split("/")[0]:
        out["reason_code"] = "UNSAFE_PATH"
        return out
    bundle_entry = ((evidence_bundle or {}).get("files") or {}).get(ref)
    if bundle_entry is None:
        # bundle 밖 파일은 bounded evidence가 아니다 — 근거 없는 인용 차단 (§5.6)
        out["reason_code"] = "FILE_NOT_IN_BUNDLE"
        return out
    path = run_dir / ref
    if not path.is_file():
        out.update(status="STALE", reason_code="FILE_MISSING")
        return out
    actual_digest = _file_digest(path)
    expected_digest = claim.get("file_digest") or bundle_entry.get("digest")
    if expected_digest != actual_digest:
        out.update(status="STALE", reason_code="FILE_DIGEST_MISMATCH",
                   observed={"file_digest": actual_digest})
        return out
    out["file_digest_ok"] = True
    text = _read_text(path)
    if text is None:
        out.update(status="FAIL", reason_code="FILE_UNREADABLE")
        return out
    expected = claim.get("expected") or {}
    if ct == "FILE_CONTAINS":
        out["location_ok"] = True
        ok, detail = _tokens_check(text, expected)
        out.update(status="PASS" if ok else "FAIL", observed=detail,
                   reason_code="CONTENT_MATCH" if ok else "CONTENT_MISMATCH")
    elif ct in ("PYTHON_SYMBOL_EXISTS", "PYTHON_SYMBOL_CONTAINS"):
        loc = _find_python_symbol(text, str(claim.get("symbol")))
        if loc is None:
            out.update(status="FAIL", reason_code="SYMBOL_NOT_FOUND",
                       observed={"symbol": claim.get("symbol")})
            return out
        out["location_ok"] = True
        if ct == "PYTHON_SYMBOL_EXISTS":
            out.update(status="PASS", reason_code="SYMBOL_PRESENT",
                       observed={"line_start": loc[0], "line_end": loc[1]})
        else:
            segment = "\n".join(text.splitlines()[loc[0] - 1:loc[1]])
            ok, detail = _tokens_check(segment, expected)
            detail.update(line_start=loc[0], line_end=loc[1])
            out.update(status="PASS" if ok else "FAIL", observed=detail,
                       reason_code="CONTENT_MATCH" if ok else "CONTENT_MISMATCH")
    elif ct in ("JSON_POINTER_EQUALS", "JSON_POINTER_TRUE"):
        data = _load_json(path)
        if data is None:
            out.update(status="FAIL", reason_code="JSON_PARSE_FAILED")
            return out
        value, found = _resolve_json_pointer(data, str(claim.get("json_pointer")))
        if not found:
            out.update(status="FAIL", reason_code="POINTER_NOT_FOUND")
            return out
        out["location_ok"] = True
        ok = (value == expected.get("value")) if ct == "JSON_POINTER_EQUALS" \
            else value is True
        out.update(status="PASS" if ok else "FAIL", observed={"value": value},
                   reason_code="VALUE_MATCH" if ok else "VALUE_MISMATCH")
    elif ct == "HTML_ELEMENT_EXISTS":
        from repo_idea_miner.factory_ux_polish import _element_hidden, _stylesheet
        eid = str(expected.get("element_id"))
        m = re.search(r"<([a-zA-Z][a-zA-Z0-9-]*)\b([^>]*\bid\s*=\s*[\"']"
                      + re.escape(eid) + r"[\"'][^>]*)>", text)
        if m is None:
            out.update(status="FAIL", reason_code="ELEMENT_NOT_FOUND",
                       observed={"element_id": eid})
            return out
        out["location_ok"] = True
        hidden = _element_hidden(m.group(2), _stylesheet(text))
        out.update(status="FAIL" if hidden else "PASS",
                   observed={"element_id": eid, "hidden": hidden},
                   reason_code="ELEMENT_HIDDEN" if hidden else "ELEMENT_PRESENT")
    elif ct == "HTML_CTA_WIRED":
        # 이슈 #22 UX validator helper 재사용 — marker-only/숨김/무연결 CTA를 동일 기준으로 거부
        from repo_idea_miner.factory_ux_polish import recheck_first_screen_cta
        root = resolve_artifact_root(run_dir)
        ok = bool(root and Path(root).is_dir() and recheck_first_screen_cta(Path(root)))
        out["location_ok"] = ok
        out.update(status="PASS" if ok else "FAIL", observed={"first_screen_cta": ok},
                   reason_code="CTA_WIRED" if ok else "CTA_NOT_WIRED")
    return out


def canonicalize_semantic_claims(claims: list[dict]) -> list[dict]:
    """claim 후보를 canonical form으로 정규화한다 (§4.7 — 순서/중복/표현 차이 무력화).

    identity = (claim_type, file, symbol, json_pointer, expected). 자연어 reason,
    LLM이 붙인 claim_id, line hint, LLM이 echo한 file_digest는 비본질이라 제거한다 —
    digest 검증은 항상 deterministic bundle digest 기준으로 수행되므로 LLM 표기 차이가
    matrix 결과를 흔들지 못한다."""
    canon: dict[tuple, dict] = {}
    for c in claims:
        key = (str(c.get("claim_type")), str(c.get("file")),
               c.get("symbol") or "", c.get("json_pointer") or "",
               json.dumps(c.get("expected") or {}, ensure_ascii=True, sort_keys=True))
        if key not in canon:
            canon[key] = {"claim_type": key[0], "file": key[1],
                          "symbol": c.get("symbol") or None,
                          "json_pointer": c.get("json_pointer") or None,
                          "expected": c.get("expected") or {}}
    return [canon[k] for k in sorted(canon)]


def coverage_context_digest(run_dir: str | Path) -> str | None:
    """coverage 판정에 영향을 주는 모든 입력의 canonical digest (이슈 #26 §4.8).

    artifact fingerprint가 놓치는 입력(contract/golden/fixture/probe spec/probe 결과/
    rule·validator version)을 포함한다. mtime/절대경로/생성 시각 같은 비본질 metadata는
    구성상 제외된다 — 동일 의미 입력이면 동일 digest다."""
    run_dir = Path(run_dir)
    root = resolve_artifact_root(run_dir)
    if root is None or not Path(root).is_dir():
        return None
    files: dict[str, str] = {}
    for pattern in ("*_contract.json", "src/**/*.py", "product/**/*",
                    "golden/**/*", "fixtures/**/*"):
        for p in sorted(Path(root).glob(pattern)):
            if p.is_file():
                files[p.relative_to(root).as_posix()] = _file_digest(p)
    spec = _load_json(run_dir / COVERAGE_SUBDIR / PROBE_SPEC_NAME)
    probe_results = _load_json(run_dir / COVERAGE_SUBDIR / PROBE_RESULTS_NAME)
    normalized = _load_json(run_dir / "normalized_challenge.json") or {}
    return _canonical_digest({
        "challenge_digest": normalized_challenge_digest(normalized),
        "artifact_files": files,
        "probe_spec_digest": probe_spec_digest(spec) if spec is not None else None,
        "probe_results_digest": probe_results_semantic_digest(probe_results)
        if probe_results is not None else None,
        "matrix_schema_version": MATRIX_SCHEMA_VERSION,
        "adjudication_rule_version": ADJUDICATION_RULE_VERSION,
        "claim_validator_version": CLAIM_VALIDATOR_VERSION,
        "evidence_bundle_selection_version": EVIDENCE_BUNDLE_SELECTION_VERSION,
        "fingerprint_version": FINGERPRINT_VERSION,
    })


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
    # 실제 scenario/golden 예시 — initial_state와 final_state의 정본 shape는 이것이다.
    # state_contract entity 이름으로 감싼 추측 shape는 runner가 거부한다 (live 실측 결함).
    scenarios = sorted(Path(root).glob("fixtures/scenario_*.json"))
    if scenarios:
        sample = _load_json(scenarios[0]) or {}
        ctx["example_scenario"] = {k: sample.get(k) for k in ("initial_state", "actions")}
    goldens = sorted(Path(root).glob("golden/expected_*.json"))
    if goldens:
        sample_out = _load_json(goldens[0]) or {}
        ctx["example_runner_output"] = {
            k: sample_out.get(k) for k in ("final_state", "events", "errors")
            if k in sample_out}
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
- initial_state와 final_state_path의 경로는 아래 ARTIFACT CONTRACTS의 example_scenario /
  example_runner_output과 **완전히 같은 구조**를 따른다. state_contract의 entity 이름으로
  임의로 감싸거나 경로를 추측하지 마라 — 예시에 없는 최상위 키는 존재하지 않는다.
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
            # 스키마가 형태 편차를 정규화한 canonical 출력을 검증·소비한다
            raw = res["model"].model_dump() if res.get("model") is not None \
                else (res["raw"] or {})
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


_SEMANTIC_PROMPT_BUDGET = 24_000
_BUNDLE_BUDGET_LADDER = ((5, 2, 80), (5, 1, 60), (3, 1, 40), (2, 1, 30))


def _fit_semantic_bundle(run_dir: Path, semantic_entries: list[dict]) -> dict:
    """고정 prompt 예산에 맞는 가장 큰 bounded bundle을 결정론적으로 고른다 (§4.4)."""
    bundle: dict = {}
    for files_n, exc_n, lines_n in _BUNDLE_BUDGET_LADDER:
        bundle = build_semantic_evidence_bundle(
            run_dir, semantic_entries, max_files_per_requirement=files_n,
            max_excerpts_per_file=exc_n, max_lines_per_excerpt=lines_n)
        if len(json.dumps(bundle, ensure_ascii=False)) <= _SEMANTIC_PROMPT_BUDGET:
            break
    return bundle


def _build_semantic_claim_prompt(semantic_entries: list[dict], bundle: dict) -> str:
    reqs = [{"requirement": e["requirement_text_or_ref"], "kind": e["requirement_kind"],
             "forbidden_simplification": bool(e.get("forbidden_simplification"))}
            for e in semantic_entries]
    claim_dsl = {
        "claim": {"requirement": "requirement 원문", "claim_type": "아래 type 중 하나",
                  "file": "bundle files의 경로만", "symbol": "PYTHON_*일 때",
                  "json_pointer": "JSON_POINTER_*일 때 (/a/b 형식)",
                  "expected": "type별 assertion", "reason": "짧은 근거"},
        "claim_types": {
            "FILE_CONTAINS": {"expected": {"required_tokens": ["..."],
                                           "forbidden_tokens": ["선택"]}},
            "PYTHON_SYMBOL_EXISTS": {"symbol": "함수/클래스 (Class.method 가능)"},
            "PYTHON_SYMBOL_CONTAINS": {"symbol": "...",
                                       "expected": {"required_tokens": ["..."]}},
            "JSON_POINTER_EQUALS": {"json_pointer": "/a/b", "expected": {"value": "..."}},
            "JSON_POINTER_TRUE": {"json_pointer": "/a/b"},
            "HTML_ELEMENT_EXISTS": {"expected": {"element_id": "..."}},
            "HTML_CTA_WIRED": {"file": "첫 화면 product surface"},
        },
    }
    return f"""너는 Product Factory의 Semantic Coverage Claim Proposer다.
결정론적 probe로 판정 불가한 requirement에 대해, 아래 bounded evidence bundle의 실제 내용에
근거한 '기계 검증 가능한 structured claim' 후보를 제안한다.

규칙:
- 너는 판정자가 아니라 제안자다. 최종 coverage status는 deterministic validator가 claim을
  실제 artifact에서 재검사해 계산한다 — 네가 쓰는 raw_coverage_status는 참고 기록일 뿐이다.
- claim은 bundle의 files에 있는 경로만 인용한다. bundle 밖 경로/추측 symbol/추측 pointer 금지.
- claim의 expected는 bundle excerpt에서 실제로 확인한 내용만 쓴다 — 파일 경로 인용만으로는
  아무것도 증명되지 않는다.
- requirement가 기계 검증 가능한 claim으로 표현되지 않으면(순수 감상/직관 판단) claims를
  비워라 — 그 requirement는 AMBIGUOUS 처리된다. 억지 claim을 만들지 마라.
- requirement당 claim 최대 4개.

JSON만 출력. Schema: {{"items": [{{"requirement": "...", "raw_coverage_status": "...", "claims": [claim...]}}]}}

=== CLAIM DSL ===
{json.dumps(claim_dsl, ensure_ascii=False, indent=1)}

=== SEMANTIC REQUIREMENTS ===
{json.dumps(reqs, ensure_ascii=False, indent=1)}

=== EVIDENCE BUNDLE ===
{json.dumps(bundle, ensure_ascii=False, indent=1)}
"""


def _ambiguous_row(reason_code: str) -> dict:
    return {"coverage_status": "AMBIGUOUS", "failure_class": "EVIDENCE_GAP",
            "reason_code": reason_code, "recommended_action": "SEMANTIC_REVIEW",
            "runtime_evidence_refs": [], "static_evidence_refs": [],
            "contract_evidence_refs": [], "row_source": "AMBIGUOUS_SEMANTIC"}


def _row_from_claim_results(results: list[dict], bundle_digest: str) -> dict:
    """requirement 1건의 최종 semantic row를 claim 결과에서 결정론적으로 계산한다 (§4.6).

    LLM raw status는 이 계산에 관여하지 않는다. FAIL은 실제 결함(NOT_COVERED/PARTIAL),
    STALE/UNSUPPORTED/INVALID는 검증 불능(AMBIGUOUS)으로 분리한다 — 어느 쪽도 COVERED가
    되지 못한다."""
    counts = {s: sum(1 for r in results if r.get("status") == s) for s in CLAIM_STATUSES}
    base = {
        "runtime_evidence_refs": [], "contract_evidence_refs": [],
        "static_evidence_refs": sorted({str(r.get("file")) for r in results}),
        "claim_ids": [str(r.get("claim_id")) for r in results],
        "claim_pass_count": counts["PASS"], "claim_fail_count": counts["FAIL"],
        "claim_unsupported_count": counts["UNSUPPORTED"] + counts["INVALID"],
        "claim_stale_count": counts["STALE"],
        "claim_validator_version": CLAIM_VALIDATOR_VERSION,
        "evidence_bundle_digest": bundle_digest,
    }
    if not results:
        row = _ambiguous_row("SEMANTIC_NO_VALID_CLAIMS")
        row.update({k: v for k, v in base.items() if k != "static_evidence_refs"})
        return row
    if counts["STALE"]:
        return {**base, "coverage_status": "AMBIGUOUS", "failure_class": "EVIDENCE_GAP",
                "reason_code": "SEMANTIC_CLAIM_STALE",
                "recommended_action": "SEMANTIC_REVIEW",
                "row_source": "AMBIGUOUS_SEMANTIC", "static_evidence_refs": []}
    if counts["UNSUPPORTED"] or counts["INVALID"]:
        return {**base, "coverage_status": "AMBIGUOUS", "failure_class": "EVIDENCE_GAP",
                "reason_code": "SEMANTIC_CLAIM_UNSUPPORTED",
                "recommended_action": "SEMANTIC_REVIEW",
                "row_source": "AMBIGUOUS_SEMANTIC", "static_evidence_refs": []}
    if counts["FAIL"]:
        status = "PARTIALLY_COVERED" if counts["PASS"] else "NOT_COVERED"
        return {**base, "coverage_status": status, "failure_class": "TRUE_CORE_GAP",
                "reason_code": "SEMANTIC_CLAIM_PARTIAL" if counts["PASS"]
                else "SEMANTIC_CLAIM_FAILED",
                "recommended_action": "REPAIR_REQUIRED",
                "row_source": "VALIDATED_SEMANTIC_CLAIMS"}
    return {**base, "coverage_status": "COVERED", "failure_class": "NONE",
            "reason_code": "VALIDATED_SEMANTIC_CLAIMS", "recommended_action": "없음",
            "row_source": "VALIDATED_SEMANTIC_CLAIMS"}


def _adjudicate_semantic_rows(run_dir: Path, semantic_entries: list[dict],
                              executor) -> dict:
    """semantic requirement를 claim proposer + deterministic validator로 판정한다 (이슈 #26).

    LLM은 bounded evidence bundle에 근거한 structured claim 후보만 제안한다. 최종 row는
    validate_semantic_claim 실행 결과에서 결정론적으로 계산되고, LLM raw status는 raw
    proposal 기록으로만 남는다. transient 인프라 실패는 NOT_COVERED로 바꾸지 않고 infra로
    보고한다 (§5.7). 무효 claim은 개별 제거(rejected 기록)한다 — 유효 claim의 판정을
    무효화하지 않아 서로 다른 잘못된 proposal도 동일 artifact truth로 수렴한다 (§4.7)."""
    out: dict = {"ok": True, "rows_by_text": {}, "infra_failure": False,
                 "desk_called": False, "problems": [], "state": "NOT_ATTEMPTED",
                 "evidence_bundle_digest": None, "raw_proposal_digest": None,
                 "proposal_rejected_count": 0}
    if not semantic_entries:
        out["state"] = "NONE_REQUIRED"
        return out
    if executor is None:
        return out
    from repo_idea_miner.factory_autopilot_desks import execute_desk
    from repo_idea_miner.factory_autopilot_schemas import (
        AUTOPILOT_INFRA_FAIL,
        SemanticCoverageClaim,
        SemanticCoverageClaimProposal,
    )
    from pydantic import ValidationError
    bundle = _fit_semantic_bundle(run_dir, semantic_entries)
    _write_json(run_dir / COVERAGE_SUBDIR / EVIDENCE_BUNDLE_NAME, bundle)
    bdig = evidence_bundle_digest(bundle)
    out["evidence_bundle_digest"] = bdig
    res = execute_desk(executor, "coverage_semantic_claims",
                       _build_semantic_claim_prompt(semantic_entries, bundle),
                       SemanticCoverageClaimProposal)
    out["desk_called"] = True
    if res.get("raw") is not None:
        out["raw_proposal_digest"] = _canonical_digest(res["raw"])
        _write_json(run_dir / COVERAGE_SUBDIR / CLAIM_PROPOSAL_NAME, {
            "raw": res["raw"], "raw_proposal_digest": out["raw_proposal_digest"],
            "desk_status": res["status"],
            "produced_by": "factory_coverage_semantic_grounding"})
    if res["status"] != "PASS":
        if res.get("failure_type") == AUTOPILOT_INFRA_FAIL:
            out["ok"] = False
            out["infra_failure"] = True
            out["problems"] += list(res.get("problems") or [])
        else:
            out["state"] = "ADJUDICATION_INVALID"
            out["problems"] += [f"semantic claim proposal 무효 → AMBIGUOUS 강등: {p}"
                                for p in (res.get("problems") or [])[:10]]
        return out
    payload = res["model"].model_dump() if res.get("model") is not None \
        else (res["raw"] or {})
    rid_by_text = {e["requirement_text_or_ref"]: str(e.get("requirement_id"))
                   for e in semantic_entries}
    bundle_files = set(bundle.get("files") or {})
    claims_by_text: dict[str, list[dict]] = {t: [] for t in rid_by_text}
    raw_status_by_text: dict[str, str] = {}
    for item in payload.get("items") or []:
        text = str(item.get("requirement"))
        if text not in rid_by_text:
            out["problems"].append(f"정본 밖 requirement claim 거부: {text[:40]!r}")
            out["proposal_rejected_count"] += len(item.get("claims") or [])
            continue
        raw_status_by_text[text] = str(item.get("raw_coverage_status") or "")
        for raw_claim in item.get("claims") or []:
            if not isinstance(raw_claim, dict):
                out["proposal_rejected_count"] += 1
                continue
            try:
                model = SemanticCoverageClaim.model_validate(
                    {**raw_claim, "requirement": text})
            except ValidationError as exc:
                out["proposal_rejected_count"] += 1
                out["problems"].append(
                    f"무효 claim 제거({text[:30]!r}): {exc.errors()[0].get('msg')}")
                continue
            claim = model.model_dump()
            if claim.get("file") not in bundle_files:
                # bundle 밖 인용은 bounded evidence가 아니다 — 개별 제거 (§4.4)
                out["proposal_rejected_count"] += 1
                out["problems"].append(
                    f"bundle 밖 파일 claim 제거({text[:30]!r}): {claim.get('file')!r}")
                continue
            claims_by_text[text].append(claim)
    results_by_rid: dict[str, list[dict]] = {}
    for entry in semantic_entries:
        text = entry["requirement_text_or_ref"]
        rid = rid_by_text[text]
        canonical = canonicalize_semantic_claims(claims_by_text.get(text) or [])
        results: list[dict] = []
        for i, claim in enumerate(canonical, start=1):
            cid = f"{rid}-C{i}"
            result = validate_semantic_claim(run_dir, {**claim, "claim_id": cid}, bundle)
            results.append({"claim_id": cid, "claim": claim, "result": result})
        results_by_rid[rid] = results
        row = _row_from_claim_results(
            [{**e["result"], "claim_id": e["claim_id"], "file": e["claim"]["file"]}
             for e in results], bdig)
        # LLM raw status는 판정에 관여하지 않는 참고 기록 — canonical matrix에는 넣지 않는다
        out["rows_by_text"][text] = row
    _write_json(run_dir / COVERAGE_SUBDIR / CLAIM_RESULTS_NAME, {
        "validator_version": CLAIM_VALIDATOR_VERSION,
        "evidence_bundle_digest": bdig,
        "results": results_by_rid,
        "produced_by": "factory_coverage_semantic_grounding",
    })
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
                           runtime_evidence_refs=refs,
                           row_source="DETERMINISTIC_PROBE")
            else:
                row.update(coverage_status="NOT_COVERED", failure_class="TRUE_CORE_GAP",
                           reason_code="PROBE_FAILED", recommended_action="REPAIR_REQUIRED",
                           runtime_evidence_refs=[], probe_refs=refs,
                           row_source="DETERMINISTIC_PROBE")
        elif mode == "SEMANTIC_ADJUDICATION":
            row.update(semantic_rows_by_text.get(text)
                       or _ambiguous_row("SEMANTIC_ADJUDICATION_NOT_ATTEMPTED"))
        elif mode == "INVALID_REQUIREMENT":
            row.update(coverage_status="AMBIGUOUS", failure_class="SPEC_OVERREACH",
                       reason_code="INVALID_OR_AMBIGUOUS_REQUIREMENT",
                       recommended_action="SPEC_REVIEW",
                       runtime_evidence_refs=[],
                       row_source="AMBIGUOUS_SEMANTIC")
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
    # 이슈 #26 §5.8: coverage 입력 전체 + claim validator/bundle selection 버전이
    # 전부 일치해야 재사용 — 필드가 없는 legacy matrix는 새 automation에서 rebuild된다.
    if matrix.get("coverage_context_digest") != coverage_context_digest(run_dir):
        problems.append("coverage context digest 불일치 (contract/golden/fixture 변경 포함)")
    if matrix.get("claim_validator_version") != CLAIM_VALIDATOR_VERSION:
        problems.append("claim validator version 불일치")
    if matrix.get("evidence_bundle_selection_version") != EVIDENCE_BUNDLE_SELECTION_VERSION:
        problems.append("evidence bundle selection version 불일치")
    if executor is not None \
            and matrix.get("semantic_adjudication_state") == "NOT_ATTEMPTED":
        problems.append("semantic rows 미판정 상태 — executor로 승급 재생성")
    return problems


def _row_stats(rows: list) -> dict:
    """matrix rows에서 provenance 통계를 결정론적으로 집계한다 (이슈 #26 §5.10)."""
    stats: dict = {
        "deterministic_row_count": sum(
            1 for r in rows if r.get("adjudication_mode") in _DETERMINISTIC_MODES),
        "semantic_row_count": sum(
            1 for r in rows if r.get("adjudication_mode") == "SEMANTIC_ADJUDICATION"),
        "invalid_requirement_count": sum(
            1 for r in rows if r.get("adjudication_mode") == "INVALID_REQUIREMENT"),
        "row_source_counts": {},
        "claim_stats": {"pass": 0, "fail": 0, "unsupported": 0, "stale": 0},
        "validated_semantic_covered_count": 0,
        "plain_path_covered_count": 0,
    }
    for r in rows:
        src = r.get("row_source")
        if src:
            stats["row_source_counts"][src] = stats["row_source_counts"].get(src, 0) + 1
        stats["claim_stats"]["pass"] += int(r.get("claim_pass_count") or 0)
        stats["claim_stats"]["fail"] += int(r.get("claim_fail_count") or 0)
        stats["claim_stats"]["unsupported"] += int(r.get("claim_unsupported_count") or 0)
        stats["claim_stats"]["stale"] += int(r.get("claim_stale_count") or 0)
        if r.get("adjudication_mode") == "SEMANTIC_ADJUDICATION" \
                and r.get("coverage_status") == "COVERED":
            if r.get("row_source") == "VALIDATED_SEMANTIC_CLAIMS" and r.get("claim_ids"):
                stats["validated_semantic_covered_count"] += 1
            else:
                stats["plain_path_covered_count"] += 1
    return stats


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
        # 이슈 #26 provenance (§5.10)
        "coverage_context_digest": None, "evidence_bundle_digest": None,
        "claim_validator_version": CLAIM_VALIDATOR_VERSION,
        "evidence_bundle_selection_version": EVIDENCE_BUNDLE_SELECTION_VERSION,
        "claim_stats": None, "row_source_counts": None,
        "validated_semantic_covered_count": 0, "plain_path_covered_count": 0,
        "proposal_rejected_count": 0, "raw_proposal_digest": None,
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
                          matrix_semantic_digest=matrix_semantic_digest(matrix),
                          coverage_context_digest=matrix.get("coverage_context_digest"),
                          evidence_bundle_digest=matrix.get("evidence_bundle_digest"))
            result.update(_row_stats(matrix.get("rows") or []))
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
        result["evidence_bundle_digest"] = sem.get("evidence_bundle_digest")
        result["raw_proposal_digest"] = sem.get("raw_proposal_digest")
        result["proposal_rejected_count"] = int(sem.get("proposal_rejected_count") or 0)
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
            "evidence_bundle_digest": sem.get("evidence_bundle_digest"),
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
    result.update(_row_stats(rows))
    result["matrix_semantic_digest"] = build["matrix_semantic_digest"]
    result["coverage_context_digest"] = built.get("coverage_context_digest")
    if result["evidence_bundle_digest"] is None:
        result["evidence_bundle_digest"] = built.get("evidence_bundle_digest")
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
