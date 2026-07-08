# judge 최종 JSON의 길이 초과를 실패가 아니라 안전한 축약으로 처리하는 모듈.
from __future__ import annotations

STRING_LIMITS = {
    "one_line_conclusion": 160,
    "why_people_cared": 400,
    "core_pattern": 300,
    "next_action": 120,
}

LIST_LIMITS = {
    "user_pain": (5, 180),
    "feature_requests": (5, 180),
    "workflow_pain": (5, 180),
    "what_to_ignore": (5, 180),
    "why_it_fails": (5, 180),
    "why_drop_or_keep": (5, 180),
}

NESTED_STRING_LIMITS = {
    ("dependency_runtime_risk", "reason"): 240,
    ("application", "reason"): 240,
    ("one_day_mvp", "reason"): 240,
    ("pattern_poc", "reason"): 240,
}

CEILING_LIST_LIMIT = 8


def _trunc(s: str, limit: int) -> tuple[str, bool]:
    if len(s) <= limit:
        return s, False
    return s[: max(0, limit - 3)].rstrip() + "...", True


def apply_length_limits(judge: dict) -> tuple[dict, list[str]]:
    """(truncated_dict, truncated_field_names). 구조는 바꾸지 않는다."""
    out = dict(judge)
    truncated: list[str] = []

    for field, limit in STRING_LIMITS.items():
        value = out.get(field)
        if isinstance(value, str):
            new, hit = _trunc(value, limit)
            if hit:
                out[field] = new
                truncated.append(field)

    for field, (max_items, item_limit) in LIST_LIMITS.items():
        value = out.get(field)
        if isinstance(value, list):
            items = value
            hit = False
            if len(items) > max_items:
                items = items[:max_items]
                hit = True
            new_items = []
            for item in items:
                if isinstance(item, str):
                    new, item_hit = _trunc(item, item_limit)
                    hit = hit or item_hit
                    new_items.append(new)
                else:
                    new_items.append(item)
            if hit:
                out[field] = new_items
                truncated.append(field)

    for (parent, child), limit in NESTED_STRING_LIMITS.items():
        obj = out.get(parent)
        if isinstance(obj, dict) and isinstance(obj.get(child), str):
            new, hit = _trunc(obj[child], limit)
            if hit:
                out[parent] = dict(obj)
                out[parent][child] = new
                truncated.append(f"{parent}.{child}")

    rules = out.get("ceiling_rules_applied")
    if isinstance(rules, list) and len(rules) > CEILING_LIST_LIMIT:
        out["ceiling_rules_applied"] = rules[:CEILING_LIST_LIMIT]
        truncated.append("ceiling_rules_applied")

    return out, truncated
