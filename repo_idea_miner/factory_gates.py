# Product Factory 검증 게이트: Static/Contract/Syntax/Smoke + import graph reachability 모듈 (§7.5~§7.8, §14).
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from repo_idea_miner.factory_sandbox import run_in_sandbox
from repo_idea_miner.factory_workspace import list_workspace_files, src_file_count
from repo_idea_miner.redaction import contains_secret

MIN_SRC_FILES = 2

# manifest에 없어도 고아 파일로 보지 않는 관리용 경로/파일
_NON_ORPHAN = ("README.md", "run_instructions.md", "manifest.json", "contract.json")
_NON_ORPHAN_PREFIXES = ("reports/", "checks/", "tests/")


@dataclass
class GateResult:
    name: str
    ok: bool
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def report_md(self) -> str:
        lines = [f"# {self.name} Report", "", f"결과: {'PASS' if self.ok else 'FAIL'}", ""]
        if self.problems:
            lines.append("## 문제")
            lines += [f"- {p}" for p in self.problems]
            lines.append("")
        if self.notes:
            lines.append("## 참고")
            lines += [f"- {n}" for n in self.notes]
            lines.append("")
        return "\n".join(lines)


def write_gate_report(workspace: Path, filename: str, result: GateResult) -> None:
    reports = workspace / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / filename).write_text(result.report_md(), encoding="utf-8")


# ---------------------------------------------------------------- import graph

_HTML_REF_RE = re.compile(r"""(?:src|href)\s*=\s*["']([^"'#?]+)["']""", re.IGNORECASE)
_JS_IMPORT_RES = (
    re.compile(r"""import\s+[^'"]*?["']([^"']+)["']"""),
    re.compile(r"""import\s*\(\s*["']([^"']+)["']\s*\)"""),
    re.compile(r"""require\s*\(\s*["']([^"']+)["']\s*\)"""),
)
_PY_IMPORT_RES = (
    re.compile(r"^\s*import\s+([\w.]+)", re.MULTILINE),
    re.compile(r"^\s*from\s+([\w.]+)\s+import", re.MULTILINE),
)
_CSS_URL_RE = re.compile(r"""url\(\s*["']?([^"')]+)["']?\s*\)""")


def _resolve_relative(base: str, ref: str) -> str | None:
    """base 파일 기준 상대 참조를 workspace 상대 경로로 정규화한다. 외부 URL은 None."""
    if ref.startswith(("http://", "https://", "//", "data:", "mailto:")):
        return None
    parts = list(Path(base).parent.parts)
    for seg in Path(ref).parts:
        if seg == ".":
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return Path(*parts).as_posix() if parts else None


def _js_candidates(path: str) -> list[str]:
    if Path(path).suffix:
        return [path]
    return [path + ".js", path + ".mjs", path + "/index.js"]


def file_references(workspace: Path, rel: str) -> list[str]:
    """파일 하나가 참조하는 workspace 내 다른 파일들의 상대 경로 목록."""
    p = workspace / rel
    if not p.is_file():
        return []
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    suffix = p.suffix.lower()
    refs: list[str] = []

    def _add(raw_ref: str, js: bool = False) -> None:
        resolved = _resolve_relative(rel, raw_ref)
        if not resolved:
            return
        candidates = _js_candidates(resolved) if js else [resolved]
        for c in candidates:
            if (workspace / c).is_file():
                refs.append(c)
                return

    if suffix in (".html", ".htm"):
        for m in _HTML_REF_RE.finditer(text):
            _add(m.group(1))
    elif suffix in (".js", ".mjs"):
        for pattern in _JS_IMPORT_RES:
            for m in pattern.finditer(text):
                _add(m.group(1), js=True)
    elif suffix == ".py":
        for pattern in _PY_IMPORT_RES:
            for m in pattern.finditer(text):
                mod = m.group(1).lstrip(".")
                mod_path = mod.replace(".", "/")
                for cand in (f"{mod_path}.py", f"{mod_path}/__init__.py"):
                    # 같은 디렉터리 기준과 workspace 루트 기준 둘 다 시도
                    for base in (Path(rel).parent.as_posix(), ""):
                        full = f"{base}/{cand}".lstrip("/")
                        if (workspace / full).is_file():
                            refs.append(full)
                            break
    elif suffix == ".css":
        for m in _CSS_URL_RE.finditer(text):
            _add(m.group(1))
    return sorted(set(refs))


