from __future__ import annotations

import asyncio
import warnings
from collections import deque
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
from app.ai.metrics import get_ai_metrics
from app.ai.prompts import get_prompt_registry
from app.core.cache import cache_backend
from app.core.db import check_db_health, get_engine, session_scope
from app.core.logging import get_logger
from app.core.redis import check_redis_health
from app.core.settings import settings
from app.models.ai_schemas import PromptUpdatePayload
from app.models.orm import ChatSession, Message
from app.services.plan_metrics import get_plan_metrics
from app.services.poi_service import get_poi_service
from app.utils.http_client import perform_internal_request
from app.utils.metrics import MetricsRegistry, get_metrics_registry
from fastapi import FastAPI
from sqlalchemy import func, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import SAWarning, SQLAlchemyError

APP_START_TIME = datetime.now(timezone.utc)
ADMIN_DB_STATS_NS = "admin:db_stats"
ADMIN_TRIP_SUMMARY_NS = "admin:trip_summary"
ADMIN_DB_SCHEMA_NS = "admin:db_schema"
ADMIN_DB_STATS_TTL = 60
ADMIN_TRIP_SUMMARY_TTL = 60
ADMIN_DB_SCHEMA_TTL = 180
LOG_TAIL_LIMIT = 120
ERROR_TAIL_LIMIT = 60

