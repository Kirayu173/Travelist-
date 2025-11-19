from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from threading import RLock
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


class _InMemoryStore:
    """Fallback storage when mem0 is not available."""

    def __init__(self) -> None:
        self._store: dict[str, list[_LocalMemory]] = defaultdict(list)
        self._lock = RLock()

    def write(self, namespace: str, text: str, metadata: dict[str, Any]) -> str:
        record_id = f"local-{uuid4().hex}"
        entry = _LocalMemory(id=record_id, text=text, metadata=dict(metadata))
        with self._lock:
            self._store[namespace].append(entry)
        return record_id

    def search(self, namespace: str, query: str, k: int) -> list[MemoryItem]:
        with self._lock:
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
        self._local_store = _InMemoryStore()
        self._engine: LocalMemoryEngine | None = None
        self._engine_error: str | None = None
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
            return fallback

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
            return
        try:
            self._engine = get_local_memory_engine()
            self._engine_error = None
        except Exception as exc:  # pragma: no cover - initialization failure
            self._logger.warning(
                "mem0.engine_init_failed",
                extra={"error": str(exc)},
            )
            self._engine = None
            self._engine_error = exc.__class__.__name__

    def _ensure_engine_ready(self) -> bool:
        if self._engine is not None:
            return True
        if self._settings.mem0_mode != "local":
            return False
        self._try_init_engine()
        return self._engine is not None


_memory_service: MemoryService | None = None


def get_memory_service() -> MemoryService:
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService()
    return _memory_service
