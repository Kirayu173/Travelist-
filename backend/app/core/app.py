from app.api import admin, health, trips
from app.core.settings import settings
from app.utils.metrics import APIMetricsMiddleware
from fastapi import FastAPI


def create_app() -> FastAPI:
    """Application factory registering routers, middleware, and config."""

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
    )

    application.add_middleware(APIMetricsMiddleware)
    application.include_router(health.router)
    application.include_router(trips.router)
    application.include_router(admin.router, prefix="/admin", tags=["admin"])
    return application
