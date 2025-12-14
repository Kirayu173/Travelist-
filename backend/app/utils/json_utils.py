from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, set):
        return list(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return value.value
    return str(value)


def json_dumps(value: Any, **kwargs: Any) -> str:
    """`json.dumps` with sane defaults for common non-JSON types."""

    kwargs.setdefault("ensure_ascii", False)
    kwargs.setdefault("default", _json_default)
    return json.dumps(value, **kwargs)
