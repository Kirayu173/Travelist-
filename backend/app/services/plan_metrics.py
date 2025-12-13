from __future__ import annotations

import json
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from statistics import mean
from threading import Lock
from typing import Deque, Literal, Protocol

from app.core.logging import get_logger
from app.core.settings import settings

try:
    from redis import Redis
    from redis.exceptions import RedisError
except Exception:  # pragma: no cover - optional dependency
    Redis = None
    RedisError = Exception


PlanMetricsBackendName = Literal["memory", "redis"]


@dataclass
class PlanCallEntry:
    trace_id: str
    mode: str
    destination: str
    days: int
    latency_ms: float
    success: bool
    error: str | None = None
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PlanMetricsBackend(Protocol):
    def record(
        self,
        *,
        trace_id: str,
        mode: str,
        destination: str,
        days: int,
        latency_ms: float,
        success: bool,
        error: str | None = None,
    ) -> None: ...

    def snapshot(self, *, top_n: int = 8) -> dict: ...

    def reset(self) -> None: ...


class InMemoryPlanMetricsBackend:
    """In-memory collector tracking planning activity for Admin observability."""

    def __init__(self, history_limit: int = 100) -> None:
        self._history: Deque[PlanCallEntry] = deque(maxlen=max(history_limit, 1))
        self._fast_calls = 0
        self._fast_failures = 0
        self._fast_total_days = 0
        self._fast_latencies_ms: Deque[float] = deque(maxlen=500)
        self._destinations = Counter()
        self._lock = Lock()

    def record(
        self,
        *,
        trace_id: str,
        mode: str,
        destination: str,
        days: int,
        latency_ms: float,
        success: bool,
        error: str | None = None,
    ) -> None:
        with self._lock:
            if mode == "fast":
                self._fast_calls += 1
                self._fast_total_days += max(int(days), 0)
                self._fast_latencies_ms.append(float(latency_ms))
                self._destinations.update([destination])
                if not success:
                    self._fast_failures += 1

            self._history.appendleft(
                PlanCallEntry(
                    trace_id=trace_id,
                    mode=mode,
                    destination=destination,
                    days=max(int(days), 0),
                    latency_ms=float(latency_ms),
                    success=success,
                    error=error,
                )
            )

    def snapshot(self, *, top_n: int = 8) -> dict:
        with self._lock:
            latencies = list(self._fast_latencies_ms)
            avg_latency = mean(latencies) if latencies else 0.0
            p95 = _percentile(latencies, 95)
            avg_days = (
                self._fast_total_days / self._fast_calls if self._fast_calls else 0.0
            )
            failure_rate = (
                self._fast_failures / self._fast_calls if self._fast_calls else 0.0
            )
            return {
                "backend": "memory",
                "plan_fast_calls": int(self._fast_calls),
                "plan_fast_failures": int(self._fast_failures),
                "plan_fast_failure_rate": round(failure_rate, 4),
                "plan_fast_avg_days": round(avg_days, 3),
                "plan_fast_latency_ms_mean": round(avg_latency, 3),
                "plan_fast_latency_ms_p95": round(p95, 3),
                "top_destinations": [
                    {"destination": dest, "count": int(count)}
                    for dest, count in self._destinations.most_common(max(top_n, 0))
                ],
                "last_10_calls": [
                    _format_entry(entry) for entry in list(self._history)[:10]
                ],
            }

    def reset(self) -> None:
        with self._lock:
            self._history.clear()
            self._fast_calls = 0
            self._fast_failures = 0
            self._fast_total_days = 0
            self._fast_latencies_ms.clear()
            self._destinations.clear()


