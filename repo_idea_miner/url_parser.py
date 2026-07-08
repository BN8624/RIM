# GitHub repo URL을 (owner, repo)로 파싱하는 모듈.
from __future__ import annotations

import re

from repo_idea_miner.errors import RIMError


class InvalidRepoURLError(RIMError):
    pass


_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/(?P<owner>[A-Za-z0-9_.\-]+)/(?P<repo>[A-Za-z0-9_.\-]+?)(?:\.git)?(?:/.*)?$"
)


def parse_repo_url(url: str) -> tuple[str, str]:
    """https://github.com/OWNER/REPO 형태를 (owner, repo)로 반환한다."""
    if not url or not isinstance(url, str):
        raise InvalidRepoURLError(f"잘못된 repo URL: {url!r}")
    m = _URL_RE.match(url.strip())
    if not m:
        raise InvalidRepoURLError(f"잘못된 repo URL: {url!r}")
    owner, repo = m.group("owner"), m.group("repo")
    if not owner or not repo:
        raise InvalidRepoURLError(f"잘못된 repo URL: {url!r}")
    return owner, repo
