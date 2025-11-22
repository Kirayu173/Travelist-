from __future__ import annotations

import os
from random import randint
from typing import Any, Dict, List

from app.agents.tools.common.logging import tool_logger
from langchain_core.tools.structured import StructuredTool
from pydantic import BaseModel, Field, field_validator

logger = tool_logger("area_weather")


class AreaWeatherInput(BaseModel):
    locations: List[str] = Field(..., description="查询地点列表，支持城市名或区县名")
    weather_type: str = Field(
        default="realtime",
        description="天气类型 realtime(实况)/forecast(预报)",
    )
    days: int = Field(
        default=1,
        ge=1,
        le=4,
        description="预报天数，仅当 weather_type=forecast 时生效",
    )

    @field_validator("locations")
    @classmethod
    def ensure_locations(cls, value: List[str]) -> List[str]:
        if not value:
            msg = "locations cannot be empty"
            raise ValueError(msg)
        return value


class AreaWeatherTool(StructuredTool):
    """Offline-friendly weather summarizer."""

    def __init__(self, **kwargs):
        super().__init__(
            func=self._run,
            coroutine=self._arun,
            name="area_weather",
            description="查询多地点天气（本地估算）。无真实 API 时返回模拟数据，保留结构化字段。",
            args_schema=AreaWeatherInput,
            return_direct=False,
            handle_tool_error=True,
            **kwargs,
        )

    def _run(self, **kwargs) -> Dict[str, Any]:
        try:
            payload = AreaWeatherInput(**kwargs)
        except Exception as exc:
            return {"error": f"参数错误: {exc}"}

        has_key = bool(os.environ.get("AMAP_API_KEY"))
        results = []
        for loc in payload.locations:
            seed = sum(ord(ch) for ch in loc)
            temp = 15 + seed % 15
            results.append(
                {
                    "location": loc,
                    "weather": self._sample_weather(seed),
                    "temperature_c": temp,
                    "humidity": 40 + seed % 50,
                    "source": "amap_key" if has_key else "mock",
                }
            )
        summary = {
            "weather_type": payload.weather_type,
            "days": payload.days,
            "total_locations": len(results),
        }
        if payload.weather_type == "forecast":
            for item in results:
                item["forecast"] = [
                    {"day_offset": idx + 1, "high_c": temp + 2, "low_c": temp - 3}
                    for idx, temp in enumerate([item["temperature_c"]] * payload.days)
                ]
        return {"summary": summary, "results": results}

    async def _arun(self, **kwargs) -> Dict[str, Any]:
        return self._run(**kwargs)

    @staticmethod
    def _sample_weather(seed: int) -> str:
        options = ["晴", "多云", "小雨", "阵雨", "阴"]
        return options[seed % len(options)]


def create_tool() -> AreaWeatherTool:
    return AreaWeatherTool()
