from __future__ import annotations

from typing import Callable

from app.agents.tools.navigation.path_navigate import PathNavigateTool
from app.agents.tools.registry import ToolRegistry
from app.agents.tools.search.deep_extract import DeepExtractTool
from app.agents.tools.search.deep_search import DeepSearchTool
from app.agents.tools.search.fast_search import FastSearchTool
from app.agents.tools.system.current_time import CurrentTimeTool
from app.agents.tools.weather.area_weather import AreaWeatherTool
from app.agents.tools.weather.weather_search import WeatherSearchTool


def _add_tool(
    registry: ToolRegistry,
    factory: Callable[[], object],
    category: str,
) -> None:
    instance = factory()
    registry.register_structured_tool(
        name=getattr(instance, "name", instance.__class__.__name__),
        description=getattr(instance, "description", instance.__doc__ or "").strip(),
        args_schema=getattr(instance, "args_schema", None),
        category=category,
        loader=lambda inst=instance: inst,
        source="agents.tools",
    )


def build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    _add_tool(registry, CurrentTimeTool, "system")
    _add_tool(registry, PathNavigateTool, "navigation")
    _add_tool(registry, AreaWeatherTool, "weather")
    _add_tool(registry, WeatherSearchTool, "weather")
    _add_tool(registry, FastSearchTool, "search")
    _add_tool(registry, DeepSearchTool, "search")
    _add_tool(registry, DeepExtractTool, "search")
    return registry
