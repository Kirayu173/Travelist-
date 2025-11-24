from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application level configuration sourced from env or .env file."""

    app_env: str = "development"
    app_name: str = "Travelist+ Backend"
    app_version: str = "0.0.1"
    debug: bool = True
    uvicorn_host: str = "0.0.0.0"
    uvicorn_port: int = 8000

    database_url: str = "postgresql+psycopg://appuser:apppass@localhost:5432/appdb"
    redis_url: str = "redis://localhost:6379/0"
    cache_provider: Literal["memory", "redis"] = "memory"
    cache_namespace: str = "cache"

    gaode_key: str | None = None
    llm_provider: str | None = None
    llm_api_key: str | None = None
    ai_provider: str | None = None
    ai_api_key: str | None = None
    ai_api_base: str | None = None
    ai_model_chat: str | None = None
    ai_request_timeout_s: float = 30.0
    mem0_default_k: int = 5
    mem0_mode: Literal["disabled", "local"] = "disabled"
    mem0_vector_provider: Literal["pgvector", "pgarray"] = "pgvector"
    mem0_pg_collection: str = "mem0_memories"
    mem0_pg_minconn: int = 1
    mem0_pg_maxconn: int = 5
    mem0_pg_use_hnsw: bool = True
    mem0_pg_use_diskann: bool = False
    mem0_embed_provider: str = "ollama"
    mem0_embed_model: str = "bge-m3"
    mem0_embed_dims: int = 1024
    mem0_embed_base_url: str | None = None
    mem0_llm_provider: str = "ollama"
    mem0_llm_model: str | None = None
    mem0_llm_base_url: str | None = None
    ai_assistant_graph_enabled: bool = True
    ai_assistant_max_history_rounds: int = 6
    ai_prompt_cache_ttl: int = 60
    ai_prompt_edit_in_prod: bool = False
    mem0_fallback_ttl_seconds: int = 1800
    mem0_fallback_max_entries_per_ns: int = 500
    mem0_fallback_max_total_entries: int = 5000

    jwt_secret: str = "change_me"
    jwt_alg: str = "HS256"
    jwt_expire_min: int = 60
    log_level: str = "INFO"
    log_directory: str = "logs"
    log_max_bytes: int = 2 * 1024 * 1024
    log_backup_count: int = 5
    admin_api_token: str | None = None
    admin_allowed_ips: list[str] | str | None = Field(default=None)

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("admin_allowed_ips", mode="before")
    @classmethod
    def parse_admin_ips(cls, value: str | list[str] | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        parts = [segment.strip() for segment in value.split(",") if segment.strip()]
        return parts


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
