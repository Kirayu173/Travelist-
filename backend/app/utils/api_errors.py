from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ApiErrorDetail:
    request_id: str
    error_type: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "error_type": self.error_type,
            "detail": self.detail,
        }


def format_exception(exc: Exception, *, request_id: str) -> ApiErrorDetail:
    return ApiErrorDetail(
        request_id=request_id,
        error_type=exc.__class__.__name__,
        detail=str(exc),
    )

