# 산출물/로그에서 API key·토큰 등 secret을 제거(redaction)하는 모듈.
from __future__ import annotations

import re
from pathlib import Path

REDACTED = "[REDACTED]"

# 알려진 secret prefix 패턴 (값 자체를 몰라도 잡아낸다)
SECRET_PATTERNS = [
    re.compile(r"ghp_[A-Za-z0-9]{8,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{8,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"AQ\.[A-Za-z0-9_\-]{16,}"),
]


def redact_text(text: str, extra_values: tuple[str, ...] | list[str] = ()) -> str:
    """알려진 secret 값과 secret-like 패턴을 모두 치환한다."""
    if not text:
        return text
    for value in extra_values:
        if value:
            text = text.replace(value, REDACTED)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def contains_secret(text: str, extra_values: tuple[str, ...] | list[str] = ()) -> bool:
    if not text:
        return False
    for value in extra_values:
        if value and value in text:
            return True
    return any(p.search(text) for p in SECRET_PATTERNS)


def scan_files_for_secrets(paths: list[Path], extra_values: list[str] = ()) -> list[str]:
    """secret이 남아 있는 파일 경로 목록을 반환한다."""
    leaked = []
    for p in paths:
        try:
            content = Path(p).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if contains_secret(content, extra_values):
            leaked.append(str(p))
    return leaked
