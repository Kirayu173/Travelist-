from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, Optional

from app.agents.tools.common.logging import tool_logger
from langchain_core.tools.structured import StructuredTool
from pydantic import BaseModel, Field

logger = tool_logger("current_time")


class CurrentTimeInput(BaseModel):
    timezone: Optional[str] = Field(
        default=None,
        description="可选时区名称，如 Asia/Shanghai、UTC，不指定则使用系统时区",
    )
    format: Optional[str] = Field(
        default="%Y-%m-%d %H:%M:%S %Z%z",
        description="时间格式字符串，默认 YYYY-MM-DD HH:MM:SS 时区",
    )


class CurrentTimeTool(StructuredTool):
    """Simple time utility that works offline."""

    def __init__(self, **kwargs):
        super().__init__(
            func=self._run,
            coroutine=self._arun,
            name="current_time",
            description="获取当前时间或指定时区时间，返回结构化字段（ISO、时间戳、日期组成等）。",
            args_schema=CurrentTimeInput,
            return_direct=False,
            handle_tool_error=True,
            **kwargs,
        )

    def _run(self, **kwargs) -> Dict[str, Any]:
        try:
            timezone_str = kwargs.get("timezone")
            fmt = kwargs.get("format") or "%Y-%m-%d %H:%M:%S %Z%z"
            now = self._now(timezone_str)
            return self._format(now, fmt, timezone_str)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("current_time.failed", extra={"error": str(exc)})
            return {"error": f"时间获取失败: {exc}"}

    async def _arun(self, **kwargs) -> Dict[str, Any]:
        return self._run(**kwargs)

    def _now(self, timezone_str: str | None) -> _dt.datetime:
        if not timezone_str:
            return _dt.datetime.now()
        try:
            from zoneinfo import ZoneInfo
        except Exception:  # pragma: no cover - fallback
            return _dt.datetime.now()
        try:
            return _dt.datetime.now(ZoneInfo(timezone_str))
        except Exception:
            logger.warning("current_time.invalid_timezone", extra={"tz": timezone_str})
            return _dt.datetime.now()

    def _format(
        self,
        current: _dt.datetime,
        fmt: str,
        timezone_str: str | None,
    ) -> Dict[str, Any]:
        try:
            formatted = current.strftime(fmt)
        except Exception:
            formatted = current.isoformat()
        timestamp = current.timestamp()
        offset = None
        if current.tzinfo:
            delta = current.utcoffset()
            offset = (delta.total_seconds() / 3600) if delta else None

        return {
            "current_time": formatted,
            "iso_format": current.isoformat(),
            "timezone": timezone_str or (current.tzname() or "local"),
            "timestamp": {"unix": int(timestamp), "milliseconds": int(timestamp * 1000)},
            "utc_offset_hours": offset,
            "summary": f"{formatted} ({timezone_str or 'local'})",
        }


def create_tool() -> CurrentTimeTool:
    return CurrentTimeTool()
