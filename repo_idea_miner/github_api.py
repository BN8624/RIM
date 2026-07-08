# GitHub REST API로 metadata/README/issues/PR/file tree/dependency evidence를 수집하는 모듈.
# Collector는 risk 판단을 하지 않고 evidence origin만 기록한다.
from __future__ import annotations

import base64
import json
import re

import requests

from repo_idea_miner.errors import (
    GitHubAuthError,
    GitHubError,
    GitHubRateLimitError,
    RepoNotFoundError,
)
from repo_idea_miner.sampler import build_body_sample
from repo_idea_miner.signals import tag_issue

API_BASE = "https://api.github.com"

BOT_AUTHORS = {
    "dependabot[bot]",
    "renovate[bot]",
    "github-actions[bot]",
    "pre-commit-ci[bot]",
    "dependabot-preview[bot]",
}

BOT_TITLE_PATTERNS = [
    "bump",
    "update dependency",
    "chore(deps)",
    "chore(deps-dev)",
    "deps:",
    "build(deps)",
    "build(deps-dev)",
]

MAINTAINER_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}

DEPENDENCY_FILES = [
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "Cargo.toml",
    "go.mod",
    "Dockerfile",
    "docker-compose.yml",
    "Makefile",
]

RISK_KEYWORDS = [
    "docker", "kubernetes", "redis", "postgres", "mysql", "mongodb", "playwright",
    "selenium", "torch", "tensorflow", "cuda", "openai", "anthropic", "stripe",
    "auth", "oauth", "s3", "aws", "gcp", "azure", "queue", "worker", "browser",
    "native", "binding",
]


class GitHubClient:
    """얇은 GitHub REST 클라이언트. 실패 유형별로 프로젝트 예외를 던진다."""

    def __init__(self, token: str | None = None, session: requests.Session | None = None, timeout: float = 30.0):
        self.token = token
        self.session = session or requests.Session()
        self.timeout = timeout

    def _headers(self, accept: str = "application/vnd.github+json") -> dict:
        headers = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _raise_for(self, resp: requests.Response, path: str) -> None:
        if resp.status_code == 404:
            raise RepoNotFoundError(f"not found: {path}")
        if resp.status_code == 401:
            raise GitHubAuthError("GitHub API 인증 실패 (401)")
        if resp.status_code == 403:
            if resp.headers.get("X-RateLimit-Remaining") == "0":
                raise GitHubRateLimitError("GitHub rate limit 초과")
            raise GitHubAuthError("GitHub API 접근 거부 (403)")
        if resp.status_code >= 400:
            raise GitHubError(f"GitHub API 오류 {resp.status_code}: {path}")

    def get_json(self, path: str, params: dict | None = None):
        resp = self.session.get(API_BASE + path, params=params, headers=self._headers(), timeout=self.timeout)
        self._raise_for(resp, path)
        return resp.json()

    def get_optional_json(self, path: str, params: dict | None = None):
        try:
            return self.get_json(path, params)
        except RepoNotFoundError:
            return None

    def get_optional_raw(self, path: str) -> str | None:
        resp = self.session.get(
            API_BASE + path, headers=self._headers("application/vnd.github.raw+json"), timeout=self.timeout
        )
        if resp.status_code == 404:
            return None
        self._raise_for(resp, path)
        return resp.text


# ---------------------------------------------------------------- metadata

