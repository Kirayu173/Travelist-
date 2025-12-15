from __future__ import annotations

import datetime as dt

import pytest
from app.agents import build_tool_registry
from app.agents.assistant.graph import build_assistant_graph
from app.agents.assistant.nodes import AssistantNodes
from app.agents.assistant.state import AssistantState
from app.agents.assistant.weather_query import build_weather_query_spec
from app.ai.models import AiChatResult
from app.ai.prompts import PromptRegistry


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


class _StubMemoryService:
    async def search_memory(self, *_, **__):
        return []


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
        return ([], {"source": "mock"})


class _StubSelector:
    async def select_tool(self, state: AssistantState):
        return None, {}, "stub"


def _now_shanghai_date() -> dt.date:
    try:
        from zoneinfo import ZoneInfo

        return dt.datetime.now(ZoneInfo("Asia/Shanghai")).date()
    except Exception:  # pragma: no cover
        return dt.date.today()


def test_weather_query_spec_tomorrow_guangzhou():
    base = dt.date(2025, 12, 14)
    spec = build_weather_query_spec("明天广州天气怎么样", base_date=base)
    assert spec.locations == ["广州"]
    assert spec.day_offset == 1
    assert spec.target_date == dt.date(2025, 12, 15)


@pytest.mark.asyncio
async def test_assistant_graph_weather_direct_uses_tomorrow_date(monkeypatch):
    monkeypatch.setenv("AMAP_API_KEY", "")
    try:
        from app.agents.tools.weather import area_weather as area_weather_mod

        area_weather_mod._api_key = None
        area_weather_mod._initialized = False
    except Exception:
        pass

    registry = build_tool_registry()
    ai_client = _StubAiClient(['{"intent": "general_qa"}'])
    # Force fallback path if any; direct weather still triggers before fallback.
    nodes = AssistantNodes(
        ai_client=ai_client,
        memory_service=_StubMemoryService(),
        prompt_registry=PromptRegistry(),
        trip_service=_StubTripService(),
        tool_selector=_StubSelector(),
        tool_registry=registry,
        poi_service=_StubPoiService(),
    )
    graph = build_assistant_graph(nodes)
    state = AssistantState(
        user_id=99,
        trip_id=None,
        session_id=1,
        query="明天广州天气怎么样",
        use_memory=False,
        top_k=3,
        history=[],
    )
    result_state = await graph.ainvoke(state)
    if isinstance(result_state, dict):
        result_state = AssistantState(**result_state)

    expected_date = (_now_shanghai_date() + dt.timedelta(days=1)).isoformat()
    assert result_state.selected_tool == "area_weather"
    assert "广州" in (result_state.answer_text or "")
    assert expected_date in (result_state.answer_text or "")
    assert any(
        t.get("node") == "tool_execute" and t.get("tool") == "area_weather"
        for t in result_state.tool_traces
    )
