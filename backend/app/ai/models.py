from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ChatRole = Literal["system", "user", "assistant", "tool"]
ResponseFormat = Literal["text", "json"]
ToolType = Literal["function"]


class AiToolFunction(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class AiToolCall(BaseModel):
    type: ToolType = "function"
    id: str | None = None
    function: AiToolFunction


class AiMessage(BaseModel):
    role: ChatRole
    content: str = ""
    tool_calls: list[AiToolCall] | None = None
    tool_call_id: str | None = None

    @field_validator("tool_call_id")
    @classmethod
    def normalize_tool_call_id(cls, value: str | None) -> str | None:
        text = (value or "").strip()
        return text or None

    @model_validator(mode="after")
    def validate_payload(self) -> "AiMessage":
        if self.role == "tool":
            if not self.tool_call_id:
                msg = "tool_call_id is required for tool messages"
                raise ValueError(msg)
            if not self.content.strip():
                msg = "tool message content is required"
                raise ValueError(msg)
            return self

        if self.tool_call_id:
            msg = "tool_call_id is only allowed for tool messages"
            raise ValueError(msg)

        if not self.content.strip() and not (self.tool_calls or []):
            msg = "message content is required"
            raise ValueError(msg)
        return self


class AiChatRequest(BaseModel):
    messages: list[AiMessage]
    response_format: ResponseFormat = "text"
    timeout_s: float = Field(default=30.0, ge=1.0, le=120.0)
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=8192)
    tools: list[dict[str, Any]] | None = None

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
