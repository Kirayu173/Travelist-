from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable

from app.core.logging import get_logger
from pydantic import BaseModel, ValidationError

Runner = Callable[[dict[str, Any]], Awaitable[Any]]


class ToolExecutionError(Exception):
    """Raised when a tool fails to execute."""

    def __init__(self, message: str, *, name: str | None = None) -> None:
        super().__init__(message)
        self.name = name


@dataclass(slots=True)
class RegisteredTool:
    name: str
    description: str
    args_schema: type[BaseModel] | None
    runner: Runner
    category: str | None = None
    source: str | None = None
    obj: Any | None = None

    async def invoke(self, payload: dict[str, Any]) -> Any:
        kwargs = self._validate_payload(payload)
        return await self.runner(kwargs)

    def _validate_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.args_schema:
            return payload
        try:
            return self.args_schema(**payload).model_dump()
        except ValidationError as exc:
            raise ToolExecutionError(
                f"invalid parameters for tool '{self.name}'", name=self.name
            ) from exc


class ToolRegistry:
    """Central registry for agent tools with defensive loading."""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        self._failures: dict[str, str] = {}
        self._logger = get_logger(__name__)

    def register_structured_tool(
        self,
        *,
        name: str,
        description: str,
        args_schema: type[BaseModel] | None,
        category: str | None,
        loader: Callable[[], Any],
        source: str | None = None,
    ) -> None:
        if name in self._tools:
            self._logger.warning("tool.duplicate", extra={"tool": name})
            return
        try:
            tool_obj = loader()
        except Exception as exc:  # pragma: no cover - defensive
            self._failures[name] = f"init_failed: {exc}"
            self._logger.warning(
                "tool.load_failed",
                extra={"tool": name, "error": str(exc)},
            )
            return

        runner = self._build_runner(tool_obj, name)
        registered = RegisteredTool(
            name=name,
            description=description.strip(),
            args_schema=args_schema,
            runner=runner,
            category=category,
            source=source,
            obj=tool_obj,
        )
        self._tools[name] = registered
        self._logger.info(
            "tool.registered",
            extra={"tool": name, "category": category, "source": source},
        )

    def available(self) -> list[RegisteredTool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return sorted(self._tools.keys())

    def failures(self) -> dict[str, str]:
        return dict(self._failures)

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def describe(self) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for tool in self._tools.values():
            items.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "category": tool.category or "",
                }
            )
        return items

    @staticmethod
    def _build_runner(tool_obj: Any, name: str) -> Runner:
        async def _runner(payload: dict[str, Any]) -> Any:
            if hasattr(tool_obj, "_arun"):
                return await tool_obj._arun(**payload)
            if hasattr(tool_obj, "ainvoke"):
                return await tool_obj.ainvoke(payload)
            if hasattr(tool_obj, "_run"):
                return await asyncio.to_thread(tool_obj._run, **payload)
            if callable(tool_obj):
                result = tool_obj(**payload)
                if asyncio.iscoroutine(result):
                    return await result
                return result
            raise ToolExecutionError(f"tool '{name}' is not callable", name=name)

        return _runner


def ensure_registry_tools(
    registry: ToolRegistry, specs: Iterable[dict[str, Any]]
) -> ToolRegistry:
    """Register tools from a collection of specs."""

    for spec in specs:
        registry.register_structured_tool(**spec)
    return registry
