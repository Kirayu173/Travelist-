from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
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
    poi_provider: Literal["mock", "gaode"] = "mock"
    poi_gaode_api_key: str | None = None
    poi_default_radius_m: int = 2000
    poi_max_radius_m: int = 5000
    poi_cache_ttl_seconds: int = 600
    poi_coord_precision: int = 4
    poi_cache_enabled: bool = True
    poi_min_results: int = 8

    geocode_provider: Literal["disabled", "mock", "amap"] = Field(
        default="mock",
        validation_alias="GEOCODE_PROVIDER",
    )
    geocode_cache_ttl_seconds: int = Field(
        default=86400,
        validation_alias="GEOCODE_CACHE_TTL_SECONDS",
    )
    amap_api_key: str | None = Field(default=None, validation_alias="AMAP_API_KEY")

    plan_default_day_start: str = Field(
        default="09:00", validation_alias="PLAN_DEFAULT_DAY_START"
    )
    plan_default_day_end: str = Field(
        default="18:00", validation_alias="PLAN_DEFAULT_DAY_END"
    )
    plan_default_slot_minutes: int = Field(
        default=90, validation_alias="PLAN_DEFAULT_SLOT_MINUTES"
    )
    plan_max_days: int = Field(default=14, validation_alias="PLAN_MAX_DAYS")
    plan_fast_random_seed: int = Field(
        default=7, validation_alias="PLAN_FAST_RANDOM_SEED"
    )
    plan_fast_poi_limit_per_day: int = Field(
        default=16, validation_alias="PLAN_FAST_POI_LIMIT_PER_DAY"
    )
    plan_fast_transport_mode: Literal["walk", "bike", "drive", "transit"] = Field(
        default="walk", validation_alias="PLAN_FAST_TRANSPORT_MODE"
    )

    # --- Stage-8 Deep planner (LLM, day-by-day) ---
    plan_deep_model: str | None = Field(
        default=None, validation_alias="PLAN_DEEP_MODEL"
    )
    plan_deep_temperature: float = Field(
        default=0.2, validation_alias="PLAN_DEEP_TEMPERATURE"
    )
    plan_deep_max_tokens: int = Field(
        default=1200, validation_alias="PLAN_DEEP_MAX_TOKENS"
    )
    plan_deep_timeout_s: float = Field(
        default=30.0, validation_alias="PLAN_DEEP_TIMEOUT_S"
    )
    plan_deep_retries: int = Field(default=1, validation_alias="PLAN_DEEP_RETRIES")
    plan_deep_prompt_version: str = Field(
        default="v1", validation_alias="PLAN_DEEP_PROMPT_VERSION"
    )
    plan_deep_max_pois: int = Field(default=24, validation_alias="PLAN_DEEP_MAX_POIS")
    plan_deep_max_days: int = Field(default=7, validation_alias="PLAN_DEEP_MAX_DAYS")
    plan_deep_fallback_to_fast: bool = Field(
        default=True, validation_alias="PLAN_DEEP_FALLBACK_TO_FAST"
    )
    plan_deep_day_max_tokens: int = Field(
        default=900, validation_alias="PLAN_DEEP_DAY_MAX_TOKENS"
    )
    plan_deep_day_min_sub_trips: int = Field(
        default=3, validation_alias="PLAN_DEEP_DAY_MIN_SUB_TRIPS"
    )
    plan_deep_context_max_days: int = Field(
        default=3, validation_alias="PLAN_DEEP_CONTEXT_MAX_DAYS"
    )
    plan_deep_context_max_chars: int = Field(
        default=1800, validation_alias="PLAN_DEEP_CONTEXT_MAX_CHARS"
    )
    plan_deep_tool_max_steps: int = Field(
        default=18, validation_alias="PLAN_DEEP_TOOL_MAX_STEPS"
    )
    plan_deep_outline_source: Literal["fast", "llm_outline"] = Field(
        default="fast", validation_alias="PLAN_DEEP_OUTLINE_SOURCE"
    )

    # --- Stage-8 Async tasks (ai_tasks) ---
    plan_task_worker_concurrency: int = Field(
        default=2, validation_alias="PLAN_TASK_WORKER_CONCURRENCY"
    )
    plan_task_queue_maxsize: int = Field(
        default=200, validation_alias="PLAN_TASK_QUEUE_MAXSIZE"
    )
    plan_task_max_running_per_user: int = Field(
        default=1, validation_alias="PLAN_TASK_MAX_RUNNING_PER_USER"
    )
    plan_task_retention_days: int = Field(
        default=7, validation_alias="PLAN_TASK_RETENTION_DAYS"
    )
    plan_metrics_backend: Literal["memory", "redis"] = Field(
        default="memory",
        validation_alias="PLAN_METRICS_BACKEND",
    )
    plan_metrics_namespace: str = Field(
        default="plan_metrics",
        validation_alias="PLAN_METRICS_NAMESPACE",
    )
    plan_metrics_history_limit: int = Field(
        default=100,
        validation_alias="PLAN_METRICS_HISTORY_LIMIT",
    )
    plan_metrics_latency_limit: int = Field(
        default=500,
        validation_alias="PLAN_METRICS_LATENCY_LIMIT",
    )
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

    jwt_secret: str = Field(
        default="change_me",
        validation_alias=AliasChoices("JWT_SECRET", "SECRET_KEY"),
    )
    jwt_alg: str = "HS256"
    jwt_expire_min: int = Field(
        default=60,
        validation_alias=AliasChoices(
            "JWT_EXPIRE_MIN",
            "ACCESS_TOKEN_EXPIRE_MINUTES",
        ),
    )
    log_level: str = "INFO"
    log_directory: str = "logs"
    log_max_bytes: int = 2 * 1024 * 1024
    log_backup_count: int = 5
    admin_api_token: str | None = None
    admin_allowed_ips: list[str] | str | None = Field(default=None)
    admin_sql_console_enabled: bool = Field(
        default=False,
        validation_alias="ADMIN_SQL_CONSOLE_ENABLED",
    )
    admin_sql_console_timeout_ms: int = Field(
        default=1500,
        validation_alias="ADMIN_SQL_CONSOLE_TIMEOUT_MS",
    )
    admin_sql_console_max_rows: int = Field(
        default=100,
        validation_alias="ADMIN_SQL_CONSOLE_MAX_ROWS",
    )

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