def collect_metadata(gh: GitHubClient, owner: str, repo: str) -> dict:
    data = gh.get_json(f"/repos/{owner}/{repo}")
    languages = gh.get_optional_json(f"/repos/{owner}/{repo}/languages") or {}
    return {
        "owner": owner,
        "repo": data.get("name") or repo,
        "full_name": data.get("full_name") or f"{owner}/{repo}",
        "description": data.get("description"),
        "stars": data.get("stargazers_count", 0),
        "forks": data.get("forks_count", 0),
        "watchers": data.get("subscribers_count", data.get("watchers_count", 0)),
        "topics": data.get("topics", []),
        "primary_language": data.get("language"),
        "languages": list(languages.keys()),
        "updated_at": data.get("updated_at"),
        "created_at": data.get("created_at"),
        "pushed_at": data.get("pushed_at"),
        "archived": data.get("archived", False),
        "disabled": data.get("disabled", False),
        "fork": data.get("fork", False),
        "is_template": data.get("is_template", False),
        "mirror_url": data.get("mirror_url"),
        "open_issues_count": data.get("open_issues_count", 0),
        "license": (data.get("license") or {}).get("spdx_id") if data.get("license") else None,
        "homepage": data.get("homepage"),
        "default_branch": data.get("default_branch", "main"),
        "size": data.get("size", 0),
        "html_url": data.get("html_url"),
    }


# ---------------------------------------------------------------- README

README_SIGNAL_PATTERNS = {
    "install": ["install", "설치", "pip install", "npm install", "cargo install"],
    "usage_example": ["usage", "example", "quick start", "quickstart", "getting started", "사용법", "예제"],
    "features": ["feature", "기능"],
    "demo_or_docs": ["demo", "screenshot", "docs", "documentation", "https://"],
    "api": ["api"],
    "docker": ["docker"],
    "external_services": RISK_KEYWORDS,
}


def collect_readme(gh: GitHubClient, owner: str, repo: str) -> tuple[str, str | None]:
    """(status, text). README 없으면 실패가 아니라 MISSING."""
    text = gh.get_optional_raw(f"/repos/{owner}/{repo}/readme")
    if text is None:
        return "MISSING", None
    return "OK", text


def readme_signals(text: str | None) -> dict:
    if not text:
        return {"status": "MISSING"}
    lower = text.lower()
    external = sorted({k for k in RISK_KEYWORDS if k in lower})
    return {
        "status": "OK",
        "length": len(text),
        "has_install": any(k in lower for k in README_SIGNAL_PATTERNS["install"]),
        "has_usage_example": any(k in lower for k in README_SIGNAL_PATTERNS["usage_example"]),
        "has_features": any(k in lower for k in README_SIGNAL_PATTERNS["features"]),
        "has_demo_or_docs_link": any(k in lower for k in README_SIGNAL_PATTERNS["demo_or_docs"]),
        "mentions_api": "api" in lower,
        "mentions_docker": "docker" in lower,
        "external_service_keywords": external,
    }


# ---------------------------------------------------------------- issues

def filter_issue_items(items: list[dict]) -> list[dict]:
    """PR이 issue 목록에 섞이면 제외한다 (pull_request key 존재)."""
    return [it for it in items if "pull_request" not in it]


def _is_bot_login(login: str | None) -> bool:
    return bool(login) and login.endswith("[bot]")


def analyze_comments(issue: dict, comments: list[dict] | None) -> dict:
    """comments 목록에서 unique commenter / maintainer ratio / bike-shedding 신호를 계산한다."""
    comments_count = issue.get("comments", 0)
    labels = [l.get("name", "").lower() for l in issue.get("labels", []) if isinstance(l, dict)]
    result = {
        "comments_count": comments_count,
        "unique_commenters_count": None,
        "maintainer_comment_ratio": None,
        "bot_comment_count": None,
        "bike_shedding_possible": False,
    }
    discussion_labels = bool({"discussion", "design", "proposal"} & set(labels))
    if comments is None:
        # comments 미수집: label 기반 최소 신호만
        result["bike_shedding_possible"] = discussion_labels and comments_count >= 10
        return result

    human = [c for c in comments if not _is_bot_login((c.get("user") or {}).get("login"))]
    bots = len(comments) - len(human)
    unique = len({(c.get("user") or {}).get("login") for c in human if c.get("user")})
    maintainer = sum(1 for c in human if c.get("author_association") in MAINTAINER_ASSOCIATIONS)
    ratio = round(maintainer / len(human), 2) if human else 0.0

    bike = False
    if comments_count >= 10 and unique <= 3:
        bike = True
    if comments_count >= 10 and ratio >= 0.6:
        bike = True
    if discussion_labels and comments_count >= 10:
        bike = True

    result.update(
        unique_commenters_count=unique,
        maintainer_comment_ratio=ratio,
        bot_comment_count=bots,
        bike_shedding_possible=bike,
    )
    return result


