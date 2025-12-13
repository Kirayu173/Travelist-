from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import mean
from threading import Lock
from typing import Deque


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


class PlanMetrics:
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
                    self._format_entry(entry) for entry in list(self._history)[:10]
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

    @staticmethod
    def _format_entry(entry: PlanCallEntry) -> dict:
        return {
            "trace_id": entry.trace_id,
            "mode": entry.mode,
            "destination": entry.destination,
            "days": entry.days,
            "latency_ms": round(entry.latency_ms, 3),
            "success": entry.success,
            "error": entry.error,
            "recorded_at": entry.recorded_at.isoformat(),
        }


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


_plan_metrics = PlanMetrics()


def get_plan_metrics() -> PlanMetrics:
    return _plan_metrics


def reset_plan_metrics() -> None:
    _plan_metrics.reset()
