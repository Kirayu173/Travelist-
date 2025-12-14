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
        model_override = str(request.model or "").strip()
        used_model = model_override or self._model
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
                model=used_model,
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
            model=used_model,
            latency_ms=round(latency, 3),
            usage_tokens=usage_tokens,
            raw=raw,
            trace_id=trace_id,
        )
        self._metrics.record_ai_call(
            trace_id=trace_id,
            provider=self._provider,
            model=used_model,
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
        if request.response_format == "json":
            answer = self._mock_json_response(prompt)
        else:
            answer = f"mock:{prompt}"
        if request.tools:
            # Minimal tool-calling stub for tests: always suggest calling the first tool
            # once, then return a textual "done" message after a tool result appears.
            has_tool_result = any(msg.role == "tool" for msg in request.messages)
            if not has_tool_result:
                first = request.tools[0] if request.tools else None
                fn = (
                    ((first or {}).get("function") or {})
                    if isinstance(first, dict)
                    else {}
                )
                tool_name = fn.get("name") or "unknown_tool"
                raw = {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "mock_tool_call_0",
                                "type": "function",
                                "function": {"name": tool_name, "arguments": {}},
                            }
                        ],
                    }
                }
                answer = ""
            else:
                raw = {"message": {"role": "assistant", "content": "done"}}
                answer = "done"
            await self._emit_chunk(
                trace_id=trace_id,
                delta=answer,
                index=0,
                done=True,
                on_chunk=on_chunk,
            )
            return answer, len(answer.split()) if answer else 0, raw
        await self._emit_chunk(
            trace_id=trace_id,
            delta=answer,
            index=0,
            done=True,
            on_chunk=on_chunk,
        )
        return answer, len(answer.split()), {"mock": True}

    @staticmethod
    def _mock_json_response(prompt: str) -> str:
        """Return deterministic JSON for tests and local development."""

        try:
            payload = json.loads(prompt)
        except Exception:
            payload = {}

        if isinstance(payload, dict) and payload.get("task") == "plan_day":
            day_index = int(payload.get("day_index") or 0)
            date = str(payload.get("date") or "2025-01-01")
            destination = str(payload.get("destination") or "目的地")
            prefs = (
                payload.get("preferences")
                if isinstance(payload.get("preferences"), dict)
                else {}
            )
            interests = (
                prefs.get("interests")
                if isinstance(prefs.get("interests"), list)
                else []
            )
            candidate_pois = (
                payload.get("candidate_pois")
                if isinstance(payload.get("candidate_pois"), list)
                else []
            )
            used_list = (
                payload.get("used_pois")
                if isinstance(payload.get("used_pois"), list)
                else []
            )

            used_keys: set[tuple[str, str]] = set()
            for item in used_list:
                if not isinstance(item, dict):
                    continue
                provider = str(item.get("provider") or "").strip()
                provider_id = str(item.get("provider_id") or "").strip()
                if provider and provider_id:
                    used_keys.add((provider, provider_id))

            def _pick_poi(category: str | None) -> dict[str, Any] | None:
                for poi in candidate_pois:
                    if not isinstance(poi, dict):
                        continue
                    provider = str(poi.get("provider") or "").strip()
                    provider_id = str(poi.get("provider_id") or "").strip()
                    if not provider or not provider_id:
                        continue
                    if (provider, provider_id) in used_keys:
                        continue
                    if (
                        category
                        and str(poi.get("category") or "").strip().lower()
                        != category.lower()
                    ):
                        continue
                    return poi
                for poi in candidate_pois:
                    if not isinstance(poi, dict):
                        continue
                    provider = str(poi.get("provider") or "").strip()
                    provider_id = str(poi.get("provider_id") or "").strip()
                    if not provider or not provider_id:
                        continue
                    if (provider, provider_id) in used_keys:
                        continue
                    return poi
                return None

            preferred = [str(x).strip().lower() for x in interests if str(x).strip()]
            first_cat = preferred[0] if preferred else None
            second_cat = preferred[1] if len(preferred) > 1 else first_cat

            poi1 = _pick_poi(first_cat)
            if poi1:
                used_keys.add(
                    (
                        str(poi1.get("provider") or ""),
                        str(poi1.get("provider_id") or ""),
                    )
                )
            poi2 = _pick_poi(second_cat)

            def _sub_trip(
                order_index: int,
                slot: str,
                start: str,
                end: str,
                poi: dict[str, Any] | None,
            ):
                category = str(poi.get("category") or "") if poi else ""
                activity = {
                    "food": "美食探索",
                    "sight": "景点游览",
                    "museum": "博物馆参观",
                    "park": "公园漫步",
                }.get(category.lower() if category else "", "自由探索")
                ext: dict[str, Any] = {"slot": slot, "planner": {"mock": True}}
                if poi:
                    ext["poi"] = {
                        "provider": poi.get("provider"),
                        "provider_id": poi.get("provider_id"),
                        "category": poi.get("category"),
                        "addr": poi.get("addr"),
                        "rating": poi.get("rating"),
                        "name": poi.get("name"),
                    }
                return {
                    "order_index": order_index,
                    "activity": activity,
                    "poi_id": None,
                    "loc_name": (poi.get("name") if poi else destination),
                    "start_time": start,
                    "end_time": end,
                    "lat": poi.get("lat") if poi else None,
                    "lng": poi.get("lng") if poi else None,
                    "ext": ext,
                }

            day_card = {
                "day_index": day_index,
                "date": date,
                "note": None,
                "sub_trips": [
                    _sub_trip(0, "morning", "09:00", "11:00", poi1),
                    _sub_trip(1, "afternoon", "14:00", "16:00", poi2),
                ],
            }
            return json.dumps(day_card, ensure_ascii=False)

        return json.dumps({"mock": True, "echo": prompt}, ensure_ascii=False)

    async def _chat_ollama(
        self,
        request: AiChatRequest,
        *,
        on_chunk: StreamCallback | None,
        trace_id: str,
    ) -> tuple[str, int | None, dict | None]:
        url = f"{self._api_base}/api/chat"
        model_override = str(request.model or "").strip()
        used_model = model_override or self._model
        payload: dict[str, Any] = {
            "model": used_model,
            "messages": [
                msg.model_dump(mode="json", exclude_none=True)
                for msg in request.messages
            ],
            "stream": True,
        }
        if request.tools:
            payload["tools"] = request.tools
            payload["stream"] = False
        if request.response_format == "json":
            payload["format"] = "json"
        options: dict[str, Any] = {}
        if request.temperature is not None:
            options["temperature"] = float(request.temperature)
        if request.max_tokens is not None:
            options["num_predict"] = int(request.max_tokens)
        if options:
            payload["options"] = options

        text_parts: list[str] = []
        last_payload: dict | None = None
        usage_tokens: int | None = None
        chunk_index = 0

        timeout = httpx.Timeout(request.timeout_s)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if request.tools:
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    last_payload = data
                    message = data.get("message") or {}
                    answer = message.get("content") or ""
                    usage_tokens = (
                        data.get("eval_count")
                        or data.get("total_tokens")
                        or data.get("prompt_eval_count")
                    )
                    await self._emit_chunk(
                        trace_id=trace_id,
                        delta=answer,
                        index=0,
                        done=True,
                        on_chunk=on_chunk,
                    )
                    if not answer and not (message.get("tool_calls") or []):
                        raise AiClientError(
                            "invalid_output",
                            "provider returned empty response",
                        )
                    return answer, usage_tokens, last_payload
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
