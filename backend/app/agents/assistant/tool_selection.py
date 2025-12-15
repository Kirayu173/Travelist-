from __future__ import annotations

import json
from typing import Any

from app.agents.assistant.state import AssistantState
from app.agents.tools.registry import RegisteredTool, ToolRegistry
from app.ai import AiChatRequest, AiClient, AiClientError, AiMessage
from app.ai.prompts import PromptRegistry
from app.core.cache import build_cache_key, cache_backend
from app.core.logging import get_logger
from app.core.settings import settings


class ToolSelector:
    """LLM-driven tool selector with heuristic fallback."""

    def __init__(
        self,
        ai_client: AiClient,
        prompt_registry: PromptRegistry,
        tool_registry: ToolRegistry,
    ) -> None:
        self._ai_client = ai_client
        self._prompt_registry = prompt_registry
        self._tool_registry = tool_registry
        self._logger = get_logger(__name__)

    async def select_tool(
        self,
        state: AssistantState,
    ) -> tuple[str | None, dict[str, Any], str | None]:
        available = self._tool_registry.available()
        if not available:
            return None, {}, "no_tools_available"

        ttl = int(getattr(settings, "ai_tool_select_cache_ttl_seconds", 30))
        tools_sig = ",".join(sorted(tool.name for tool in available))
        cache_key = build_cache_key(
            "assistant:tool_select",
            q=state.query,
            intent=state.intent or "",
            tools=tools_sig,
            session_id=state.session_id or 0,
        )

        async def _compute():
            model_choice = await self._run_llm_routing(state, available)
            if model_choice:
                name, args, reason = model_choice
                return name, args, reason

            heuristic_choice = self._heuristic_choice(state.query)
            if heuristic_choice:
                return heuristic_choice
            return None, {}, "no_tool_matched"

        name, args, reason = await cache_backend.remember_async(
            "assistant_tool_select",
            cache_key,
            ttl,
            _compute,
        )
        return name, args, reason

    async def _run_llm_routing(
        self,
        state: AssistantState,
        available: list[RegisteredTool],
    ) -> tuple[str, dict[str, Any], str] | None:
        prompt = self._prompt_registry.get_prompt("assistant.tools.selector")
        tool_lines = [
            f"- {tool.name}: {tool.description}"
            + (f" (category: {tool.category})" if tool.category else "")
            for tool in available
        ]
        tools_block = "\n".join(tool_lines)
        user_block = (
            f"用户问题: {state.query}\n"
            f"已识别意图: {state.intent or 'unknown'}\n"
            f"可用工具:\n{tools_block}"
        )
        messages = [
            AiMessage(role=prompt.role, content=prompt.content),
            AiMessage(role="user", content=user_block),
        ]
        request = AiChatRequest(
            messages=messages,
            response_format="text",
            timeout_s=settings.ai_request_timeout_s,
        )
        try:
            result = await self._ai_client.chat(request)
            parsed = self._parse_model_output(result.content, available)
            if parsed:
                self._logger.info(
                    "tool.selection.llm",
                    extra={
                        "trace_id": result.trace_id,
                        "tool": parsed[0],
                        "reason": parsed[2],
                    },
                )
                return parsed
            self._logger.info(
                "tool.selection.llm_empty",
                extra={"raw": result.content, "trace_id": result.trace_id},
            )
        except AiClientError as exc:  # pragma: no cover - defensive
            self._logger.warning(
                "tool.selection.ai_error",
                extra={"error": exc.message, "type": exc.type},
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.warning(
                "tool.selection.unexpected",
                extra={"error": str(exc)},
            )
        return None

    def _parse_model_output(
        self,
        raw: str,
        available: list[RegisteredTool],
    ) -> tuple[str, dict[str, Any], str] | None:
        if not raw:
            return None
        payload_text = raw.split("mock:", 1)[-1].strip() if "mock:" in raw else raw
        if not payload_text:
            return None
        try:
            data = json.loads(payload_text)
        except json.JSONDecodeError:
            return None

        name = data.get("tool") or data.get("name")
        if not name:
            return None
        if name not in {tool.name for tool in available}:
            return None
        args = data.get("arguments") or data.get("args") or {}
        reason = data.get("reason") or "model_selected"
        return name, args, reason

    def _heuristic_choice(self, query: str) -> tuple[str, dict[str, Any], str] | None:
        lowered = query.lower()
        if any(word in lowered for word in ["天气", "weather", "气温", "下雨"]):
            return (
                "weather_search",
                {"destination": query, "month": "当前或近期"},
                "heuristic:weather",
            )
        if any(word in lowered for word in ["路线", "路径", "导航", "route"]):
            return (
                "path_navigate",
                {"routes": [{"origin": "出发地", "destination": query}]},
                "heuristic:navigation",
            )
        if any(word in lowered for word in ["时间", "date", "clock", "几点"]):
            return "current_time", {}, "heuristic:time"
        if "提取" in lowered or "网页" in lowered:
            return (
                "deep_extract",
                {"urls": [query], "query": "提取关键信息"},
                "heuristic:extract",
            )
        if "搜" in lowered or "search" in lowered:
            return (
                "fast_search",
                {"query": query, "time_range": "week"},
                "heuristic:search",
            )
        return None
