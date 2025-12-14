from app.admin.auth import AdminAuthError
from app.api import admin, ai, health, poi, trips
from app.core.logging import setup_logging
from app.core.settings import settings
from app.services.plan_task_worker import get_plan_task_worker
from app.utils.metrics import APIMetricsMiddleware
from fastapi import FastAPI


def create_app() -> FastAPI:
    """Application factory registering routers, middleware, and config."""

    setup_logging()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
    )

    application.add_middleware(APIMetricsMiddleware)
    application.include_router(health.router)
    application.include_router(trips.router)
    application.include_router(poi.router)
    application.include_router(ai.router)
    application.include_router(admin.router, prefix="/admin", tags=["admin"])
    application.add_exception_handler(
        AdminAuthError,
        admin.admin_auth_exception_handler,
    )

    @application.on_event("startup")
    async def _start_plan_task_worker() -> None:
        await get_plan_task_worker().start()

    @application.on_event("shutdown")
    async def _stop_plan_task_worker() -> None:
        await get_plan_task_worker().stop()

    return application
