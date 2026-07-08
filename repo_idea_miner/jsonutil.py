# LLM 출력에서 JSON 추출·syntax repair를 담당하는 모듈. 누락 필드 창작은 하지 않는다.
from __future__ import annotations

import json
import re

_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n?|\n?```\s*$", re.MULTILINE)


def strip_markdown_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        # 첫 fence 줄 제거
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*\n?", "", text)
    if text.rstrip().endswith("```"):
        text = re.sub(r"\n?```\s*$", "", text.rstrip())
    return text.strip()


def extract_json_object(text: str) -> str | None:
    """앞뒤 설명 문장을 버리고 첫 번째 최상위 JSON object 문자열만 추출한다."""
    if not text:
        return None
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def repair_json_syntax(s: str) -> str:
    """허용된 syntax repair만 수행한다: fence 제거, trailing comma 제거, smart quote 교정.

    새 필드 창작, 값 변경은 절대 하지 않는다.
    """
    s = strip_markdown_fences(s)
    extracted = extract_json_object(s)
    if extracted is not None:
        s = extracted
    # smart quotes -> ASCII quotes
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    # trailing commas: ,] / ,}
    s = re.sub(r",\s*([\]}])", r"\1", s)
    return s


def parse_json_with_repair(text: str, repair_attempts: int = 1) -> tuple[dict | None, bool]:
    """(parsed_dict | None, repair_used)를 반환한다."""
    candidate = strip_markdown_fences(text or "")
    extracted = extract_json_object(candidate)
    if extracted is not None:
        candidate = extracted
    try:
        obj = json.loads(candidate)
        if isinstance(obj, dict):
            return obj, False
        return None, False
    except (json.JSONDecodeError, TypeError):
        pass
    repair_used = False
    for _ in range(max(0, repair_attempts)):
        repair_used = True
        candidate = repair_json_syntax(text or "")
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj, True
            return None, True
        except (json.JSONDecodeError, TypeError):
            continue
    return None, repair_used
