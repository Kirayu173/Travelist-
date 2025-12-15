from __future__ import annotations

import json
from typing import Any


def sse_data(payload: dict[str, Any]) -> str:
    """Format a single Server-Sent Events data message."""

    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def sse_done() -> str:
    return "data: [DONE]\n\n"

