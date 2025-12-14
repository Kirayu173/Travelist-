from __future__ import annotations

import json
import math
from dataclasses import dataclass
from time import monotonic
from typing import Any, Iterable

import sqlalchemy as sa
from anyio import to_thread
from app.core.db import session_scope
from app.core.logging import get_logger
from app.core.redis import get_redis_client
from app.core.settings import settings
from app.models.orm import Poi
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import text


class PoiServiceError(Exception):
    """Raised when POI service encounters invalid input or provider errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class PoiMetrics:
    cache_hits: int = 0
    cache_misses: int = 0
    api_calls: int = 0
    api_failures: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "api_calls": self.api_calls,
            "api_failures": self.api_failures,
        }


class _MemoryCache:
    """Lightweight TTL cache used when Redis不可用."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    def get(self, key: str) -> list[dict[str, Any]] | None:
        item = self._store.get(key)
        if not item:
            return None
        expires_at, value = item
        if monotonic() >= expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: list[dict[str, Any]], ttl_seconds: int) -> None:
        self._store[key] = (monotonic() + max(ttl_seconds, 1), value)


class BasePoiProvider:
    async def search(
        self, lat: float, lng: float, poi_type: str | None, radius: int, limit: int
    ) -> list[dict[str, Any]]:
        raise NotImplementedError


class MockPoiProvider(BasePoiProvider):
    """Deterministic mock provider used在测试与无 Key 场景."""

    async def search(
        self, lat: float, lng: float, poi_type: str | None, radius: int, limit: int
    ) -> list[dict[str, Any]]:
        pois: list[dict[str, Any]] = []
        typestr = poi_type or "place"
        for idx in range(min(limit, 10)):
            offset = (idx + 1) * 0.001
            pois.append(
                {
                    "provider": "mock",
                    "provider_id": f"{typestr}-{idx}",
                    "name": f"Mock {typestr.title()} {idx + 1}",
                    "category": typestr,
                    "addr": f"附近道路 {idx + 1} 号",
                    "rating": round(4.0 - idx * 0.05, 2),
                    "lat": lat + offset,
                    "lng": lng + offset,
                }
            )
        return pois


