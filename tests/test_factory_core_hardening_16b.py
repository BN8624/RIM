# Phase 1.6b gate 보강 테스트: Core Contract wiring·Product Layer 소비·Green/Continuation·Build Review 재계산·validate·live validation (§12).
import json
from pathlib import Path

import pytest

from repo_idea_miner.config import Settings
from repo_idea_miner.factory_core_gates import (
    action_wiring,
    augment_core_contract_runtime,
    product_layer_consumes_core,
    run_core_contract_gate,
    strip_comments,
)
from repo_idea_miner.factory_core_pipeline import run_core_factory
from repo_idea_miner.factory_core_prompts import (
    mock_broken_core_build_output,
    mock_core_build_output,
    mock_core_contract_draft,
    mock_core_factory_overrides,
)
from repo_idea_miner.factory_core_schemas import (
    build_live_validation_summary,
    verdict_consistency,
)
from repo_idea_miner.factory_db import open_factory_db
from repo_idea_miner.factory_pipeline import FactorySettings, sample_challenge
from repo_idea_miner.factory_validate import validate_product_run_dir
from repo_idea_miner.llm_client import LLMCallLogger, MockLLMClient

from tests.test_factory_core_gates import build_mock_workspace

TIMEOUT = 60.0
FSET = FactorySettings(use_docker="off", sandbox_timeout_seconds=60.0)
SETTINGS = Settings(google_keys={})


def _run(tmp_path, overrides=None, db=False, mode="mock", live_validation=False, llm=None):
    conn = open_factory_db(tmp_path / "challenge.db") if db else None
    llm = llm or MockLLMClient(overrides={**mock_core_factory_overrides(), **(overrides or {})},
                               call_logger=LLMCallLogger(None))
    result = run_core_factory(
        sample_challenge(), mode=mode, output_dir=tmp_path / "runs",
        db_conn=conn, settings=SETTINGS, factory_settings=FSET, llm=llm,
        live_validation=live_validation,
    )
    return result, llm


# ---------------------------------------------------------------- Scenario review clip (live 검증에서 발견한 약점)

def test_scenario_review_prompt_keeps_large_but_complete_bundle():
    """live 검증 발견: 큰(그러나 완전한) scenario/golden 번들이 review 프롬프트에서 잘려
    scenario가 '절단됐다'고 오판되면 안 된다."""
    from repo_idea_miner.factory_core_prompts import build_scenario_golden_review_prompt

    scenarios = [{"id": f"scenario_{i:03d}", "title": f"case {i}", "case_type": "normal",
                  "actions": [{"type": "execute_graph", "payload": {"x": "y" * 1800}}]}
                 for i in range(1, 7)]
    goldens = [{"scenario_id": f"scenario_{i:03d}", "expected_final_state": {"v": i},
                "comparison_mode": "exact"} for i in range(1, 7)]
    bundle = json.dumps({"scenarios": scenarios, "goldens": goldens}, ensure_ascii=False)
    assert 9000 < len(bundle) <= 16000  # 과거 9000 clip이면 잘렸을 크기
    prompt = build_scenario_golden_review_prompt("{}", bundle)
    assert "scenario_006" in prompt  # 마지막 scenario가 프롬프트에 온전히 포함
    assert "[길이 제한으로 잘렸습니다]" not in prompt


# ---------------------------------------------------------------- Core Contract Gate wiring (§12-1~4)

def test_action_wiring_classifies_context():
    assert action_wiring("def execute_command():\n pass", "def execute_command():\n pass",
                         "execute_command") == "callable"
    assert action_wiring('if t == "follow_up":', 'if t == "follow_up":', "follow_up") == "dispatch"
    assert action_wiring('handlers = {"run_step": fn}', 'handlers = {"run_step": fn}',
                         "run_step") == "dispatch"
    # §12-2: 주석에만 있으면 comment_only (stripped에서 사라짐)
    assert action_wiring("", "# execute_command 는 나중에", "execute_command") == "comment_only"
    # §12-4: dispatch/정의 없이 장식용 문자열만 → weak
    assert action_wiring('notes = ["execute_command is planned"]',
                         'notes = ["execute_command is planned"]', "execute_command") == "weak"
    assert action_wiring("", "", "execute_command") == "absent"


def test_strip_comments_keeps_dispatch_strings():
    py = 'x = "execute_command"  # 이건 주석 execute_command_note\n'
    stripped = strip_comments(py, ".py")
    assert '"execute_command"' in stripped  # dispatch 문자열 보존
    assert "execute_command_note" not in stripped  # 주석 제거


def test_core_contract_gate_passes_on_wired_mock(tmp_path):
    ws, core, runner, _ = build_mock_workspace(tmp_path)
    assert run_core_contract_gate(ws, core, runner).ok