class RedisPlanMetricsBackend:
    """Redis-backed plan metrics for multi-instance deployments."""

    def __init__(
        self,
        *,
        url: str,
        namespace: str = "plan_metrics",
        history_limit: int = 100,
        latency_limit: int = 500,
    ) -> None:
        if Redis is None:
            raise RuntimeError("redis package not available")
        self._client = Redis.from_url(url, decode_responses=True)
        self._ns = namespace.rstrip(":")
        self._history_limit = max(int(history_limit), 1)
        self._latency_limit = max(int(latency_limit), 1)
        self._logger = get_logger(__name__)

    def _key(self, suffix: str) -> str:
        return f"{self._ns}:{suffix}"

    def record(
        self,
        *,
        trace_id: str,
        mode: str,
        destination: str,
        days: int,
        latency_ms: float,
        success: bool,
        error: str | None = None,
    ) -> None:
        entry = PlanCallEntry(
            trace_id=trace_id,
            mode=mode,
            destination=destination,
            days=max(int(days), 0),
            latency_ms=float(latency_ms),
            success=bool(success),
            error=error,
        )
        try:
            pipe = self._client.pipeline(transaction=False)
            pipe.lpush(self._key("history"), json.dumps(_format_entry(entry)))
            pipe.ltrim(self._key("history"), 0, self._history_limit - 1)

            if mode == "fast":
                pipe.hincrby(self._key("counts"), "fast_calls", 1)
                pipe.hincrby(self._key("counts"), "fast_total_days", max(int(days), 0))
                pipe.hincrbyfloat(
                    self._key("counts"), "fast_latency_sum_ms", float(latency_ms)
                )
                if not success:
                    pipe.hincrby(self._key("counts"), "fast_failures", 1)
                pipe.lpush(self._key("fast_latencies_ms"), str(float(latency_ms)))
                pipe.ltrim(self._key("fast_latencies_ms"), 0, self._latency_limit - 1)
                if destination:
                    pipe.zincrby(self._key("destinations"), 1, destination)
            pipe.execute()
        except RedisError as exc:
            self._logger.warning(
                "plan_metrics.redis_record_failed",
                extra={"error": str(exc)},
            )

    def snapshot(self, *, top_n: int = 8) -> dict:
        try:
            counts = self._client.hgetall(self._key("counts")) or {}
            fast_calls = int(float(counts.get("fast_calls") or 0))
            fast_failures = int(float(counts.get("fast_failures") or 0))
            fast_total_days = int(float(counts.get("fast_total_days") or 0))
            fast_latency_sum = float(counts.get("fast_latency_sum_ms") or 0.0)

            lat_raw = self._client.lrange(self._key("fast_latencies_ms"), 0, -1) or []
            latencies: list[float] = []
            for item in lat_raw:
                try:
                    latencies.append(float(item))
                except ValueError:
                    continue
            avg_latency = (fast_latency_sum / fast_calls) if fast_calls else 0.0
            p95 = _percentile(latencies, 95)
            avg_days = (fast_total_days / fast_calls) if fast_calls else 0.0
            failure_rate = (fast_failures / fast_calls) if fast_calls else 0.0

            top_pairs = self._client.zrevrange(
                self._key("destinations"),
                0,
                max(int(top_n), 0) - 1,
                withscores=True,
            )
            top_destinations = [
                {"destination": dest, "count": int(score)} for dest, score in top_pairs
            ]

            history_raw = self._client.lrange(self._key("history"), 0, 9) or []
            last_10_calls: list[dict] = []
            for item in history_raw:
                try:
                    last_10_calls.append(json.loads(item))
                except Exception:
                    continue

            return {
                "backend": "redis",
                "plan_fast_calls": fast_calls,
                "plan_fast_failures": fast_failures,
                "plan_fast_failure_rate": round(failure_rate, 4),
                "plan_fast_avg_days": round(avg_days, 3),
                "plan_fast_latency_ms_mean": round(avg_latency, 3),
                "plan_fast_latency_ms_p95": round(p95, 3),
                "top_destinations": top_destinations,
                "last_10_calls": last_10_calls,
            }
        except RedisError as exc:
            self._logger.warning(
                "plan_metrics.redis_snapshot_failed",
                extra={"error": str(exc)},
            )
            return InMemoryPlanMetricsBackend().snapshot(top_n=top_n)

    def reset(self) -> None:
        try:
            self._client.delete(
                self._key("counts"),
                self._key("history"),
                self._key("fast_latencies_ms"),
                self._key("destinations"),
            )
        except RedisError:
            return


def _format_entry(entry: PlanCallEntry) -> dict:
    payload = asdict(entry)
    payload["recorded_at"] = entry.recorded_at.isoformat()
    return payload


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if p <= 0:
        return float(min(values))
    if p >= 100:
        return float(max(values))
    ordered = sorted(values)
    k = (len(ordered) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    if f == c:
        return float(ordered[f])
    d0 = ordered[f] * (c - k)
    d1 = ordered[c] * (k - f)
    return float(d0 + d1)


def _init_backend() -> PlanMetricsBackend:
    backend: PlanMetricsBackendName = getattr(
        settings, "plan_metrics_backend", "memory"
    )
    if backend == "redis":
        try:
            namespace = getattr(settings, "plan_metrics_namespace", "plan_metrics")
            history_limit = int(getattr(settings, "plan_metrics_history_limit", 100))
            latency_limit = int(getattr(settings, "plan_metrics_latency_limit", 500))
            return RedisPlanMetricsBackend(
                url=settings.redis_url,
                namespace=namespace,
                history_limit=history_limit,
                latency_limit=latency_limit,
            )
        except Exception as exc:  # pragma: no cover - optional path
            logger = get_logger(__name__)
            logger.warning(
                "plan_metrics.redis_init_failed",
                extra={"error": str(exc)},
            )
    return InMemoryPlanMetricsBackend(
        history_limit=int(getattr(settings, "plan_metrics_history_limit", 100))
    )


_plan_metrics: PlanMetricsBackend = _init_backend()


def get_plan_metrics() -> PlanMetricsBackend:
    return _plan_metrics


def reset_plan_metrics() -> None:
    _plan_metrics.reset()
