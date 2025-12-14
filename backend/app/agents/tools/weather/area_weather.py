from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from app.agents.tools.common.base import TravelistBaseTool
from app.agents.tools.common.config_utils import get_key, load_env
from app.agents.tools.common.logging import get_tool_logger, log_tool_event
from pydantic import BaseModel, Field, field_validator

logger = get_tool_logger("area_weather")

# cache
_api_key: Optional[str] = None
_adcode_cache: Dict[str, str] = {}
_initialized = False


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


class AreaWeatherTool(TravelistBaseTool):
    """高德 API 天气查询，带本地 adcode 缓存、日志记录和错误兜底。"""

    name: str = "area_weather"
    description: str = (
        "查询多地点天气（支持实时/预报），优先使用本地缓存的行政区编码，缺失时自动查询。"
    )
    args_schema: type[BaseModel] = AreaWeatherInput

    @staticmethod
    def _ensure_initialized() -> None:
        global _initialized, _api_key, _adcode_cache
        if _initialized:
            return

        # 使用统一的配置加载工具
        load_env()

        _api_key = get_key("AMAP_API_KEY")
        if not _api_key:
            log_tool_event(
                "area_weather",
                event="init",
                status="error",
                error_code="missing_api_key",
                message="AMAP_API_KEY not configured",
            )
        else:
            log_tool_event(
                "area_weather",
                event="init",
                status="info",
                message="AMAP_API_KEY loaded successfully",
            )

        _adcode_cache = AreaWeatherTool._load_adcode_cache()
        _initialized = True

    @staticmethod
    def _load_adcode_cache() -> Dict[str, str]:
        cache: Dict[str, str] = {}
        cache_file = (
            Path(__file__).resolve().parent.parent / "resources" / "adcoder.json"
        )
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                for item in data:
                    name = item.get("中文名") or item.get("name")
                    adcode = item.get("adcode")
                    if name and adcode:
                        cache[name] = adcode
            except Exception as exc:  # pragma: no cover - defensive
                log_tool_event(
                    "area_weather",
                    event="load_cache",
                    status="error",
                    error_code="cache_load_failed",
                    message=str(exc),
                )
        return cache

    def _run(self, **kwargs) -> Dict[str, Any]:
        self._ensure_initialized()
        try:
            payload = AreaWeatherInput(**kwargs)
        except Exception as exc:
            log_tool_event(
                "area_weather",
                event="invoke",
                status="invalid_args",
                request=kwargs,
                error_code="invalid_params",
                message=str(exc),
            )
            return {"error": f"参数错误: {exc}"}

        has_key = bool(_api_key)
        results = []
        for loc in payload.locations:
            adcode = self._get_location_adcode(loc) if has_key else None
            if has_key and adcode:
                results.append(self._build_result(loc, adcode, payload))
            elif has_key:
                results.append(
                    {
                        "location": loc,
                        "status": "failed",
                        "error": "无法获取行政区编码",
                    }
                )
            else:
                seed = sum(ord(ch) for ch in loc)
                temp = 15 + seed % 15
                fallback = {
                    "location": loc,
                    "weather": self._sample_weather(seed),
                    "temperature_c": temp,
                    "humidity": 40 + seed % 50,
                    "source": "mock",
                    "status": "estimated",
                }
                if payload.weather_type == "forecast":
                    try:
                        from zoneinfo import ZoneInfo

                        base_date = dt.datetime.now(ZoneInfo("Asia/Shanghai")).date()
                    except Exception:  # pragma: no cover - fallback
                        base_date = dt.date.today()
                    temp_series = [fallback["temperature_c"]] * payload.days
                    fallback["forecast"] = []
                    for idx, value in enumerate(temp_series):
                        date = base_date + dt.timedelta(days=idx)
                        fallback["forecast"].append(
                            {
                                "date": date.isoformat(),
                                "week": str(date.isoweekday()),
                                "dayweather": fallback["weather"],
                                "nightweather": fallback["weather"],
                                "daytemp": str(value + 2),
                                "nighttemp": str(value - 3),
                                "daywind": "未知",
                                "nightwind": "未知",
                                "daypower": "未知",
                                "nightpower": "未知",
                            }
                        )
                results.append(fallback)

        summary = {
            "weather_type": payload.weather_type,
            "days": payload.days,
            "total_locations": len(results),
        }
        response = {"summary": summary, "results": results}
        log_tool_event(
            "area_weather",
            event="invoke",
            status="ok" if has_key else "mock",
            request=kwargs,
            response=response,
            raw_input=kwargs,
            output=response,
            error_code=None,
        )
        return response

    async def _arun(self, **kwargs) -> Dict[str, Any]:
        return self._run(**kwargs)

    def _get_location_adcode(self, location: str) -> Optional[str]:
        if location in _adcode_cache:
            return _adcode_cache[location]
        if not _api_key:
            return None
        params = {
            "key": _api_key,
            "keywords": location,
            "subdistrict": 0,
            "extensions": "base",
        }
        try:
            resp = requests.get(
                "https://restapi.amap.com/v3/config/district",
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            log_tool_event(
                "area_weather",
                event="lookup_adcode",
                status="ok" if data.get("status") == "1" else "error",
                request=params,
                response=data,
                raw_input=location,
                output=data,
                error_code=None if data.get("status") == "1" else data.get("info"),
            )
            if data.get("status") == "1" and data.get("districts"):
                adcode = data["districts"][0].get("adcode")
                if adcode:
                    _adcode_cache[location] = adcode
                    return adcode
        except Exception as exc:
            log_tool_event(
                "area_weather",
                event="lookup_adcode",
                status="error",
                request=params,
                error_code="adcode_request_failed",
                message=str(exc),
            )
        return None

    def _query_realtime(self, adcode: str) -> dict[str, Any]:
        params = {"key": _api_key, "city": adcode, "extensions": "base"}
        resp = requests.get(
            "https://restapi.amap.com/v3/weather/weatherInfo",
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data

    def _query_forecast(self, adcode: str) -> dict[str, Any]:
        params = {"key": _api_key, "city": adcode, "extensions": "all"}
        resp = requests.get(
            "https://restapi.amap.com/v3/weather/weatherInfo",
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _sample_weather(seed: int) -> str:
        options = ["晴", "多云", "小雨", "阵雨", "阴"]
        return options[seed % len(options)]

    def _build_result(
        self, location: str, adcode: Optional[str], payload: AreaWeatherInput
    ) -> Dict[str, Any]:
        if not adcode:
            return {
                "location": location,
                "error": "无法获取行政区编码",
                "status": "failed",
            }
        try:
            if payload.weather_type == "forecast":
                raw = self._query_forecast(adcode)
            else:
                raw = self._query_realtime(adcode)
            status_ok = raw.get("status") == "1"
            log_tool_event(
                "area_weather",
                event=f"api_{payload.weather_type}",
                status="ok" if status_ok else "error",
                request={"city": adcode, "type": payload.weather_type},
                response=raw,
                raw_input=location,
                output=raw,
                error_code=None if status_ok else raw.get("info"),
            )
            if not status_ok:
                return {
                    "location": location,
                    "adcode": adcode,
                    "error": raw.get("info", "查询失败"),
                    "status": "failed",
                }
            if payload.weather_type == "forecast" and raw.get("forecasts"):
                cast = raw["forecasts"][0]
                return {
                    "location": location,
                    "adcode": adcode,
                    "status": "success",
                    "forecast": cast.get("casts", [])[: payload.days],
                    "report_time": cast.get("reporttime"),
                }
            if payload.weather_type == "realtime" and raw.get("lives"):
                live = raw["lives"][0]
                return {
                    "location": location,
                    "adcode": adcode,
                    "status": "success",
                    "weather": live.get("weather"),
                    "temperature": live.get("temperature"),
                    "humidity": live.get("humidity"),
                    "winddirection": live.get("winddirection"),
                    "windpower": live.get("windpower"),
                    "report_time": live.get("reporttime"),
                }
        except Exception as exc:
            log_tool_event(
                "area_weather",
                event="api_error",
                status="error",
                request={"city": adcode, "type": payload.weather_type},
                error_code="request_failed",
                message=str(exc),
            )
            return {
                "location": location,
                "adcode": adcode,
                "status": "failed",
                "error": str(exc),
            }
        return {
            "location": location,
            "adcode": adcode,
            "status": "failed",
            "error": "未获取到天气数据",
        }


def create_tool() -> AreaWeatherTool:
    return AreaWeatherTool()
