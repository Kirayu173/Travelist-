from __future__ import annotations

import pytest
from app.models.ai_schemas import ChatPayload
from app.services.assistant_service import AssistantService


@pytest.mark.asyncio
async def test_assistant_handles_poi_intent(monkeypatch):
    service = AssistantService()
    payload = ChatPayload(
        user_id=1,
        query="附近有什么好吃的",
        use_memory=False,
        location={"lat": 23.12908, "lng": 113.26436},
        poi_radius=500,
    )

    # 避免消息落库在此用例中放缓测试
    monkeypatch.setattr(service, "_persist_messages", lambda **kwargs: None)

    result = await service.run_chat(payload)
    assert result.intent in {"poi_nearby", "general_qa"}
    assert any(trace["node"] == "poi" for trace in result.tool_traces)
