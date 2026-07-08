# issue 본문에서 앞/끝/키워드 주변 문맥을 조합해 body_sample(최대 1500자)을 만드는 모듈.
from __future__ import annotations

import re

from repo_idea_miner.signals import ALL_SAMPLER_KEYWORDS

MAX_SAMPLE_CHARS = 1500
HEAD_CHARS = 500
TAIL_CHARS = 500
KEYWORD_CTX_CHARS = 500
SEPARATOR = "\n[...]\n"

TEMPLATE_SECTION_HEADS = [
    "environment",
    "system info",
    "os",
    "python version",
    "node version",
    "package version",
    "logs",
    "checklist",
]

_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)


def _compress_code_blocks(body: str, keep_head: int = 200, keep_tail: int = 100, threshold: int = 400) -> str:
    def repl(m: re.Match) -> str:
        block = m.group(0)
        if len(block) <= threshold:
            return block
        return block[:keep_head] + "\n[로그 압축됨]\n" + block[-keep_tail:]

    return _CODE_BLOCK_RE.sub(repl, body)


def compress_template_sections(body: str) -> str:
    """Environment/Logs 등 템플릿성 섹션이 너무 길면 압축한다. 완전히 삭제하지는 않는다."""
    body = _compress_code_blocks(body)
    lines = body.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip().lstrip("#*").strip().rstrip(":").lower()
        if stripped in TEMPLATE_SECTION_HEADS:
            # 다음 헤딩 또는 빈 줄 전까지만 섹션으로 본다 (뒤의 실제 내용을 삼키지 않도록)
            j = i + 1
            while j < len(lines) and lines[j].strip() and not lines[j].strip().startswith(("#", "**")):
                j += 1
            section = "\n".join(lines[i + 1 : j])
            out.append(line)
            if len(section) > 200:
                out.append(section[:120] + "\n[템플릿 섹션 압축됨]")
            else:
                out.append(section)
            i = j
        else:
            out.append(line)
            i += 1
    return "\n".join(out)


def _keyword_contexts(body: str, max_chars: int = KEYWORD_CTX_CHARS, window: int = 120) -> str:
    lower = body.lower()
    spans: list[tuple[int, int]] = []
    for kw in ALL_SAMPLER_KEYWORDS:
        start = 0
        k = kw.lower()
        while True:
            pos = lower.find(k, start)
            if pos < 0:
                break
            spans.append((max(0, pos - window), min(len(body), pos + len(k) + window)))
            start = pos + len(k)
            if len(spans) > 40:
                break
        if len(spans) > 40:
            break
    if not spans:
        return ""
    spans.sort()
    merged: list[list[int]] = [list(spans[0])]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    pieces = []
    total = 0
    for s, e in merged:
        piece = body[s:e].strip()
        if not piece:
            continue
        if total + len(piece) > max_chars:
            piece = piece[: max_chars - total]
        pieces.append(piece)
        total += len(piece)
        if total >= max_chars:
            break
    return " … ".join(pieces)


def build_body_sample(body: str | None, max_total: int = MAX_SAMPLE_CHARS) -> str:
    """앞부분 + 키워드 주변 문맥 + 끝부분을 조합해 최대 1500자 sample을 만든다."""
    if not body:
        return ""
    body = compress_template_sections(body.strip())
    head = body[:HEAD_CHARS]
    tail_start = max(HEAD_CHARS, len(body) - TAIL_CHARS)
    tail = body[tail_start:] if len(body) > HEAD_CHARS else ""
    kw_ctx = _keyword_contexts(body)

    parts = [head]
    if kw_ctx:
        # head/tail에 이미 완전히 포함된 문맥은 중복 제거
        if kw_ctx not in head and kw_ctx not in tail:
            parts.append(kw_ctx)
    if tail:
        parts.append(tail)
    sample = SEPARATOR.join(p for p in parts if p)
    return sample[:max_total]
