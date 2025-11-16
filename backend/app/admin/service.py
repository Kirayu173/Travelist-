from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from anyio import to_thread
from app.admin.checks import CheckCallable, DataCheckRegistry
from app.admin.schemas import (
    ApiTestCase,
    ApiTestRequest,
    ApiTestResult,
    DataCheckResult,
)
from app.core.db import check_db_health, get_engine
from app.core.redis import check_redis_health
from app.core.settings import settings
from app.utils.http_client import perform_internal_request
from app.utils.metrics import MetricsRegistry, get_metrics_registry
from fastapi import FastAPI
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import SQLAlchemyError

APP_START_TIME = datetime.now(timezone.utc)

PREDEFINED_TESTS: Sequence[ApiTestCase] = [
    ApiTestCase(
        name="healthz",
        method="GET",
        path="/healthz",
        description="基础健康检查",
    ),
    ApiTestCase(
        name="admin_ping",
        method="GET",
        path="/admin/ping",
        description="Admin Ping",
    ),
    ApiTestCase(
        name="admin_api_summary",
        method="GET",
        path="/admin/api/summary",
        description="API 统计摘要",
    ),
]

CORE_TABLES: tuple[str, ...] = (
    "users",
    "trips",
    "day_cards",
    "sub_trips",
    "pois",
    "favorites",
)