def test_core_contract_gate_fails_when_action_only_in_comment(tmp_path):
    """§12-2: action name이 주석에만 있으면 FAIL."""
    ws, core, runner, _ = build_mock_workspace(tmp_path / "c")
    # engine을 action name이 주석에만 등장하는 stub으로 덮어쓴다 (entity 키는 유지)
    (ws / "src" / "core" / "engine.py").write_text(
        "# execute_command 와 follow_up 핸들러는 아직 미구현\n"
        "def apply_action(state, action):\n"
        "    state['history'] = []\n"
        "    state['tick'] = 0\n"
        "    state['history_count'] = 0\n"
        "    return state, [], []\n",
        encoding="utf-8",
    )
    r = run_core_contract_gate(ws, core, runner)
    assert not r.ok
    assert any("주석에만" in p for p in r.problems)


def test_core_contract_gate_fails_when_runner_does_not_import_core(tmp_path):
    """§12-3: runner가 core 모듈을 import하지 않으면 FAIL(dead core)."""
    build = mock_core_build_output()
    for f in build["files"]:
        if f["path"] == "src/runner.py":
            f["content"] = f["content"].replace("from core import engine  # noqa: E402",
                                                "# (core import 제거됨) engine 사용 안 함")
    ws, core, runner, _ = build_mock_workspace(tmp_path / "d", build=build)
    r = run_core_contract_gate(ws, core, runner)
    assert not r.ok
    assert any("import/require" in p for p in r.problems)


def test_augment_runtime_flags_unreflected_entity():
    """§12-5 흐름: runner 출력 final_state에 entity가 반영되지 않으면 core_contract gate 실패."""
    from repo_idea_miner.factory_gates import GateResult

    core = mock_core_contract_draft()["core_contract"]
    good = {"s1": {"parsed": {"final_state": {"history": [], "tick": 0, "history_count": 0}}}}
    r_good = GateResult(name="Core Contract Gate", ok=True)
    augment_core_contract_runtime(r_good, core, good)
    assert r_good.ok, r_good.problems

    bad = {"s1": {"parsed": {"final_state": {"unrelated": 1}}}}
    r_bad = GateResult(name="Core Contract Gate", ok=True)
    augment_core_contract_runtime(r_bad, core, bad)
    assert not r_bad.ok
    assert any("final_state에 반영되지 않음" in p for p in r_bad.problems)


# ---------------------------------------------------------------- Product Layer 소비 (§12-6~9)

_GOOD_PRODUCT = {
    "product/viewer/index.html": "<div id=app></div>",
    "product/viewer/viewer.js": (
        'const r = await fetch("../../replay/index.json");\n'
        'el.textContent = data.summary;\n'
        'stateEl.textContent = JSON.stringify(data.final_state);\n'
        '(data.events||[]).forEach(render);\n'
    ),
}


def test_product_layer_consumes_pass():
    """§12-7,8: replay/index.json 참조 + final_state/events/summary ≥2 → 통과."""
    assert product_layer_consumes_core(_GOOD_PRODUCT) == []


def test_product_layer_replay_string_only_fails():
    """§12-6: replay 문자열만 있고 실제 접근이 없으면 FAIL."""
    files = {"product/viewer/app.js": (
        "// 이 뷰어는 replay 결과를 보여줍니다 (실제로는 안 읽음)\n"
        "const final_state = demo; const summary = 'x';\n"
    )}
    problems = product_layer_consumes_core(files)
    assert any("실제로 읽지 않음" in p for p in problems)


def test_product_layer_too_few_fields_fails():
    """§12-8: final_state/events/summary 중 1개만 사용하면 FAIL."""
    files = {"product/v.js": 'fetch("../../replay/index.json").then(r=>r.json());\n'
                             'el.textContent = data.summary;\n'}
    problems = product_layer_consumes_core(files)
    assert any("< 2" in p for p in problems)


def test_product_layer_fake_state_only_fails():
    """§12-9: replay 접근 없이 fake state만 있으면 FAIL."""
    files = {"product/v.js": "const final_state={a:1}; const events=[]; const summary='canned';\n"}
    problems = product_layer_consumes_core(files)
    assert any("실제로 읽지 않음" in p for p in problems)


