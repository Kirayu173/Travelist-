from datetime import datetime, timezone

from app.admin import AdminService, get_admin_service, templates
from app.admin.schemas import ApiTestRequest
from app.core.settings import settings
from app.utils.responses import success_response
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/ping")
def admin_ping() -> dict:
    """Return quick admin heartbeat with version and server time."""

    payload = {
        "version": settings.app_version,
        "time": datetime.now(tz=timezone.utc).isoformat(),
    }
    return success_response(payload)


@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> HTMLResponse:
    """Render admin dashboard with runtime and monitoring data."""

    context = await admin_service.get_dashboard_context()
    context["request"] = request
    return templates.TemplateResponse("dashboard.html", context)


@router.get("/api/summary")
async def admin_api_summary(
    window: int | None = Query(default=None, ge=1, description="时间窗口（秒）"),
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    """Expose API usage metrics collected by the middleware."""

    summary = await admin_service.get_api_summary(window_seconds=window)
    return success_response(summary)


@router.get("/api/testcases")
async def admin_api_testcases(
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    """Return pre-defined smoke test cases for the dashboard."""

    testcases = [case.model_dump() for case in admin_service.get_predefined_testcases()]
    return success_response(testcases)


@router.post("/api/test")
async def admin_api_test(
    payload: ApiTestRequest,
    request: Request,
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    """Execute a HTTP call against the running FastAPI app."""

    result = await admin_service.run_api_test(
        payload,
        request.app,
        str(request.base_url),
    )
    return success_response(result)


@router.get("/health")
async def admin_health(
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    """Expose aggregated dependency health."""

    health = await admin_service.get_health_summary()
    return success_response(health)


@router.get("/db/health")
async def admin_db_health(
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    """Expose real database connectivity information."""

    status = await admin_service.get_db_health()
    return success_response(status)


@router.get("/db/stats")
async def admin_db_stats(
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    """Return row-count statistics for core tables."""

    stats = await admin_service.get_db_stats()
    return success_response(stats)


@router.get("/db/status")
async def admin_db_status(
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    """Deprecated alias kept for backward compatibility."""

    status = await admin_service.get_db_status()
    return success_response(status)


@router.get("/redis/status")
async def admin_redis_status(
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    status = await admin_service.get_redis_status()
    return success_response(status)


@router.get("/checks")
async def admin_data_checks(
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    checks = await admin_service.list_data_checks()
    payload = [check.model_dump(mode="json") for check in checks]
    return success_response(payload)
