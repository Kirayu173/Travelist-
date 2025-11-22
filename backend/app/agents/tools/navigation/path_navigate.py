from __future__ import annotations

import math
from typing import Any, Dict, List, Literal, Optional

from app.agents.tools.common.logging import tool_logger
from langchain_core.tools.structured import StructuredTool
from pydantic import BaseModel, Field, field_validator

logger = tool_logger("path_navigate")


class PathNavigateInput(BaseModel):
    routes: List[Dict[str, str]] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="路径列表，每项包含 origin 和 destination",
    )
    travel_mode: Literal["driving", "walking", "transit", "bicycling"] = "driving"
    strategy: int = Field(
        default=0,
        ge=0,
        le=9,
        description="驾车策略，仅 driving 生效",
    )
    city: Optional[str] = Field(default=None, description="可选城市名称，用于 transit 描述")

    @field_validator("routes")
    @classmethod
    def ensure_routes(cls, value: List[Dict[str, str]]) -> List[Dict[str, str]]:
        if not value:
            msg = "routes must not be empty"
            raise ValueError(msg)
        return value


class PathNavigateTool(StructuredTool):
    """Lightweight, offline-friendly route estimator."""

    def __init__(self, **kwargs):
        super().__init__(
            func=self._run,
            coroutine=self._arun,
            name="path_navigate",
            description="规划多条路线的粗略距离与时长评估（本地估算，缺少真实路况时返回近似值）。",
            args_schema=PathNavigateInput,
            return_direct=False,
            handle_tool_error=True,
            **kwargs,
        )

    def _run(self, **kwargs) -> Dict[str, Any]:
        try:
            payload = PathNavigateInput(**kwargs)
        except Exception as exc:
            return {"error": f"参数错误: {exc}"}

        results: list[dict[str, Any]] = []
        for route in payload.routes:
            origin = route.get("origin") or "未知起点"
            destination = route.get("destination") or "未知终点"
            distance_km = self._estimate_distance(origin, destination)
            duration_min = self._estimate_duration(distance_km, payload.travel_mode)
            results.append(
                {
                    "origin": origin,
                    "destination": destination,
                    "distance_km": round(distance_km, 1),
                    "duration_min": round(duration_min),
                    "travel_mode": payload.travel_mode,
                    "strategy": payload.strategy if payload.travel_mode == "driving" else None,
                    "city": payload.city,
                }
            )
        return {
            "summary": {
                "total_routes": len(results),
                "travel_mode": payload.travel_mode,
            },
            "routes": results,
        }

    async def _arun(self, **kwargs) -> Dict[str, Any]:
        return self._run(**kwargs)

    @staticmethod
    def _estimate_distance(origin: str, destination: str) -> float:
        seed = len(origin) + len(destination)
        return max(1.0, min(1200.0, seed * 3.1))

    @staticmethod
    def _estimate_duration(distance_km: float, travel_mode: str) -> float:
        speeds = {
            "driving": 60.0,
            "transit": 40.0,
            "bicycling": 15.0,
            "walking": 5.0,
        }
        speed = speeds.get(travel_mode, 40.0)
        return (distance_km / speed) * 60.0


def create_tool() -> PathNavigateTool:
    return PathNavigateTool()
