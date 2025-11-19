from __future__ import annotations

from typing import Any

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
