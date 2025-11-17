from datetime import datetime, timezone

from app.admin import AdminService, get_admin_service, templates
from app.admin.schemas import ApiTestRequest
from app.core.settings import settings
from app.utils.responses import error_response, success_response
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

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

    try:
        result = await admin_service.run_api_test(
            payload,
            request.app,
            str(request.base_url),
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content=error_response(str(exc), code=14020),
        )
    return success_response(result)


@router.get("/api/routes")
def admin_api_routes(
    request: Request,
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    routes = admin_service.get_api_routes(request.app)
    return success_response({"routes": routes})


@router.get("/api/schemas")
def admin_api_schemas(
    request: Request,
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    data = admin_service.get_api_schemas(request.app)
    return success_response(data)


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


@router.get("/db/schema")
async def admin_db_schema(
    request: Request,
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
):
    """Return table schema metadata or render structure page."""

    schema = await admin_service.get_db_schema_overview()
    accept = (request.headers.get("accept") or "").lower()
    wants_html = (
        "text/html" in accept
        and "application/json" not in accept
        or request.query_params.get("view") == "1"
    )
    if wants_html:
        context = {
            "request": request,
            "schema": schema,
        }
        return templates.TemplateResponse("db_schema.html", context)
    return success_response(schema)


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


@router.get("/trips/summary")
async def admin_trip_summary(
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    summary = await admin_service.get_trip_summary()
    return success_response(summary)


@router.get("/api-docs", response_class=HTMLResponse)
async def admin_api_docs(request: Request) -> HTMLResponse:
    context = {"request": request}
    return templates.TemplateResponse("api_docs.html", context)
