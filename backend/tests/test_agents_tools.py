from __future__ import annotations

import pytest
from app.agents import build_tool_registry
from app.agents.assistant.graph import build_assistant_graph
from app.agents.assistant.nodes import AssistantNodes
from app.agents.assistant.state import AssistantState
from app.agents.assistant.tool_selection import ToolSelector
from app.agents.tools.system.current_time import CurrentTimeTool
from app.ai.models import AiChatResult
from app.ai.prompts import PromptRegistry
from app.core.cache import cache_backend


class _StubAiClient:
    def __init__(self, contents: list[str]):
        self._contents = list(contents)

    async def chat(self, request, *_, **__):
        content = self._contents.pop(0) if self._contents else "mock:ok"
        return AiChatResult(
            content=content,
            provider="mock",
            model="stub-model",
            latency_ms=0.1,
            usage_tokens=0,
            raw={},
            trace_id="stub-trace",
        )


class _StaticSelector:
    def __init__(self, tool: str | None, args: dict):
        self._tool = tool
        self._args = args

    async def select_tool(self, state: AssistantState):
        return self._tool, self._args, "static"


class _StubMemoryService:
    async def search_memory(self, *_, **__):
        return []

    async def write_memory(self, *_, **__):
        return "mem-id"


class _StubTripService:
    def get_trip(self, *_):
        class Trip:
            user_id = 1
            day_cards: list = []

            def model_dump(self, mode: str = "json"):
                return {"title": "demo", "day_cards": []}

        return Trip()


class _StubPoiService:
    async def get_poi_around(self, **kwargs):
        return (
            [
                {
                    "name": "Stub POI",
                    "provider": "mock",
                    "provider_id": "stub",
                    "lat": 0.0,
                    "lng": 0.0,
                    "distance_m": 10,
                }
            ],
            {"source": "mock"},
        )


def test_tool_registry_contains_expected_tools():
    registry = build_tool_registry()
    assert set(registry.names()) == {
        "current_time",
        "path_navigate",
        "area_weather",
        "weather_search",
        "fast_search",
        "deep_search",
        "deep_extract",
    }
    assert registry.failures() == {}


def test_current_time_tool_outputs_fields():
    tool = CurrentTimeTool()
    result = tool._run()
    assert "current_time" in result
    assert "timestamp" in result


@pytest.mark.asyncio
async def test_tool_selector_prefers_model_json():
    registry = build_tool_registry()
    model_reply = (
        '{"tool": "current_time", "arguments": {"timezone": "UTC"}, '
        '"reason": "time question"}'
    )
    selector = ToolSelector(
        ai_client=_StubAiClient([model_reply]),
        prompt_registry=PromptRegistry(),
        tool_registry=registry,
    )
    state = AssistantState(
        user_id=1,
        trip_id=None,
        session_id=None,
        query="现在几点",
        top_k=3,
    )
    name, args, reason = await selector.select_tool(state)
    assert name == "current_time"
    assert args.get("timezone") == "UTC"
    assert reason


@pytest.mark.asyncio
async def test_tool_selector_cache_reuses_llm_result():
    cache_backend.invalidate("assistant_tool_select")
    registry = build_tool_registry()
    model_reply = '{"tool": "current_time", "arguments": {}, "reason": "cached"}'
    selector = ToolSelector(
        ai_client=_StubAiClient([model_reply]),
        prompt_registry=PromptRegistry(),
        tool_registry=registry,
    )
    state = AssistantState(
        user_id=1,
        trip_id=None,
        session_id=42,
        query="现在几点",
        top_k=3,
    )
    first = await selector.select_tool(state)
    second = await selector.select_tool(state)
    assert first == second


@pytest.mark.asyncio
async def test_assistant_graph_runs_with_tool_execution():
    registry = build_tool_registry()
    ai_client = _StubAiClient(['{"intent": "general_qa"}', "mock:final"])
    selector = _StaticSelector("current_time", {})
    nodes = AssistantNodes(
        ai_client=ai_client,
        memory_service=_StubMemoryService(),
        prompt_registry=PromptRegistry(),
        trip_service=_StubTripService(),
        tool_selector=selector,
        tool_registry=registry,
        poi_service=_StubPoiService(),
    )
    graph = build_assistant_graph(nodes)
    state = AssistantState(
        user_id=99,
        trip_id=None,
        session_id=1,
        query="现在几点",
        use_memory=False,
        top_k=3,
        history=[],
    )
    result_state = await graph.ainvoke(state)
    if isinstance(result_state, dict):
        result_state = AssistantState(**result_state)
    assert result_state.selected_tool == "current_time"
    assert result_state.tool_result is not None
    assert any(
        t["node"] == "tool_execute" and t["status"] == "ok"
        for t in result_state.tool_traces
    )
