from __future__ import annotations

import contextlib
import json
from typing import Any

from app.ai import AiChatRequest, AiClient, AiMessage
from app.agents.assistant.state import AssistantState
from app.agents.assistant.tool_selection import ToolSelector
from app.agents.tools.registry import ToolExecutionError, ToolRegistry
from app.ai.memory_models import MemoryLevel
from app.ai.prompts import PromptRegistry
from app.core.logging import get_logger
from app.core.settings import settings
from app.services.memory_service import MemoryService
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
    ) -> None:
        self._ai_client = ai_client
        self._memory_service = memory_service
        self._prompt_registry = prompt_registry
        self._trip_service = trip_service
        self._tool_selector = tool_selector
        self._tool_registry = tool_registry
        self._logger = get_logger(__name__)

    async def memory_read_node(self, state: AssistantState) -> AssistantState:
        self._logger.info(
            "node.enter.memory_read",
            extra={"user_id": state.user_id, "session_id": state.session_id},
        )
        if not state.use_memory:
            state.tool_traces.append({"node": "memory_read", "status": "skipped"})
            return state

        level = self._resolve_memory_level(state)
        try:
            memories = await self._memory_service.search_memory(
                user_id=state.user_id,
                level=level,
                query=state.query,
                trip_id=state.trip_id,
                session_id=str(state.session_id) if state.session_id else None,
                k=state.top_k,
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.warning("memory.read_failed", extra={"error": str(exc)})
            state.tool_traces.append(
                {"node": "memory_read", "status": "error", "error": str(exc)}
            )
            return state

        state.memories = memories
        state.tool_traces.append(
            {"node": "memory_read", "status": "ok", "count": len(memories)}
        )
        self._logger.info(
            "assistant.memory_read",
            extra={
                "user_id": state.user_id,
                "session_id": state.session_id,
                "trip_id": state.trip_id,
                "count": len(memories),
            },
        )
        return state

    async def assistant_node(self, state: AssistantState) -> AssistantState:
        self._logger.info(
            "node.enter.assistant",
            extra={"user_id": state.user_id, "session_id": state.session_id},
        )
        prompt = self._prompt_registry.get_prompt("assistant.intent.classify")
        history_block = self._render_history_block(state.history)
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
        self._logger.info(
            "assistant.intent",
            extra={
                "trace_id": result.trace_id,
                "intent": intent,
                "latency_ms": result.latency_ms,
                "model": result.model,
            },
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
            self._logger.info(
                "assistant.trip_query",
                extra={
                    "user_id": trip_schema.user_id,
                    "trip_id": state.trip_id,
                    "days": len(trip_schema.day_cards or []),
                },
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.warning("trip.query_failed", extra={"error": str(exc)})
            state.tool_traces.append(
                {"node": "trip_query", "status": "error", "error": str(exc)}
            )
        return state

    async def tool_selection_node(self, state: AssistantState) -> AssistantState:
        self._logger.info(
            "node.enter.tool_select",
            extra={
                "query": state.query,
                "intent": state.intent,
                "available": self._tool_registry.names(),
            },
        )
        state.available_tools = self._tool_registry.names()
        name, args, reason = await self._tool_selector.select_tool(state)
        normalized_args = self._normalize_tool_args(name, args or {}, state)
        state.selected_tool = name
        state.tool_args = normalized_args
        state.selected_tool_reason = reason
        self._logger.info(
            "tool.selected",
            extra={"tool": name, "reason": reason, "tool_args": normalized_args},
        )
        state.tool_traces.append(
            {
                "node": "tool_select",
                "status": "ok" if name else "skipped",
                "tool": name,
                "reason": reason,
            }
        )
        return state

    async def tool_execution_node(self, state: AssistantState) -> AssistantState:
        self._logger.info(
            "node.enter.tool_execute",
            extra={"tool": state.selected_tool, "tool_args": state.tool_args},
        )
        if not state.selected_tool:
            state.tool_traces.append(
                {"node": "tool_execute", "status": "skipped", "reason": "no_tool"}
            )
            return state
        tool = self._tool_registry.get(state.selected_tool)
        if not tool:
            state.tool_error = "tool_not_registered"
            state.tool_traces.append(
                {"node": "tool_execute", "status": "error", "error": state.tool_error}
            )
            return state
        try:
            result = await tool.invoke(state.tool_args or {})
            state.tool_result = result
            state.tool_error = None
            state.tool_traces.append(
                {
                    "node": "tool_execute",
                    "status": "ok",
                    "tool": state.selected_tool,
                }
            )
        except ToolExecutionError as exc:
            state.tool_error = str(exc)
            self._logger.warning(
                "tool.execute.validation_error",
                extra={
                    "tool": state.selected_tool,
                    "args": state.tool_args,
                    "error": str(exc),
                },
            )
            # best-effort fallback for weather queries
            if state.selected_tool == "area_weather":
                fallback_args = self._normalize_tool_args(
                    "weather_search", {}, state
                )
                fallback_tool = self._tool_registry.get("weather_search")
                if fallback_tool:
                    try:
                        state.tool_result = await fallback_tool.invoke(fallback_args)
                        state.tool_error = None
                        state.selected_tool = "weather_search"
                        state.tool_args = fallback_args
                        state.tool_traces.append(
                            {
                                "node": "tool_execute",
                                "status": "ok",
                                "tool": "weather_search",
                                "reason": "fallback_from_area_weather",
                            }
                        )
                        return state
                    except Exception as inner_exc:  # pragma: no cover - defensive
                        self._logger.warning(
                            "tool.execute.fallback_failed",
                            extra={"error": str(inner_exc)},
                        )
            state.tool_traces.append(
                {
                    "node": "tool_execute",
                    "status": "error",
                    "tool": state.selected_tool,
                    "error": str(exc),
                }
            )
        except Exception as exc:  # pragma: no cover - defensive
            state.tool_error = str(exc)
            self._logger.warning(
                "tool.execute.unexpected",
                extra={"tool": state.selected_tool, "error": str(exc)},
            )
            state.tool_traces.append(
                {
                    "node": "tool_execute",
                    "status": "error",
                    "tool": state.selected_tool,
                    "error": str(exc),
                }
            )
        return state

    async def response_formatter_node(self, state: AssistantState) -> AssistantState:
        self._logger.info(
            "node.enter.response_formatter",
            extra={
                "tool": state.selected_tool,
                "tool_error": state.tool_error,
                "used_memory": len(state.memories),
            },
        )
        prompt = self._prompt_registry.get_prompt("assistant.response.formatter")
        context_blocks = []
        if state.trip_data:
            context_blocks.append(self._summarize_trip(state.trip_data))
        if state.memories:
            context_blocks.append(self._summarize_memories(state.memories))
        if state.tool_result:
            context_blocks.append(self._summarize_tool_result(state))
        history_block = self._render_history_block(state.history)
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
        fallback_answer = self._build_fallback_answer(state, context_text)
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
    @staticmethod
    def _resolve_memory_level(state: AssistantState) -> MemoryLevel:
        if state.session_id:
            return MemoryLevel.session
        if state.trip_id:
            return MemoryLevel.trip
        return MemoryLevel.user

    def _infer_intent(self, model_output: str, query: str) -> str:
        parsed_intent: str | None = None
        with contextlib.suppress(json.JSONDecodeError):
            if "{" in model_output:
                obj = json.loads(model_output.split("mock:", 1)[-1])
                parsed_intent = obj.get("intent")
        lowered = query.lower()
        heuristic = "general_qa"
        if any(keyword in lowered for keyword in ["行程", "trip", "计划", "安排"]):
            heuristic = "trip_query"
        intent = parsed_intent or heuristic
        return intent

    def _normalize_tool_args(
        self, tool_name: str | None, args: dict[str, Any], state: AssistantState
    ) -> dict[str, Any]:
        """Fill missing tool arguments with sensible defaults to avoid validation errors."""

        if not tool_name:
            return args
        if tool_name == "weather_search":
            args.setdefault("destination", state.query)
            args.setdefault("month", "当前或近期")
            args.setdefault("max_results", 3)
        elif tool_name == "area_weather":
            args.setdefault("locations", [state.query])
            args.setdefault("weather_type", "forecast")
            args.setdefault("days", 1)
        elif tool_name == "path_navigate":
            if not args.get("routes"):
                args["routes"] = [{"origin": "出发地", "destination": state.query}]
            args.setdefault("travel_mode", "driving")
            args.setdefault("strategy", 0)
        return args

    @staticmethod
    def _render_history_block(history: list[dict[str, Any]]) -> str:
        if not history:
            return ""
        lines = []
        for item in history[-settings.ai_assistant_max_history_rounds :]:
            role = item.get("role")
            content = item.get("content")
            lines.append(f"{role}: {content}")
        return "近期对话历史：\n" + "\n".join(lines)

    @staticmethod
    def _summarize_memories(memories) -> str:
        lines = ["记忆摘要："]
        for item in memories[:5]:
            prefix = f"[{item.score:.2f}] " if item.score is not None else ""
            lines.append(f"- {prefix}{item.text}")
        return "\n".join(lines)

    @staticmethod
    def _summarize_trip(trip_data: dict[str, Any]) -> str:
        if not trip_data:
            return ""
        title = trip_data.get("title") or "行程"
        destination = trip_data.get("destination") or ""
        day_cards = trip_data.get("day_cards") or []
        lines = [f"{title} {destination}".strip()]
        for day in day_cards:
            day_index = day.get("day_index", 0)
            date = day.get("date") or ""
            lines.append(f"Day {day_index} {date}".strip())
            for sub in day.get("sub_trips") or []:
                activity = sub.get("activity") or sub.get("loc_name") or "活动"
                start = sub.get("start_time") or ""
                end = sub.get("end_time") or ""
                lines.append(f"- {activity} {start}-{end}".strip())
        return "\n".join(lines)

    @staticmethod
    def _summarize_tool_result(state: AssistantState) -> str:
        tool_name = state.selected_tool or "tool"
        if isinstance(state.tool_result, str):
            return f"工具 {tool_name} 返回：{state.tool_result}"
        if isinstance(state.tool_result, dict):
            preview = json.dumps(state.tool_result, ensure_ascii=False)[:400]
            return f"工具 {tool_name} 返回数据：{preview}"
        return f"工具 {tool_name} 已执行。"

    @staticmethod
    def _build_fallback_answer(state: AssistantState, context_text: str) -> str:
        if state.tool_result:
            return f"基于工具 {state.selected_tool or ''} 的结果：\n{context_text}"
        if state.trip_data:
            trip_intro = state.trip_data.get("title") or "你的行程"
            return f"{trip_intro} 的简要安排如下：\n{context_text}"
        if state.memories:
            return f"结合你的记忆（{len(state.memories)} 条），建议：\n{context_text}"
        return f"关于“{state.query}”暂时没有额外上下文，建议提供更多细节。"
