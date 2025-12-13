from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger
from app.core.settings import settings


@dataclass
class AgentContext:
    user_id: str
    session_id: str | None = None


class ToolAgentRunner:
    """Wrapper around langchain create_agent to orchestrate tool calls."""

    def __init__(self, tools: list[Any]) -> None:
        self._tools = tools
        self._logger = get_logger(__name__)
        self._agent = None
        self._checkpointer = None
        self._ensure_agent()

    def _ensure_agent(self) -> None:
        if self._agent:
            return
        try:
            from langchain.agents import create_agent
            from langchain_ollama import ChatOllama
            from langgraph.checkpoint.memory import InMemorySaver
        except Exception as exc:  # pragma: no cover - optional dependency
            self._logger.warning("tool_agent.init_failed", extra={"error": str(exc)})
            return

        model = ChatOllama(
            model=settings.ai_model_chat or "gpt-oss:120b-cloud",
            temperature=0,
            base_url=settings.ai_api_base or "http://127.0.0.1:11434",
        )
        system_prompt = self._build_prompt()
        self._checkpointer = InMemorySaver()
        self._agent = create_agent(
            model=model,
            system_prompt=system_prompt,
            tools=self._tools,
            context_schema=AgentContext,
            checkpointer=self._checkpointer,
        )

    def _build_prompt(self) -> str:
        lines = [
            "你是 Travelist+ 的工具调度代理，必须严格按工具定义使用参数，"
            "必要时礼貌澄清缺失信息。",
            "可用工具列表：",
        ]
        for tool in self._tools:
            name = getattr(tool, "name", tool.__class__.__name__)
            desc = getattr(tool, "description", "") or ""
            schema = getattr(tool, "args_schema", None)
            args_desc = []
            if schema:
                for field_name, field in schema.model_fields.items():
                    field_desc = field.description or field_name
                    args_desc.append(f"- {field_name}: {field_desc}")
            args_text = "\n".join(args_desc) if args_desc else "无特定参数要求"
            lines.append(f"* {name}: {desc}\n{args_text}")
        return "\n".join(lines)

    async def run(self, *, messages: list[dict[str, str]], context: AgentContext):
        if not self._agent:
            raise RuntimeError("tool agent not initialized (missing dependencies?)")
        config = {"configurable": {"thread_id": context.session_id or "tool-agent"}}
        return await asyncio.to_thread(
            self._agent.invoke,
            {"messages": messages},
            config=config,
            context=context,
        )


def build_tool_agent(tools: list[Any]) -> ToolAgentRunner | None:
    materialized = []
    for tool in tools:
        # RegisteredTool keeps original object in .obj
        obj = getattr(tool, "obj", None)
        if obj is not None:
            materialized.append(obj)
        elif tool is not None:
            materialized.append(tool)
    runner = ToolAgentRunner(materialized)
    return runner if runner._agent else None
