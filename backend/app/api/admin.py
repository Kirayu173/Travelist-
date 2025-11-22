from __future__ import annotations

# ruff: noqa: B008
from datetime import datetime, timezone

from app.admin import AdminService, get_admin_service, templates
from app.admin.auth import AdminAuthError, verify_admin_access
from app.admin.schemas import ApiTestRequest
from app.core.db import get_db
from app.core.settings import settings
from app.models.ai_schemas import PromptUpdatePayload
from app.utils.responses import error_response, success_response
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

router = APIRouter()


async def admin_auth_exception_handler(
    request: Request,
    exc: AdminAuthError,
) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content=error_response(exc.message, code=2001),
    )


@router.get(
    "/ping",
    summary="Admin 心跳",
    description="返回当前版本与服务器时间，可作为监控探活接口。",
)
def admin_ping() -> dict:
    payload = {
        "version": settings.app_version,
        "time": datetime.now(tz=timezone.utc).isoformat(),
    }
    return success_response(payload)


@router.get(
    "/dashboard",
    response_class=HTMLResponse,
    summary="管理主界面",
)
async def admin_dashboard(
    request: Request,
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> HTMLResponse:
    context = await admin_service.get_dashboard_context(request.app)
    context["request"] = request
    # --- Fix: 注入 settings，供 base.html 使用 ---
    context["settings"] = settings
    return templates.TemplateResponse("dashboard.html", context)


# --- Integrated Workbench Routes (Docs & DB) ---


@router.get("/api-docs", response_class=HTMLResponse, summary="API 文档 (Integrated)")
async def admin_api_docs_page(request: Request):
    """Render the integrated API Docs page (Swagger UI)."""
    return templates.TemplateResponse(
        request,
        "api_docs.html",
        {"request": request, "settings": settings},
    )


@router.get("/api/routes", summary="列出 API 路由")
async def admin_api_routes(
    request: Request,
    admin_service: AdminService = Depends(get_admin_service),
    _: None = Depends(verify_admin_access),
) -> dict:
    routes = admin_service.get_api_routes(request.app)
    return success_response({"routes": routes})


@router.get("/api/schemas", summary="列出 API Schemas")
async def admin_api_schemas(
    request: Request,
    admin_service: AdminService = Depends(get_admin_service),
    _: None = Depends(verify_admin_access),
) -> dict:
    schemas = admin_service.get_api_schemas(request.app)
    return success_response(schemas)


@router.get("/db/schema", summary="数据库结构概览")
async def admin_db_schema(
    request: Request,
    view: int | None = Query(default=None),
    admin_service: AdminService = Depends(get_admin_service),
) -> Response:
    # HTML 视图禁用缓存，确保最新结构
    data = await admin_service.get_db_schema_overview(use_cache=not bool(view))
    if view:
        tables_dict = data.get("tables", {}) or {}
        tables = [{"name": name, **details} for name, details in tables_dict.items()]
        return templates.TemplateResponse(
            request,
            "db_schema.html",
            {"request": request, "settings": settings, "tables": tables},
        )
    return success_response(data)


@router.post("/api/sql_test", summary="SQL 调试 (Restricted)")
def run_sql_test(
    payload: dict[str, str], request: Request, db: Session = Depends(get_db)
):
    """
    Execute a raw SQL query for debugging (RESTRICTED).
    Only allows SELECT queries.
    """
    query = payload.get("query", "").strip()
    if not query:
        return success_response({"error": "Empty query"})

    if not query.lower().startswith("select"):
        raise HTTPException(400, "Only SELECT queries are allowed in this console.")

    try:
        # Execute synchronously
        result = db.execute(text(query))
        keys = list(result.keys())
        rows = result.fetchall()

        # Convert rows to dicts
        data = [dict(zip(keys, row, strict=False)) for row in rows]

        return success_response(
            {
                "columns": keys,
                "rows": data[:100],  # Limit to 100 rows
                "count": len(data),
            }
        )
    except Exception as e:
        return success_response({"error": str(e)})


# --- Existing Admin Service Routes ---


@router.get("/checks")
async def admin_checks(
    admin_service: AdminService = Depends(get_admin_service),
) -> dict:
    checks = await admin_service.list_data_checks()
    return success_response(checks)


@router.get("/db/status")
async def admin_db_status(
    admin_service: AdminService = Depends(get_admin_service),
) -> dict:
    status = await admin_service.get_db_status()
    return success_response(status)


@router.get("/redis/status")
async def admin_redis_status(
    admin_service: AdminService = Depends(get_admin_service),
) -> dict:
    status = await admin_service.get_redis_status()
    return success_response(status)


@router.get("/db/health")
async def admin_db_health(
    admin_service: AdminService = Depends(get_admin_service),
) -> dict:
    status = await admin_service.get_db_health()
    return success_response(status)


@router.get("/trips/summary")
async def admin_trip_summary(
    admin_service: AdminService = Depends(get_admin_service),
) -> dict:
    summary = await admin_service.get_trip_summary()
    return success_response(summary)


@router.get("/api/summary")
async def admin_api_summary(
    window: int | None = Query(default=None, ge=1),
    admin_service: AdminService = Depends(get_admin_service),
) -> dict:
    summary = await admin_service.get_api_summary(window_seconds=window)
    return success_response(summary)


@router.get("/api/testcases")
async def admin_api_testcases(
    admin_service: AdminService = Depends(get_admin_service),
    _: None = Depends(verify_admin_access),
) -> dict:
    testcases = [case.model_dump() for case in admin_service.get_predefined_testcases()]
    return success_response(testcases)


@router.post("/api/test")
async def admin_api_test(
    payload: ApiTestRequest,
    request: Request,
    admin_service: AdminService = Depends(get_admin_service),
    _: None = Depends(verify_admin_access),
) -> dict:
    try:
        result = await admin_service.run_api_test(
            payload, request.app, str(request.base_url)
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400, content=error_response(str(exc), code=14020)
        )
    return success_response(result)


@router.get("/ai/summary")
def admin_ai_summary_data(
    admin_service: AdminService = Depends(get_admin_service),
    _: None = Depends(verify_admin_access),
) -> dict:
    summary = admin_service.get_ai_summary()
    return success_response(summary)


@router.get("/chat/summary")
def admin_chat_summary_data(
    admin_service: AdminService = Depends(get_admin_service),
    _: None = Depends(verify_admin_access),
) -> dict:
    summary = admin_service.get_chat_summary()
    return success_response(summary)


@router.get("/api/prompts")
async def admin_prompt_list(
    admin_service: AdminService = Depends(get_admin_service),
    _: None = Depends(verify_admin_access),
):
    prompts = admin_service.list_prompts()
    return success_response([item.model_dump(mode="json") for item in prompts])


@router.get("/api/prompts/{key}")
async def admin_prompt_detail(
    key: str,
    admin_service: AdminService = Depends(get_admin_service),
    _: None = Depends(verify_admin_access),
):
    try:
        prompt = admin_service.get_prompt_detail(key)
    except KeyError:
        return JSONResponse(
            status_code=404, content=error_response("Prompt 不存在", code=24004)
        )
    return success_response(prompt.model_dump(mode="json"))


@router.put("/api/prompts/{key}")
async def admin_prompt_update(
    key: str,
    payload: PromptUpdatePayload,
    admin_service: AdminService = Depends(get_admin_service),
    _: None = Depends(verify_admin_access),
):
    updated = admin_service.update_prompt(key, payload)
    return success_response(updated.model_dump(mode="json"))


@router.post("/api/prompts/{key}/reset")
async def admin_prompt_reset(
    key: str,
    admin_service: AdminService = Depends(get_admin_service),
    _: None = Depends(verify_admin_access),
):
    prompt = admin_service.reset_prompt(key)
    return success_response(prompt.model_dump(mode="json"))


@router.get("/ai/console", response_class=HTMLResponse)
async def admin_ai_console(
    request: Request,
    admin_service: AdminService = Depends(get_admin_service),
    _: None = Depends(verify_admin_access),
) -> HTMLResponse:
    context = admin_service.get_ai_console_context()
    context["request"] = request
    # --- Fix: 注入 settings，供 base.html 使用 ---
    context["settings"] = settings

    response = templates.TemplateResponse(request, "ai_console.html", context)
    token = request.query_params.get("token")
    if token:
        response.set_cookie("admin_token", token, httponly=True, samesite="lax")
    return response


@router.get("/ai/prompts", response_class=HTMLResponse)
async def admin_ai_prompts(
    request: Request,
    admin_service: AdminService = Depends(get_admin_service),
    _: None = Depends(verify_admin_access),
) -> HTMLResponse:
    context = {
        "request": request,
        "settings": settings,
        "prompts": [p.model_dump(mode="json") for p in admin_service.list_prompts()],
    }
    response = templates.TemplateResponse(request, "ai_prompts.html", context)
    token = request.query_params.get("token")
    if token:
        response.set_cookie("admin_token", token, httponly=True, samesite="lax")
    return response


@router.get("/health")
async def admin_health(
    admin_service: AdminService = Depends(get_admin_service),
) -> dict:
    health = await admin_service.get_health_summary()
    return success_response(health)


@router.get("/db/stats")
async def admin_db_stats(
    admin_service: AdminService = Depends(get_admin_service),
) -> dict:
    stats = await admin_service.get_db_stats()
    return success_response(stats)
