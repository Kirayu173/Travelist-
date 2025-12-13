from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

import httpx
from app.core.cache import build_cache_key, cache_backend
from app.core.logging import get_logger
from app.core.settings import settings

GeocodeProvider = Literal["disabled", "mock", "amap"]


@dataclass(frozen=True)
class GeocodeResult:
    lat: float
    lng: float
    provider: str
    source: str


class GeocodeServiceError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _pseudo_city_center(destination: str) -> tuple[float, float]:
    digest = hashlib.md5(destination.encode("utf-8")).hexdigest()
    n1 = int(digest[:8], 16)
    n2 = int(digest[8:16], 16)
    lat = 20.0 + (n1 % 1500) / 100.0  # 20.00 ~ 35.00
    lng = 100.0 + (n2 % 2500) / 100.0  # 100.00 ~ 125.00
    return lat, lng


class GeocodeService:
    """Resolve destination -> city center coordinates with caching and fallback."""

    def __init__(self) -> None:
        self._logger = get_logger(__name__)

    async def resolve_city_center(self, destination: str) -> GeocodeResult:
        dest = destination.strip()
        if not dest:
            raise GeocodeServiceError("destination must not be empty")

        provider: GeocodeProvider = getattr(settings, "geocode_provider", "mock")
        if provider == "disabled":
            lat, lng = _pseudo_city_center(dest)
            return GeocodeResult(
                lat=lat, lng=lng, provider="disabled", source="fallback_pseudo"
            )

        ttl_seconds = max(
            int(getattr(settings, "geocode_cache_ttl_seconds", 86400)), 60
        )
        key = build_cache_key("geocode:center", provider=provider, dest=dest)

        async def _loader() -> GeocodeResult:
            if provider == "mock":
                lat, lng = _pseudo_city_center(dest)
                return GeocodeResult(
                    lat=lat, lng=lng, provider="mock", source="deterministic"
                )
            if provider == "amap":
                return await self._amap_geocode_city_center(dest)
            lat, lng = _pseudo_city_center(dest)
            return GeocodeResult(
                lat=lat, lng=lng, provider=str(provider), source="fallback_pseudo"
            )

        result = await cache_backend.remember_async(
            "geocode", key, ttl_seconds, _loader
        )
        if isinstance(result, GeocodeResult):
            return result
        return GeocodeResult(**result)

    async def _amap_geocode_city_center(self, destination: str) -> GeocodeResult:
        api_key = (
            getattr(settings, "amap_api_key", None)
            or getattr(settings, "gaode_key", None)
            or getattr(settings, "poi_gaode_api_key", None)
        )
        if not api_key:
            lat, lng = _pseudo_city_center(destination)
            return GeocodeResult(
                lat=lat, lng=lng, provider="amap", source="fallback_missing_key"
            )

        url = "https://restapi.amap.com/v3/geocode/geo"
        params = {"address": destination, "key": api_key}
        timeout_s = max(float(getattr(settings, "ai_request_timeout_s", 30.0)), 5.0)
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.get(url, params=params)
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            self._logger.warning(
                "geocode.amap_failed",
                extra={"destination": destination, "error": str(exc)},
            )
            lat, lng = _pseudo_city_center(destination)
            return GeocodeResult(lat=lat, lng=lng, provider="amap", source="fallback")

        if str(data.get("status")) != "1":
            lat, lng = _pseudo_city_center(destination)
            return GeocodeResult(
                lat=lat,
                lng=lng,
                provider="amap",
                source="fallback_bad_status",
            )

        geocodes = data.get("geocodes") or []
        if not geocodes:
            lat, lng = _pseudo_city_center(destination)
            return GeocodeResult(
                lat=lat, lng=lng, provider="amap", source="fallback_empty"
            )

        loc = str(geocodes[0].get("location") or "")
        if "," not in loc:
            lat, lng = _pseudo_city_center(destination)
            return GeocodeResult(
                lat=lat, lng=lng, provider="amap", source="fallback_missing_location"
            )

        lng_str, lat_str = loc.split(",", 1)
        try:
            lat = float(lat_str)
            lng = float(lng_str)
        except ValueError:
            lat, lng = _pseudo_city_center(destination)
            return GeocodeResult(
                lat=lat, lng=lng, provider="amap", source="fallback_parse"
            )
        return GeocodeResult(lat=lat, lng=lng, provider="amap", source="api")


_geocode_service: GeocodeService | None = None


def get_geocode_service() -> GeocodeService:
    global _geocode_service
    if _geocode_service is None:
        _geocode_service = GeocodeService()
    return _geocode_service
