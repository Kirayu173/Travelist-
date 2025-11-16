from __future__ import annotations

from time import monotonic, perf_counter
from typing import Any

from anyio import to_thread
from app.core.settings import settings
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

_engine: Engine | None = None
_cached_db_status: dict[str, Any] | None = None
_cached_db_ts: float | None = None
HEALTH_CACHE_SECONDS = 5.0


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        connect_args: dict[str, Any] = {}
        if settings.database_url.startswith("postgresql"):
            connect_args["connect_timeout"] = 1
        _engine = create_engine(
            settings.database_url,
            connect_args=connect_args,
            pool_pre_ping=True,
            future=True,
        )
    return _engine


def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
    invalidate_db_health_cache()


def invalidate_db_health_cache() -> None:
    global _cached_db_status, _cached_db_ts
    _cached_db_status = None
    _cached_db_ts = None


async def check_db_health(use_cache: bool = True) -> dict[str, Any]:
    global _cached_db_status, _cached_db_ts

    if use_cache and _cached_db_status is not None and _cached_db_ts is not None:
        if monotonic() - _cached_db_ts < HEALTH_CACHE_SECONDS:
            return _cached_db_status

    def _run() -> dict[str, Any]:
        engine = get_engine()
        start = perf_counter()
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            latency = (perf_counter() - start) * 1000
            return {"status": "ok", "latency_ms": round(latency, 3), "error": None}
        except SQLAlchemyError as exc:
            return {"status": "fail", "error": str(exc)}
        except Exception as exc:
            return {"status": "fail", "error": str(exc)}

    result = await to_thread.run_sync(_run)
    if use_cache:
        _cached_db_status = result
        _cached_db_ts = monotonic()
    return result
