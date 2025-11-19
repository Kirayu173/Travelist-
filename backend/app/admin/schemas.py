from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

HttpMethod = Literal["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"]


class ApiTestRequest(BaseModel):
    method: HttpMethod = "GET"
    path: str
    query: dict[str, Any] | None = None
    path_params: dict[str, Any] | None = None
    headers: dict[str, str] | None = None
    json_body: dict[str, Any] | None = None
    timeout_ms: int = Field(5000, ge=100, le=60000)

    @field_validator("method", mode="before")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        return value.upper()

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if not value:
            msg = "path is required"
            raise ValueError(msg)
        if value.startswith("http://") or value.startswith("https://"):
            msg = "absolute URLs are not allowed"
            raise ValueError(msg)
        if not value.startswith("/"):
            value = f"/{value}"
        return value


class ApiTestResult(BaseModel):
    status_code: int | None
    duration_ms: float
    ok: bool
    response_headers: dict[str, str]
    response_body_excerpt: str | None = None
    error: str | None = None


class ApiTestCase(BaseModel):
    name: str
    method: HttpMethod
    path: str
    description: str | None = None
    query: dict[str, Any] | None = None
    path_params: dict[str, Any] | None = None
    json_body: dict[str, Any] | None = None


class DataCheckResult(BaseModel):
    name: str
    level: Literal["info", "warn", "error"]
    status: Literal["pass", "fail", "unknown"]
    detail: str
    suggestion: str | None = None
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
