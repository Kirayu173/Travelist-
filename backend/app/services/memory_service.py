from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from difflib import SequenceMatcher
from threading import RLock
from time import monotonic
from typing import Any
from uuid import uuid4

from anyio import to_thread
from app.ai.local_memory_engine import LocalMemoryEngine, get_local_memory_engine
from app.ai.memory_models import MemoryItem, MemoryLevel
from app.ai.metrics import AiMetrics, get_ai_metrics
from app.core.logging import get_logger
from app.core.settings import settings


@dataclass
class _LocalMemory:
    id: str
    text: str
    metadata: dict[str, Any]
    created_at: float


class _InMemoryStore:
    """Fallback storage when mem0 is not available."""

    def __init__(
        self,
        *,
        ttl_seconds: int,
        max_entries_per_namespace: int,
        max_total_entries: int,
    ) -> None:
        self._store: dict[str, deque[_LocalMemory]] = defaultdict(deque)
        self._lock = RLock()
        self._ttl_seconds = max(ttl_seconds, 1)
        self._max_entries_per_namespace = max(max_entries_per_namespace, 1)
        self._max_total_entries = max(max_total_entries, 1)

    def write(self, namespace: str, text: str, metadata: dict[str, Any]) -> str:
        record_id = f"local-{uuid4().hex}"
        entry = _LocalMemory(
            id=record_id,
            text=text,
            metadata=dict(metadata),
            created_at=monotonic(),
        )
        with self._lock:
            self._prune_namespace(namespace)
            bucket = self._store[namespace]
            bucket.append(entry)
            self._enforce_limits(bucket)
        self._enforce_global_limit()
        return record_id

    def search(self, namespace: str, query: str, k: int) -> list[MemoryItem]:
        with self._lock:
            self._prune_namespace(namespace)
            entries = list(self._store.get(namespace, []))
        scored: list[tuple[float, _LocalMemory]] = []
        for entry in entries:
            score = self._score(entry.text, query)
            scored.append((score, entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        payload: list[MemoryItem] = []
        for score, entry in scored[:k]:
            payload.append(
                MemoryItem(
                    id=entry.id,
                    text=entry.text,
                    score=round(score, 4),
                    metadata=entry.metadata,
                )
            )
        return payload

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            entries: list[tuple[str, _LocalMemory]] = []
            for namespace, bucket in self._store.items():
                for item in bucket:
                    entries.append((namespace, item))
        # order by created_at descending
        entries.sort(key=lambda pair: pair[1].created_at, reverse=True)
        rows = []
        for namespace, item in entries[: max(limit, 1)]:
            rows.append(
                {
                    "id": item.id,
                    "namespace": namespace,
                    "text": item.text,
                    "metadata": item.metadata,
                    "created_at": item.created_at,
                }
            )
        return rows

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def stats(self) -> dict[str, int]:
        with self._lock:
            namespaces = len(self._store)
            total_entries = sum(len(bucket) for bucket in self._store.values())
        return {
            "namespaces": namespaces,
            "total_entries": total_entries,
            "max_entries_per_namespace": self._max_entries_per_namespace,
            "max_total_entries": self._max_total_entries,
        }

    def _prune_namespace(self, namespace: str) -> None:
        bucket = self._store.get(namespace)
        if not bucket:
            return
        now = monotonic()
        ttl_threshold = now - self._ttl_seconds
        while bucket and bucket[0].created_at < ttl_threshold:
            bucket.popleft()
        self._enforce_limits(bucket)

    def _enforce_limits(self, bucket: deque[_LocalMemory]) -> None:
        while len(bucket) > self._max_entries_per_namespace:
            bucket.popleft()

    def _enforce_global_limit(self) -> None:
        total_entries = sum(len(bucket) for bucket in self._store.values())
        if total_entries <= self._max_total_entries:
            return
        # Drop oldest across namespaces by simple round-robin
        while total_entries > self._max_total_entries:
            for _namespace, bucket in list(self._store.items()):
                if bucket:
                    bucket.popleft()
                    total_entries -= 1
                    if total_entries <= self._max_total_entries:
                        break

    @staticmethod
    def _score(text: str, query: str) -> float:
        if not text:
            return 0.0
        if query.lower() in text.lower():
            return 1.0
        matcher = SequenceMatcher(None, query, text)
        return matcher.quick_ratio()


class MemoryService:
    """High-level memory operations backed by mem0 with graceful fallback."""

    def __init__(self, metrics: AiMetrics | None = None) -> None:
        self._metrics = metrics or get_ai_metrics()
        self._settings = settings
        self._logger = get_logger(__name__)
        self._local_store = _InMemoryStore(
            ttl_seconds=self._settings.mem0_fallback_ttl_seconds,
            max_entries_per_namespace=self._settings.mem0_fallback_max_entries_per_ns,
            max_total_entries=self._settings.mem0_fallback_max_total_entries,
        )
        self._engine: LocalMemoryEngine | None = None
        self._engine_error: str | None = None
        self._engine_ready = False
        self._try_init_engine()

    async def write_memory(
        self,
        user_id: int,
        level: MemoryLevel,
        text: str,
        *,
        trip_id: int | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        namespace, base_metadata = self._build_namespace(
            user_id=user_id,
            level=level,
            trip_id=trip_id,
            session_id=session_id,
        )
        merged_meta = {**base_metadata, **(metadata or {})}
        local_id = self._local_store.write(namespace, text, merged_meta)
        self._report_fallback_stats()

        if not self._ensure_engine_ready():
            self._metrics.record_mem0_call(
                operation="write",
                success=False,
                error_type=self._engine_error or "disabled",
            )
            return local_id

        try:
            mem0_id = await to_thread.run_sync(
                lambda: self._engine.add_memory(
                    user_id=user_id,
                    level=level,
                    text=text,
                    metadata=merged_meta,
                )
            )
            self._metrics.record_mem0_call(operation="write", success=True)
            return mem0_id or local_id
        except Exception as exc:  # pragma: no cover - engine interactions
            self._logger.warning(
                "mem0.write_failed",
                extra={"error": str(exc)},
            )
            self._metrics.record_mem0_call(
                operation="write",
                success=False,
                error_type=exc.__class__.__name__,
            )
            self._report_fallback_stats()
            return local_id

    async def search_memory(
        self,
        user_id: int,
        level: MemoryLevel,
        query: str,
        *,
        trip_id: int | None = None,
        session_id: str | None = None,
        k: int | None = None,
    ) -> list[MemoryItem]:
        namespace, base_metadata = self._build_namespace(
            user_id=user_id,
            level=level,
            trip_id=trip_id,
            session_id=session_id,
        )
        limit = k or self._settings.mem0_default_k or 5
        fallback = self._local_store.search(namespace, query, limit)
        self._report_fallback_stats()

        if not self._ensure_engine_ready():
            self._metrics.record_mem0_call(
                operation="search",
                success=False,
                error_type=self._engine_error or "disabled",
            )
            return fallback

        try:
            items = await to_thread.run_sync(
                lambda: self._engine.search_memories(
                    user_id=user_id,
                    level=level,
                    query=query,
                    filters=self._build_filters(base_metadata),
                    limit=limit,
                )
            )
            self._metrics.record_mem0_call(operation="search", success=True)
            return items or fallback
        except Exception as exc:  # pragma: no cover - engine interactions
            self._logger.warning(
                "mem0.search_failed",
                extra={"error": str(exc)},
            )
            self._metrics.record_mem0_call(
                operation="search",
                success=False,
                error_type=exc.__class__.__name__,
            )
            self._report_fallback_stats()
            return fallback

    async def list_memories(
        self,
        *,
        user_id: int,
        level: MemoryLevel,
        query: str = "",
        trip_id: int | None = None,
        session_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryItem]:
        """
        List memories for diagnostics/inspection, leveraging the same search path.
        Offset is applied locally after retrieval to stay compatible with
        mem0/local store.
        """

        fetch_limit = max(limit + offset, 1)
        items = await self.search_memory(
            user_id=user_id,
            level=level,
            query=query or "*",
            trip_id=trip_id,
            session_id=session_id,
            k=fetch_limit,
        )
        return items[offset : offset + limit]

    @staticmethod
    def _build_namespace(
        *,
        user_id: int,
        level: MemoryLevel,
        trip_id: int | None,
        session_id: str | None,
    ) -> tuple[str, dict[str, Any]]:
        if level is MemoryLevel.user:
            namespace = f"user:{user_id}"
        elif level is MemoryLevel.trip:
            if trip_id is None:
                msg = "trip_id is required for trip level memories"
                raise ValueError(msg)
            namespace = f"user:{user_id}:trip:{trip_id}"
        else:
            if session_id is None:
                msg = "session_id is required for session level memories"
                raise ValueError(msg)
            namespace = f"user:{user_id}:session:{session_id}"
        metadata = {
            "level": level.value,
            "user_id": str(user_id),
        }
        if trip_id is not None:
            metadata["trip_id"] = trip_id
        if session_id is not None:
            metadata["session_id"] = session_id
        metadata["namespace"] = namespace
        return namespace, metadata

    @staticmethod
    def _build_filters(base_metadata: dict[str, Any]) -> dict[str, Any]:
        filters = {
            "level": base_metadata.get("level"),
            "user_id": base_metadata.get("user_id"),
        }
        if "trip_id" in base_metadata:
            filters["trip_id"] = base_metadata["trip_id"]
        if "session_id" in base_metadata:
            filters["session_id"] = base_metadata["session_id"]
        return filters

    def _try_init_engine(self) -> None:
        if self._settings.mem0_mode != "local":
            self._engine = None
            self._engine_error = "disabled"
            self._engine_ready = False
            return
        try:
            self._engine = get_local_memory_engine()
            self._engine_error = None
            if not self._engine_ready:
                self._local_store.clear()
                self._report_fallback_stats()
            self._engine_ready = True
        except Exception as exc:  # pragma: no cover - initialization failure
            self._logger.warning(
                "mem0.engine_init_failed",
                extra={"error": str(exc)},
            )
            self._engine = None
            self._engine_error = exc.__class__.__name__
            self._engine_ready = False

    def _ensure_engine_ready(self) -> bool:
        if self._engine is not None:
            return True
        if self._settings.mem0_mode != "local":
            return False
        self._try_init_engine()
        return self._engine is not None

    def _report_fallback_stats(self) -> None:
        stats = self._local_store.stats()
        self._metrics.update_mem0_fallback(
            namespaces=stats["namespaces"],
            total_entries=stats["total_entries"],
            max_entries_per_namespace=stats["max_entries_per_namespace"],
            max_total_entries=stats["max_total_entries"],
        )

    def list_recent_memories(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent fallback memories for diagnostics."""

        return self._local_store.list_recent(limit=limit)


_memory_service: MemoryService | None = None


def get_memory_service() -> MemoryService:
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService()
    return _memory_service