PREDEFINED_TESTS: Sequence[ApiTestCase] = [
    ApiTestCase(
        name="trip_list",
        method="GET",
        path="/api/trips",
        description="行程列表（user_id=1）",
        query={"user_id": 1},
    ),
    ApiTestCase(
        name="trip_detail",
        method="GET",
        path="/api/trips/{trip_id}",
        description="行程详情（示例 ID）",
        path_params={"trip_id": 1},
    ),
    ApiTestCase(
        name="create_trip",
        method="POST",
        path="/api/trips",
        description="创建示例行程（需存在 user_id=1）",
        json_body={
            "user_id": 1,
            "title": "示例行程",
            "destination": "测试城市",
            "status": "draft",
            "day_cards": [],
        },
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
        self._ai_metrics = get_ai_metrics()
        self._start_time = APP_START_TIME
        self._project_root = Path(__file__).resolve().parents[3]
        self._logger = get_logger(__name__)
        self._log_dir = Path(settings.log_directory).resolve()
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._check_registry = DataCheckRegistry()
        self._register_builtin_checks()
        self._poi_service = get_poi_service()

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

    def get_recent_logs(
        self,
        *,
        limit: int = 80,
        errors_only: bool = False,
    ) -> list[dict[str, str]]:
        if limit <= 0:
            return []
        log_file = self._log_dir / ("errors.log" if errors_only else "app.log")
        if not log_file.exists():
            return []
        lines: deque[str] = deque(maxlen=limit)
        try:
            with log_file.open("r", encoding="utf-8", errors="ignore") as handle:
                for raw_line in handle:
                    stripped = raw_line.strip()
                    if stripped:
                        lines.append(stripped)
        except OSError as exc:
            self._logger.warning(
                "admin.log_read_failed",
                extra={"file": str(log_file), "error": str(exc)},
            )
            return []
        entries: list[dict[str, str]] = []
        for raw_line in reversed(list(lines)):
            parts = [segment.strip() for segment in raw_line.split("|", 3)]
            if len(parts) == 4:
                timestamp, level, logger_name, message = parts
            else:
                timestamp, level, logger_name, message = raw_line, "", "", ""
            entries.append(
                {
                    "timestamp": timestamp,
                    "level": level,
                    "logger": logger_name,
                    "message": message,
                }
            )
        return entries

    def _register_builtin_checks(self) -> None:
        self.register_check(self._build_db_check)
        self.register_check(self._build_redis_check)
        self.register_check(self._build_postgis_check)
        self.register_check(self._build_core_tables_check)
        self.register_check(self._build_migration_version_check)
        self.register_check(self._build_seed_data_check)
        self.register_check(self._build_alembic_check)

    async def get_dashboard_context(self, app: FastAPI) -> dict[str, Any]:
        basic_info = self.get_basic_info()
        current_time = datetime.now(timezone.utc)
        (
            health,
            data_checks,
            db_stats,
            trip_summary,
            db_schema,
        ) = await asyncio.gather(
            self.get_health_summary(),
            self.list_data_checks(),
            self.get_db_stats(),
            self.get_trip_summary(),
            self.get_db_schema_overview(),
        )
        api_summary = await self.get_api_summary()
        ai_summary = self.get_ai_summary()
        api_routes = self.get_api_routes(app)
        api_components = self.get_api_schemas(app)
        recent_logs = self.get_recent_logs(limit=LOG_TAIL_LIMIT)
        recent_errors = self.get_recent_logs(limit=ERROR_TAIL_LIMIT, errors_only=True)
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
            "ai_summary": ai_summary,
            "api_routes": api_routes,
            "api_components": api_components,
            "trip_summary": trip_summary,
            "db_schema": db_schema,
            "recent_logs": recent_logs,
            "recent_errors": recent_errors,
            "log_directory": str(self._log_dir),
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

    def get_ai_summary(self) -> dict[str, Any]:
        return self._ai_metrics.snapshot()

    def get_plan_summary(self) -> dict[str, Any]:
        return get_plan_metrics().snapshot()

    def get_chat_summary(self) -> dict[str, Any]:
        today = datetime.now(timezone.utc).date()
        with session_scope() as session:
            sessions_total = session.query(func.count(ChatSession.id)).scalar() or 0
            sessions_today = (
                session.query(func.count(ChatSession.id))
                .filter(func.date(ChatSession.opened_at) == today)
                .scalar()
                or 0
            )
            messages_total = session.query(func.count(Message.id)).scalar() or 0
            user_messages = (
                session.query(func.count(Message.id))
                .filter(Message.role == "user")
                .scalar()
                or 0
            )
            intent_rows = (
                session.query(Message.intent, func.count(Message.intent))
                .filter(Message.intent.isnot(None))
                .group_by(Message.intent)
                .all()
            )
        avg_turns = round(user_messages / sessions_total, 2) if sessions_total else 0.0
        top_intents = [
            {"intent": intent or "unknown", "count": int(count or 0)}
            for intent, count in intent_rows
        ]
        return {
            "sessions_total": int(sessions_total),
            "sessions_today": int(sessions_today),
            "messages_total": int(messages_total),
            "avg_turns_per_session": avg_turns,
            "top_intents": top_intents,
        }

    def get_ai_console_context(self) -> dict[str, Any]:
        recent_sessions = self._list_recent_sessions()
        default_session = recent_sessions[0]["id"] if recent_sessions else None
        return {
            "summary": self.get_ai_summary(),
            "recent_sessions": recent_sessions,
            "default_payload": {
                "user_id": recent_sessions[0]["user_id"] if recent_sessions else 1,
                "trip_id": recent_sessions[0]["trip_id"] if recent_sessions else None,
                "session_id": default_session,
                "use_memory": True,
                "return_memory": True,
                "top_k_memory": settings.mem0_default_k,
            },
        }

    def list_prompts(self):
        registry = get_prompt_registry()
        return registry.list_prompts()

    def get_prompt_detail(self, key: str):
        registry = get_prompt_registry()
        return registry.get_prompt(key)

    def update_prompt(self, key: str, payload: PromptUpdatePayload):
        registry = get_prompt_registry()
        return registry.update_prompt(key, payload)

    def reset_prompt(self, key: str):
        registry = get_prompt_registry()
        return registry.reset_prompt(key)

    def _list_recent_sessions(self, limit: int = 6) -> list[dict[str, Any]]:
        with session_scope() as session:
            rows = (
                session.query(ChatSession)
                .order_by(ChatSession.opened_at.desc())
                .limit(limit)
                .all()
            )
        return [
            {
                "id": row.id,
                "user_id": row.user_id,
                "trip_id": row.trip_id,
                "opened_at": row.opened_at.isoformat(),
            }
            for row in rows
        ]

    def get_api_routes(self, app: FastAPI) -> list[dict[str, Any]]:
        schema = app.openapi()
        paths: dict[str, Any] = schema.get("paths", {})
        routes: list[dict[str, Any]] = []
        for path, operations in paths.items():
            if not path.startswith("/api/"):
                continue
            for method, spec in operations.items():
                method_upper = method.upper()
                if method_upper not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                    continue
                request_schema = self._extract_schema_name(
                    spec.get("requestBody", {})
                    .get("content", {})
                    .get("application/json", {})
                    .get("schema")
                )
                responses = spec.get("responses", {})
                response_schema = None
                for status_code in ("200", "201", "202"):
                    block = responses.get(status_code)
                    if not block:
                        continue
                    response_schema = self._extract_schema_name(
                        block.get("content", {})
                        .get("application/json", {})
                        .get("schema")
                    )
                    if response_schema:
                        break
                routes.append(
                    {
                        "path": path,
                        "method": method_upper,
                        "summary": spec.get("summary") or spec.get("operationId"),
                        "description": spec.get("description"),
                        "tags": spec.get("tags", []),
                        "parameters": spec.get("parameters", []),
                        "has_request_body": bool(request_schema),
                        "request_schema": request_schema,
                        "response_schema": response_schema,
                    }
                )
        routes.sort(
            key=lambda item: (
                item["tags"][0] if item["tags"] else "",
                item["path"],
                item["method"],
            )
        )
        return routes

    def get_api_schemas(self, app: FastAPI) -> dict[str, Any]:
        schema = app.openapi()
        components = schema.get("components", {})
        return {
            "schemas": components.get("schemas", {}),
            "parameters": components.get("parameters", {}),
        }

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

    async def get_poi_summary(self) -> dict[str, Any]:
        db_counts = await to_thread.run_sync(self._collect_poi_counts)
        metrics = self._poi_service.metrics_snapshot()
        return {
            "pois_total": db_counts.get("total") or 0,
            "pois_recent_7d": db_counts.get("recent_7d") or 0,
            "cache_hits": metrics.get("cache_hits", 0),
            "cache_misses": metrics.get("cache_misses", 0),
            "api_calls": metrics.get("api_calls", 0),
            "api_failures": metrics.get("api_failures", 0),
        }

    async def get_db_stats(self, use_cache: bool = True) -> dict[str, Any]:
        async def _loader() -> dict[str, Any]:
            try:
                tables = await self._collect_table_counts()
            except SQLAlchemyError as exc:
                return {"tables": {}, "error": self._format_db_error(exc)}
            return {
                "tables": tables,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        if not use_cache:
            return await _loader()

        return await cache_backend.remember_async(
            ADMIN_DB_STATS_NS,
            "default",
            ADMIN_DB_STATS_TTL,
            _loader,
        )

    async def get_trip_summary(self, use_cache: bool = True) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            engine = get_engine()
            with engine.connect() as connection:
                totals = (
                    connection.execute(
                        text(
                            "SELECT "
                            "(SELECT COUNT(*) FROM trips) AS total_trips, "
                            "(SELECT COUNT(*) FROM day_cards) AS total_day_cards, "
                            "(SELECT COUNT(*) FROM sub_trips) AS total_sub_trips"
                        )
                    )
                    .mappings()
                    .one()
                )
                summary = {
                    "total_trips": int(totals["total_trips"]),
                    "total_day_cards": int(totals["total_day_cards"]),
                    "total_sub_trips": int(totals["total_sub_trips"]),
                }
                recent_rows = (
                    connection.execute(
                        text(
                            "SELECT t.id AS trip_id, t.title, t.updated_at, "
                            "COUNT(DISTINCT dc.id) AS day_count, "
                            "COUNT(st.id) AS sub_trip_count "
                            "FROM trips t "
                            "LEFT JOIN day_cards dc ON dc.trip_id = t.id "
                            "LEFT JOIN sub_trips st ON st.day_card_id = dc.id "
                            "GROUP BY t.id "
                            "ORDER BY t.updated_at DESC "
                            "LIMIT 10"
                        )
                    )
                    .mappings()
                    .all()
                )
                summary["recent_trips"] = [
                    {
                        "trip_id": int(row["trip_id"]),
                        "title": row["title"],
                        "updated_at": _format_iso(row["updated_at"]),
                        "day_count": int(row["day_count"]),
                        "sub_trip_count": int(row["sub_trip_count"]),
                    }
                    for row in recent_rows
                ]
                return summary

        async def _loader() -> dict[str, Any]:
            try:
                summary = await to_thread.run_sync(_run)
            except SQLAlchemyError as exc:
                return {
                    "error": self._format_db_error(exc),
                    "total_trips": None,
                    "total_day_cards": None,
                    "total_sub_trips": None,
                    "recent_trips": [],
                    "avg_sub_trips_per_day": None,
                }
            total_day_cards = summary.get("total_day_cards") or 0
            total_sub_trips = summary.get("total_sub_trips") or 0
            avg = (
                round(total_sub_trips / total_day_cards, 2) if total_day_cards else 0.0
            )
            summary["avg_sub_trips_per_day"] = avg
            return summary

        if not use_cache:
            return await _loader()

        return await cache_backend.remember_async(
            ADMIN_TRIP_SUMMARY_NS,
            "default",
            ADMIN_TRIP_SUMMARY_TTL,
            _loader,
        )

    async def get_redis_status(self) -> dict[str, Any]:
        return await check_redis_health()

    async def run_api_test(
        self,
        payload: ApiTestRequest,
        app: FastAPI,
        base_url: str,
    ) -> ApiTestResult:
        api_path = self._prepare_api_path(payload.path, payload.path_params)
        result = await perform_internal_request(
            app=app,
            base_url=base_url,
            method=payload.method,
            path=api_path,
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

    async def get_db_schema_overview(
        self,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            engine = get_engine()
            inspector = inspect(engine)
            tables: dict[str, Any] = {}
            for name in sorted(inspector.get_table_names()):
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message=r"Did not recognize type .* of column .*",
                        category=SAWarning,
                    )
                    columns = inspector.get_columns(name)

                pk = inspector.get_pk_constraint(name)
                pk_cols = set(pk.get("constrained_columns", []) if pk else [])
                fks = inspector.get_foreign_keys(name)
                indexes = inspector.get_indexes(name)
                tables[name] = {
                    "columns": [
                        {
                            "name": column["name"],
                            "type": str(column["type"]),
                            "nullable": column.get("nullable", True),
                            "pk": column["name"] in pk_cols,
                            "default": (
                                str(column.get("default"))
                                if column.get("default") is not None
                                else None
                            ),
                        }
                        for column in columns
                    ],
                    "primary_key": pk.get("constrained_columns", []) if pk else [],
                    "foreign_keys": [
                        {
                            "constrained_columns": fk.get("constrained_columns", []),
                            "referred_table": fk.get("referred_table"),
                            "referred_columns": fk.get("referred_columns", []),
                        }
                        for fk in fks
                    ],
                    "indexes": [
                        {
                            "name": idx.get("name"),
                            "column_names": idx.get("column_names"),
                            "unique": bool(idx.get("unique")),
                        }
                        for idx in indexes
                    ],
                }
            return {"tables": tables}

        async def _loader() -> dict[str, Any]:
            try:
                return await to_thread.run_sync(_run)
            except SQLAlchemyError as exc:
                return {"tables": {}, "error": self._format_db_error(exc)}

        if not use_cache:
            return await _loader()

        return await cache_backend.remember_async(
            ADMIN_DB_SCHEMA_NS,
            "default",
            ADMIN_DB_SCHEMA_TTL,
            _loader,
        )

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
                    except (
                        SQLAlchemyError
                    ) as exc:  # pragma: no cover - dialect specific
                        stats[table] = {
                            "row_count": None,
                            "error": self._format_db_error(exc),
                        }
                    else:
                        stats[table] = {"row_count": int(count)}
            return stats

        return await to_thread.run_sync(_run)

    def _extract_schema_name(self, schema: dict[str, Any] | None) -> str | None:
        if not schema:
            return None
        ref = schema.get("$ref")
        if ref:
            return ref.split("/")[-1]
        if "items" in schema:
            nested = self._extract_schema_name(schema.get("items"))
            return f"{nested}[]" if nested else "array"
        schema_type = schema.get("type")
        if schema_type:
            return schema_type
        return None

    def _collect_poi_counts(self) -> dict[str, int]:
        engine = get_engine()
        try:
            with engine.connect() as connection:
                totals = (
                    connection.execute(
                        text(
                            "SELECT "
                            "(SELECT COUNT(*) FROM pois) AS total, "
                            "(SELECT COUNT(*) FROM pois WHERE created_at >= NOW() - "
                            "INTERVAL '7 days') AS recent_7d"
                        )
                    )
                    .mappings()
                    .one()
                )
                return {
                    "total": int(totals.get("total") or 0),
                    "recent_7d": int(totals.get("recent_7d") or 0),
                }
        except SQLAlchemyError as exc:  # pragma: no cover - defensive
            self._logger.warning(
                "poi.count_failed",
                extra={"error": self._format_db_error(exc)},
            )
            return {"total": 0, "recent_7d": 0}

    def _prepare_api_path(
        self,
        path: str,
        path_params: dict[str, Any] | None,
    ) -> str:
        normalized = path if path.startswith("/") else f"/{path}"
        if path_params:
            for key, value in path_params.items():
                placeholder = "{" + key + "}"
                normalized = normalized.replace(placeholder, str(value))
        if "{" in normalized or "}" in normalized:
            msg = "存在未替换的路径参数"
            raise ValueError(msg)
        if not normalized.startswith("/api/"):
            msg = "仅允许在此处调用 /api/* 接口"
            raise ValueError(msg)
        return normalized

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
        stmt = text(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis')"
        )
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


def _format_iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # pragma: no cover - defensive
            return str(value)
    return str(value)


_admin_service: AdminService | None = None


def get_admin_service() -> AdminService:
    global _admin_service
    if _admin_service is None:
        _admin_service = AdminService()
    return _admin_service
