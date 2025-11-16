from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine.url import make_url

from app.core.db import dispose_engine, get_engine
from app.core.settings import settings
from backend.tests.utils.db import clone_url_with_database, drop_database, ensure_database


def test_alembic_upgrade_and_downgrade() -> None:
    """Alembic scripts should run cleanly against a fresh PostgreSQL database."""

    project_root = Path(__file__).resolve().parents[3]
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root / "backend" / "migrations"))

    original_url = settings.database_url
    base_url = make_url(original_url)
    admin_url = clone_url_with_database(base_url, "postgres")
    temp_db_name = f"{(base_url.database or 'travelist')}_migration_{uuid4().hex[:8]}"
    drop_database(admin_url, temp_db_name)
    ensure_database(admin_url, temp_db_name)
    temp_url = clone_url_with_database(base_url, temp_db_name)
    settings.database_url = temp_url.render_as_string(hide_password=False)
    dispose_engine()

    core_tables = {"users", "trips", "day_cards", "sub_trips", "pois", "favorites"}

    command.upgrade(cfg, "head")
    inspector = inspect(get_engine())
    tables = set(inspector.get_table_names())
    assert core_tables <= tables

    command.downgrade(cfg, "base")
    dispose_engine()
    inspector = inspect(get_engine())
    remaining = set(inspector.get_table_names())
    assert core_tables.isdisjoint(remaining)

    settings.database_url = original_url
    dispose_engine()
    drop_database(admin_url, temp_db_name)