def build_issue_record(issue: dict, comments: list[dict] | None = None) -> dict:
    body = issue.get("body") or ""
    sample = build_body_sample(body)
    tags = tag_issue(issue.get("title", ""), body)
    rec = {
        "title": issue.get("title"),
        "number": issue.get("number"),
        "url": issue.get("html_url"),
        "state": issue.get("state"),
        "labels": [l.get("name") for l in issue.get("labels", []) if isinstance(l, dict)],
        "updated_at": issue.get("updated_at"),
        "created_at": issue.get("created_at"),
        "closed_at": issue.get("closed_at"),
        "body_sample": sample,
        "signal_tags": tags,
    }
    rec.update(analyze_comments(issue, comments))
    return rec


def collect_issues(gh: GitHubClient, owner: str, repo: str, max_issues: int = 10) -> dict:
    """3개 bucket: 최근 open 5 / high-comment open 3 / 최근 closed 3."""
    base = f"/repos/{owner}/{repo}/issues"
    open_items = filter_issue_items(
        gh.get_optional_json(base, {"state": "open", "sort": "updated", "per_page": 30}) or []
    )
    closed_items = filter_issue_items(
        gh.get_optional_json(base, {"state": "closed", "sort": "updated", "per_page": 15}) or []
    )

    recent_open = open_items[:5]
    high_comment = sorted(open_items, key=lambda x: x.get("comments", 0), reverse=True)
    recent_nums = {i.get("number") for i in recent_open}
    high_comment = [i for i in high_comment if i.get("comments", 0) > 0][:3]
    recent_closed = closed_items[:3]

    def records(items, fetch_comments=False):
        out = []
        for it in items:
            comments = None
            if fetch_comments and it.get("comments", 0) > 0:
                comments = gh.get_optional_json(
                    f"{base}/{it['number']}/comments", {"per_page": 50}
                )
            out.append(build_issue_record(it, comments))
        return out

    buckets = {
        "recent_open": records(recent_open),
        "high_comment_open": records(high_comment, fetch_comments=True),
        "recent_closed": records(recent_closed),
    }
    seen: set[int] = set()
    all_records: list[dict] = []
    for bucket in buckets.values():
        for r in bucket:
            if r["number"] not in seen:
                seen.add(r["number"])
                all_records.append(r)
    buckets["all_records"] = all_records[:max_issues]
    buckets["status"] = "OK" if all_records else "MISSING"
    return buckets


# ---------------------------------------------------------------- PRs

def is_bot_pr(pr: dict) -> bool:
    login = ((pr.get("user") or {}).get("login") or "").lower()
    if login in {b.lower() for b in BOT_AUTHORS} or login.endswith("[bot]"):
        return True
    title = (pr.get("title") or "").lower()
    return any(title.startswith(p) or p in title for p in BOT_TITLE_PATTERNS)


def split_prs(prs: list[dict]) -> tuple[list[dict], list[dict]]:
    """(human_prs, excluded_bot_prs)."""
    human, excluded = [], []
    for pr in prs:
        (excluded if is_bot_pr(pr) else human).append(pr)
    return human, excluded


