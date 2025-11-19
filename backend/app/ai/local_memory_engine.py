from __future__ import annotations

from threading import Lock
from typing import Any

from app.ai.memory_models import MemoryItem, MemoryLevel
from app.core.logging import get_logger
from app.core.settings import Settings, settings
from mem0.configs.base import MemoryConfig
from mem0.embeddings.configs import EmbedderConfig
from mem0.llms.configs import LlmConfig
from mem0.memory.main import Memory as OssMemory
from mem0.vector_stores.configs import VectorStoreConfig
from sqlalchemy.engine.url import URL, make_url

LOGGER = get_logger(__name__)
_ENGINE_LOCK = Lock()
_ENGINE_INSTANCE: "LocalMemoryEngine | None" = None


def _build_pg_connection_string(database_url: str) -> str:
    url: URL = make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        msg = "mem0 本地模式仅支持 PostgreSQL（pgvector）"
        raise ValueError(msg)
    simple = url.set(drivername="postgresql")
    return simple.render_as_string(hide_password=False)


class LocalMemoryEngine:
    """Wrapper around mem0 OSS Memory with project-specific configuration."""

    def __init__(
        self,
        memory: OssMemory,
        *,
        collection: str,
        provider: str,
    ) -> None:
        self._memory = memory
        self._collection = collection
        self._provider = provider
        self._logger = get_logger(__name__)

    @classmethod
    def create(cls, app_settings: Settings) -> "LocalMemoryEngine":
        provider = app_settings.mem0_vector_provider
        try:
            config = cls._build_memory_config(app_settings, provider=provider)
            oss_memory = OssMemory(config)
            return cls(
                oss_memory,
                collection=app_settings.mem0_pg_collection,
                provider=provider,
            )
        except Exception as exc:
            missing_vector = 'extension "vector" is not available' in str(exc)
            if provider == "pgvector" and missing_vector:
                LOGGER.warning(
                    "pgvector extension 不可用，自动降级到 pgarray 存储",
                    extra={"error": str(exc)},
                )
                fallback_config = cls._build_memory_config(
                    app_settings,
                    provider="pgarray",
                )
                oss_memory = OssMemory(fallback_config)
                return cls(
                    oss_memory,
                    collection=app_settings.mem0_pg_collection,
                    provider="pgarray",
                )
            raise

    @staticmethod
    def _build_memory_config(app_settings: Settings, *, provider: str) -> MemoryConfig:
        connection_string = _build_pg_connection_string(app_settings.database_url)
        if provider == "pgvector":
            vector_config: dict[str, Any] = {
                "connection_string": connection_string,
                "collection_name": app_settings.mem0_pg_collection,
                "embedding_model_dims": app_settings.mem0_embed_dims,
                "diskann": app_settings.mem0_pg_use_diskann,
                "hnsw": app_settings.mem0_pg_use_hnsw,
                "minconn": app_settings.mem0_pg_minconn,
                "maxconn": app_settings.mem0_pg_maxconn,
            }
        elif provider == "pgarray":
            vector_config = {
                "connection_string": connection_string,
                "collection_name": app_settings.mem0_pg_collection,
                "embedding_model_dims": app_settings.mem0_embed_dims,
                "minconn": app_settings.mem0_pg_minconn,
                "maxconn": app_settings.mem0_pg_maxconn,
            }
        else:
            msg = f"Unsupported vector provider: {provider}"
            raise ValueError(msg)
        vector_store = VectorStoreConfig(
            provider=provider,
            config=vector_config,
        )
        embed_base = (
            app_settings.mem0_embed_base_url
            or app_settings.ai_api_base
            or "http://127.0.0.1:11434"
        )
        embedder = EmbedderConfig(
            provider=app_settings.mem0_embed_provider,
            config={
                "model": app_settings.mem0_embed_model,
                "embedding_dims": app_settings.mem0_embed_dims,
                "ollama_base_url": embed_base,
            },
        )
        llm_base = (
            app_settings.mem0_llm_base_url
            or app_settings.ai_api_base
            or "http://127.0.0.1:11434"
        )
        llm_model = app_settings.mem0_llm_model or app_settings.ai_model_chat
        llm = LlmConfig(
            provider=app_settings.mem0_llm_provider,
            config={
                "model": llm_model,
                "ollama_base_url": llm_base,
            },
        )
        return MemoryConfig(
            vector_store=vector_store,
            embedder=embedder,
            llm=llm,
        )

    def add_memory(
        self,
        *,
        user_id: int,
        level: MemoryLevel,
        text: str,
        metadata: dict[str, Any],
    ) -> str | None:
        payload = dict(metadata)
        payload["level"] = level.value
        payload["user_id"] = str(user_id)
        result = self._memory.add(
            text,
            user_id=str(user_id),
            metadata=payload,
            infer=False,
        )
        return self._extract_memory_id(result)

    def search_memories(
        self,
        *,
        user_id: int,
        level: MemoryLevel,
        query: str,
        filters: dict[str, Any],
        limit: int,
    ) -> list[MemoryItem]:
        normalized_filters = {
            **filters,
            "level": level.value,
        }
        response = self._memory.search(
            query,
            user_id=str(user_id),
            limit=limit,
            filters=normalized_filters,
            rerank=False,
        )
        records = []
        if isinstance(response, dict):
            records = response.get("results") or []
        return [self._to_memory_item(record) for record in records if record]

    @staticmethod
    def _extract_memory_id(result: Any) -> str | None:
        if not isinstance(result, dict):
            return None
        results = result.get("results")
        if isinstance(results, list) and results:
            item = results[0]
            for key in ("id", "memory_id", "uuid"):
                if key in item and item[key]:
                    return str(item[key])
        return None

    @staticmethod
    def _to_memory_item(record: dict[str, Any]) -> MemoryItem:
        metadata = record.get("metadata") or record.get("payload") or {}
        text = record.get("memory") or record.get("text") or ""
        return MemoryItem(
            id=str(record.get("id") or record.get("memory_id") or ""),
            text=text,
            score=record.get("score"),
            metadata=metadata,
        )


def get_local_memory_engine() -> LocalMemoryEngine:
    global _ENGINE_INSTANCE
    if _ENGINE_INSTANCE is None:
        with _ENGINE_LOCK:
            if _ENGINE_INSTANCE is None:
                LOGGER.info(
                    "初始化本地 mem0 引擎（PGVector collection=%s）",
                    settings.mem0_pg_collection,
                )
                _ENGINE_INSTANCE = LocalMemoryEngine.create(settings)
    return _ENGINE_INSTANCE