def build_import_graph(workspace: Path, files: list[str]) -> dict[str, list[str]]:
    return {f: file_references(workspace, f) for f in files}


def reachable_from(graph: dict[str, list[str]], start: str) -> set[str]:
    seen: set[str] = set()
    stack = [start]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(graph.get(node, []))
    return seen


# ---------------------------------------------------------------- Static Gate (§7.5)

def run_static_gate(workspace: Path, manifest: dict, secrets: list[str]) -> GateResult:
    r = GateResult(name="Static Gate", ok=True)
    disk_files = list_workspace_files(workspace)

    for required in ("README.md", "manifest.json", "contract.json"):
        if not (workspace / required).is_file():
            r.problems.append(f"필수 파일 없음: {required}")

    entrypoint = manifest.get("entrypoint") or ""
    if not entrypoint or not (workspace / entrypoint).is_file():
        r.problems.append(f"entrypoint 없음: {entrypoint or '(미지정)'}")

    manifest_paths = {f["path"] for f in (manifest.get("files") or [])}
    for mp in sorted(manifest_paths):
        if not (workspace / mp).is_file():
            r.problems.append(f"manifest에 있으나 실제 파일 없음: {mp}")
    for df in disk_files:
        if df in manifest_paths or df in _NON_ORPHAN:
            continue
        if any(df.startswith(pfx) for pfx in _NON_ORPHAN_PREFIXES):
            continue
        r.problems.append(f"고아 파일 (manifest에 없음): {df}")

    n_src = src_file_count(workspace)
    if n_src < MIN_SRC_FILES:
        r.problems.append(f"src 파일 수 부족: {n_src} < {MIN_SRC_FILES}")

    for forbidden in manifest.get("forbidden_files") or []:
        if (workspace / forbidden).exists():
            r.problems.append(f"생성 금지 파일 존재: {forbidden}")

    # fake multi-file 사전 검사: entrypoint가 src 파일을 하나도 참조하지 않으면 의심
    if entrypoint and (workspace / entrypoint).is_file() and n_src >= MIN_SRC_FILES:
        graph = build_import_graph(workspace, [entrypoint] + [f for f in disk_files if f.startswith("src/")])
        reached = reachable_from(graph, entrypoint)
        if not any(f.startswith("src/") for f in reached):
            r.problems.append("fake multi-file 의심: entrypoint가 src 파일을 하나도 참조하지 않음")

    for df in disk_files:
        try:
            text = (workspace / df).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if contains_secret(text, secrets):
            r.problems.append(f"secret-like 문자열 발견: {df}")

    r.notes.append(f"src 파일 수: {n_src}")
    r.notes.append(f"workspace 파일 수: {len(disk_files)}")
    r.ok = not r.problems
    return r


# ---------------------------------------------------------------- Contract Gate (§7.6, V1)

