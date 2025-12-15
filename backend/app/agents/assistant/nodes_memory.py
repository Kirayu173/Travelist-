from __future__ import annotations

from typing import Any

from app.ai.memory_models import MemoryItem, MemoryLevel
from app.core.cache import build_cache_key, cache_backend
from app.core.settings import settings
from app.services.memory_service import MemoryService


async def search_memories_multi_scope(
    *,
    memory_service: MemoryService,
    user_id: int,
    trip_id: int | None,
    session_id: int | None,
    query: str,
    top_k: int,
) -> tuple[list[MemoryItem], dict[str, int]]:
    """
    Search memories across session/trip/user scopes and merge results.

    This avoids mismatches between first-turn writes and later-turn reads, and
    enables cross-session recall (user/trip) without losing per-session memory.
    """

    normalized_query = (query or "").strip()
    if not normalized_query:
        return [], {}

    top_k = max(1, top_k or 5)
    ttl = int(getattr(settings, "ai_memory_cache_ttl_seconds", 30))

    scopes: list[tuple[str, MemoryLevel, dict[str, Any]]] = []
    if session_id:
        scopes.append(
            (
                "session",
                MemoryLevel.session,
                {
                    "trip_id": trip_id,
                    "session_id": str(session_id),
                },
            )
        )
    if trip_id:
        scopes.append(
            (
                "trip",
                MemoryLevel.trip,
                {
                    "trip_id": trip_id,
                    "session_id": str(session_id) if session_id else None,
                },
            )
        )
    scopes.append(
        (
            "user",
            MemoryLevel.user,
            {
                "trip_id": trip_id,
                "session_id": str(session_id) if session_id else None,
            },
        )
    )

    merged: dict[str, MemoryItem] = {}
    counts: dict[str, int] = {}
    per_scope_k = max(2, top_k)

    for scope_name, level, ids in scopes:
        cache_key = build_cache_key(
            "assistant:mem_search",
            scope=scope_name,
            user_id=user_id,
            trip_id=ids.get("trip_id") or 0,
            session_id=ids.get("session_id") or "",
            q=normalized_query,
            k=per_scope_k,
        )

        async def _load(*, level: MemoryLevel = level, ids: dict[str, Any] = ids):
            return await memory_service.search_memory(
                user_id=user_id,
                level=level,
                query=normalized_query,
                trip_id=ids.get("trip_id"),
                session_id=ids.get("session_id"),
                k=per_scope_k,
            )

        items: list[MemoryItem] = await cache_backend.remember_async(
            "assistant_memory",
            cache_key,
            ttl,
            _load,
        )
        counts[scope_name] = len(items)
        for item in items:
            key = item.id or item.text
            if not key:
                continue
            existing = merged.get(key)
            if existing is None or (item.score or 0) > (existing.score or 0):
                merged[key] = item

    results = list(merged.values())
    results.sort(key=lambda m: (m.score or 0), reverse=True)
    return results[:top_k], counts
