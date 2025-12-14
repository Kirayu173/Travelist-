from __future__ import annotations

import pytest
from app.agents import build_tool_registry
from app.agents.assistant.nodes import AssistantNodes
from app.agents.assistant.state import AssistantState
from app.ai.memory_models import MemoryItem
from app.ai.models import AiChatResult
from app.ai.prompts import PromptRegistry


class _CaptureAiClient:
    def __init__(self, reply: str):
        self._reply = reply
        self.last_request = None

    async def chat(self, request, *_, **__):
        self.last_request = request
        return AiChatResult(
            content=self._reply,
            provider="stub",
            model="stub-model",
            latency_ms=0.1,
            usage_tokens=0,
            raw={},
            trace_id="stub-trace",
        )


class _StubMemoryService:
    async def search_memory(self, *_, **__):
        return []


class _StubTripService:
    def get_trip(self, *_):
        raise AssertionError("not used in this test")


class _StubSelector:
    async def select_tool(self, state: AssistantState):
        return None, {}, "stub"


class _StubPoiService:
    async def get_poi_around(self, **kwargs):
        return ([], {"source": "mock"})


@pytest.mark.asyncio
async def test_response_formatter_uses_memory_when_tool_agent_no_tool_calls():
    ai_client = _CaptureAiClient("FINAL_ANSWER")
    nodes = AssistantNodes(
        ai_client=ai_client,
        memory_service=_StubMemoryService(),
        prompt_registry=PromptRegistry(),
        trip_service=_StubTripService(),
        tool_selector=_StubSelector(),
        tool_registry=build_tool_registry(),
        poi_service=_StubPoiService(),
        tool_agent=None,
    )
    state = AssistantState(
        user_id=1,
        trip_id=None,
        session_id=1,
        query="穿一件薄外套会冷吗",
        use_memory=True,
        top_k=3,
        history=[],
    )
    state.selected_tool = "create_agent"
    state.answer_text = "（工具智能体）需要城市和日期"
    state.memories = [
        MemoryItem(
            id="m1",
            score=0.67,
            text=(
                "Q: 明天广州天气怎么样 A: 广州明天（2025-12-15）的天气预报如下："
                "最高19°C，最低9°C"
            ),
        )
    ]

    result = await nodes.response_formatter_node(state)
    assert result.answer_text == "FINAL_ANSWER"
    assert ai_client.last_request is not None
    prompt_input = ai_client.last_request.messages[-1].content
    assert "记忆摘要" in prompt_input
    assert "广州" in prompt_input
    assert "工具智能体草稿回答" in prompt_input
