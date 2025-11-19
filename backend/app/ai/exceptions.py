from __future__ import annotations


class AiClientError(Exception):
    """Normalized AI provider error."""

    def __init__(
        self,
        error_type: str,
        message: str,
        *,
        status_code: int | None = None,
        trace_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.type = error_type
        self.message = message
        self.status_code = status_code
        self.trace_id = trace_id
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "message": self.message,
            "status_code": self.status_code,
            "trace_id": self.trace_id,
            "details": self.details,
        }
