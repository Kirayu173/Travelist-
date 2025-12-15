from __future__ import annotations

import json
from typing import Any


def sanitize_for_json(
    value: Any,
    *,
    depth: int = 0,
    max_depth: int = 5,
    max_items: int = 50,
    max_str: int = 4000,
) -> Any:
    """
    Convert arbitrary objects into JSON-serializable structures.

    Assistant/tool outputs may include custom objects (e.g. LangChain messages)
    that are not directly serializable by Pydantic/JSON.
    """

    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= max_str else value[:max_str] + "…"
    if depth >= max_depth:
        return {"type": value.__class__.__name__, "repr": repr(value)[:max_str]}

    if isinstance(value, dict):
        payload: dict[str, Any] = {}
        for idx, (key, item) in enumerate(value.items()):
            if idx >= max_items:
                payload["__truncated__"] = True
                break
            normalized_key = key if isinstance(key, str) else str(key)
            payload[normalized_key] = sanitize_for_json(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
                max_str=max_str,
            )
        return payload

    if isinstance(value, (list, tuple, set)):
        items = list(value)
        truncated = False
        if len(items) > max_items:
            items = items[:max_items]
            truncated = True
        payload = [
            sanitize_for_json(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
                max_str=max_str,
            )
            for item in items
        ]
        if truncated:
            payload.append({"__truncated__": True})
        return payload

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="json")
        except TypeError:
            dumped = model_dump()
        return sanitize_for_json(
            dumped,
            depth=depth + 1,
            max_depth=max_depth,
            max_items=max_items,
            max_str=max_str,
        )

    as_dict = getattr(value, "dict", None)
    if callable(as_dict):
        try:
            dumped = as_dict()
        except Exception:
            dumped = None
        if dumped is not None:
            return sanitize_for_json(
                dumped,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
                max_str=max_str,
            )

    content = getattr(value, "content", None)
    if isinstance(content, str):
        payload = {
            "type": value.__class__.__name__,
            "content": content if len(content) <= max_str else content[:max_str] + "…",
        }
        role = getattr(value, "type", None) or getattr(value, "role", None)
        if isinstance(role, str):
            payload["role"] = role
        return payload

    return {"type": value.__class__.__name__, "repr": repr(value)[:max_str]}


def json_preview(value: Any, *, max_len: int = 400) -> str:
    """Return a compact preview string suitable for logs/prompt context."""

    try:
        payload = sanitize_for_json(value)
        text = json.dumps(payload, ensure_ascii=False)
    except Exception:
        text = repr(value)
    return text if len(text) <= max_len else text[:max_len] + "…"

