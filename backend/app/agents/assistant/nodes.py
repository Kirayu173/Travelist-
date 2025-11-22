from __future__ import annotations

import contextlib
import json
from typing import Any

from app.ai import AiChatRequest, AiClient, AiMessage
from app.agents.assistant.state import AssistantState
from app.agents.assistant.tool_selection import ToolSelector
from app.agents.tool_agent import AgentContext, ToolAgentRunner
from app.agents.tools.registry import ToolRegistry
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
        tool_agent: ToolAgentRunner | None = None,
    ) -> None:
        self._ai_client = ai_client
        self._memory_service = memory_service
        self._prompt_registry = prompt_registry
        self._trip_service = trip_service
        self._tool_selector = tool_selector
        self._tool_registry = tool_registry
        self._tool_agent = tool_agent
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

    async def tool_agent_node(self, state: AssistantState) -> AssistantState:
        self._logger.info(
            "node.enter.tool_agent",
            extra={"query": state.query, "session_id": state.session_id},
        )
        if not self._tool_agent:
            return await self._fallback_direct_tool_run(state)
        try:
            messages = [{"role": "user", "content": state.query}]
            context = AgentContext(
                user_id=str(state.user_id),
                session_id=str(state.session_id or state.user_id),
            )
            result = await self._tool_agent.run(messages=messages, context=context)
            final_text = self._extract_final_text(result)
            tool_calls = self._extract_tool_calls(result)
            tool_names = [call["tool"] for call in tool_calls if call.get("tool")]
            state.tool_result = result
            state.answer_text = final_text or state.answer_text
            state.selected_tool = (tool_names[0] if tool_names else None) or "create_agent"
            state.tool_traces.append(
                {
                    "node": "tool_agent",
                    "status": "ok",
                    "tool": state.selected_tool,
                    "invoked_tools": tool_names[:5] if tool_names else [],
                    "args_preview": [
                        {
                            "tool": call.get("tool"),
                            "args_keys": sorted(call.get("args").keys())
                            if isinstance(call.get("args"), dict)
                            else None,
                        }
                        for call in tool_calls[:5]
                    ]
                    if tool_calls
                    else [],
                }
            )
            if tool_names:
                self._logger.info(
                    "tool_agent.complete",
                    extra={
                        "tools": tool_names,
                        "selected": state.selected_tool,
                    },
                )
        except Exception as exc:
            state.tool_error = str(exc)
            state.tool_traces.append(
                {
                    "node": "tool_agent",
                    "status": "error",
                    "error": str(exc),
                }
            )
            self._logger.warning(
                "tool_agent.failed",
                extra={"error": str(exc)},
            )
        return state

    async def _fallback_direct_tool_run(self, state: AssistantState) -> AssistantState:
        state.available_tools = self._tool_registry.names()
        name, args, reason = await self._tool_selector.select_tool(state)
        state.selected_tool = name
        state.tool_args = self._normalize_tool_args(name, args or {}, state)
        state.selected_tool_reason = reason
        state.tool_traces.append(
            {
                "node": "tool_agent",
                "status": "skipped" if not name else "ok",
                "tool": name,
                "reason": reason or "fallback_direct",
            }
        )
        if not name:
            return state
        tool = self._tool_registry.get(name)
        if not tool:
            state.tool_error = "tool_not_registered"
            return state
        try:
            result = await tool.invoke(state.tool_args or {})
            state.tool_result = result
            state.answer_text = state.answer_text or (
                result if isinstance(result, str) else None
            )
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

    async def response_formatter_node(self, state: AssistantState) -> AssistantState:
        self._logger.info(
            "node.enter.response_formatter",
            extra={
                "tool": state.selected_tool,
                "tool_error": state.tool_error,
                "used_memory": len(state.memories),
            },
        )
        if state.answer_text:
            state.tool_traces.append(
                {
                    "node": "response_formatter",
                    "status": "skipped",
                    "reason": "answer_prepared_by_tool_agent",
                }
            )
            return state

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
        tool_name = state.selected_tool or "tool_agent"
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

    @staticmethod
    def _extract_final_text(agent_result: Any) -> str | None:
        if agent_result is None:
            return None
        if isinstance(agent_result, dict):
            messages = agent_result.get("messages")
            if isinstance(messages, list) and messages:
                last = messages[-1]
                if isinstance(last, dict):
                    return last.get("content")
                if hasattr(last, "content"):
                    return getattr(last, "content")
        if isinstance(agent_result, str):
            return agent_result
        return None

    @staticmethod
    def _extract_tool_calls(agent_result: Any) -> list[dict[str, Any]]:
        def _collect_from_message(msg: Any) -> list[dict[str, Any]]:
            calls: list[dict[str, Any]] = []
            if msg is None:
                return calls
            # dict message
            if isinstance(msg, dict):
                tool_calls = msg.get("tool_calls") or msg.get("tool_call")
                if tool_calls and isinstance(tool_calls, list):
                    for call in tool_calls:
                        if not isinstance(call, dict):
                            continue
                        calls.append(
                            {
                                "tool": call.get("name"),
                                "args": call.get("args"),
                            }
                        )
                # LangChain ToolMessage shape
                if msg.get("type") == "tool" and msg.get("name"):
                    calls.append({"tool": msg.get("name"), "args": msg.get("content")})
            else:
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls and isinstance(tool_calls, list):
                    for call in tool_calls:
                        name = getattr(call, "name", None) or getattr(
                            call, "tool", None
                        )
                        args = getattr(call, "args", None) or getattr(
                            call, "input", None
                        )
                        calls.append({"tool": name, "args": args})
                # ToolMessage objects expose .name / .additional_kwargs
                name = getattr(msg, "name", None)
                if name and getattr(msg, "tool_call_id", None):
                    calls.append(
                        {
                            "tool": name,
                            "args": getattr(msg, "additional_kwargs", None),
                        }
                    )
            return calls

        if not agent_result:
            return []
        messages = []
        if isinstance(agent_result, dict) and "messages" in agent_result:
            messages = agent_result.get("messages") or []
        elif isinstance(agent_result, list):
            messages = agent_result
        else:
            maybe_messages = getattr(agent_result, "messages", None)
            if maybe_messages is not None:
                messages = maybe_messages
        collected: list[dict[str, Any]] = []
        for msg in messages:
            collected.extend(_collect_from_message(msg))
        return collected

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
            args.setdefault("locations", [state.query])
            args.setdefault("weather_type", "forecast")
            args.setdefault("days", 1)
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
