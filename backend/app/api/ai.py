from __future__ import annotations

import asyncio
import json
from contextlib import suppress

from app.ai import AiClientError, AiStreamChunk
from app.models.ai_schemas import ChatDemoPayload, ChatPayload
from app.models.plan_schemas import PlanRequest
from app.services.ai_chat_service import AiChatDemoService, get_ai_chat_service
from app.services.assistant_service import AssistantService, get_assistant_service
from app.services.plan_service import PlanServiceError, get_plan_service
from app.services.plan_task_service import PlanTaskServiceError, get_plan_task_service
from app.utils.responses import error_response, success_response
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter(prefix="/api/ai", tags=["ai"])


def _demo_service() -> AiChatDemoService:
    return get_ai_chat_service()


def _assistant_service() -> AssistantService:
    return get_assistant_service()


@router.post(
    "/plan",
    summary="行程规划（fast/deep 统一入口）",
    description=(
        "Stage-7 实现 mode=fast（规则规划）；Stage-8 扩展 mode=deep（按天多轮生成）。"
    ),
)
async def plan(payload: PlanRequest):
    if payload.mode == "deep" and payload.async_:
        task_service = get_plan_task_service()
        try:
            result = task_service.enqueue_deep_task(payload)
        except PlanTaskServiceError as exc:
            return JSONResponse(
                status_code=400,
                content=error_response(
                    exc.message,
                    code=exc.code,
                    data={"trace_id": exc.trace_id, **(exc.data or {})},
                ),
            )
        return success_response(result.model_dump(mode="json", by_alias=True))

    service = get_plan_service()
    try:
        result, _trip_id = await service.plan(payload)
    except PlanServiceError as exc:
        return JSONResponse(
            status_code=400,
            content=error_response(
                exc.message,
                code=exc.code,
                data={"trace_id": exc.trace_id, **(exc.data or {})},
            ),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return JSONResponse(
            status_code=502,
            content=error_response("规划失败", code=14079, data={"error": str(exc)}),
        )
    return success_response(result.model_dump(mode="json", by_alias=True))


@router.get(
    "/plan/tasks/{task_id}",
    summary="查询 Deep 规划任务状态",
    description="Stage-8：轮询任务状态与结果（仅任务所属用户或 Admin 可读）。",
)
async def get_plan_task(
    task_id: str,
    request: Request,
    user_id: int | None = Query(default=None, ge=1),
):
    service = get_plan_task_service()
    try:
        task = service.get_task(task_id, request=request, user_id=user_id)
    except PlanTaskServiceError as exc:
        status = 404 if exc.code == 14084 else 400
        return JSONResponse(
            status_code=status,
            content=error_response(
                exc.message,
                code=exc.code,
                data={"trace_id": exc.trace_id, **(exc.data or {})},
            ),
        )
    return success_response(task.model_dump(mode="json", by_alias=True))


async def _enqueue_sse_chunk(queue: asyncio.Queue[str], chunk: AiStreamChunk) -> None:
    if not chunk.delta and not chunk.done:
        return
    event = {
        "event": "chunk",
        "trace_id": chunk.trace_id,
        "index": chunk.index,
        "delta": chunk.delta,
        "done": chunk.done,
    }
    await queue.put(_format_sse(event))


async def _event_stream(queue: asyncio.Queue[str], producer_task: asyncio.Task):
    try:
        while True:
            chunk = await queue.get()
            yield chunk
            if chunk.strip().endswith("[DONE]"):
                break
    finally:
        if not producer_task.done():
            producer_task.cancel()
            with suppress(asyncio.CancelledError):
                await producer_task


@router.post(
    "/chat_demo",
    summary="AI 问答演示",
    description="串联 AiClient 与 mem0，演示上下文增强与记忆写入。",
)
async def chat_demo(payload: ChatDemoPayload):
    service = _demo_service()
    if payload.stream:
        return await _stream_chat(service, payload)

    try:
        result = await service.run_chat(payload)
    except AiClientError as exc:
        data = {"trace_id": exc.trace_id, "error_type": exc.type}
        return JSONResponse(
            status_code=502,
            content=error_response("AI 调用失败", code=3001, data=data),
        )
    return success_response(result.model_dump(mode="json"))


@router.post(
    "/chat",
    summary="智能助手（多轮，对接 LangGraph）",
    description="支持 session_id 的多轮对话，行程查询与记忆读写，支持流式输出。",
)
async def chat(payload: ChatPayload):
    service = _assistant_service()
    if payload.stream:
        return await _stream_assistant(service, payload)
    try:
        result = await service.run_chat(payload)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content=error_response(str(exc), code=14030),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return JSONResponse(
            status_code=502,
            content=error_response("AI 调用失败", code=3001, data={"error": str(exc)}),
        )
    return success_response(result.model_dump(mode="json"))


async def _stream_chat(
    service: AiChatDemoService,
    payload: ChatDemoPayload,
) -> StreamingResponse:
    queue: asyncio.Queue[str] = asyncio.Queue()

    async def on_chunk(chunk: AiStreamChunk) -> None:
        await _enqueue_sse_chunk(queue, chunk)

    async def producer() -> None:
        try:
            result = await service.run_chat(payload, stream_handler=on_chunk)
            await queue.put(
                _format_sse(
                    {
                        "event": "result",
                        "payload": result.model_dump(mode="json"),
                    }
                )
            )
        except AiClientError as exc:
            await queue.put(
                _format_sse(
                    {
                        "event": "error",
                        "error_type": exc.type,
                        "message": exc.message,
                        "trace_id": exc.trace_id,
                    }
                )
            )
        finally:
            await queue.put("data: [DONE]\n\n")

    producer_task = asyncio.create_task(producer())
    return StreamingResponse(
        _event_stream(queue, producer_task), media_type="text/event-stream"
    )


async def _stream_assistant(
    service: AssistantService,
    payload: ChatPayload,
) -> StreamingResponse:
    queue: asyncio.Queue[str] = asyncio.Queue()

    async def on_chunk(chunk: AiStreamChunk) -> None:
        await _enqueue_sse_chunk(queue, chunk)

    async def producer() -> None:
        try:
            result = await service.run_chat(payload, stream_handler=on_chunk)
            await queue.put(
                _format_sse(
                    {
                        "event": "result",
                        "payload": result.model_dump(mode="json"),
                    }
                )
            )
        except ValueError as exc:
            await queue.put(
                _format_sse(
                    {
                        "event": "error",
                        "error_type": "bad_request",
                        "message": str(exc),
                    }
                )
            )
        except Exception as exc:  # pragma: no cover - defensive
            await queue.put(
                _format_sse(
                    {
                        "event": "error",
                        "error_type": exc.__class__.__name__,
                        "message": "AI 调用失败",
                    }
                )
            )
        finally:
            await queue.put("data: [DONE]\n\n")

    producer_task = asyncio.create_task(producer())
    return StreamingResponse(
        _event_stream(queue, producer_task), media_type="text/event-stream"
    )


def _format_sse(payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"data: {data}\n\n"
