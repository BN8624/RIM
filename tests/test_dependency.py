# dependency evidence 테스트 (§34.8): origin 구분, Docker 오탐 방지.
from repo_idea_miner.github_api import (
    classify_docker,
    parse_package_json,
    parse_pyproject,
    parse_requirements,
)


def test_package_json_dep_split():
    text = '{"dependencies": {"react": "^18"}, "devDependencies": {"jest": "^29"}, "optionalDependencies": {"fsevents": "*"}}'
    entries = parse_package_json(text)
    origins = {e["name"]: e["origin"] for e in entries}
    assert origins["react"] == "RUNTIME"
    assert origins["jest"] == "DEV_TEST"
    assert origins["fsevents"] == "OPTIONAL"


def test_pyproject_groups_split():
    text = """
[project]
dependencies = ["requests>=2"]

[project.optional-dependencies]
dev = ["pytest"]
extra = ["rich"]
"""
    entries = parse_pyproject(text)
    origins = {e["name"].split(">")[0]: e["origin"] for e in entries}
    assert origins["requests"].startswith("RUNTIME")
    assert origins["pytest"] == "DEV_TEST"
    assert origins["rich"] == "OPTIONAL"


def test_requirements_collected():
    entries = parse_requirements("requests>=2.0\n# comment\nflask[async]==3.0\n")
    names = [e["name"] for e in entries]
    assert names == ["requests", "flask"]
    assert all(e["origin"] == "RUNTIME" for e in entries)


def test_dockerfile_only_not_high_risk():
    result = classify_docker(readme_text="A simple CLI tool. pip install and run.", has_dockerfile=True, has_compose=False)
    assert result["origin"] in ("DOCKER_LOCAL", "CONFIG_ONLY")


def test_compose_only_not_high_risk():
    result = classify_docker(readme_text=None, has_dockerfile=False, has_compose=True)
    assert result["origin"] == "DOCKER_LOCAL"


def test_docker_central_readme_raises_origin():
    result = classify_docker(
        readme_text="## Install\nRun `docker compose up` to start everything.",
        has_dockerfile=True,
        has_compose=True,
    )
    assert result["origin"] in ("SCRIPT_ENTRYPOINT", "RUNTIME")


def test_no_docker_returns_none():
    assert classify_docker("readme", False, False) is None
