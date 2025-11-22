from __future__ import annotations

from typing import Any

from app.ai import AiStreamChunk, StreamCallback, get_ai_client
from app.ai.memory_models import MemoryLevel
from app.ai.prompts import get_prompt_registry
from app.agents import AssistantState, build_assistant_graph, build_tool_registry
from app.agents.assistant.nodes import AssistantNodes
from app.agents.assistant.tool_selection import ToolSelector
from app.agents.tools.registry import ToolRegistry
from app.core.db import session_scope
from app.core.logging import get_logger
from app.core.settings import settings
from app.models.ai_schemas import ChatMessageSchema, ChatPayload, ChatResult
from app.models.orm import ChatSession, Message
from app.services.memory_service import MemoryService, get_memory_service
from app.services.trip_service import TripQueryService


class AssistantService:
    """Entry point for the Stage-5 assistant REST API."""

    def __init__(
        self,
        *,
        memory_service: MemoryService | None = None,
        trip_service: TripQueryService | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self._ai_client = get_ai_client()
        self._memory_service = memory_service or get_memory_service()
        self._trip_service = trip_service or TripQueryService()
        self._prompt_registry = get_prompt_registry()
        self._tool_registry = tool_registry or build_tool_registry()
        self._tool_selector = ToolSelector(
            ai_client=self._ai_client,
            prompt_registry=self._prompt_registry,
            tool_registry=self._tool_registry,
        )
        nodes = AssistantNodes(
            ai_client=self._ai_client,
            memory_service=self._memory_service,
            prompt_registry=self._prompt_registry,
            trip_service=self._trip_service,
            tool_selector=self._tool_selector,
            tool_registry=self._tool_registry,
        )
        self._graph = build_assistant_graph(nodes)
        self._logger = get_logger(__name__)

    async def run_chat(
        self,
        payload: ChatPayload,
        *,
        stream_handler: StreamCallback | None = None,
    ) -> ChatResult:
        session_obj = self._ensure_session(payload)
        history = self._load_history(session_obj.id)
        max_k = payload.top_k_memory or settings.mem0_default_k
        state = AssistantState(
            user_id=payload.user_id,
            trip_id=payload.trip_id,
            session_id=session_obj.id,
            query=payload.query,
            use_memory=payload.use_memory,
            top_k=max_k,
            history=history,
        )
        self._logger.info(
            "assistant.enter",
            extra={
                "user_id": payload.user_id,
                "trip_id": payload.trip_id,
                "session_id": session_obj.id,
                "use_memory": payload.use_memory,
                "top_k": max_k,
            },
        )
        if settings.ai_assistant_graph_enabled:
            result_state = await self._graph.ainvoke(state)
            if isinstance(result_state, dict):
                result_state = AssistantState(**result_state)
        else:  # pragma: no cover - feature toggle fallback
            result_state = state
            result_state.answer_text = f"[助手已关闭] 直接回复：{payload.query}"
            result_state.ai_meta = {
                "provider": "disabled",
                "model": "n/a",
                "latency_ms": 0.0,
                "usage_tokens": 0,
                "trace_id": "assistant-disabled",
            }

        answer = result_state.answer_text or "抱歉，暂时无法生成回答。"
        self._logger.info(
            "assistant.answer",
            extra={
                "session_id": session_obj.id,
                "intent": result_state.intent,
                "trace_id": (result_state.ai_meta or {}).get("trace_id"),
                "latency_ms": (result_state.ai_meta or {}).get("latency_ms"),
            },
        )
        if stream_handler:
            await self._emit_stream(answer, result_state.ai_meta, stream_handler)

        memory_record_id = await self._write_memory(
            payload=payload,
            session_id=session_obj.id,
            answer=answer,
        )
        self._persist_messages(
            session_id=session_obj.id,
            user_id=payload.user_id,
            query=payload.query,
            answer=answer,
            intent=result_state.intent,
            ai_meta=result_state.ai_meta,
        )
        messages = (
            [
                ChatMessageSchema.model_validate(entry)
                for entry in self._load_history(session_obj.id)
            ]
            if payload.return_messages
            else []
        )
        used_memory = result_state.memories if payload.return_memory else []
        tool_traces = result_state.tool_traces if payload.return_tool_traces else []
        result = ChatResult(
            session_id=session_obj.id,
            answer=answer,
            intent=result_state.intent,
            used_memory=used_memory,
            tool_traces=tool_traces,
            ai_meta=result_state.ai_meta or {},
            messages=messages,
            memory_record_id=memory_record_id,
            selected_tool=result_state.selected_tool,
            tool_result=result_state.tool_result,
            tool_error=result_state.tool_error,
        )
        return result

    def _ensure_session(self, payload: ChatPayload) -> ChatSession:
        with session_scope() as session:
            if payload.session_id:
                session_obj = session.get(ChatSession, payload.session_id)
                if session_obj is None or session_obj.user_id != payload.user_id:
                    msg = "会话不存在或不属于该用户"
                    raise ValueError(msg)
                return session_obj
            session_obj = ChatSession(user_id=payload.user_id, trip_id=payload.trip_id)
            session.add(session_obj)
            session.commit()
            session.refresh(session_obj)
            return session_obj

    def _load_history(self, session_id: int) -> list[dict[str, Any]]:
        limit = settings.ai_assistant_max_history_rounds * 2
        with session_scope() as session:
            rows = (
                session.query(Message)
                .filter(Message.session_id == session_id)
                .order_by(Message.created_at.desc())
                .limit(limit)
                .all()
            )
        rows = list(reversed(rows))
        history: list[dict[str, Any]] = []
        for row in rows:
            history.append(
                {
                    "role": row.role,
                    "content": row.content,
                    "created_at": row.created_at,
                }
            )
        return history

    def _persist_messages(
        self,
        *,
        session_id: int,
        user_id: int,
        query: str,
        answer: str,
        intent: str | None,
        ai_meta: dict[str, Any] | None,
    ) -> None:
        with session_scope() as session:
            user_msg = Message(
                session_id=session_id,
                role="user",
                content=query,
                intent=intent,
            )
            ai_msg = Message(
                session_id=session_id,
                role="assistant",
                content=answer,
                intent=intent,
                meta=ai_meta or {},
            )
            session.add_all([user_msg, ai_msg])
            session.commit()

    async def _write_memory(
        self,
        *,
        payload: ChatPayload,
        session_id: int,
        answer: str,
    ) -> str | None:
        try:
            level = self._resolve_memory_level(payload, session_id)
        except ValueError:
            return None
        metadata = {
            "source": "assistant_v1",
            "session_id": session_id,
        }
        if payload.trip_id:
            metadata["trip_id"] = payload.trip_id
        return await self._memory_service.write_memory(
            user_id=payload.user_id,
            level=level,
            text=f"Q: {payload.query}\nA: {answer}",
            trip_id=payload.trip_id,
            session_id=str(session_id),
            metadata=metadata,
        )

    @staticmethod
    def _resolve_memory_level(payload: ChatPayload, session_id: int) -> MemoryLevel:
        if session_id:
            return MemoryLevel.session
        if payload.trip_id:
            return MemoryLevel.trip
        return MemoryLevel.user

    async def _emit_stream(
        self,
        answer: str,
        ai_meta: dict[str, Any] | None,
        stream_handler: StreamCallback,
    ) -> None:
        trace_id = (ai_meta or {}).get("trace_id") or "assistant-stream"
        parts = [answer[i : i + 40] for i in range(0, len(answer), 40)] or [""]
        for idx, chunk in enumerate(parts):
            await stream_handler(
                AiStreamChunk(
                    trace_id=trace_id,
                    delta=chunk,
                    index=idx,
                    done=idx == len(parts) - 1,
                )
            )


_assistant_service: AssistantService | None = None


def get_assistant_service() -> AssistantService:
    global _assistant_service
    if _assistant_service is None:
        _assistant_service = AssistantService()
    return _assistant_service