def collect_prs(gh: GitHubClient, owner: str, repo: str, max_prs: int = 10) -> dict:
    items = gh.get_optional_json(
        f"/repos/{owner}/{repo}/pulls", {"state": "all", "sort": "updated", "direction": "desc", "per_page": 30}
    ) or []
    human, excluded = split_prs(items)

    def slim(pr):
        return {
            "title": pr.get("title"),
            "number": pr.get("number"),
            "author": (pr.get("user") or {}).get("login"),
            "state": pr.get("state"),
            "updated_at": pr.get("updated_at"),
            "url": pr.get("html_url"),
        }

    return {
        "status": "OK" if items else "MISSING",
        "human": [slim(p) for p in human[:max_prs]],
        "excluded_bot": [slim(p) for p in excluded[:max_prs]],
    }


# ---------------------------------------------------------------- file tree

DOC_PATH_HINTS = ("docs", "examples", "demo", "example")


def collect_file_tree(gh: GitHubClient, owner: str, repo: str, default_branch: str, depth: int = 2) -> dict:
    data = gh.get_optional_json(f"/repos/{owner}/{repo}/git/trees/{default_branch}", {"recursive": "1"})
    if not data or "tree" not in data:
        return {"status": "MISSING", "paths": [], "docs_examples_demo": [], "truncated": False}
    paths = []
    doc_paths = []
    for entry in data["tree"]:
        path = entry.get("path", "")
        if path.count("/") < depth:
            paths.append(path + ("/" if entry.get("type") == "tree" else ""))
        first = path.split("/", 1)[0].lower()
        if first in DOC_PATH_HINTS:
            doc_paths.append(path)
    return {
        "status": "OK",
        "paths": sorted(paths)[:400],
        "docs_examples_demo": sorted(doc_paths)[:50],
        "truncated": bool(data.get("truncated")),
    }


# ---------------------------------------------------------------- dependency evidence

ORIGIN_VALUES = [
    "README_ONLY", "DOCS_ONLY", "DEV_TEST", "OPTIONAL", "RUNTIME",
    "SCRIPT_ENTRYPOINT", "DOCKER_LOCAL", "CONFIG_ONLY", "UNKNOWN",
]


def parse_package_json(text: str) -> list[dict]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [{"file": "package.json", "name": "(파싱 실패)", "origin": "UNKNOWN"}]
    entries = []
    for name in (data.get("dependencies") or {}):
        entries.append({"file": "package.json", "name": name, "origin": "RUNTIME"})
    for name in (data.get("devDependencies") or {}):
        entries.append({"file": "package.json", "name": name, "origin": "DEV_TEST"})
    for name in (data.get("optionalDependencies") or {}):
        entries.append({"file": "package.json", "name": name, "origin": "OPTIONAL"})
    return entries


def parse_pyproject(text: str) -> list[dict]:
    import tomllib

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return [{"file": "pyproject.toml", "name": "(파싱 실패)", "origin": "UNKNOWN"}]
    entries = []
    project = data.get("project") or {}
    for dep in project.get("dependencies") or []:
        entries.append({"file": "pyproject.toml", "name": str(dep), "origin": "RUNTIME"})
    for group, deps in (project.get("optional-dependencies") or {}).items():
        origin = "DEV_TEST" if group.lower() in ("dev", "test", "tests", "lint", "typing") else "OPTIONAL"
        for dep in deps:
            entries.append({"file": "pyproject.toml", "name": str(dep), "origin": origin})
    # poetry 스타일
    poetry = ((data.get("tool") or {}).get("poetry") or {})
    for name in (poetry.get("dependencies") or {}):
        if name.lower() != "python":
            entries.append({"file": "pyproject.toml", "name": name, "origin": "RUNTIME"})
    for name in ((poetry.get("group") or {}).get("dev", {}).get("dependencies") or {}):
        entries.append({"file": "pyproject.toml", "name": name, "origin": "DEV_TEST"})
    return entries


def parse_requirements(text: str, filename: str = "requirements.txt") -> list[dict]:
    origin = "DEV_TEST" if ("dev" in filename or "test" in filename) else "RUNTIME"
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-r", "--")):
            continue
        name = re.split(r"[<>=!~\[;]", line, maxsplit=1)[0].strip()
        if name:
            entries.append({"file": filename, "name": name, "origin": origin})
    return entries


