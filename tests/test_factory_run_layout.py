# R1 run layout 정본 테스트 — artifact root 해석과 workspace-only child 지원.
from pathlib import Path

from repo_idea_miner.factory_run_layout import RunLayout, resolve_artifact_root, resolve_run_layout


def test_prefers_final_artifact(tmp_path):
    (tmp_path / "final_artifact").mkdir()
    (tmp_path / "workspace").mkdir()
    assert resolve_artifact_root(tmp_path) == tmp_path / "final_artifact"


def test_falls_back_to_workspace(tmp_path):
    (tmp_path / "workspace").mkdir()
    assert resolve_artifact_root(tmp_path) == tmp_path / "workspace"


def test_layout_fields(tmp_path):
    (tmp_path / "workspace").mkdir()
    layout = resolve_run_layout(tmp_path)
    assert isinstance(layout, RunLayout)
    assert layout.artifact_root_name == "workspace"
    assert layout.has_final_artifact is False
    assert layout.has_workspace is True
    assert layout.review_dir == tmp_path / "review"


def test_workspace_only_child_probe_root(tmp_path):
    """§8.3: workspace-only child를 final_artifact로 복제하지 않고 직접 읽는다."""
    from repo_idea_miner.factory_product_capabilities import build_capability_profile
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "core_contract.json").write_text(
        '{"state_entities": [{"name": "Graph"}], "actions": [{"name": "add_node"}]}',
        encoding="utf-8")
    (ws / "runner_contract.json").write_text(
        '{"runner_command": "python runner.py", "required_output_fields": ["ok"]}',
        encoding="utf-8")
    profile = build_capability_profile(tmp_path)
    assert profile["editable_entities"] == ["Graph"]
    assert profile["profile_sources"]["core_contract"] == "workspace/core_contract.json"
