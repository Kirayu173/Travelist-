from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

import httpx
from app.ai.exceptions import AiClientError
from app.ai.metrics import AiMetrics, get_ai_metrics
from app.ai.models import (
    AiChatRequest,
    AiChatResult,
    AiStreamChunk,
    StreamCallback,
)
from app.core.logging import get_logger
from app.core.settings import settings


class AiClient:
    """Unified asynchronous client for LLM providers."""

    def __init__(self, metrics: AiMetrics | None = None) -> None:
        self._settings = settings
        provider_value = self._settings.ai_provider or self._settings.llm_provider
        self._provider = (provider_value or "ollama").strip().lower()
        self._model = (self._settings.ai_model_chat or "gpt-oss:120b-cloud").strip()
        self._api_base = (
            self._settings.ai_api_base or "http://127.0.0.1:11434"
        ).rstrip("/")
        self._logger = get_logger(__name__)
        self._metrics = metrics or get_ai_metrics()

    async def chat(
        self,
        request: AiChatRequest,
        *,
        on_chunk: StreamCallback | None = None,
    ) -> AiChatResult:
        if not self._provider or self._provider == "disabled":
            msg = "AI provider is not configured"
            raise AiClientError("not_configured", msg)

        trace_id = self._build_trace_id()
        start = perf_counter()
        try:
            if self._provider == "mock":
                content, usage_tokens, raw = await self._chat_mock(
                    request,
                    on_chunk=on_chunk,
                    trace_id=trace_id,
                )
            elif self._provider == "ollama":
                content, usage_tokens, raw = await self._chat_ollama(
                    request,
                    on_chunk=on_chunk,
                    trace_id=trace_id,
                )
            else:
                raise AiClientError(
                    "provider_error",
                    f"unsupported provider: {self._provider}",
                )
        except AiClientError as exc:
            latency = (perf_counter() - start) * 1000
            self._metrics.record_ai_call(
                trace_id=trace_id,
                provider=self._provider,
                model=self._model,
                latency_ms=latency,
                success=False,
                error_type=exc.type,
            )
            exc.trace_id = exc.trace_id or trace_id
            raise

        latency = (perf_counter() - start) * 1000
        result = AiChatResult(
            content=content,
            provider=self._provider,
            model=self._model,
            latency_ms=round(latency, 3),
            usage_tokens=usage_tokens,
            raw=raw,
            trace_id=trace_id,
        )
        self._metrics.record_ai_call(
            trace_id=trace_id,
            provider=self._provider,
            model=self._model,
            latency_ms=result.latency_ms,
            success=True,
            error_type=None,
            usage_tokens=usage_tokens,
        )
        return result

    async def _chat_mock(
        self,
        request: AiChatRequest,
        *,
        on_chunk: StreamCallback | None,
        trace_id: str,
    ) -> tuple[str, int | None, dict]:
        prompt = request.messages[-1].content
        answer = f"mock:{prompt}"
        await self._emit_chunk(
            trace_id=trace_id,
            delta=answer,
            index=0,
            done=True,
            on_chunk=on_chunk,
        )
        return answer, len(answer.split()), {"mock": True}

    async def _chat_ollama(
        self,
        request: AiChatRequest,
        *,
        on_chunk: StreamCallback | None,
        trace_id: str,
    ) -> tuple[str, int | None, dict | None]:
        url = f"{self._api_base}/api/chat"
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [msg.model_dump(mode="json") for msg in request.messages],
            "stream": True,
        }
        if request.response_format == "json":
            payload["format"] = "json"

        text_parts: list[str] = []
        last_payload: dict | None = None
        usage_tokens: int | None = None
        chunk_index = 0

        timeout = httpx.Timeout(request.timeout_s)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload) as response:
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        raise self._http_error(exc) from exc

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        data = self._parse_json_line(line)
                        last_payload = data
                        message = data.get("message") or {}
                        delta = message.get("content") or ""
                        if delta:
                            text_parts.append(delta)
                            await self._emit_chunk(
                                trace_id=trace_id,
                                delta=delta,
                                index=chunk_index,
                                done=False,
                                on_chunk=on_chunk,
                            )
                            chunk_index += 1
                        if data.get("done"):
                            usage_tokens = (
                                data.get("eval_count")
                                or data.get("total_tokens")
                                or data.get("prompt_eval_count")
                            )
                            break
        except httpx.TimeoutException as exc:
            raise AiClientError(
                "timeout",
                "AI provider request timed out",
                details={"error": str(exc)},
            ) from exc
        except httpx.RequestError as exc:
            raise AiClientError(
                "network_error",
                "failed to reach AI provider",
                details={"error": str(exc)},
            ) from exc

        if not text_parts:
            raise AiClientError("invalid_output", "provider returned empty response")
        answer = "".join(text_parts)
        await self._emit_chunk(
            trace_id=trace_id,
            delta="",
            index=chunk_index,
            done=True,
            on_chunk=on_chunk,
        )
        return answer, usage_tokens, last_payload

    async def _emit_chunk(
        self,
        *,
        trace_id: str,
        delta: str,
        index: int,
        done: bool,
        on_chunk: StreamCallback | None,
    ) -> None:
        if on_chunk is None:
            return
        chunk = AiStreamChunk(
            trace_id=trace_id,
            delta=delta,
            index=index,
            done=done,
        )
        maybe_awaitable = on_chunk(chunk)
        if maybe_awaitable is not None:
            await maybe_awaitable

    @staticmethod
    def _build_trace_id() -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        suffix = secrets.token_hex(4)
        return f"ai-{timestamp}-{suffix}"

    @staticmethod
    def _parse_json_line(line: str) -> dict:
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise AiClientError(
                "invalid_output",
                f"provider returned non-JSON chunk: {line[:100]}",
            ) from exc

    @staticmethod
    def _http_error(exc: httpx.HTTPStatusError) -> AiClientError:
        text = exc.response.text
        return AiClientError(
            "provider_error",
            f"provider returned status {exc.response.status_code}",
            status_code=exc.response.status_code,
            details={"body": text[:200]},
        )


_ai_client: AiClient | None = None


def get_ai_client() -> AiClient:
    global _ai_client
    if _ai_client is None:
        _ai_client = AiClient()
    return _ai_client


def reset_ai_client() -> None:
    global _ai_client
    _ai_client = None
