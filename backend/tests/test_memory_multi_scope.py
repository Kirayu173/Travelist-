from __future__ import annotations

import pytest
from app.agents.assistant.nodes_memory import search_memories_multi_scope
from app.ai.memory_models import MemoryItem, MemoryLevel
from app.core.cache import cache_backend


class _StubMemoryService:
    async def search_memory(
        self,
        user_id: int,
        level: MemoryLevel,
        query: str,
        *,
        trip_id: int | None = None,
        session_id: str | None = None,
        k: int | None = None,
    ) -> list[MemoryItem]:
        if level is MemoryLevel.session:
            return [MemoryItem(id="m1", text="session", score=0.9)]
        if level is MemoryLevel.trip:
            return [
                MemoryItem(id="m1", text="trip-dup", score=0.8),
                MemoryItem(id="m2", text="trip", score=0.7),
            ]
        return [MemoryItem(id="m3", text="user", score=0.6)]


@pytest.mark.asyncio
async def test_search_memories_multi_scope_dedups_and_orders() -> None:
    cache_backend.invalidate("assistant_memory")
    items, counts = await search_memories_multi_scope(
        memory_service=_StubMemoryService(),
        user_id=1,
        trip_id=2,
        session_id=3,
        query="hello",
        top_k=3,
    )
    assert counts["session"] == 1
    assert counts["trip"] == 2
    assert counts["user"] == 1
    assert [item.id for item in items] == ["m1", "m2", "m3"]
    assert items[0].text == "session"