def classify_docker(readme_text: str | None, has_dockerfile: bool, has_compose: bool) -> dict | None:
    """Docker evidence origin 분류. keyword만으로 high risk를 만들지 않는다."""
    if not has_dockerfile and not has_compose:
        return None
    lower = (readme_text or "").lower()
    docker_central = False
    for marker in ("docker run", "docker compose up", "docker-compose up", "docker build"):
        if marker in lower:
            docker_central = True
            break
    if docker_central:
        origin = "SCRIPT_ENTRYPOINT"
        note = "README 설치/실행 경로가 Docker 중심"
    elif has_compose and not has_dockerfile:
        origin = "DOCKER_LOCAL"
        note = "docker-compose.yml만 존재, runtime entrypoint와 연결 근거 없음"
    else:
        origin = "DOCKER_LOCAL"
        note = "Dockerfile 존재하나 README에서 필수 실행 경로로 설명되지 않음"
    return {
        "has_dockerfile": has_dockerfile,
        "has_compose": has_compose,
        "origin": origin,
        "note": note,
    }


def scan_risk_keywords(entries: list[dict], readme_text: str | None) -> list[dict]:
    hits = []
    for e in entries:
        name = (e.get("name") or "").lower()
        for kw in RISK_KEYWORDS:
            if kw in name:
                hits.append({"keyword": kw, "where": e["file"], "origin": e["origin"]})
    lower = (readme_text or "").lower()
    for kw in RISK_KEYWORDS:
        if kw in lower:
            hits.append({"keyword": kw, "where": "README", "origin": "README_ONLY"})
    # 중복 제거
    seen = set()
    unique = []
    for h in hits:
        key = (h["keyword"], h["where"], h["origin"])
        if key not in seen:
            seen.add(key)
            unique.append(h)
    return unique


def collect_dependency_evidence(gh: GitHubClient, owner: str, repo: str, readme_text: str | None) -> dict:
    files_found = []
    entries: list[dict] = []
    contents: dict[str, str] = {}
    for filename in DEPENDENCY_FILES:
        text = gh.get_optional_raw(f"/repos/{owner}/{repo}/contents/{filename}")
        if text is None:
            continue
        files_found.append(filename)
        contents[filename] = text[:100_000]

    if not files_found:
        return {"status": "not_collected", "files_found": [], "entries": [], "docker": None, "risk_keyword_hits": scan_risk_keywords([], readme_text)}

    if "package.json" in contents:
        entries += parse_package_json(contents["package.json"])
    if "pyproject.toml" in contents:
        entries += parse_pyproject(contents["pyproject.toml"])
    if "requirements.txt" in contents:
        entries += parse_requirements(contents["requirements.txt"])
    if "Cargo.toml" in contents:
        entries.append({"file": "Cargo.toml", "name": "(Cargo 프로젝트)", "origin": "RUNTIME"})
    if "go.mod" in contents:
        entries.append({"file": "go.mod", "name": "(Go 프로젝트)", "origin": "RUNTIME"})
    if "Makefile" in contents:
        entries.append({"file": "Makefile", "name": "(Makefile 존재)", "origin": "SCRIPT_ENTRYPOINT"})

    docker = classify_docker(readme_text, "Dockerfile" in contents, "docker-compose.yml" in contents)
    return {
        "status": "OK",
        "files_found": files_found,
        "entries": entries[:200],
        "docker": docker,
        "risk_keyword_hits": scan_risk_keywords(entries, readme_text),
    }


# ---------------------------------------------------------------- search

def search_repositories(gh: GitHubClient, query: str, limit: int = 30, explore: bool = False) -> list[dict]:
    params = {"q": query, "per_page": min(limit, 100)}
    if explore:
        params["sort"] = "updated"
    data = gh.get_json("/search/repositories", params)
    return (data.get("items") or [])[:limit]