def test_large_viewer_consumption_not_truncated(tmp_path):
    """live #47 발견: CSS 뒤 <script>의 replay fetch가 짧은 read로 잘려 false-negative 나면 안 된다."""
    from repo_idea_miner.factory_core_gates import PRODUCT_READ_LIMIT, product_layer_consumes_core
    from repo_idea_miner.factory_workspace import read_workspace_file, write_workspace_file

    ws = tmp_path / "ws"
    ws.mkdir()
    big_css = "\n".join(f".n{i} {{ color: #{i:06d}; padding: 4px; }}" for i in range(120))  # 3000자 이상
    html = (f"<style>{big_css}</style>\n<body><div id=app></div>\n<script>\n"
            "const d = await fetch('../../replay/index.json').then(r=>r.json());\n"
            "el.textContent = d.summary; render(d.final_state); (d.events||[]).forEach(show);\n"
            "</script></body>")
    write_workspace_file(ws, "product/viewer/index.html", html, [])
    assert len(html) > 3300 and html.find("replay/index.json") > 3000  # fetch가 3000 뒤에 있음
    files = {"product/viewer/index.html": read_workspace_file(ws, "product/viewer/index.html", PRODUCT_READ_LIMIT)}
    assert product_layer_consumes_core(files) == []  # 전체를 읽어 소비로 판정
    truncated = {"product/viewer/index.html": read_workspace_file(ws, "product/viewer/index.html", 3000)}
    assert product_layer_consumes_core(truncated)  # 짧게 자르면 놓침(회귀 가드)


def test_product_layer_core_logic_duplication_fails():
    """§5.4: product가 core action 로직을 복제하면 FAIL."""
    files = {"product/v.js": (
        'fetch("../../replay/index.json");\n'
        'function execute_command(s){ return s; }\n'
        'el.textContent = data.summary; render(data.final_state);\n'
    )}
    core = mock_core_contract_draft()["core_contract"]
    problems = product_layer_consumes_core(files, core)
    assert any("복제" in p for p in problems)


# ---------------------------------------------------------------- verdict 정직성 (§12-19)

def test_verdict_consistency_catches_dishonest_review_ready():
    gates_fail = {"core_contract": True, "runner": True, "scenario_replay": True,
                  "golden_output": False, "state_invariant": True, "determinism": True,
                  "anti_hardcode": True}
    honest, issues = verdict_consistency("REVIEW_READY", gates_fail, "low", "PASS", True, 3)
    assert not honest and any("gate 일부 실패" in i for i in issues)

    gates_ok = {g: True for g in gates_fail}
    honest2, issues2 = verdict_consistency("REVIEW_READY", gates_ok, "low", "PASS", True, 3)
    assert honest2 and not issues2


def test_build_live_validation_summary_has_honest_field():
    gates_ok = {g: True for g in ("core_contract", "runner", "scenario_replay", "golden_output",
                                  "state_invariant", "determinism", "anti_hardcode")}
    out = build_live_validation_summary("47", 3, "REVIEW_READY", gates_ok, "low", "PASS", True, 3, ["x"])
    lv = out["live_validation"]
    assert "verdict_is_honest" in lv and lv["verdict_is_honest"] is True
    assert lv["challenge_id"] == "47" and lv["gate_hardening_applied"] == ["x"]


# ---------------------------------------------------------------- Green vs Continuation Base (§12-10~12)

def test_green_base_only_on_full_pass(tmp_path):
    """§12-10: 전 gate 통과 시 green_base 생성, continuation 없음."""
    result, _ = _run(tmp_path)
    assert all(result["gate_summary"].values())
    assert result["green_base_path"] and Path(result["green_base_path"]).is_dir()
    assert result["continuation_base_path"] is None
    run_dir = Path(result["run_dir"])
    assert (run_dir / "green_base.json").is_file()
    assert not (run_dir / "continuation_base.json").is_file()


def test_continuation_base_when_partial_but_patchable(tmp_path):
    """§12-11: 일부 gate 실패지만 patchable이면 continuation_base 생성(green 아님)."""
    broken = mock_broken_core_build_output()
    broken_patch = {"files": [f for f in broken["files"] if f["path"] == "src/core/engine.py"],
                    "patch_report": "여전히 깨진 patch"}
    result, _ = _run(tmp_path, overrides={"core_build": broken, "patch_repair": broken_patch})
    assert not all(result["gate_summary"].values())
    assert result["verdict"] == "NEEDS_MORE_GEMMA_LOOP"
    assert result["green_base_path"] is None
    assert result["continuation_base_path"] and Path(result["continuation_base_path"]).is_dir()
    run_dir = Path(result["run_dir"])
    assert (run_dir / "continuation_base.json").is_file()
    assert not (run_dir / "green_base.json").is_file()


def test_dashboard_summary_distinguishes_bases(tmp_path):
    """§12-12: green_base/continuation_base가 dashboard_summary에서 구분된다."""
    result, _ = _run(tmp_path)
    dsum = json.loads((Path(result["run_dir"]) / "dashboard_summary.json").read_text(encoding="utf-8"))
    assert dsum["green_base"] is True
    assert dsum["continuation_base"] is False
    assert dsum["product_layer_consumes_core"] is True


# ---------------------------------------------------------------- Build Review 재계산 (§12-13,14)

