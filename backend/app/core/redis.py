from __future__ import annotations

from time import monotonic, perf_counter

from app.core.settings import settings
from redis.asyncio import Redis

_redis_client: Redis | None = None
_cached_redis_status: dict[str, object] | None = None
_cached_redis_ts: float | None = None
HEALTH_CACHE_SECONDS = 5.0


def get_redis_client() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
    return _redis_client


async def close_redis_client() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
    invalidate_redis_health_cache()


def invalidate_redis_health_cache() -> None:
    global _cached_redis_status, _cached_redis_ts
    _cached_redis_status = None
    _cached_redis_ts = None


async def check_redis_health(use_cache: bool = True) -> dict[str, object]:
    global _cached_redis_status, _cached_redis_ts

    if use_cache and _cached_redis_status is not None and _cached_redis_ts is not None:
        if monotonic() - _cached_redis_ts < HEALTH_CACHE_SECONDS:
            return _cached_redis_status

    client = get_redis_client()
    start = perf_counter()
    try:
        await client.ping()
        latency = (perf_counter() - start) * 1000
        result = {
            "status": "ok",
            "latency_ms": round(latency, 3),
            "error": None,
        }
    except Exception as exc:
        result = {"status": "fail", "error": str(exc)}

    if use_cache:
        _cached_redis_status = result
        _cached_redis_ts = monotonic()
    return result
