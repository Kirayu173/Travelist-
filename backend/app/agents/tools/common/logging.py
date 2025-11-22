from __future__ import annotations

from app.core.logging import get_logger


def tool_logger(name: str):
    """Return a namespaced logger for agent tools."""

    return get_logger(f"agent_tool.{name}")