class _RecordingLLM(MockLLMClient):
    """desk별 프롬프트를 기록하는 mock (Build Review 재계산 검증용)."""

    def __init__(self, overrides):
        super().__init__(overrides=overrides, call_logger=LLMCallLogger(None))
        self.prompts: dict[str, list[str]] = {}

    def generate_json(self, prompt, schema_name, **kw):
        self.prompts.setdefault(schema_name, []).append(prompt)
        return super().generate_json(prompt, schema_name, **kw)


def test_build_review_recomputed_after_patch(tmp_path):
    """§12-13,14: patch 후 Build Review가 재계산되고 최신 gate 결과를 반영한다."""
    llm = _RecordingLLM(overrides={**mock_core_factory_overrides(),
                                   "core_build": mock_broken_core_build_output()})
    result, _ = _run(tmp_path, llm=llm)
    assert result["patch_attempts"] == 1
    # 초기 1회 + patch마다 1회 재계산
    assert len(llm.prompts["build_review"]) == result["patch_attempts"] + 1
    first, second = llm.prompts["build_review"][0], llm.prompts["build_review"][1]
    assert "(exact) 불일치" in first  # patch 전: golden 실패가 리뷰 입력에 있음
    assert "(exact) 불일치" not in second  # patch 후 재계산: 실패가 해소된 최신 gate 기준
    harness = json.loads((Path(result["run_dir"]) / "harness_summary.json").read_text(encoding="utf-8"))
    assert harness["stages"]["repair"]["build_review_recomputes"] == 1


# ---------------------------------------------------------------- live validation summary (§12-18,19)

def test_live_validation_summary_written(tmp_path):
    """§12-18,19: live 검증 run은 verdict_is_honest 포함 요약을 생성한다."""
    result, _ = _run(tmp_path, live_validation=True)
    run_dir = Path(result["run_dir"])
    lv_path = run_dir / "live_validation_summary.json"
    assert lv_path.is_file()
    lv = json.loads(lv_path.read_text(encoding="utf-8"))["live_validation"]
    assert lv["verdict"] == result["verdict"]
    assert lv["verdict_is_honest"] is True  # mock 완주는 전 gate 통과 → 정직
    assert lv["gate_hardening_applied"]
    # final_artifact에도 복사됨
    assert (Path(result["final_artifact_dir"]) / "live_validation_summary.json").is_file()
    # dashboard_summary에 live 표시
    dsum = json.loads((run_dir / "dashboard_summary.json").read_text(encoding="utf-8"))
    assert dsum["is_live_validation"] is True


def test_no_live_validation_summary_by_default(tmp_path):
    result, _ = _run(tmp_path)
    assert not (Path(result["run_dir"]) / "live_validation_summary.json").is_file()
    dsum = json.loads((Path(result["run_dir"]) / "dashboard_summary.json").read_text(encoding="utf-8"))
    assert dsum["is_live_validation"] is False


# ---------------------------------------------------------------- factory-validate 정합성 (§12-15~17)

@pytest.fixture(scope="module")
def core_run(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("val16b")
    conn = open_factory_db(tmp_path / "challenge.db")
    llm = MockLLMClient(overrides=mock_core_factory_overrides(), call_logger=LLMCallLogger(None))
    result = run_core_factory(
        sample_challenge(), mode="mock", output_dir=tmp_path / "runs",
        db_conn=conn, settings=SETTINGS, factory_settings=FSET, llm=llm,
    )
    conn.close()
    assert result["ok"], result["error"]
    return result


def test_core_run_validates(core_run):
    """§12-15: final_artifact 기준 파일 존재·실행 가능 검사 통과."""
    ok, problems = validate_product_run_dir(core_run["run_dir"], [])
    assert ok, problems


def test_workspace_final_mismatch_fails(core_run, tmp_path):
    """§12-16: workspace에는 있는데 final_artifact에 없으면 실패."""
    import shutil

    copy = tmp_path / "mm"
    shutil.copytree(core_run["run_dir"], copy)
    (copy / "final_artifact" / "README.md").unlink()  # workspace에는 남아있음
    ok, problems = validate_product_run_dir(copy, [])
    assert not ok
    assert any("final_artifact에 없음" in p for p in problems)


def test_run_instructions_bad_path_fails(core_run, tmp_path):
    """§12-17: run_instructions가 없는 경로를 가리키면 실패."""
    import shutil

    copy = tmp_path / "ri"
    shutil.copytree(core_run["run_dir"], copy)
    ri = copy / "final_artifact" / "run_instructions.md"
    ri.write_text("# 실행\n```bash\npython src/ghost_runner.py --scenario fixtures/scenario_001.json\n```\n",
                  encoding="utf-8")
    ok, problems = validate_product_run_dir(copy, [])
    assert not ok
    assert any("없는 경로를 가리킴" in p and "ghost_runner.py" in p for p in problems)
