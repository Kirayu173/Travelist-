from __future__ import annotations

from datetime import datetime, timezone
from typing import Awaitable, Callable, Literal

from pydantic import BaseModel, Field, field_validator

ChatRole = Literal["system", "user", "assistant"]
ResponseFormat = Literal["text", "json"]


class AiMessage(BaseModel):
    role: ChatRole
    content: str

    @field_validator("content")
    @classmethod
    def ensure_content(cls, value: str) -> str:
        if not value.strip():
            msg = "message content is required"
            raise ValueError(msg)
        return value


class AiChatRequest(BaseModel):
    messages: list[AiMessage]
    response_format: ResponseFormat = "text"
    timeout_s: float = Field(default=30.0, ge=1.0, le=120.0)
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=8192)

    @field_validator("messages")
    @classmethod
    def ensure_messages(cls, value: list[AiMessage]) -> list[AiMessage]:
        if not value:
            msg = "at least one message is required"
            raise ValueError(msg)
        return value


class AiChatResult(BaseModel):
    content: str
    provider: str
    model: str
    latency_ms: float
    usage_tokens: int | None = None
    raw: dict | None = None
    trace_id: str
    finished_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AiStreamChunk(BaseModel):
    trace_id: str
    delta: str
    index: int
    done: bool = False


StreamCallback = Callable[[AiStreamChunk], Awaitable[None] | None]