class GaodePoiProvider(BasePoiProvider):
    """高德周边搜索简化封装."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._logger = get_logger(__name__)

    async def search(
        self, lat: float, lng: float, poi_type: str | None, radius: int, limit: int
    ) -> list[dict[str, Any]]:
        import httpx

        params = {
            "key": self._api_key,
            "location": f"{lng},{lat}",
            "radius": radius,
            "offset": min(limit, 20),
            "sortrule": "distance",
            "page": 1,
            "output": "JSON",
        }
        if poi_type:
            params["types"] = poi_type
        url = "https://restapi.amap.com/v3/place/around"
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:  # pragma: no cover - 网络异常
            self._logger.warning(
                "poi.gaode.error", extra={"error": str(exc), "url": url}
            )
            raise

        if payload.get("status") != "1":
            info = payload.get("info") or "gaode_error"
            raise RuntimeError(f"gaode api failed: {info}")
        pois: list[dict[str, Any]] = []
        for item in payload.get("pois", [])[:limit]:
            try:
                lng_str, lat_str = (item.get("location") or "0,0").split(",")
                pois.append(
                    {
                        "provider": "gaode",
                        "provider_id": item.get("id") or item.get("uid") or "",
                        "name": item.get("name") or "",
                        "category": item.get("type") or "",
                        "addr": item.get("address") or "",
                        "rating": (
                            float(item.get("biz_ext", {}).get("rating") or 0)
                            if isinstance(item.get("biz_ext"), dict)
                            else None
                        ),
                        "lat": float(lat_str),
                        "lng": float(lng_str),
                        "ext": {"tel": item.get("tel"), "pname": item.get("pname")},
                    }
                )
            except Exception:
                continue
        return pois


class PoiService:
    """POI 查询服务：Redis 缓存 -> 本地 DB -> 第三方回源."""

    def __init__(
        self,
        *,
        cache_ttl_seconds: int | None = None,
        provider: BasePoiProvider | None = None,
    ) -> None:
        self._logger = get_logger(__name__)
        self._cache_ttl = cache_ttl_seconds or settings.poi_cache_ttl_seconds
        self._metrics = PoiMetrics()
        self._memory_cache = _MemoryCache()
        self._redis = None
        if settings.poi_cache_enabled:
            try:
                self._redis = get_redis_client()
            except Exception:
                self._redis = None
        self._provider = provider or self._build_provider(settings.poi_provider)

    def _build_provider(self, provider_name: str | None) -> BasePoiProvider:
        if provider_name == "gaode" and settings.poi_gaode_api_key:
            return GaodePoiProvider(settings.poi_gaode_api_key)
        return MockPoiProvider()

    @staticmethod
    def _normalize_coord(value: float) -> float:
        precision = max(settings.poi_coord_precision, 0)
        return round(value, precision)

    def _build_cache_key(
        self, lat: float, lng: float, poi_type: str | None, radius: int, limit: int
    ) -> str:
        lat_q = self._normalize_coord(lat)
        lng_q = self._normalize_coord(lng)
        type_q = poi_type or "all"
        return f"poi:around:{lat_q}:{lng_q}:{type_q}:{radius}:{limit}"

    async def _cache_get(self, key: str) -> list[dict[str, Any]] | None:
        if self._redis:
            try:
                raw = await self._redis.get(key)
                if raw:
                    data = json.loads(raw)
                    self._metrics.cache_hits += 1
                    return data
            except Exception:
                pass
        cached = self._memory_cache.get(key)
        if cached:
            self._metrics.cache_hits += 1
        return cached

    async def _cache_set(self, key: str, value: list[dict[str, Any]]) -> None:
        ttl = self._cache_ttl
        self._memory_cache.set(key, value, ttl)
        if not self._redis:
            return
        try:
            await self._redis.setex(key, ttl, json.dumps(value))
        except Exception:
            return

    def _validate_inputs(
        self, lat: float, lng: float, radius: int | None, poi_type: str | None
    ) -> tuple[float, float, int, str | None]:
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise PoiServiceError("坐标超出范围")
        max_radius = max(settings.poi_max_radius_m, 1)
        default_radius = min(settings.poi_default_radius_m, max_radius)
        resolved_radius = radius or default_radius
        if resolved_radius <= 0 or resolved_radius > max_radius:
            raise PoiServiceError(f"半径需在 1~{max_radius} 米之间")
        normalized_type = (poi_type or "").strip() or None
        return lat, lng, resolved_radius, normalized_type

    async def get_poi_around(
        self,
        *,
        lat: float,
        lng: float,
        poi_type: str | None = None,
        radius: int | None = None,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        lat, lng, resolved_radius, normalized_type = self._validate_inputs(
            lat, lng, radius, poi_type
        )
        cache_key = self._build_cache_key(
            lat, lng, normalized_type, resolved_radius, limit
        )
        cached = await self._cache_get(cache_key)
        if cached is not None:
            return cached, {"source": "cache"}
        self._metrics.cache_misses += 1

        db_results = await to_thread.run_sync(
            self._query_db, lat, lng, normalized_type, resolved_radius, limit
        )
        results = list(db_results)
        source = "db"

        if len(results) < settings.poi_min_results:
            api_results = await self._fetch_from_provider(
                lat, lng, normalized_type, resolved_radius, limit
            )
            if api_results:
                await to_thread.run_sync(self._upsert_pois, api_results)
                merged = self._merge_results(results, api_results, lat, lng)
                results = merged[:limit]
                source = "api"

        await self._cache_set(cache_key, results)
        return results, {"source": source}

    def _query_db(
        self,
        lat: float,
        lng: float,
        poi_type: str | None,
        radius: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        with session_scope() as session:
            dialect = session.bind.dialect.name if session.bind else "postgresql"
            if dialect != "postgresql":
                return []
            stmt = text(
                """
                    SELECT id, provider, provider_id, name, category, addr, rating,
                           ST_Y(geom::geometry) AS lat,
                           ST_X(geom::geometry) AS lng,
                           ext,
                           created_at,
                           updated_at,
                           ST_Distance(
                               geom,
                               ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
                           ) AS distance_m
                    FROM pois
                    WHERE geom IS NOT NULL
                      AND ST_DWithin(
                          geom,
                          ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                          :radius
                      )
                      AND (:poi_type IS NULL OR category = :poi_type)
                    ORDER BY distance_m ASC
                    LIMIT :limit
                    """
            ).bindparams(
                sa.bindparam("lat", type_=sa.Float),
                sa.bindparam("lng", type_=sa.Float),
                sa.bindparam("radius", type_=sa.Integer),
                sa.bindparam("poi_type", type_=sa.String),
                sa.bindparam("limit", type_=sa.Integer),
            )
            try:
                rows = session.execute(
                    stmt,
                    {
                        "lat": lat,
                        "lng": lng,
                        "radius": radius,
                        "poi_type": poi_type,
                        "limit": limit,
                    },
                ).mappings()
            except Exception as exc:  # pragma: no cover - best effort fallback
                self._logger.warning(
                    "poi.db_query_failed",
                    extra={
                        "error": str(exc),
                        "lat": lat,
                        "lng": lng,
                        "radius": radius,
                        "poi_type": poi_type,
                        "limit": limit,
                    },
                )
                return []
            payload: list[dict[str, Any]] = []
            for row in rows:
                payload.append(
                    {
                        "id": row["id"],
                        "provider": row["provider"],
                        "provider_id": row["provider_id"],
                        "name": row["name"],
                        "category": row["category"],
                        "addr": row["addr"],
                        "rating": (
                            float(row["rating"]) if row["rating"] is not None else None
                        ),
                        "lat": float(row["lat"]) if row["lat"] is not None else None,
                        "lng": float(row["lng"]) if row["lng"] is not None else None,
                        "ext": row["ext"] or {},
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                        "distance_m": (
                            float(row["distance_m"])
                            if row["distance_m"] is not None
                            else None
                        ),
                        "source": "db",
                    }
                )
            return payload

    async def _fetch_from_provider(
        self,
        lat: float,
        lng: float,
        poi_type: str | None,
        radius: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        try:
            self._metrics.api_calls += 1
            results = await self._provider.search(lat, lng, poi_type, radius, limit)
            return results
        except Exception as exc:
            self._metrics.api_failures += 1
            self._logger.warning("poi.provider.failed", extra={"error": str(exc)})
            return []

    def _merge_results(
        self,
        db_results: list[dict[str, Any]],
        api_results: list[dict[str, Any]],
        lat: float,
        lng: float,
    ) -> list[dict[str, Any]]:
        seen: set[tuple[str, str]] = set()
        merged: list[dict[str, Any]] = []
        for item in db_results:
            key = (item.get("provider") or "", item.get("provider_id") or "")
            seen.add(key)
            merged.append(item)
        for item in api_results:
            key = (item.get("provider") or "", item.get("provider_id") or "")
            if key in seen:
                continue
            distance = self._haversine_distance(
                lat, lng, item.get("lat"), item.get("lng")
            )
            merged.append(
                {
                    **item,
                    "distance_m": distance,
                    "source": item.get("source") or "api",
                }
            )
        merged.sort(key=lambda x: x.get("distance_m") or 1e9)
        return merged

    def _upsert_pois(self, items: Iterable[dict[str, Any]]) -> None:
        payloads = []
        for item in items:
            lat = item.get("lat")
            lng = item.get("lng")
            if lat is None or lng is None:
                continue
            payloads.append(
                {
                    "provider": item.get("provider") or "unknown",
                    "provider_id": item.get("provider_id") or "",
                    "name": item.get("name") or "",
                    "category": item.get("category"),
                    "addr": item.get("addr"),
                    "rating": item.get("rating"),
                    "geom_wkt": f"POINT({lng} {lat})",
                    "ext": item.get("ext") or {},
                }
            )
        if not payloads:
            return

        with session_scope() as session:
            dialect = session.bind.dialect.name if session.bind else "postgresql"
            if dialect != "postgresql":
                return

            for chunk in self._chunk(payloads, 100):
                insert_stmt = (
                    postgresql.insert(Poi.__table__)
                    .values(
                        [
                            {
                                "provider": row["provider"],
                                "provider_id": row["provider_id"],
                                "name": row["name"],
                                "category": row["category"],
                                "addr": row["addr"],
                                "rating": row["rating"],
                                "geom": sa.text(
                                    f"ST_GeogFromText('SRID=4326;{row['geom_wkt']}')"
                                ),
                                "ext": row["ext"],
                            }
                            for row in chunk
                        ]
                    )
                    .on_conflict_do_nothing(index_elements=["provider", "provider_id"])
                )
                session.execute(insert_stmt)
            session.commit()

    @staticmethod
    def _chunk(
        items: list[dict[str, Any]],
        size: int,
    ) -> Iterable[list[dict[str, Any]]]:
        for idx in range(0, len(items), size):
            yield items[idx : idx + size]

    @staticmethod
    def _haversine_distance(
        lat1: float, lng1: float, lat2: float | None, lng2: float | None
    ) -> float | None:
        if lat2 is None or lng2 is None:
            return None
        r = 6371000.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        d_phi = math.radians(lat2 - lat1)
        d_lambda = math.radians(lng2 - lng1)
        a = (
            math.sin(d_phi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return round(r * c, 2)

    def metrics_snapshot(self) -> dict[str, int]:
        return self._metrics.snapshot()


_poi_service: PoiService | None = None


def get_poi_service() -> PoiService:
    global _poi_service
    if _poi_service is None:
        _poi_service = PoiService()
    return _poi_service
