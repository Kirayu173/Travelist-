from __future__ import annotations

# ruff: noqa: E402
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"
for path in (PROJECT_ROOT, BACKEND_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pytest
from alembic import command
from alembic.config import Config
from app.ai.client import reset_ai_client
from app.core.app import create_app
from app.core.db import dispose_engine
from app.core.settings import settings
from app.services.plan_metrics import reset_plan_metrics
from app.utils.metrics import reset_metrics_registry
from fastapi.testclient import TestClient
from sqlalchemy.engine.url import make_url

from backend.tests.utils.db import (
    clone_url_with_database,
    drop_database,
    ensure_database,
)

FAST_DB_MODE = os.environ.get("PYTEST_FAST_DB") == "1"


@pytest.fixture(autouse=True)
def configure_admin_and_ai() -> None:
    """Ensure admin guard and AiClient use deterministic test settings."""

    settings.admin_api_token = "test-admin-token"
    settings.admin_allowed_ips = []
    settings.ai_provider = "mock"
    settings.ai_model_chat = "mock-test"
    settings.mem0_mode = "disabled"
    settings.poi_provider = "mock"
    settings.poi_cache_enabled = False
    reset_ai_client()
    reset_plan_metrics()


@pytest.fixture(scope="session", autouse=True)
def configure_test_database() -> str:
    """Point settings.database_url to a dedicated PostgreSQL database for tests."""

    original_url = settings.database_url
    base_url = make_url(original_url)
    db_name = base_url.database or "travelist"
    test_db_name = f"{db_name}_test"
    admin_url = clone_url_with_database(base_url, "postgres")
    if FAST_DB_MODE:
        ensure_database(admin_url, test_db_name)
    else:
        drop_database(admin_url, test_db_name)
        ensure_database(admin_url, test_db_name)
    test_url = clone_url_with_database(base_url, test_db_name)
    settings.database_url = test_url.render_as_string(hide_password=False)
    dispose_engine()
    yield settings.database_url
    dispose_engine()
    if not FAST_DB_MODE:
        drop_database(admin_url, test_db_name)
    settings.database_url = original_url
    dispose_engine()


@pytest.fixture(scope="session", autouse=True)
def apply_migrations(configure_test_database: str) -> None:
    """Run Alembic migrations once for the PostgreSQL test database."""

    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option(
        "script_location", str(PROJECT_ROOT / "backend" / "migrations")
    )
    dispose_engine()
    command.upgrade(alembic_cfg, "head")
    yield
    dispose_engine()
    if not FAST_DB_MODE:
        command.downgrade(alembic_cfg, "base")


@pytest.fixture()
def client(apply_migrations: None) -> TestClient:
    reset_metrics_registry()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