class AdminService:
    """Aggregate monitoring, health, and diagnostic utilities for admin endpoints."""

    def __init__(self, metrics_registry: MetricsRegistry | None = None) -> None:
        self._metrics_registry = metrics_registry or get_metrics_registry()
        self._start_time = APP_START_TIME
        self._project_root = Path(__file__).resolve().parents[3]
        self._check_registry = DataCheckRegistry()
        self._register_builtin_checks()

    def get_basic_info(self) -> dict[str, Any]:
        return {
            "app_name": settings.app_name,
            "version": settings.app_version,
            "env": settings.app_env,
            "start_time": self._start_time,
        }

    def get_predefined_testcases(self) -> Sequence[ApiTestCase]:
        return PREDEFINED_TESTS

    def register_check(self, check: CheckCallable) -> None:
        """Allow later stages to plug in custom data checks."""

        self._check_registry.register(check)

    def _register_builtin_checks(self) -> None:
        self.register_check(self._build_db_check)
        self.register_check(self._build_redis_check)
        self.register_check(self._build_postgis_check)
        self.register_check(self._build_core_tables_check)
        self.register_check(self._build_migration_version_check)
        self.register_check(self._build_seed_data_check)
        self.register_check(self._build_alembic_check)

    async def get_dashboard_context(self) -> dict[str, Any]:
        basic_info = self.get_basic_info()
        current_time = datetime.now(timezone.utc)
        health, data_checks, db_stats = await asyncio.gather(
            self.get_health_summary(),
            self.list_data_checks(),
            self.get_db_stats(),
        )
        api_summary = await self.get_api_summary()
        db_health = health.get("db") or {
            "status": "unknown",
            "engine_url": self._redact_db_url(settings.database_url),
            "latency_ms": None,
            "error": None,
        }
        return {
            "basic_info": basic_info,
            "current_time": current_time,
            "health": health,
            "db_health": db_health,
            "db_stats": db_stats,
            "api_summary": api_summary,
            "checks": [check.model_dump(mode="json") for check in data_checks],
            "predefined_tests": [
                case.model_dump(mode="json") for case in self.get_predefined_testcases()
            ],
        }

    async def get_api_summary(
        self,
        window_seconds: int | None = None,
    ) -> dict[str, Any]:
        if window_seconds:
            return self._metrics_registry.snapshot_window(window_seconds)
        return self._metrics_registry.snapshot()

    async def get_health_summary(self) -> dict[str, Any]:
        db, redis_state = await asyncio.gather(
            self.get_db_health(),
            check_redis_health(),
        )
        return {"app": "ok", "db": db, "redis": redis_state}

    async def get_db_health(self) -> dict[str, Any]:
        status = await check_db_health()
        if status.get("error"):
            status["error"] = self._format_db_error(status["error"])
        status["engine_url"] = self._redact_db_url(settings.database_url)
        return status

    async def get_db_status(self) -> dict[str, Any]:
        return await self.get_db_health()

    async def get_db_stats(self) -> dict[str, Any]:
        try:
            tables = await self._collect_table_counts()
        except SQLAlchemyError as exc:
            return {"tables": {}, "error": self._format_db_error(exc)}
        return {
            "tables": tables,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def get_redis_status(self) -> dict[str, Any]:
        return await check_redis_health()

    async def run_api_test(
        self,
        payload: ApiTestRequest,
        app: FastAPI,
        base_url: str,
    ) -> ApiTestResult:
        result = await perform_internal_request(
            app=app,
            base_url=base_url,
            method=payload.method,
            path=payload.path,
            query=payload.query,
            headers=payload.headers,
            json_body=payload.json_body,
            timeout_ms=payload.timeout_ms,
        )
        return ApiTestResult(
            status_code=result.status_code,
            duration_ms=result.duration_ms,
            ok=result.ok,
            response_headers=result.response_headers,
            response_body_excerpt=result.response_body_excerpt,
            error=result.error,
        )

    async def list_data_checks(self) -> list[DataCheckResult]:
        return await self._check_registry.run_all()

    async def _collect_table_counts(self) -> dict[str, dict[str, Any]]:
        def _run() -> dict[str, dict[str, Any]]:
            engine = get_engine()
            stats: dict[str, dict[str, Any]] = {}
            with engine.connect() as connection:
                for table in CORE_TABLES:
                    try:
                        count = connection.execute(
                            text(f"SELECT COUNT(*) FROM {table}")
                        ).scalar_one()
                    except SQLAlchemyError as exc:  # pragma: no cover - dialect specific
                        stats[table] = {
                            "row_count": None,
                            "error": self._format_db_error(exc),
                        }
                    else:
                        stats[table] = {"row_count": int(count)}
            return stats

        return await to_thread.run_sync(_run)

    async def _run_db_callable(self, func: Callable[[Connection], Any]) -> Any:
        def _runner() -> Any:
            engine = get_engine()
            with engine.connect() as connection:
                return func(connection)

        return await to_thread.run_sync(_runner)

    async def _get_existing_tables(self) -> set[str]:
        def _run() -> set[str]:
            engine = get_engine()
            inspector = inspect(engine)
            return {name.lower() for name in inspector.get_table_names()}

        return await to_thread.run_sync(_run)

    async def _fetch_migration_version(self) -> tuple[bool, str | None]:
        def _run() -> tuple[bool, str | None]:
            engine = get_engine()
            inspector = inspect(engine)
            has_table = inspector.has_table("alembic_version")
            version: str | None = None
            if has_table:
                with engine.connect() as connection:
                    row = connection.execute(
                        text(
                            "SELECT version_num FROM alembic_version "
                            "ORDER BY version_num DESC LIMIT 1"
                        )
                    ).first()
                    if row:
                        version = row[0]
            return has_table, version

        return await to_thread.run_sync(_run)

    def _redact_db_url(self, raw_url: str) -> str:
        try:
            url = make_url(raw_url)
        except Exception:  # pragma: no cover - fallback for invalid URLs
            return raw_url
        return url.render_as_string(hide_password=True)

    def _format_db_error(self, error: Any) -> str:
        message = str(error)
        sensitive = settings.database_url
        if sensitive and sensitive in message:
            message = message.replace(sensitive, self._redact_db_url(sensitive))
        return message[:500]

    async def _build_db_check(self) -> DataCheckResult:
        status = await self.get_db_health()
        if status.get("status") == "ok":
            detail = f"数据库连接正常，延迟 {status.get('latency_ms', '-')} ms"
            level = "info"
            result_status = "pass"
            suggestion = None
        elif status.get("status") == "fail":
            detail = f"数据库连接失败: {status.get('error', '未知错误')}"
            level = "error"
            result_status = "fail"
            suggestion = "确认 DATABASE_URL 并检查数据库服务是否启动"
        else:
            detail = "无法确定数据库状态"
            level = "warn"
            result_status = "unknown"
            suggestion = "在数据库准备就绪后重新运行检查"

        return DataCheckResult(
            name="db_connectivity",
            level=level,
            status=result_status,
            detail=detail,
            suggestion=suggestion,
        )

    async def _build_redis_check(self) -> DataCheckResult:
        status = await check_redis_health()
        if status.get("status") == "ok":
            detail = f"Redis 连接正常，延迟 {status.get('latency_ms', '-')} ms"
            level = "info"
            result_status = "pass"
            suggestion = None
        elif status.get("status") == "fail":
            detail = f"Redis 连接失败: {status.get('error', '未知错误')}"
            level = "error"
            result_status = "fail"
            suggestion = "确认 REDIS_URL 并检查 Redis 服务是否运行"
        else:
            detail = "无法确定 Redis 状态"
            level = "warn"
            result_status = "unknown"
            suggestion = "在 Redis 可用后重新运行检查"

        return DataCheckResult(
            name="redis_connectivity",
            level=level,
            status=result_status,
            detail=detail,
            suggestion=suggestion,
        )


    async def _build_postgis_check(self) -> DataCheckResult:
        stmt = text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis')")
        try:
            enabled = await self._run_db_callable(
                lambda conn: bool(conn.execute(stmt).scalar())
            )
        except SQLAlchemyError as exc:  # pragma: no cover - depends on dialect
            return DataCheckResult(
                name="postgis_extension",
                level="warn",
                status="unknown",
                detail=f"无法确认 PostGIS 状态: {self._format_db_error(exc)}",
                suggestion="确认数据库为 PostgreSQL 并运行 `CREATE EXTENSION postgis;`",
            )

        if enabled:
            return DataCheckResult(
                name="postgis_extension",
                level="info",
                status="pass",
                detail="PostGIS 扩展已启用",
                suggestion=None,
            )
        return DataCheckResult(
            name="postgis_extension",
            level="error",
            status="fail",
            detail="PostGIS 扩展未启用",
            suggestion="在数据库中执行 `CREATE EXTENSION postgis;` 后重新运行检查",
        )

    async def _build_core_tables_check(self) -> DataCheckResult:
        try:
            tables = await self._get_existing_tables()
        except SQLAlchemyError as exc:
            return DataCheckResult(
                name="core_tables",
                level="warn",
                status="unknown",
                detail=f"无法读取数据表信息: {self._format_db_error(exc)}",
                suggestion="检查数据库连通性并确认迁移已执行",
            )

        missing = [name for name in CORE_TABLES if name.lower() not in tables]
        if not missing:
            return DataCheckResult(
                name="core_tables",
                level="info",
                status="pass",
                detail="核心业务表均已创建",
                suggestion=None,
            )
        missing_str = ", ".join(missing)
        return DataCheckResult(
            name="core_tables",
            level="error",
            status="fail",
            detail=f"缺少核心业务表：{missing_str}",
            suggestion="运行 Alembic 迁移（`alembic upgrade head`）以创建缺失表",
        )

    async def _build_migration_version_check(self) -> DataCheckResult:
        try:
            has_table, version = await self._fetch_migration_version()
        except SQLAlchemyError as exc:
            return DataCheckResult(
                name="migration_version",
                level="warn",
                status="unknown",
                detail=f"无法读取迁移版本：{self._format_db_error(exc)}",
                suggestion="确认数据库可访问并执行迁移",
            )

        if not has_table:
            return DataCheckResult(
                name="migration_version",
                level="warn",
                status="unknown",
                detail="数据库中尚未创建 alembic_version 表",
                suggestion="运行 `alembic upgrade head` 初始化数据库结构",
            )
        if version:
            return DataCheckResult(
                name="migration_version",
                level="info",
                status="pass",
                detail=f"当前 Alembic 版本：{version}",
                suggestion=None,
            )
        return DataCheckResult(
            name="migration_version",
            level="warn",
            status="fail",
            detail="alembic_version 表存在但没有版本记录",
            suggestion="执行一次迁移（`alembic upgrade head`）以写入版本号",
        )

    async def _build_seed_data_check(self) -> DataCheckResult:
        stats = await self.get_db_stats()
        tables = stats.get("tables", {})
        users_stats = tables.get("users") or {}
        row_count = users_stats.get("row_count")
        if row_count is None:
            detail = users_stats.get("error", "无法获取用户行数")
            return DataCheckResult(
                name="seed_data",
                level="warn",
                status="unknown",
                detail=str(detail),
                suggestion="确认数据库可访问后再次运行检查",
            )
        if row_count == 0:
            return DataCheckResult(
                name="seed_data",
                level="warn",
                status="fail",
                detail="当前没有任何用户数据，后续功能无法联调",
                suggestion="插入测试用户与行程样例数据后重试",
            )
        return DataCheckResult(
            name="seed_data",
            level="info",
            status="pass",
            detail=f"已存在 {row_count} 名用户，可用于后续测试",
            suggestion=None,
        )

    async def _build_alembic_check(self) -> DataCheckResult:
        alembic_ini = self._project_root / "alembic.ini"
        backend_migrations = self._project_root / "backend" / "migrations"
        root_migrations = self._project_root / "migrations"
        migrations_dir = (
            backend_migrations if backend_migrations.exists() else root_migrations
        )
        env_py = migrations_dir / "env.py"
        versions_dir = migrations_dir / "versions"

        if env_py.exists() and versions_dir.exists():
            level = "info"
            status = "pass"
            detail = "检测到 Alembic 迁移目录，配置完整"
            suggestion = None
        elif alembic_ini.exists() or migrations_dir.exists():
            level = "warn"
            status = "fail"
            detail = "发现 Alembic 部分配置，但缺少 env.py 或 versions 目录"
            suggestion = "执行 `alembic init` 或检查迁移目录结构"
        else:
            level = "warn"
            status = "unknown"
            detail = "没有发现 Alembic 配置，可能尚未初始化迁移"
            suggestion = "当需要数据库迁移时，请运行 `alembic init migrations`"

        return DataCheckResult(
            name="alembic_initialized",
            level=level,
            status=status,
            detail=detail,
            suggestion=suggestion,
        )


_admin_service: AdminService | None = None


def get_admin_service() -> AdminService:
    global _admin_service
    if _admin_service is None:
        _admin_service = AdminService()
    return _admin_service
