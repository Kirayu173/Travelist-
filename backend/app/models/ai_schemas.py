from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from app.ai.memory_models import MemoryItem, MemoryLevel
from pydantic import BaseModel, Field, field_validator, model_validator


class ChatDemoPayload(BaseModel):
    user_id: int = Field(..., ge=1)
    trip_id: int | None = Field(default=None, ge=1)
    session_id: str | None = Field(default=None, max_length=64)
    level: MemoryLevel = MemoryLevel.user
    query: str = Field(..., min_length=1, max_length=2000)
    use_memory: bool = True
    top_k: int | None = Field(default=None, ge=1, le=20)
    return_memory: bool = True
    stream: bool = False
    system_prompt: str | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            msg = "query must not be empty"
            raise ValueError(msg)
        return value

    @field_validator("session_id")
    @classmethod
    def strip_session(cls, value: str | None) -> str | None:
        return value.strip() if value else value

    @model_validator(mode="after")
    def validate_scope(self) -> "ChatDemoPayload":
        if self.level is MemoryLevel.trip and not self.trip_id:
            msg = "trip_id is required when level=trip"
            raise ValueError(msg)
        if self.level is MemoryLevel.session and not self.session_id:
            msg = "session_id is required when level=session"
            raise ValueError(msg)
        return self


class ChatDemoResult(BaseModel):
    answer: str
    used_memory: list[MemoryItem] = Field(default_factory=list)
    ai_meta: dict[str, Any]
    memory_record_id: str | None = None


class ChatPayload(BaseModel):
    user_id: int = Field(..., ge=1)
    trip_id: int | None = Field(default=None, ge=1)
    session_id: int | None = Field(default=None, ge=1)
    query: str = Field(..., min_length=1, max_length=2000)
    use_memory: bool = True
    top_k_memory: int | None = Field(default=None, ge=1, le=20)
    return_memory: bool = True
    return_tool_traces: bool = True
    return_messages: bool = True
    stream: bool = False

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            msg = "query must not be empty"
            raise ValueError(msg)
        return value


class ChatMessageSchema(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: datetime


class ChatResult(BaseModel):
    session_id: int
    answer: str
    intent: str | None = None
    used_memory: list[MemoryItem] = Field(default_factory=list)
    tool_traces: list[dict[str, Any]] = Field(default_factory=list)
    ai_meta: dict[str, Any]
    messages: list[ChatMessageSchema] = Field(default_factory=list)
    memory_record_id: str | None = None


class PromptSchema(BaseModel):
    key: str
    title: str
    role: str
    content: str
    version: int
    tags: list[str] = Field(default_factory=list)
    is_active: bool
    updated_at: datetime | None = None
    updated_by: str | None = None
    default_content: str | None = None


class PromptUpdatePayload(BaseModel):
    title: str | None = None
    role: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    is_active: bool | None = None
    reset_default: bool = False
    updated_by: str | None = None
