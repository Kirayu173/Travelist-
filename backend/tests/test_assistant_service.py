from __future__ import annotations

import json

import pytest
from app.ai.memory_models import MemoryLevel
from app.models.ai_schemas import ChatPayload, ChatResult
from app.services.assistant_service import AssistantService
from app.utils.serialization import sanitize_for_json


class _StubMemoryService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def write_memory(
        self,
        user_id: int,
        level: MemoryLevel,
        text: str,
        *,
        trip_id: int | None = None,
        session_id: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        self.calls.append(
            {
                "user_id": user_id,
                "level": level,
                "trip_id": trip_id,
                "session_id": session_id,
                "metadata": metadata or {},
                "text": text,
            }
        )
        return {
            MemoryLevel.session: "stub-session-id",
            MemoryLevel.trip: "stub-trip-id",
            MemoryLevel.user: "stub-user-id",
        }.get(level, "stub-record-id")


@pytest.mark.asyncio
async def test_write_memory_uses_trip_scope_when_no_session(monkeypatch):
    stub = _StubMemoryService()
    service = AssistantService(memory_service=stub)
    payload = ChatPayload(
        user_id=1,
        trip_id=7,
        session_id=None,
        query="查询行程",
        use_memory=True,
    )

    # bypass DB interactions
    monkeypatch.setattr(service, "_persist_messages", lambda **kwargs: None)
    monkeypatch.setattr(service, "_load_history", lambda session_id: [])
    monkeypatch.setattr(service, "_ensure_session", lambda payload: None)

    record = await service._write_memory(payload=payload, session_id=99, answer="答复")
    assert record == "stub-session-id"
    levels = [call["level"] for call in stub.calls]
    assert MemoryLevel.session in levels
    assert MemoryLevel.trip in levels


@pytest.mark.asyncio
async def test_write_memory_prefers_session_when_client_supplied(monkeypatch):
    stub = _StubMemoryService()
    service = AssistantService(memory_service=stub)
    payload = ChatPayload(
        user_id=2,
        trip_id=3,
        session_id=101,
        query="session 级别",
        use_memory=True,
    )

    monkeypatch.setattr(service, "_persist_messages", lambda **kwargs: None)
    monkeypatch.setattr(service, "_load_history", lambda session_id: [])
    monkeypatch.setattr(service, "_ensure_session", lambda payload: None)

    await service._write_memory(payload=payload, session_id=101, answer="答复")
    levels = [call["level"] for call in stub.calls]
    assert MemoryLevel.session in levels
    assert MemoryLevel.trip in levels


@pytest.mark.asyncio
async def test_write_memory_defaults_to_user_level(monkeypatch):
    stub = _StubMemoryService()
    service = AssistantService(memory_service=stub)
    payload = ChatPayload(
        user_id=5,
        trip_id=None,
        session_id=None,
        query="用户级",
        use_memory=True,
    )

    monkeypatch.setattr(service, "_persist_messages", lambda **kwargs: None)
    monkeypatch.setattr(service, "_load_history", lambda session_id: [])
    monkeypatch.setattr(service, "_ensure_session", lambda payload: None)

    await service._write_memory(payload=payload, session_id=0, answer="答复")
    levels = [call["level"] for call in stub.calls]
    assert MemoryLevel.session in levels
    assert MemoryLevel.user in levels


def test_sanitize_tool_result_makes_payload_json_serializable() -> None:
    class _Msg:
        def __init__(self, content: str) -> None:
            self.content = content
            self.type = "assistant"

    raw = {"messages": [_Msg("hello")]}
    sanitized = sanitize_for_json(raw)
    result = ChatResult(
        session_id=1,
        answer="ok",
        intent="general_qa",
        used_memory=[],
        tool_traces=[],
        ai_meta={},
        messages=[],
        tool_result=sanitized,
    )
    json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
