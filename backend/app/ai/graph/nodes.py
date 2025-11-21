from __future__ import annotations

import contextlib
import json
from typing import Any

from app.ai import AiChatRequest, AiClient, AiMessage
from app.ai.graph.state import AssistantState
from app.ai.memory_models import MemoryLevel
from app.ai.prompts import PromptRegistry
from app.core.logging import get_logger
from app.core.settings import settings
from app.services.memory_service import MemoryService
from app.services.trip_service import TripQueryService


class AssistantNodes:
    """Collection of LangGraph nodes used by the助手 graph."""

    def __init__(
        self,
        ai_client: AiClient,
        memory_service: MemoryService,
        prompt_registry: PromptRegistry,
        trip_service: TripQueryService,
    ) -> None:
        self._ai_client = ai_client
        self._memory_service = memory_service
        self._prompt_registry = prompt_registry
        self._trip_service = trip_service
        self._logger = get_logger(__name__)

    async def memory_read_node(self, state: AssistantState) -> AssistantState:
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

    async def response_formatter_node(self, state: AssistantState) -> AssistantState:
        prompt = self._prompt_registry.get_prompt("assistant.response.formatter")
        context_blocks = []
        if state.trip_data:
            context_blocks.append(self._summarize_trip(state.trip_data))
        if state.memories:
            context_blocks.append(self._summarize_memories(state.memories))
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
        if any(keyword in lowered for keyword in ["行程", "明天", "安排", "计划"]):
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
    def _build_fallback_answer(state: AssistantState, context_text: str) -> str:
        if state.trip_data:
            trip_intro = state.trip_data.get("title") or "你的行程"
            return f"{trip_intro} 的简要安排如下：\n{context_text}"
        if state.memories:
            return f"结合你的记忆（{len(state.memories)} 条），建议：\n{context_text}"
        return (
            f"关于“{state.query}”目前没有额外上下文，"
            "建议明确日期和行程，以便给出更准确的建议。"
        )
