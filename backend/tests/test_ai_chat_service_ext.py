from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.ai import MemoryItem
from app.ai.memory_models import MemoryLevel
from app.models.ai_schemas import ChatDemoPayload
from app.services.ai_chat_service import AiChatDemoService


@dataclass
class _FakeAiResponse:
    content: str = "mock: hi"
    provider: str = "mock"
    model: str = "stub-model"
    latency_ms: float = 12.3
    usage_tokens: int = 5
    trace_id: str = "ai-stub"


class _FakeAiClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def chat(self, request, on_chunk=None):
        self.calls.append({"request": request, "on_chunk": on_chunk})
        if on_chunk:
            await on_chunk(type("Chunk", (), {"delta": "part", "trace_id": "ai-stub"}))
        return _FakeAiResponse()


class _FakeMemoryService:
    def __init__(self) -> None:
        self.search_calls: list[dict] = []
        self.write_calls: list[dict] = []

    async def search_memory(self, **kwargs):
        self.search_calls.append(kwargs)
        return [
            MemoryItem(id="m1", text="记忆1", score=0.9, metadata={"level": "user"})
        ]

    async def write_memory(self, user_id, level, text, **kwargs):
        self.write_calls.append(
            {"user_id": user_id, "level": level, "text": text, **kwargs}
        )
        return "mem-written"


def test_chat_demo_uses_memory_and_writes_back():
    ai_client = _FakeAiClient()
    memory_service = _FakeMemoryService()
    service = AiChatDemoService(ai_client=ai_client, memory_service=memory_service)

    payload = ChatDemoPayload(
        user_id=1,
        trip_id=None,
        session_id=None,
        level=MemoryLevel.user,
        query="你好",
        use_memory=True,
        return_memory=True,
        stream=False,
    )
    result = asyncio.get_event_loop().run_until_complete(service.run_chat(payload))

    assert result.answer.startswith("mock:")
    assert memory_service.search_calls, "should perform memory search"
    assert memory_service.write_calls, "should write memory after answer"
    assert result.used_memory, "should return retrieved memories"


def test_chat_demo_streams_chunks_when_requested():
    ai_client = _FakeAiClient()
    memory_service = _FakeMemoryService()
    service = AiChatDemoService(ai_client=ai_client, memory_service=memory_service)
    payload = ChatDemoPayload(
        user_id=2,
        trip_id=None,
        session_id=None,
        level=MemoryLevel.user,
        query="stream test",
        use_memory=False,
        return_memory=False,
        stream=True,
    )

    chunks: list[str] = []

    async def _on_chunk(chunk):
        chunks.append(chunk.delta)

    payload_dict = payload.model_dump()
    # run stream path
    result = asyncio.get_event_loop().run_until_complete(
        service.run_chat(payload.copy(update={"stream": True}), stream_handler=_on_chunk)
    )
    assert chunks, "stream handler should receive chunks"
    assert result.answer