def run_contract_gate(workspace: Path, contract: dict, manifest: dict) -> GateResult:
    r = GateResult(name="Contract Gate", ok=True)
    entrypoint = contract.get("entrypoint") or manifest.get("entrypoint") or ""

    for required in contract.get("required_files") or []:
        if not (workspace / required).is_file():
            r.problems.append(f"contract 필수 파일 없음: {required}")

    if not entrypoint or not (workspace / entrypoint).is_file():
        r.problems.append(f"contract entrypoint 없음: {entrypoint or '(미지정)'}")
        r.ok = False
        return r

    module_paths = [m["path"] for m in (contract.get("modules") or [])]
    for mp in module_paths:
        if not (workspace / mp).is_file():
            r.problems.append(f"contract 주요 모듈 없음: {mp}")

    # import/require graph reachability (V1 필수)
    disk_files = list_workspace_files(workspace)
    code_files = [f for f in disk_files if f.startswith("src/") or f == entrypoint]
    graph = build_import_graph(workspace, code_files)
    reached = reachable_from(graph, entrypoint)
    for f in code_files:
        if f not in reached:
            r.problems.append(f"고아 모듈 (entrypoint에서 도달 불가): {f}")

    if not any(f.startswith("src/") for f in reached):
        r.problems.append("fake multi-file: entrypoint에서 도달 가능한 src 모듈이 없음")

    # 선언된 연결 관계 확인
    for conn in contract.get("connections") or []:
        src_file, target = conn.get("source"), conn.get("target")
        if not src_file or not target:
            continue
        if target not in graph.get(src_file, []):
            r.problems.append(f"contract 연결 누락: {src_file} → {target}")

    # Difficulty Anchors 관련 코드 위치 존재 (V1 필수)
    for req in contract.get("difficulty_anchor_requirements") or []:
        anchor = req.get("anchor") or "(anchor)"
        expected = req.get("expected_files") or []
        missing = [f for f in expected if not (workspace / f).is_file()]
        if missing:
            r.problems.append(f"anchor '{anchor}' 담당 파일 없음: {missing}")
            continue
        markers = req.get("expected_markers") or []
        if markers:
            combined = "\n".join(
                (workspace / f).read_text(encoding="utf-8", errors="replace") for f in expected
            )
            if not any(m in combined for m in markers):
                r.problems.append(f"anchor '{anchor}' 마커 미발견: {markers}")

    r.notes.append(f"reachable: {len(reached)}/{len(code_files)} code files")
    r.ok = not r.problems
    return r


# ---------------------------------------------------------------- Syntax Gate (§7.7)

def _node_available() -> bool:
    return shutil.which("node") is not None


_ESM_RE = re.compile(r"^\s*(import\s|export\s)", re.MULTILINE)


def _node_check(p: Path, text: str) -> subprocess.CompletedProcess:
    """node --check 실행. .js에 ESM 문법이 있으면 node가 검사를 건너뛰므로 임시 .mjs 사본으로 검사한다."""
    if p.suffix.lower() == ".js" and _ESM_RE.search(text):
        import tempfile

        tmp = tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8")
        try:
            tmp.write(text)
            tmp.close()
            return subprocess.run(
                ["node", "--check", tmp.name], capture_output=True, text=True, timeout=60,
            )
        finally:
            Path(tmp.name).unlink(missing_ok=True)
    return subprocess.run(["node", "--check", str(p)], capture_output=True, text=True, timeout=60)


def run_syntax_gate(workspace: Path) -> GateResult:
    """가장 싼 문법 검사: py_compile / node --check / json parse / html 참조 검사."""
    r = GateResult(name="Syntax Gate", ok=True)
    node_ok = _node_available()
    files = list_workspace_files(workspace)
    for rel in files:
        p = workspace / rel
        suffix = p.suffix.lower()
        if suffix == ".py":
            proc = subprocess.run(
                [sys.executable, "-m", "py_compile", str(p)],
                capture_output=True, text=True, timeout=60,
            )
            if proc.returncode != 0:
                r.problems.append(f"python 문법 오류: {rel}: {(proc.stderr or '').strip()[:300]}")
        elif suffix in (".js", ".mjs"):
            if not node_ok:
                r.notes.append(f"node 없음 → {rel} 문법 검사 SKIP")
                continue
            proc = _node_check(p, p.read_text(encoding="utf-8", errors="replace"))
            if proc.returncode != 0:
                r.problems.append(f"javascript 문법 오류: {rel}: {(proc.stderr or '').strip()[:300]}")
        elif suffix == ".json":
            try:
                json.loads(p.read_text(encoding="utf-8", errors="replace"))
            except json.JSONDecodeError as exc:
                r.problems.append(f"json parse 실패: {rel}: {exc}")
        elif suffix in (".html", ".htm"):
            text = p.read_text(encoding="utf-8", errors="replace")
            for m in _HTML_REF_RE.finditer(text):
                resolved = _resolve_relative(rel, m.group(1))
                if resolved and not (workspace / resolved).is_file():
                    r.problems.append(f"html 참조 파일 없음: {rel} → {m.group(1)}")
    r.notes.append(f"검사 파일 수: {len(files)} (node {'있음' if node_ok else '없음'})")
    r.ok = not r.problems
    return r


