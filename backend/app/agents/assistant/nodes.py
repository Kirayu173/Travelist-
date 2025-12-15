from __future__ import annotations

import contextlib
import datetime as dt
import json
from typing import Any

from app.agents.assistant.nodes_memory import search_memories_multi_scope
from app.agents.assistant.nodes_rendering import (
    build_fallback_answer,
    guess_poi_type,
    render_history_block,
    summarize_memories,
    summarize_poi_results,
    summarize_tool_result,
    summarize_trip,
)
from app.agents.assistant.state import AssistantState
from app.agents.assistant.tool_selection import ToolSelector
from app.agents.assistant.weather_query import (
    WeatherQuerySpec,
    build_weather_query_spec,
)
from app.agents.tools.registry import ToolRegistry
from app.ai import AiChatRequest, AiClient, AiMessage
from app.ai.prompts import PromptRegistry
from app.core.logging import get_logger
from app.core.settings import settings
from app.services.memory_service import MemoryService
from app.services.poi_service import PoiService, PoiServiceError
from app.services.trip_service import TripQueryService


class AssistantNodes:
    """LangGraph nodes for the Travelist+ assistant."""

    def __init__(
        self,
        ai_client: AiClient,
        memory_service: MemoryService,
        prompt_registry: PromptRegistry,
        trip_service: TripQueryService,
        tool_selector: ToolSelector,
        tool_registry: ToolRegistry,
        poi_service: PoiService,
    ) -> None:
        self._ai_client = ai_client
        self._memory_service = memory_service
        self._prompt_registry = prompt_registry
        self._trip_service = trip_service
        self._tool_selector = tool_selector
        self._tool_registry = tool_registry
        self._logger = get_logger(__name__)
        self._poi_service = poi_service

    async def memory_read_node(self, state: AssistantState) -> AssistantState:
        self._logger.info(
            "node.enter.memory_read",
            extra={"user_id": state.user_id, "session_id": state.session_id},
        )
        if not state.use_memory:
            state.tool_traces.append({"node": "memory_read", "status": "skipped"})
            return state

        try:
            memories, scope_counts = await search_memories_multi_scope(
                memory_service=self._memory_service,
                user_id=state.user_id,
                trip_id=state.trip_id,
                session_id=state.session_id,
                query=state.query,
                top_k=state.top_k,
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.warning("memory.read_failed", extra={"error": str(exc)})
            state.tool_traces.append(
                {"node": "memory_read", "status": "error", "error": str(exc)}
            )
            return state

        state.memories = memories
        state.tool_traces.append(
            {
                "node": "memory_read",
                "status": "ok",
                "count": len(memories),
                "scopes": scope_counts,
            }
        )
        return state

    async def assistant_node(self, state: AssistantState) -> AssistantState:
        self._logger.info(
            "node.enter.assistant",
            extra={"user_id": state.user_id, "session_id": state.session_id},
        )
        prompt = self._prompt_registry.get_prompt("assistant.intent.classify")
        history_block = render_history_block(
            state.history, max_rounds=settings.ai_assistant_max_history_rounds
        )
        messages = [AiMessage(role=prompt.role, content=prompt.content)]
        if history_block:
            messages.append(AiMessage(role="system", content=history_block))
        messages.append(AiMessage(role="user", content=state.query))
        request = AiChatRequest(
            messages=messages,
            response_format="text",
            timeout_s=settings.ai_request_timeout_s,
        )
        result = await self._ai_client.chat(request)
        intent = self._infer_intent(result.content, state.query)
        state.intent = intent
        if intent and intent.startswith("poi"):
            inferred_type = guess_poi_type(state.query)
            state.poi_query = state.poi_query or {}
            if inferred_type and not state.poi_query.get("type"):
                state.poi_query["type"] = inferred_type
        state.ai_meta = {
            "provider": result.provider,
            "model": result.model,
            "latency_ms": result.latency_ms,
            "usage_tokens": result.usage_tokens,
            "trace_id": result.trace_id,
        }
        state.tool_traces.append(
            {"node": "assistant", "status": "ok", "intent": intent}
        )
        return state

    async def poi_node(self, state: AssistantState) -> AssistantState:
        self._logger.info(
            "node.enter.poi",
            extra={"user_id": state.user_id, "session_id": state.session_id},
        )
        poi_intents = {"poi_nearby", "poi_food", "poi_attraction", "poi_hotel"}
        if state.intent not in poi_intents:
            state.tool_traces.append(
                {"node": "poi", "status": "skipped", "reason": "intent_not_poi"}
            )
            return state
        if not state.location:
            state.tool_traces.append(
                {"node": "poi", "status": "error", "error": "missing_location"}
            )
            return state
        query = state.poi_query or {}
        poi_type = query.get("type")
        radius = query.get("radius")
        try:
            results, meta = await self._poi_service.get_poi_around(
                lat=float(state.location.get("lat")),
                lng=float(state.location.get("lng")),
                poi_type=poi_type,
                radius=radius,
                limit=query.get("limit") or 20,
            )
        except PoiServiceError as exc:
            state.tool_traces.append(
                {"node": "poi", "status": "error", "error": exc.message}
            )
            return state
        except Exception as exc:  # pragma: no cover - defensive
            state.tool_traces.append(
                {"node": "poi", "status": "error", "error": str(exc)}
            )
            return state

        state.poi_results = results
        state.tool_traces.append(
            {
                "node": "poi",
                "status": "ok",
                "count": len(results),
                "source": (meta or {}).get("source"),
            }
        )
        return state

    async def trip_query_node(self, state: AssistantState) -> AssistantState:
        self._logger.info(
            "node.enter.trip_query",
            extra={"user_id": state.user_id, "trip_id": state.trip_id},
        )
        if state.intent != "trip_query" or not state.trip_id:
            state.tool_traces.append(
                {
                    "node": "trip_query",
                    "status": "skipped",
                    "reason": "intent_not_trip_query",
                }
            )
            return state
        try:
            trip_schema = self._trip_service.get_trip(state.trip_id)
            state.trip_data = trip_schema.model_dump(mode="json")
            state.tool_traces.append(
                {
                    "node": "trip_query",
                    "status": "ok",
                    "trip_id": state.trip_id,
                    "day_cards": len(trip_schema.day_cards or []),
                }
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.warning("trip.query_failed", extra={"error": str(exc)})
            state.tool_traces.append(
                {"node": "trip_query", "status": "error", "error": str(exc)}
            )
        return state

    async def tool_select_node(self, state: AssistantState) -> AssistantState:
        self._logger.info(
            "node.enter.tool_select",
            extra={"query": state.query, "session_id": state.session_id},
        )
        state.available_tools = self._tool_registry.names()

        weather_spec = self._build_weather_query_spec(state.query)
        if self._should_run_weather_direct(state.query, weather_spec):
            return await self._run_weather_direct(state, weather_spec)

        name, args, reason = await self._tool_selector.select_tool(state)
        if not name or name == "none":
            state.selected_tool = None
            state.tool_args = {}
            state.selected_tool_reason = reason
            state.tool_traces.append(
                {
                    "node": "tool_select",
                    "status": "skipped",
                    "reason": reason or "no_tool_selected",
                }
            )
            return state

        normalized = self._normalize_tool_args(name, args or {}, state)
        state.selected_tool = name
        state.tool_args = normalized
        state.selected_tool_reason = reason
        state.tool_traces.append(
            {
                "node": "tool_select",
                "status": "ok",
                "tool": name,
                "reason": reason or "selected",
                "args_keys": sorted(normalized.keys()),
            }
        )
        return state

    async def tool_execute_node(self, state: AssistantState) -> AssistantState:
        self._logger.info(
            "node.enter.tool_execute",
            extra={"tool": state.selected_tool, "session_id": state.session_id},
        )
        name = state.selected_tool
        if not name:
            state.tool_traces.append(
                {"node": "tool_execute", "status": "skipped", "reason": "no_tool"}
            )
            return state
        if name == "area_weather" and state.answer_text and state.tool_result is None:
            state.tool_traces.append(
                {
                    "node": "tool_execute",
                    "status": "skipped",
                    "tool": name,
                    "reason": "weather_direct_answer",
                }
            )
            return state
        if any(
            trace.get("node") == "tool_execute"
            and trace.get("status") == "ok"
            and trace.get("tool") == name
            for trace in (state.tool_traces or [])
        ):
            state.tool_traces.append(
                {
                    "node": "tool_execute",
                    "status": "skipped",
                    "tool": name,
                    "reason": "already_executed",
                }
            )
            return state
        tool = self._tool_registry.get(name)
        if not tool:
            state.tool_error = "tool_not_registered"
            state.tool_traces.append(
                {
                    "node": "tool_execute",
                    "status": "error",
                    "tool": name,
                    "error": "tool_not_registered",
                }
            )
            return state
        try:
            result = await tool.invoke(state.tool_args or {})
            state.tool_result = result
            if isinstance(result, str) and not state.answer_text:
                state.answer_text = result
            state.tool_traces.append(
                {
                    "node": "tool_execute",
                    "status": "ok",
                    "tool": name,
                }
            )
        except Exception as exc:  # pragma: no cover - defensive
            state.tool_error = str(exc)
            state.tool_traces.append(
                {
                    "node": "tool_execute",
                    "status": "error",
                    "tool": name,
                    "error": str(exc),
                }
            )
        return state

    @staticmethod
    def _now_shanghai() -> dt.datetime:
        try:
            from zoneinfo import ZoneInfo

            return dt.datetime.now(ZoneInfo("Asia/Shanghai"))
        except Exception:  # pragma: no cover - fallback
            return dt.datetime.now()

    def _render_time_anchor_message(self) -> str:
        now = self._now_shanghai()
        return (
            f"当前时间: {now.isoformat()} (Asia/Shanghai)。"
            "当用户使用“今天/明天/后天/大后天”等相对日期词时，必须以此时间为基准理解。"
        )

    def _build_weather_query_spec(self, query: str) -> WeatherQuerySpec:
        base_date = self._now_shanghai().date()
        return build_weather_query_spec(query, base_date=base_date)

    @staticmethod
    def _looks_like_weather_query(query: str) -> bool:
        lowered = (query or "").lower()
        keywords = ["天气", "weather", "气温", "温度", "下雨", "降雨", "风力", "风向"]
        return any(word in lowered for word in keywords)

    @staticmethod
    def _should_run_weather_direct(query: str, spec: WeatherQuerySpec) -> bool:
        if not AssistantNodes._looks_like_weather_query(query):
            return False
        if spec.day_offset is not None:
            return True
        if spec.target_date is not None:
            return True
        return False

    async def _run_weather_direct(
        self, state: AssistantState, spec: WeatherQuerySpec
    ) -> AssistantState:
        tool = self._tool_registry.get("area_weather")
        if not tool:
            state.tool_error = "tool_not_registered"
            return state

        base_date = self._now_shanghai().date()
        target_date = spec.target_date
        offset = spec.day_offset
        if target_date is not None and offset is None:
            offset = (target_date - base_date).days
        if offset is None:
            offset = 0
        if target_date is None:
            target_date = base_date + dt.timedelta(days=offset)

        if offset < 0:
            state.selected_tool = "area_weather"
            state.answer_text = (
                f"你查询的日期（{target_date.isoformat()}）早于今天，无法提供预报。"
            )
            state.tool_traces.append(
                {
                    "node": "tool_select",
                    "status": "ok",
                    "tool": "area_weather",
                    "mode": "direct",
                }
            )
            return state
        if offset > 3:
            state.selected_tool = "area_weather"
            state.answer_text = (
                "目前仅支持查询未来 4 天内的天气预报；你请求的是 "
                f"{target_date.isoformat()}。"
            )
            state.tool_traces.append(
                {
                    "node": "tool_select",
                    "status": "ok",
                    "tool": "area_weather",
                    "mode": "direct",
                }
            )
            return state

        locations = spec.locations or []
        if not locations:
            state.selected_tool = "area_weather"
            state.answer_text = "想查询哪个城市/地区的天气？例如：明天广州天气怎么样。"
            state.tool_traces.append(
                {
                    "node": "tool_select",
                    "status": "ok",
                    "tool": "area_weather",
                    "mode": "direct",
                }
            )
            return state

        # Ensure the returned forecast list covers the requested offset.
        # AMap includes today as index 0.
        days = min(4, max(1, offset + 1))
        payload = {"locations": locations[:1], "weather_type": "forecast", "days": days}
        result = await tool.invoke(payload)
        state.tool_result = result
        state.selected_tool = "area_weather"
        state.tool_args = payload
        state.tool_traces.append(
            {
                "node": "tool_select",
                "status": "ok",
                "tool": "area_weather",
                "invoked_tools": ["area_weather"],
                "mode": "direct",
            }
        )
        state.tool_traces.append(
            {"node": "tool_execute", "status": "ok", "tool": "area_weather"}
        )

        answer = self._format_area_weather_forecast_answer(
            locations[0], target_date=target_date, day_offset=offset, tool_result=result
        )
        state.answer_text = answer
        return state

    @staticmethod
    def _format_area_weather_forecast_answer(
        location: str,
        *,
        target_date: dt.date,
        day_offset: int,
        tool_result: Any,
    ) -> str:
        day_label = {0: "今天", 1: "明天", 2: "后天", 3: "大后天"}.get(
            day_offset, "当天"
        )
        date_text = target_date.isoformat()

        first = None
        if isinstance(tool_result, dict):
            results = tool_result.get("results")
            if isinstance(results, list) and results:
                first = results[0]
        if not isinstance(first, dict):
            return f"{location}{day_label}（{date_text}）的天气预报暂不可用。"

        forecast = first.get("forecast")
        cast = None
        if isinstance(forecast, list) and forecast:
            if 0 <= day_offset < len(forecast):
                cast = forecast[day_offset]
            else:
                cast = forecast[0]
        if not isinstance(cast, dict):
            return f"{location}{day_label}（{date_text}）的天气预报暂不可用。"

        # Prefer AMap forecast keys.
        cast_date = cast.get("date")
        if isinstance(cast_date, str) and cast_date.strip():
            date_text = cast_date.strip()

        day_weather = cast.get("dayweather") or cast.get("day_weather")
        night_weather = cast.get("nightweather") or cast.get("night_weather")
        high = cast.get("daytemp") or cast.get("high_c") or cast.get("high")
        low = cast.get("nighttemp") or cast.get("low_c") or cast.get("low")
        day_wind = cast.get("daywind") or cast.get("winddirection") or cast.get("wind")
        day_power = cast.get("daypower") or cast.get("windpower")

        weather_line = None
        if day_weather or night_weather:
            if day_weather and night_weather:
                weather_line = f"天气情况：白天{day_weather}，夜间{night_weather}"
            elif day_weather:
                weather_line = f"天气情况：{day_weather}"
            else:
                weather_line = f"天气情况：{night_weather}"
        else:
            fallback_weather = first.get("weather")
            if fallback_weather:
                weather_line = f"天气情况：{fallback_weather}"

        lines = [f"{location}{day_label}（{date_text}）的天气预报如下："]
        if weather_line:
            lines.append(weather_line)
        if high is not None:
            lines.append(f"最高气温：约 {high} °C")
        if low is not None:
            lines.append(f"最低气温：约 {low} °C")
        if day_wind or day_power:
            wind_text = "风向/风力："
            if day_wind:
                wind_text += str(day_wind)
            if day_power:
                wind_text += f" {day_power}"
            lines.append(wind_text.strip())
        return "\n".join(lines)

    async def response_formatter_node(self, state: AssistantState) -> AssistantState:
        self._logger.info(
            "node.enter.response_formatter",
            extra={
                "tool": state.selected_tool,
                "tool_error": state.tool_error,
                "used_memory": len(state.memories),
            },
        )
        draft_answer: str | None = None
        if state.answer_text and state.selected_tool is None:
            draft_answer = state.answer_text
            state.answer_text = None
        elif state.answer_text and state.selected_tool == "area_weather":
            state.tool_traces.append(
                {
                    "node": "response_formatter",
                    "status": "skipped",
                    "reason": "answer_prepared_by_weather_tool",
                }
            )
            return state
        elif state.answer_text and state.tool_result is not None:
            draft_answer = state.answer_text
            state.answer_text = None
        elif state.answer_text:
            state.tool_traces.append(
                {
                    "node": "response_formatter",
                    "status": "skipped",
                    "reason": "answer_prepared",
                }
            )
            return state

        prompt = self._prompt_registry.get_prompt("assistant.response.formatter")
        context_blocks = []
        if state.trip_data:
            context_blocks.append(summarize_trip(state.trip_data))
        if state.memories:
            context_blocks.append(summarize_memories(state.memories))
        if draft_answer:
            context_blocks.append("草稿回答：\n" + draft_answer)
        if state.poi_results:
            context_blocks.append(summarize_poi_results(state.poi_results))
        if state.tool_result:
            context_blocks.append(
                summarize_tool_result(
                    selected_tool=state.selected_tool,
                    tool_result=state.tool_result,
                )
            )
        history_block = render_history_block(
            state.history, max_rounds=settings.ai_assistant_max_history_rounds
        )
        if history_block.strip():
            context_blocks.append(history_block)
        context_text = "\n\n".join(context_blocks) if context_blocks else "无额外上下文"

        request = AiChatRequest(
            messages=[
                AiMessage(role=prompt.role, content=prompt.content),
                AiMessage(
                    role="user",
                    content=f"用户提问: {state.query}\n可用上下文:\n{context_text}",
                ),
            ],
            response_format="text",
            timeout_s=settings.ai_request_timeout_s,
        )
        result = await self._ai_client.chat(request)
        fallback_answer = build_fallback_answer(
            query=state.query,
            context_text=context_text,
            poi_results=state.poi_results,
            tool_result=state.tool_result,
            selected_tool=state.selected_tool,
            trip_data=state.trip_data,
            memories=state.memories,
        )
        answer = (
            fallback_answer
            if result.provider == "mock" or result.content.startswith("mock:")
            else result.content or fallback_answer
        )
        state.answer_text = answer
        state.ai_meta = state.ai_meta or {
            "provider": result.provider,
            "model": result.model,
            "latency_ms": result.latency_ms,
            "usage_tokens": result.usage_tokens,
            "trace_id": result.trace_id,
        }
        state.tool_traces.append(
            {
                "node": "response_formatter",
                "status": "ok",
                "used_trip": bool(state.trip_data),
                "used_memory": len(state.memories),
                "used_tool": bool(state.tool_result),
            }
        )
        return state

    # --- helpers ---------------------------------------------------------
    def _infer_intent(self, model_output: str, query: str) -> str:
        parsed_intent: str | None = None
        with contextlib.suppress(json.JSONDecodeError):
            if "{" in model_output:
                obj = json.loads(model_output.split("mock:", 1)[-1])
                parsed_intent = obj.get("intent")
        lowered = query.lower()
        heuristic = "general_qa"
        poi_keywords = ["附近", "周边", "周围", "景点", "好吃", "餐厅", "美食", "hotel"]
        if any(keyword in lowered for keyword in poi_keywords):
            heuristic = "poi_nearby"
        elif any(keyword in lowered for keyword in ["行程", "trip", "计划", "安排"]):
            heuristic = "trip_query"
        intent = parsed_intent or heuristic
        return intent

    @staticmethod
    def _normalize_tool_args(
        tool_name: str | None, args: dict[str, Any], state: AssistantState
    ) -> dict[str, Any]:
        if not tool_name:
            return args
        if tool_name == "weather_search":
            args.setdefault("destination", state.query)
            args.setdefault("month", "当前或近期")
            args.setdefault("max_results", 3)
        elif tool_name == "area_weather":
            spec = build_weather_query_spec(
                state.query,
                base_date=AssistantNodes._now_shanghai().date(),
            )
            args.setdefault("locations", spec.locations or [state.query])
            args.setdefault("weather_type", "forecast")
            if "days" not in args:
                if spec.day_offset is None:
                    args["days"] = 1
                else:
                    args["days"] = min(4, max(1, spec.day_offset + 1))
        elif tool_name == "path_navigate":
            if not args.get("routes"):
                args["routes"] = [{"origin": "出发地", "destination": state.query}]
            args.setdefault("travel_mode", "driving")
            args.setdefault("strategy", 0)
        elif tool_name == "fast_search":
            args.setdefault("query", state.query)
            args.setdefault("time_range", "week")
            args.setdefault("max_results", 5)
        elif tool_name == "deep_search":
            args.setdefault("origin_city", "出发地")
            args.setdefault("destination_city", state.query)
            args.setdefault("start_date", "2025-01-01")
            args.setdefault("end_date", "2025-01-05")
            args.setdefault("num_travelers", 1)
            args.setdefault("search_type", "all")
        elif tool_name == "deep_extract":
            if not args.get("urls"):
                args["urls"] = [state.query]
            args.setdefault("query", "提取关键信息")
        return args
