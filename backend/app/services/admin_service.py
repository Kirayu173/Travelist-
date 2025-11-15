from __future__ import annotations

from collections import defaultdict
from contextlib import suppress
from dataclasses import dataclass
from threading import Lock
from time import perf_counter
from typing import Callable, Dict

import psycopg
import redis
from app.core.settings import settings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


@dataclass
class RouteStat:
    count: int = 0
    last_ms: float = 0.0
    last_status: int = 0


class _MetricsCollector:
    def __init__(self) -> None:
        self._routes: Dict[str, RouteStat] = defaultdict(RouteStat)
        self._total_requests: int = 0
        self._lock = Lock()

    def record(self, route_key: str, elapsed_ms: float, status_code: int) -> None:
        with self._lock:
            stat = self._routes[route_key]
            stat.count += 1
            stat.last_ms = elapsed_ms
            stat.last_status = status_code
            self._total_requests += 1

    def summary(self) -> dict[str, object]:
        with self._lock:
            routes = {
                route: {
                    "count": stat.count,
                    "last_ms": round(stat.last_ms, 3),
                    "last_status": stat.last_status,
                }
                for route, stat in self._routes.items()
            }
            return {"routes": routes, "total_requests": self._total_requests}

    def reset(self) -> None:
        with self._lock:
            self._routes = defaultdict(RouteStat)
            self._total_requests = 0


metrics_collector = _MetricsCollector()


class APIMetricsMiddleware(BaseHTTPMiddleware):
    """Middleware that records request level metrics for admin summary endpoints."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Response],
    ) -> Response:
        start = perf_counter()
        response = await call_next(request)
        elapsed_ms = (perf_counter() - start) * 1000
        route_key = f"{request.method} {request.url.path}"
        metrics_collector.record(route_key, elapsed_ms, response.status_code)
        return response


def get_api_summary() -> dict[str, object]:
    """Return an aggregated API metrics snapshot compliant with Spec Stage-0."""

    return metrics_collector.summary()


def _normalize_pg_dsn(url: str) -> str:
    scheme, sep, rest = url.partition("://")
    if "+" in scheme:
        scheme = scheme.split("+", 1)[0]
    return f"{scheme}{sep}{rest}"


def _check_postgres() -> str:
    dsn = _normalize_pg_dsn(settings.database_url)
    try:
        with psycopg.connect(dsn, connect_timeout=1) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return "ok"
    except Exception:
        return "error"


def _check_redis() -> str:
    client = redis.Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        client.ping()
        return "ok"
    except Exception:
        return "error"
    finally:
        with suppress(Exception):
            client.close()


def get_health_status() -> dict[str, str]:
    """Return real subsystem health data for app, PostgreSQL, and Redis."""

    return {
        "app": "ok",
        "db": _check_postgres(),
        "redis": _check_redis(),
    }


def reset_metrics() -> None:
    """Testing helper to reset the in-memory counters."""

    metrics_collector.reset()
