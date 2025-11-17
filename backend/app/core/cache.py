from __future__ import annotations

import inspect
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Any, Awaitable, Callable, Dict


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class CacheBackend:
    """In-memory TTL cache with namespace based invalidation."""

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, _CacheEntry]] = {}
        self._lock = RLock()

    def _resolve(self, namespace: str) -> Dict[str, _CacheEntry]:
        if namespace not in self._store:
            self._store[namespace] = {}
        return self._store[namespace]

    def get(self, namespace: str, key: str) -> Any | None:
        with self._lock:
            bucket = self._store.get(namespace)
            if not bucket:
                return None
            entry = bucket.get(key)
            if not entry:
                return None
            if monotonic() >= entry.expires_at:
                bucket.pop(key, None)
                return None
            return entry.value

    def set(self, namespace: str, key: str, value: Any, ttl_seconds: int) -> None:
        expires_at = monotonic() + max(ttl_seconds, 1)
        with self._lock:
            bucket = self._resolve(namespace)
            bucket[key] = _CacheEntry(value=value, expires_at=expires_at)

    def invalidate(self, namespace: str, key: str | None = None) -> None:
        with self._lock:
            if namespace not in self._store:
                return
            if key is None:
                self._store.pop(namespace, None)
                return
            bucket = self._store.get(namespace)
            if bucket is not None:
                bucket.pop(key, None)

    def remember(
        self,
        namespace: str,
        key: str,
        ttl_seconds: int,
        loader: Callable[[], Any],
    ) -> Any:
        cached = self.get(namespace, key)
        if cached is not None:
            return cached
        value = loader()
        self.set(namespace, key, value, ttl_seconds)
        return value

    async def remember_async(
        self,
        namespace: str,
        key: str,
        ttl_seconds: int,
        loader: Callable[[], Any | Awaitable[Any]],
    ) -> Any:
        cached = self.get(namespace, key)
        if cached is not None:
            return cached
        value = loader()
        if inspect.isawaitable(value):
            value = await value
        self.set(namespace, key, value, ttl_seconds)
        return value


def build_cache_key(*parts: Any, **named_parts: Any) -> str:
    """Creates a deterministic cache key from args for convenience."""

    positional = "|".join(str(part) for part in parts)
    keyword = "|".join(f"{key}={value}" for key, value in sorted(named_parts.items()))
    if positional and keyword:
        return f"{positional}::{keyword}"
    if positional:
        return positional
    return keyword


cache_backend = CacheBackend()
