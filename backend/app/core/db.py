from __future__ import annotations

from contextlib import contextmanager
from time import monotonic, perf_counter
from typing import Any, Generator

from anyio import to_thread
from app.core.settings import settings
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_cached_db_status: dict[str, Any] | None = None
_cached_db_ts: float | None = None
HEALTH_CACHE_SECONDS = 5.0


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        connect_args: dict[str, Any] = {}
        if settings.database_url.startswith("postgresql"):
            connect_args["connect_timeout"] = 1
        _engine = create_engine(
            settings.database_url,
            connect_args=connect_args,
            pool_pre_ping=True,
            future=True,
        )
    return _engine


def _get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            future=True,
        )
    return _session_factory


def get_session() -> Session:
    """Return a new SQLAlchemy session bound to the shared engine."""

    factory = _get_session_factory()
    return factory()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Provide transactional scope for DB interactions."""

    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
        _engine = None
    _session_factory = None
    invalidate_db_health_cache()


def invalidate_db_health_cache() -> None:
    global _cached_db_status, _cached_db_ts
    _cached_db_status = None
    _cached_db_ts = None


async def check_db_health(use_cache: bool = True) -> dict[str, Any]:
    global _cached_db_status, _cached_db_ts

    if use_cache and _cached_db_status is not None and _cached_db_ts is not None:
        if monotonic() - _cached_db_ts < HEALTH_CACHE_SECONDS:
            return _cached_db_status

    def _run() -> dict[str, Any]:
        engine = get_engine()
        start = perf_counter()
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            latency = (perf_counter() - start) * 1000
            return {"status": "ok", "latency_ms": round(latency, 3), "error": None}
        except SQLAlchemyError as exc:
            return {"status": "fail", "error": str(exc)}
        except Exception as exc:
            return {"status": "fail", "error": str(exc)}

    result = await to_thread.run_sync(_run)
    if use_cache:
        _cached_db_status = result
        _cached_db_ts = monotonic()
    return result
