from __future__ import annotations

from typing import Any

from app.ai.memory_models import MemoryItem, MemoryLevel
from pydantic import BaseModel, ConfigDict, Field


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
    memory_level: MemoryLevel | None = None

    selected_tool: str | None = None
    selected_tool_reason: str | None = None
    tool_args: dict[str, Any] = Field(default_factory=dict)
    tool_result: Any | None = None
    tool_error: str | None = None
    available_tools: list[str] = Field(default_factory=list)

    answer_text: str | None = None
    tool_traces: list[dict[str, Any]] = Field(default_factory=list)
    ai_meta: dict[str, Any] | None = None

    model_config = ConfigDict(extra="allow")
