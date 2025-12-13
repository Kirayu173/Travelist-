from __future__ import annotations

import asyncio

import pytest
from app.agents.tools.registry import RegisteredTool, ToolExecutionError, ToolRegistry
from pydantic import BaseModel


class _Args(BaseModel):
    text: str


def test_tool_registry_runs_sync_and_async():
    registry = ToolRegistry()

    def _sync_tool(text: str) -> str:
        return text.upper()

    async def _async_tool(text: str) -> str:
        await asyncio.sleep(0)
        return text + "!"

    registry.register_structured_tool(
        name="sync_tool",
        description="sync",
        args_schema=_Args,
        category="test",
        loader=lambda: _sync_tool,
        source="unit",
    )
    registry.register_structured_tool(
        name="async_tool",
        description="async",
        args_schema=_Args,
        category="test",
        loader=lambda: _async_tool,
        source="unit",
    )

    sync_tool = registry.get("sync_tool")
    async_tool = registry.get("async_tool")
    assert isinstance(sync_tool, RegisteredTool)
    assert isinstance(async_tool, RegisteredTool)

    result_sync = asyncio.get_event_loop().run_until_complete(
        sync_tool.invoke({"text": "hi"})
    )
    result_async = asyncio.get_event_loop().run_until_complete(
        async_tool.invoke({"text": "hi"})
    )
    assert result_sync == "HI"
    assert result_async == "hi!"


def test_tool_registry_handles_validation_error():
    registry = ToolRegistry()
    registry.register_structured_tool(
        name="validator",
        description="validate",
        args_schema=_Args,
        category="test",
        loader=lambda: (lambda text: text),
        source="unit",
    )
    tool = registry.get("validator")
    with pytest.raises(ToolExecutionError):
        asyncio.get_event_loop().run_until_complete(tool.invoke({"wrong": "x"}))
