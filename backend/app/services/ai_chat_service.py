from __future__ import annotations

from app.ai import (
    AiChatRequest,
    AiClient,
    AiMessage,
    MemoryItem,
    StreamCallback,
    get_ai_client,
)
from app.core.settings import settings
from app.models.ai_schemas import ChatDemoPayload, ChatDemoResult
from app.services.memory_service import MemoryService, get_memory_service

# SYSTEM_PROMPT = (
#     "You are Travelist+, a helpful travel assistant. "
#     "Answer with concise, actionable guidance using the provided context. "
#     "If previous memories are supplied, weave them naturally into the answer."
# )

SYSTEM_PROMPT = """你是一名友好且有用的AI助手。
你具有以下特点：
- 耐心回答用户问题
- 提供准确有用的信息
- 以友善的态度与用户交流
- 如果不知道答案，诚实说明

请始终保持专业和帮助性的态度。"""


class AiChatDemoService:
    """Coordinates AiClient + MemoryService for the chat demo endpoint."""

    def __init__(
        self,
        ai_client: AiClient | None = None,
        memory_service: MemoryService | None = None,
    ) -> None:
        self._ai_client = ai_client or get_ai_client()
        self._memory_service = memory_service or get_memory_service()
        self._settings = settings

    async def run_chat(
        self,
        payload: ChatDemoPayload,
        *,
        stream_handler: StreamCallback | None = None,
    ) -> ChatDemoResult:
        memories: list[MemoryItem] = []
        if payload.use_memory:
            memories = await self._memory_service.search_memory(
                user_id=payload.user_id,
                level=payload.level,
                query=payload.query,
                trip_id=payload.trip_id,
                session_id=payload.session_id,
                k=payload.top_k,
            )

        messages = self._build_messages(payload, memories)
        request = AiChatRequest(
            messages=messages,
            response_format="text",
            timeout_s=self._settings.ai_request_timeout_s,
        )
        result = await self._ai_client.chat(request, on_chunk=stream_handler)

        memory_metadata = {
            "source": "chat_demo",
            "level": payload.level.value,
        }
        if payload.trip_id is not None:
            memory_metadata["trip_id"] = payload.trip_id
        if payload.session_id is not None:
            memory_metadata["session_id"] = payload.session_id
        if payload.metadata:
            memory_metadata.update(payload.metadata)
        memory_record_id = await self._memory_service.write_memory(
            payload.user_id,
            payload.level,
            text=f"Q: {payload.query}\nA: {result.content}",
            trip_id=payload.trip_id,
            session_id=payload.session_id,
            metadata=memory_metadata,
        )

        used_memory = memories if payload.return_memory else []
        response = ChatDemoResult(
            answer=result.content,
            used_memory=used_memory,
            ai_meta={
                "provider": result.provider,
                "model": result.model,
                "latency_ms": result.latency_ms,
                "usage_tokens": result.usage_tokens,
                "trace_id": result.trace_id,
            },
            memory_record_id=memory_record_id,
        )
        return response

    def _build_messages(
        self,
        payload: ChatDemoPayload,
        memories: list[MemoryItem],
    ) -> list[AiMessage]:
        system_prompt = payload.system_prompt or SYSTEM_PROMPT
        messages = [AiMessage(role="system", content=system_prompt)]
        if memories:
            summarized = self._render_memories(memories)
            messages.append(
                AiMessage(
                    role="system",
                    content=(
                        "Relevant context from mem0:\n"
                        f"{summarized}\n"
                        "Use these details when possible."
                    ),
                )
            )
        messages.append(AiMessage(role="user", content=payload.query))
        return messages

    @staticmethod
    def _render_memories(memories: list[MemoryItem]) -> str:
        lines = []
        for item in memories:
            prefix = f"[{item.score:.2f}] " if item.score is not None else ""
            lines.append(f"- {prefix}{item.text}")
        return "\n".join(lines)


def get_ai_chat_service() -> AiChatDemoService:
    return AiChatDemoService()
