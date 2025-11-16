from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from time import perf_counter, time
from typing import Deque, Dict, List, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


@dataclass
class RouteStats:
    """Aggregated statistics for a single HTTP route."""

    method: str
    path: str
    count: int = 0
    total_ms: float = 0.0
    last_ms: float = 0.0
    last_status: int = 0
    durations: Deque[float] = field(default_factory=lambda: deque(maxlen=200))

    def add(self, duration_ms: float, status_code: int) -> None:
        self.count += 1
        self.total_ms += duration_ms
        self.last_ms = duration_ms
        self.last_status = status_code
        self.durations.append(duration_ms)


@dataclass
class RequestEvent:
    method: str
    path: str
    duration_ms: float
    recorded_at: float


class MetricsRegistry:
    """Thread-safe in-memory store for per-route request metrics."""

    def __init__(self) -> None:
        self._routes: Dict[Tuple[str, str], RouteStats] = {}
        self._total_requests = 0
        self._events: Deque[RequestEvent] = deque()
        self._lock = Lock()

    def record(
        self,
        method: str,
        path: str,
        duration_ms: float,
        status_code: int,
    ) -> None:
        key = (method, path)
        with self._lock:
            route_stat = self._routes.get(key)
            if route_stat is None:
                route_stat = RouteStats(method=method, path=path)
                self._routes[key] = route_stat
            route_stat.add(duration_ms, status_code)
            self._total_requests += 1
            self._events.append(
                RequestEvent(
                    method=method,
                    path=path,
                    duration_ms=duration_ms,
                    recorded_at=time(),
                )
            )

    def snapshot(self) -> dict:
        with self._lock:
            routes = self._format_routes(self._routes.values())
            return {
                "total_requests": self._total_requests,
                "routes": routes,
            }

    def snapshot_window(self, window_seconds: int) -> dict:
        if window_seconds <= 0:
            return self.snapshot()

        with self._lock:
            now = time()
            self._prune_events(now, window_seconds)
            aggregated: Dict[Tuple[str, str], dict] = {}
            for event in self._events:
                key = (event.method, event.path)
                bucket = aggregated.setdefault(
                    key,
                    {
                        "method": event.method,
                        "path": event.path,
                        "count": 0,
                        "total_ms": 0.0,
                        "durations": [],
                    },
                )
                bucket["count"] += 1
                bucket["total_ms"] += event.duration_ms
                bucket["durations"].append(event.duration_ms)

            routes = [
                self._build_route_payload(
                    method=data["method"],
                    path=data["path"],
                    count=data["count"],
                    total_ms=data["total_ms"],
                    durations=data["durations"],
                    last_ms=None,
                    last_status=None,
                )
                for data in aggregated.values()
            ]

            total_requests = sum(item["count"] for item in aggregated.values())
            return {
                "total_requests": total_requests,
                "routes": routes,
                "window_seconds": window_seconds,
            }

    def reset(self) -> None:
        with self._lock:
            self._routes.clear()
            self._events.clear()
            self._total_requests = 0

    def _prune_events(self, now: float, window_seconds: int) -> None:
        threshold = now - window_seconds
        while self._events and self._events[0].recorded_at < threshold:
            self._events.popleft()

    def _format_routes(self, routes: List[RouteStats]) -> List[dict]:
        payload: List[dict] = []
        for stats in routes:
            payload.append(
                self._build_route_payload(
                    method=stats.method,
                    path=stats.path,
                    count=stats.count,
                    total_ms=stats.total_ms,
                    durations=list(stats.durations),
                    last_ms=stats.last_ms,
                    last_status=stats.last_status,
                )
            )
        payload.sort(key=lambda item: item["count"], reverse=True)
        return payload

    def _build_route_payload(
        self,
        *,
        method: str,
        path: str,
        count: int,
        total_ms: float,
        durations: List[float],
        last_ms: float | None,
        last_status: int | None,
    ) -> dict:
        avg_ms = total_ms / count if count else 0.0
        p95 = self._percentile(durations, 0.95)
        payload = {
            "method": method,
            "path": path,
            "count": count,
            "avg_ms": round(avg_ms, 3),
            "p95_ms": round(p95, 3) if p95 is not None else None,
        }
        if last_ms is not None:
            payload["last_ms"] = round(last_ms, 3)
        if last_status is not None:
            payload["last_status"] = last_status
        return payload

    @staticmethod
    def _percentile(values: List[float], percentile: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        k = (len(ordered) - 1) * percentile
        lower = int(k)
        upper = min(lower + 1, len(ordered) - 1)
        if lower == upper:
            return ordered[int(k)]
        frac = k - lower
        return ordered[lower] + (ordered[upper] - ordered[lower]) * frac


metrics_registry = MetricsRegistry()


class APIMetricsMiddleware(BaseHTTPMiddleware):
    """Middleware that records request metrics for later inspection."""

    def __init__(self, app: ASGIApp, registry: MetricsRegistry | None = None) -> None:
        super().__init__(app)
        self._registry = registry or metrics_registry

    async def dispatch(self, request: Request, call_next) -> Response:
        start = perf_counter()
        response = await call_next(request)
        elapsed = (perf_counter() - start) * 1000
        self._registry.record(
            request.method,
            request.url.path,
            elapsed,
            response.status_code,
        )
        return response


def get_metrics_registry() -> MetricsRegistry:
    return metrics_registry


def reset_metrics_registry() -> None:
    metrics_registry.reset()