# ---------------------------------------------------------------- Smoke Gate (§7.8, §14 Level 3~5)

_INTERACTION_MARKERS = ("addEventListener", "onclick", "onsubmit", "oninput", "onkeydown", "input(", "argparse")


def run_smoke_gate(
    workspace: Path,
    manifest: dict,
    secrets: list[str],
    use_docker: bool | None = None,
    timeout_seconds: float = 120.0,
) -> GateResult:
    r = GateResult(name="Smoke Gate", ok=True)
    project_type = manifest.get("project_type") or "static_web"
    entrypoint = manifest.get("entrypoint") or ""

    # Level 3: 의존성 설치 단계 (network 제한 허용, timeout 필수)
    install_command = manifest.get("install_command")
    if install_command:
        res = run_in_sandbox(
            workspace, install_command, phase="install", project_type=project_type,
            timeout_seconds=timeout_seconds, use_docker=use_docker, secrets=secrets,
        )
        r.notes.append(f"install ({'docker' if res.used_docker else 'local'}): {install_command}")
        if not res.ok:
            r.problems.append(f"의존성 설치 실패: {res.error or res.stderr[:300]}")
            r.ok = False
            return r

    # Level 4: 기본 실행 검사 (execution/test 단계, network 차단)
    if project_type == "static_web":
        # static server로 index.html 로드에 해당하는 정적 로드 검사:
        # entrypoint가 존재하고, 참조 파일이 모두 로드 가능해야 한다.
        ep = workspace / entrypoint
        if not ep.is_file():
            r.problems.append(f"entrypoint 로드 실패: {entrypoint}")
        else:
            text = ep.read_text(encoding="utf-8", errors="replace")
            for m in _HTML_REF_RE.finditer(text):
                resolved = _resolve_relative(entrypoint, m.group(1))
                if resolved and not (workspace / resolved).is_file():
                    r.problems.append(f"핵심 파일 로드 실패: {m.group(1)}")
    else:
        run_command = manifest.get("run_command") or ""
        if not run_command:
            r.problems.append("run_command 없음")
        else:
            res = run_in_sandbox(
                workspace, run_command, phase="execute", project_type=project_type,
                timeout_seconds=timeout_seconds, use_docker=use_docker, secrets=secrets,
            )
            r.notes.append(f"run ({'docker' if res.used_docker else 'local'}): {run_command}")
            if not res.ok:
                detail = res.error or (res.stderr or res.stdout)[:300]
                r.problems.append(f"기본 실행 실패: {detail}")

    # check_commands (checks/ 실행, network 차단)
    for check_cmd in manifest.get("check_commands") or []:
        res = run_in_sandbox(
            workspace, check_cmd, phase="execute", project_type=project_type,
            timeout_seconds=timeout_seconds, use_docker=use_docker, secrets=secrets,
        )
        r.notes.append(f"check ({'docker' if res.used_docker else 'local'}): {check_cmd}")
        if not res.ok:
            detail = res.error or (res.stderr or res.stdout)[:300]
            r.problems.append(f"검증 명령 실패: {check_cmd}: {detail}")

    # Level 5: 입력/버튼/상태 변화 최소 존재
    combined = []
    for rel in list_workspace_files(workspace):
        if Path(rel).suffix.lower() in (".html", ".htm", ".js", ".mjs", ".py"):
            combined.append((workspace / rel).read_text(encoding="utf-8", errors="replace"))
    blob = "\n".join(combined)
    if not any(marker in blob for marker in _INTERACTION_MARKERS):
        r.problems.append("입력/버튼/상태 변화 코드가 발견되지 않음 (상호작용 최소 기준 미달)")

    r.ok = not r.problems
    return r
