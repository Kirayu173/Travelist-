from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from app.admin.checks import CheckCallable, DataCheckRegistry
from app.admin.schemas import (
    ApiTestCase,
    ApiTestRequest,
    ApiTestResult,
    DataCheckResult,
)
from app.core.db import check_db_health
from app.core.redis import check_redis_health
from app.core.settings import settings
from app.utils.http_client import perform_internal_request
from app.utils.metrics import MetricsRegistry, get_metrics_registry
from fastapi import FastAPI

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
        self.register_check(self._build_alembic_check)

    async def get_dashboard_context(self) -> dict[str, Any]:
        basic_info = self.get_basic_info()
        current_time = datetime.now(timezone.utc)
        health, data_checks = await asyncio.gather(
            self.get_health_summary(),
            self.list_data_checks(),
        )
        api_summary = await self.get_api_summary()
        return {
            "basic_info": basic_info,
            "current_time": current_time,
            "health": health,
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
        db, redis_state = await asyncio.gather(check_db_health(), check_redis_health())
        return {"app": "ok", "db": db, "redis": redis_state}

    async def get_db_status(self) -> dict[str, Any]:
        return await check_db_health()

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

    async def _build_db_check(self) -> DataCheckResult:
        status = await check_db_health()
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
