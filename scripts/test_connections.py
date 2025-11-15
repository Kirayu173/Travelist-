#!/usr/bin/env python3
"""
Simple connectivity tester for DATABASE_URL and REDIS_URL defined in .env.
Run with:  python scripts/test_connections.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict
from urllib.parse import urlparse

import psycopg
import redis


def load_env(path: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def normalize_pg_dsn(url: str) -> str:
    scheme, sep, rest = url.partition("://")
    if "+" in scheme:
        scheme = scheme.split("+", 1)[0]
    return f"{scheme}{sep}{rest}"


def test_postgres(url: str) -> None:
    parsed = urlparse(normalize_pg_dsn(url))
    print(f"[PostgreSQL] connecting to {parsed.hostname}:{parsed.port or 5432}/{parsed.path.lstrip('/')}")
    try:
        conn = psycopg.connect(
            dbname=parsed.path.lstrip("/"),
            user=parsed.username,
            password=parsed.password,
            host=parsed.hostname,
            port=parsed.port or 5432,
            connect_timeout=3,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            version = cur.fetchone()[0]
        conn.close()
        print(f"[PostgreSQL] OK -> {version}")
    except Exception as exc:
        print(f"[PostgreSQL] FAILED -> {exc}")


def test_redis(url: str) -> None:
    parsed = urlparse(url)
    print(f"[Redis] connecting to {parsed.hostname}:{parsed.port or 6379}/{parsed.path.lstrip('/') or '0'}")
    client = redis.Redis.from_url(url, socket_connect_timeout=3, socket_timeout=3)
    try:
        pong = client.ping()
        print(f"[Redis] OK -> PING response = {pong}")
    except Exception as exc:
        print(f"[Redis] FAILED -> {exc}")
    finally:
        client.close()


def main() -> None:
    env_path = Path("..", ".env") if Path(__file__).resolve().parent.name == "scripts" else Path(".env")
    if not env_path.exists():
        raise SystemExit(f"Cannot find {env_path}")
    env = load_env(env_path)
    db_url = env.get("DATABASE_URL")
    redis_url = env.get("REDIS_URL")

    if db_url:
        test_postgres(db_url)
    else:
        print("[PostgreSQL] DATABASE_URL not set.")

    if redis_url:
        test_redis(redis_url)
    else:
        print("[Redis] REDIS_URL not set.")


if __name__ == "__main__":
    main()
