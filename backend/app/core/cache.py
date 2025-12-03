from __future__ import annotations

import inspect
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Any, Awaitable, Callable, Dict

import pickle
import warnings

from app.core.settings import settings

try:
    from redis import Redis
    from redis.exceptions import RedisError
except Exception:  # pragma: no cover - optional dependency
    Redis = None
    RedisError = Exception


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


class RedisCacheBackend(CacheBackend):
    """Redis-backed cache providing cross-process sharing."""

    def __init__(self, url: str, namespace_prefix: str = "cache") -> None:
        if Redis is None:
            raise RuntimeError("redis package not available")
        self._client = Redis.from_url(url, decode_responses=False)
        self._prefix = namespace_prefix.rstrip(":")

    def _full_key(self, namespace: str, key: str) -> str:
        return f"{self._prefix}:{namespace}:{key}"

    def get(self, namespace: str, key: str) -> Any | None:
        full_key = self._full_key(namespace, key)
        try:
            raw = self._client.get(full_key)
        except RedisError:
            return None
        if raw is None:
            return None
        try:
            return pickle.loads(raw)
        except Exception:
            return None

    def set(self, namespace: str, key: str, value: Any, ttl_seconds: int) -> None:
        full_key = self._full_key(namespace, key)
        payload = pickle.dumps(value)
        try:
            self._client.setex(full_key, max(ttl_seconds, 1), payload)
        except RedisError:
            return None

    def invalidate(self, namespace: str, key: str | None = None) -> None:
        if key is not None:
            try:
                self._client.delete(self._full_key(namespace, key))
            except RedisError:
                return
            return
        pattern = f"{self._prefix}:{namespace}:*"
        try:
            for found in self._client.scan_iter(pattern):
                self._client.delete(found)
        except RedisError:
            return


def _init_cache_backend() -> CacheBackend:
    provider = getattr(settings, "cache_provider", "memory")
    if provider == "redis":
        try:
            return RedisCacheBackend(
                settings.redis_url, namespace_prefix=settings.cache_namespace
            )
        except Exception as exc:  # pragma: no cover - optional path
            warnings.warn(
                f"Redis cache init failed ({exc}), falling back to in-memory cache"
            )
    return CacheBackend()


cache_backend = _init_cache_backend()
