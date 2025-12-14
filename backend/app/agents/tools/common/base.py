from __future__ import annotations

from langchain_core.tools import BaseTool


class TravelistBaseTool(BaseTool):
    """Project-standard BaseTool (pydantic v2) configuration."""

    return_direct: bool = False
    handle_tool_error: bool = True
