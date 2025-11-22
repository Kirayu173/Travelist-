from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agents.tools.common.logging import tool_logger
from langchain_core.tools.structured import StructuredTool
from pydantic import BaseModel, Field

logger = tool_logger("weather_search")


class WeatherSearchInput(BaseModel):
    destination: str = Field(..., description="目标地点，如 Paris")
    month: str = Field(..., description="月份或时间范围，如 2025-11")
    max_results: Optional[int] = Field(default=5, ge=1, le=10)


class WeatherSearchTool(StructuredTool):
    """Generate a lightweight weather summary without external API calls."""

    def __init__(self, **kwargs):
        super().__init__(
            func=self._run,
            coroutine=self._arun,
            name="weather_search",
            description="根据地点和月份生成天气概览（温度、降雨概率、简要建议），无需外部 API。",
            args_schema=WeatherSearchInput,
            return_direct=False,
            handle_tool_error=True,
            **kwargs,
        )

    def _run(self, **kwargs) -> Dict[str, Any]:
        try:
            payload = WeatherSearchInput(**kwargs)
        except Exception as exc:
            return {"error": f"参数错误: {exc}"}

        summary = (
            f"{payload.destination} 在 {payload.month} 的典型天气："
            "温度温和，注意携带基础出行装备。"
        )
        results: List[Dict[str, Any]] = []
        for idx in range(payload.max_results or 3):
            results.append(
                {
                    "title": f"{payload.destination} 天气参考 #{idx + 1}",
                    "snippet": "温度区间约在 10℃-25℃，早晚温差适中，建议分层穿着。",
                    "link": f"https://example.com/weather/{payload.destination}/{payload.month}/{idx+1}",
                }
            )

        return {
            "weather_summary": summary,
            "destination": payload.destination,
            "month": payload.month,
            "web_results": results,
        }

    async def _arun(self, **kwargs) -> Dict[str, Any]:
        return self._run(**kwargs)


def create_tool() -> WeatherSearchTool:
    return WeatherSearchTool()
