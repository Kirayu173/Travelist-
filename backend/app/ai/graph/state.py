from __future__ import annotations

from typing import Any

from app.ai.memory_models import MemoryItem
from pydantic import BaseModel, Field


class AssistantState(BaseModel):
    user_id: int
    trip_id: int | None = None
    session_id: int | None = None
    query: str
    intent: str | None = None

    use_memory: bool = True
    top_k: int = 5
    history: list[dict[str, Any]] = Field(default_factory=list)
    memories: list[MemoryItem] = Field(default_factory=list)
    trip_data: dict[str, Any] | None = None

    answer_text: str | None = None
    tool_traces: list[dict[str, Any]] = Field(default_factory=list)
    ai_meta: dict[str, Any] | None = None
