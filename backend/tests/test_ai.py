from __future__ import annotations

import pytest
from app.ai import AiChatRequest, AiMessage, MemoryLevel, get_ai_client
from app.services.memory_service import MemoryService


@pytest.mark.asyncio
async def test_ai_client_mock_provider_streams_chunks(configure_admin_and_ai) -> None:
    client = get_ai_client()
    chunks: list[str] = []

    async def on_chunk(chunk):
        chunks.append(chunk.delta)

    result = await client.chat(
        AiChatRequest(messages=[AiMessage(role="user", content="测试 streaming")]),
        on_chunk=on_chunk,
    )
    assert result.content.startswith("mock:")
    assert result.trace_id.startswith("ai-")
    assert chunks, "should receive at least one chunk"


@pytest.mark.asyncio
async def test_memory_service_fallback_roundtrip(configure_admin_and_ai) -> None:
    service = MemoryService()
    record_id = await service.write_memory(
        user_id=99,
        level=MemoryLevel.user,
        text="Q: 喜欢登山\nA: 记得准备登山鞋",
    )
    assert record_id
    results = await service.search_memory(
        user_id=99,
        level=MemoryLevel.user,
        query="登山",
        k=3,
    )
    assert results
    assert any("登山鞋" in item.text for item in results)
