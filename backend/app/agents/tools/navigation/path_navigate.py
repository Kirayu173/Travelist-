from __future__ import annotations

import math
from typing import Any, Dict, List, Literal, Optional

import os
from pathlib import Path
from app.agents.tools.common.logging import get_tool_logger, log_tool_event
from dotenv import load_dotenv
import requests
from langchain_core.tools.structured import StructuredTool
from pydantic import BaseModel, Field, field_validator

logger = get_tool_logger("path_navigate")
_api_key: str | None = None
_init_done = False


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
            log_tool_event(
                "path_navigate",
                event="invoke",
                status="invalid_args",
                request=kwargs,
                error_code="invalid_params",
                message=str(exc),
            )
            return {"error": f"参数错误: {exc}"}

        self._ensure_key()
        if not _api_key:
            # Fallback to heuristic estimates
            return self._fallback_estimate(payload, kwargs)

        routes: list[dict[str, Any]] = []
        for item in payload.routes:
            origin = item.get("origin") or "未知起点"
            destination = item.get("destination") or "未知终点"
            origin_geo = self._geocode(origin, payload.city)
            dest_geo = self._geocode(destination, payload.city)
            if origin_geo.get("error") or dest_geo.get("error"):
                routes.append(
                    {
                        "origin": origin,
                        "destination": destination,
                        "status": "failed",
                        "error": origin_geo.get("error") or dest_geo.get("error"),
                    }
                )
                continue
            navigate = self._navigate_route(
                origin_geo["coord"],
                dest_geo["coord"],
                payload.travel_mode,
                payload.strategy,
                payload.city,
            )
            routes.append(
                {
                    "origin": origin,
                    "destination": destination,
                    "status": "success" if navigate.get("success") else "failed",
                    "route_info": navigate.get("route_info"),
                    "error": navigate.get("error"),
                }
            )

        response = {
            "summary": {"total_routes": len(routes), "travel_mode": payload.travel_mode},
            "routes": routes,
        }
        log_tool_event(
            "path_navigate",
            event="invoke",
            status="ok",
            request=kwargs,
            response=response,
            raw_input=kwargs,
            output=response,
        )
        return response

    def _fallback_estimate(self, payload: PathNavigateInput, kwargs: dict) -> Dict[str, Any]:
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
                    "status": "estimated",
                }
            )
        response = {
            "summary": {"total_routes": len(results), "travel_mode": payload.travel_mode},
            "routes": results,
        }
        log_tool_event(
            "path_navigate",
            event="invoke",
            status="ok",
            request=kwargs,
            response=response,
            raw_input=kwargs,
            output=response,
        )
        return response

    async def _arun(self, **kwargs) -> Dict[str, Any]:
        return self._run(**kwargs)

    @staticmethod
    def _ensure_key() -> None:
        global _api_key, _init_done
        if _init_done:
            return
        env_path = Path(__file__).resolve().parent.parent.parent.parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)
        _api_key = os.getenv("AMAP_API_KEY")
        _init_done = True

    def _geocode(self, address: str, city: str | None = None) -> Dict[str, Any]:
        if not _api_key:
            return {"error": "AMAP_API_KEY missing"}
        params = {"key": _api_key, "address": address, "output": "json"}
        if city:
            params["city"] = city
        try:
            resp = requests.get(
                "https://restapi.amap.com/v3/geocode/geo", params=params, timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            success = data.get("status") == "1" and data.get("geocodes")
            log_tool_event(
                "path_navigate",
                event="geocode",
                status="ok" if success else "error",
                request=params,
                response=data,
                raw_input=address,
                output=data,
                error_code=None if success else data.get("info"),
            )
            if success:
                geo = data["geocodes"][0]
                lng, lat = geo.get("location", "0,0").split(",")
                return {"coord": (lng, lat)}
            return {"error": data.get("info", "geocode failed")}
        except Exception as exc:
            log_tool_event(
                "path_navigate",
                event="geocode",
                status="error",
                request=params,
                error_code="geocode_request_failed",
                message=str(exc),
            )
            return {"error": str(exc)}

    def _navigate_route(
        self,
        origin: tuple[str, str],
        destination: tuple[str, str],
        travel_mode: str,
        strategy: int,
        city: str | None,
    ) -> Dict[str, Any]:
        if not _api_key:
            return {"success": False, "error": "AMAP_API_KEY missing"}
        base_params = {
            "key": _api_key,
            "origin": ",".join(origin),
            "destination": ",".join(destination),
            "output": "json",
        }
        url = "https://restapi.amap.com/v3/direction/driving"
        if travel_mode == "walking":
            url = "https://restapi.amap.com/v3/direction/walking"
        elif travel_mode == "transit":
            url = "https://restapi.amap.com/v3/direction/transit/integrated"
            if city:
                base_params["city"] = city
        elif travel_mode == "bicycling":
            url = "https://restapi.amap.com/v3/direction/bicycling"
        if travel_mode == "driving":
            base_params["strategy"] = strategy
        try:
            resp = requests.get(url, params=base_params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            success = data.get("status") == "1"
            log_tool_event(
                "path_navigate",
                event=f"route_{travel_mode}",
                status="ok" if success else "error",
                request=base_params,
                response=data,
                raw_input={"origin": origin, "destination": destination},
                output=data,
                error_code=None if success else data.get("info"),
            )
            return {
                "success": success,
                "route_info": data.get("route"),
                "error": None if success else data.get("info", "route failed"),
            }
        except Exception as exc:
            log_tool_event(
                "path_navigate",
                event="route_error",
                status="error",
                request=base_params,
                error_code="route_request_failed",
                message=str(exc),
            )
            return {"success": False, "error": str(exc)}

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
