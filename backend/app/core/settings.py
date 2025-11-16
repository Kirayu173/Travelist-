from functools import lru_cache

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

    gaode_key: str | None = None
    llm_provider: str | None = None
    llm_api_key: str | None = None

    jwt_secret: str = "change_me"
    jwt_alg: str = "HS256"
    jwt_expire_min: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
