from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock


@dataclass
class AiCallEntry:
    trace_id: str
    provider: str
    model: str
    latency_ms: float
    success: bool
    error_type: str | None
    usage_tokens: int | None
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Mem0Entry:
    operation: str
    success: bool
    error_type: str | None
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AiMetrics:
    """In-memory collector tracking AI and mem0 activity."""

    def __init__(self, history_limit: int = 50) -> None:
        self._history_limit = history_limit
        self._ai_calls_total = 0
        self._ai_calls_success = 0
        self._ai_calls_failed = 0
        self._latency_total = 0.0
        self._usage_tokens_total = 0
        self._usage_tokens_samples = 0
        self._history: deque[AiCallEntry] = deque(maxlen=history_limit)
        self._mem0_calls = 0
        self._mem0_errors = 0
        self._mem0_history: deque[Mem0Entry] = deque(maxlen=history_limit)
        self._lock = Lock()

    def record_ai_call(
        self,
        *,
        trace_id: str,
        provider: str,
        model: str,
        latency_ms: float,
        success: bool,
        error_type: str | None = None,
        usage_tokens: int | None = None,
    ) -> None:
        with self._lock:
            self._ai_calls_total += 1
            if success:
                self._ai_calls_success += 1
            else:
                self._ai_calls_failed += 1
            self._latency_total += latency_ms
            if usage_tokens is not None:
                self._usage_tokens_total += usage_tokens
                self._usage_tokens_samples += 1
            entry = AiCallEntry(
                trace_id=trace_id,
                provider=provider,
                model=model,
                latency_ms=latency_ms,
                success=success,
                error_type=error_type,
                usage_tokens=usage_tokens,
            )
            self._history.appendleft(entry)

    def record_mem0_call(
        self,
        *,
        operation: str,
        success: bool,
        error_type: str | None = None,
    ) -> None:
        with self._lock:
            self._mem0_calls += 1
            if not success:
                self._mem0_errors += 1
            entry = Mem0Entry(
                operation=operation,
                success=success,
                error_type=error_type,
            )
            self._mem0_history.appendleft(entry)

    def snapshot(self) -> dict:
        with self._lock:
            avg_latency = (
                self._latency_total / self._ai_calls_total
                if self._ai_calls_total
                else 0.0
            )
            avg_tokens = (
                self._usage_tokens_total / self._usage_tokens_samples
                if self._usage_tokens_samples
                else None
            )
            return {
                "ai_calls_total": self._ai_calls_total,
                "ai_calls_success": self._ai_calls_success,
                "ai_calls_failed": self._ai_calls_failed,
                "avg_latency_ms": round(avg_latency, 3),
                "avg_usage_tokens": (
                    round(avg_tokens, 2) if avg_tokens is not None else None
                ),
                "last_calls": [
                    self._format_call(entry) for entry in list(self._history)
                ],
                "mem0_calls_total": self._mem0_calls,
                "mem0_errors": self._mem0_errors,
                "mem0_recent": [
                    self._format_mem0(entry) for entry in list(self._mem0_history)
                ],
            }

    @staticmethod
    def _format_call(entry: AiCallEntry) -> dict:
        return {
            "trace_id": entry.trace_id,
            "provider": entry.provider,
            "model": entry.model,
            "latency_ms": round(entry.latency_ms, 3),
            "success": entry.success,
            "error_type": entry.error_type,
            "usage_tokens": entry.usage_tokens,
            "recorded_at": entry.recorded_at.isoformat(),
        }

    @staticmethod
    def _format_mem0(entry: Mem0Entry) -> dict:
        return {
            "operation": entry.operation,
            "success": entry.success,
            "error_type": entry.error_type,
            "recorded_at": entry.recorded_at.isoformat(),
        }


_ai_metrics = AiMetrics()


def get_ai_metrics() -> AiMetrics:
    return _ai_metrics
