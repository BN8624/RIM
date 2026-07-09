# Static/Contract/Syntax/Smoke gate와 import graph reachability 테스트.
import json

import pytest

from repo_idea_miner.factory_gates import (
    build_import_graph,
    reachable_from,
    run_contract_gate,
    run_smoke_gate,
    run_static_gate,
    run_syntax_gate,
)
from repo_idea_miner.factory_prompts import mock_build_output, mock_technical_spec
from repo_idea_miner.factory_workspace import apply_file_entries


@pytest.fixture
def workspace(tmp_path):
    """mock 고정 workspace를 실제 디스크에 만든다."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    spec = mock_technical_spec()
    (ws / "manifest.json").write_text(json.dumps(spec["manifest"], ensure_ascii=False), encoding="utf-8")
    (ws / "contract.json").write_text(json.dumps(spec["contract"], ensure_ascii=False), encoding="utf-8")
    apply_file_entries(ws, mock_build_output()["files"], [])
    return ws, spec["manifest"], spec["contract"]


def test_import_graph_reachability(workspace):
    ws, manifest, _ = workspace
    files = ["index.html", "src/app.js", "src/commands.js", "src/state.js", "src/render.js", "src/style.css"]
    graph = build_import_graph(ws, files)
    assert "src/app.js" in graph["index.html"]
    assert "src/commands.js" in graph["src/app.js"]
    reached = reachable_from(graph, "index.html")
    assert set(files) <= reached


def test_static_gate_passes_on_mock_workspace(workspace):
    ws, manifest, _ = workspace
    r = run_static_gate(ws, manifest, [])
    assert r.ok, r.problems


def test_static_gate_fails_on_manifest_mismatch(workspace):
    """manifest와 실제 파일 불일치 시 실패 (§22-17)."""
    ws, manifest, _ = workspace
    (ws / "src" / "render.js").unlink()
    r = run_static_gate(ws, manifest, [])
    assert not r.ok
    assert any("render.js" in p for p in r.problems)


def test_static_gate_fails_on_orphan_file(workspace):
    ws, manifest, _ = workspace
    (ws / "mystery.js").write_text("console.log(1);", encoding="utf-8")
    r = run_static_gate(ws, manifest, [])
    assert not r.ok
    assert any("고아 파일" in p for p in r.problems)


def test_static_gate_fails_on_single_src_file(tmp_path):
    """Final 후보가 사실상 단일파일이면 실패 (§1)."""
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "README.md").write_text("# r", encoding="utf-8")
    (ws / "manifest.json").write_text("{}", encoding="utf-8")
    (ws / "contract.json").write_text("{}", encoding="utf-8")
    (ws / "index.html").write_text("<html></html>", encoding="utf-8")
    (ws / "src" / "only.js").write_text("var a = 1;", encoding="utf-8")
    manifest = {"entrypoint": "index.html", "files": [{"path": "index.html", "role": "e"}, {"path": "src/only.js", "role": "s"}]}
    r = run_static_gate(ws, manifest, [])
    assert not r.ok
    assert any("src 파일 수 부족" in p for p in r.problems)


def test_static_gate_detects_secret_like_string(workspace):
    ws, manifest, _ = workspace
    (ws / "src" / "state.js").write_text(
        (ws / "src" / "state.js").read_text(encoding="utf-8")
        + '\nconst k = "AQ.abcdefghijklmnopqrstuvwx";\n',
        encoding="utf-8",
    )
    r = run_static_gate(ws, manifest, [])
    assert not r.ok
    assert any("secret-like" in p for p in r.problems)


def test_contract_gate_passes_on_mock_workspace(workspace):
    ws, manifest, contract = workspace
    r = run_contract_gate(ws, contract, manifest)
    assert r.ok, r.problems


def test_contract_gate_fails_when_module_missing(workspace):
    """contract와 실제 코드 불일치 시 실패 (§22-18)."""
    ws, manifest, contract = workspace
    (ws / "src" / "state.js").unlink()
    r = run_contract_gate(ws, contract, manifest)
    assert not r.ok
    assert any("state.js" in p for p in r.problems)


def test_contract_gate_v1_checks_entrypoint_and_import_graph(workspace):
    """V1 Contract Gate: 파일/entrypoint/import graph/주요 모듈 검사 (§22-19)."""
    ws, manifest, contract = workspace
    # entrypoint에서 app.js 연결을 끊으면 도달 불가 모듈이 생긴다
    html = (ws / "index.html").read_text(encoding="utf-8").replace(
        '<script type="module" src="src/app.js"></script>', ""
    )
    (ws / "index.html").write_text(html, encoding="utf-8")
    r = run_contract_gate(ws, contract, manifest)
    assert not r.ok
    assert any("도달 불가" in p or "연결 누락" in p or "fake multi-file" in p for p in r.problems)


def test_contract_gate_fails_when_anchor_marker_missing(workspace):
    ws, manifest, contract = workspace
    text = (ws / "src" / "commands.js").read_text(encoding="utf-8").replace("filterCommands", "searchStuff")
    (ws / "src" / "commands.js").write_text(text, encoding="utf-8")
    # app.js의 import도 함께 바꿔 문법은 유지
    app = (ws / "src" / "app.js").read_text(encoding="utf-8").replace("filterCommands", "searchStuff")
    (ws / "src" / "app.js").write_text(app, encoding="utf-8")
    r = run_contract_gate(ws, contract, manifest)
    assert not r.ok
    assert any("마커 미발견" in p for p in r.problems)


def test_syntax_gate_passes_on_mock_workspace(workspace):
    ws, _, _ = workspace
    r = run_syntax_gate(ws)
    assert r.ok, r.problems


def test_syntax_gate_fails_on_broken_python(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "broken.py").write_text("def x(:\n    pass\n", encoding="utf-8")
    r = run_syntax_gate(ws)
    assert not r.ok
    assert any("python 문법 오류" in p for p in r.problems)


def test_syntax_gate_fails_on_broken_json(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "bad.json").write_text("{not json", encoding="utf-8")
    r = run_syntax_gate(ws)
    assert not r.ok
    assert any("json parse 실패" in p for p in r.problems)


def test_syntax_gate_fails_on_missing_html_reference(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "index.html").write_text('<script src="src/nothing.js"></script>', encoding="utf-8")
    r = run_syntax_gate(ws)
    assert not r.ok
    assert any("참조 파일 없음" in p for p in r.problems)


def test_smoke_gate_local_passes_on_mock_workspace(workspace):
    ws, manifest, _ = workspace
    r = run_smoke_gate(ws, manifest, [], use_docker=False)
    assert r.ok, r.problems


def test_smoke_gate_fails_when_check_command_fails(workspace):
    ws, manifest, _ = workspace
    (ws / "checks" / "check_structure.py").write_text(
        "import sys\nprint('FAIL: forced')\nsys.exit(1)\n", encoding="utf-8"
    )
    r = run_smoke_gate(ws, manifest, [], use_docker=False)
    assert not r.ok
    assert any("검증 명령 실패" in p for p in r.problems)


def test_smoke_gate_requires_interaction_markers(tmp_path):
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "index.html").write_text("<html><body>정적 페이지</body></html>", encoding="utf-8")
    (ws / "src" / "a.js").write_text("var a = 1;", encoding="utf-8")
    (ws / "src" / "b.js").write_text("var b = 2;", encoding="utf-8")
    manifest = {"project_type": "static_web", "entrypoint": "index.html", "files": []}
    r = run_smoke_gate(ws, manifest, [], use_docker=False)
    assert not r.ok
    assert any("상호작용 최소 기준" in p for p in r.problems)
