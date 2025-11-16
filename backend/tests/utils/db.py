from __future__ import annotations

from sqlalchemy.engine import URL
from psycopg import connect, sql


def to_psycopg_url(url: URL) -> URL:
    driver = url.drivername.split("+", 1)[0]
    return url.set(drivername=driver)


def render_psycopg_dsn(url: URL) -> str:
    return to_psycopg_url(url).render_as_string(hide_password=False)


def ensure_database(admin_url: URL, database: str) -> None:
    dsn = render_psycopg_dsn(admin_url)
    with connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (database,),
            )
            if cur.fetchone():
                return
            cur.execute(
                sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(
                    sql.Identifier(database)
                )
            )


def drop_database(admin_url: URL, database: str) -> None:
    dsn = render_psycopg_dsn(admin_url)
    with connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database)
                )
            )


def clone_url_with_database(url: URL, database: str) -> URL:
    return url.set(database=database)


__all__ = [
    "clone_url_with_database",
    "drop_database",
    "ensure_database",
    "render_psycopg_dsn",
    "to_psycopg_url",
]
