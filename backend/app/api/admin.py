from datetime import datetime, timezone
from typing import Any

from app.admin import AdminService, get_admin_service, templates
from app.admin.auth import AdminAuthError, verify_admin_access
from app.admin.schemas import ApiTestRequest
from app.core.settings import settings
from app.core.db import get_db
from app.utils.responses import error_response, success_response
from fastapi import APIRouter, Depends, Query, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text, inspect, Inspector

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
    return templates.TemplateResponse(request, "dashboard.html", context)


# --- Integrated Workbench Routes (Docs & DB) ---

@router.get("/api/routes", response_class=HTMLResponse, summary="API 文档 (Integrated)")
async def admin_api_docs_integrated(request: Request):
    """Render the integrated API Docs page (Swagger UI)."""
    return templates.TemplateResponse(
        "api_docs.html",
        {"request": request, "settings": settings}
    )


@router.get("/db/schema", response_class=HTMLResponse, summary="DB 工作台")
def admin_db_workbench(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Render the DB Workbench with schema visualization.
    Uses synchronous SQLAlchemy inspection.
    """
    try:
        inspector: Inspector = inspect(db.connection())
        table_names = inspector.get_table_names()
        tables_data = []
        for t_name in table_names:
            columns = inspector.get_columns(t_name)
            cols_display = [
                {
                    "name": c["name"],
                    "type": str(c["type"]),
                    "nullable": c.get("nullable", True),
                    "pk": c.get("primary_key", False)
                }
                for c in columns
            ]
            tables_data.append({"name": t_name, "columns": cols_display})
    except Exception as e:
        tables_data = []
        print(f"Error fetching schema: {e}")

    return templates.TemplateResponse(
        "db_schema.html",
        {
            "request": request,
            "settings": settings,
            "tables": tables_data
        }
    )


@router.post("/api/sql_test", summary="SQL 调试 (Restricted)")
def run_sql_test(
    payload: dict[str, str],
    request: Request,
    db: Session = Depends(get_db)
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
        data = [dict(zip(keys, row)) for row in rows]
        
        return success_response({
            "columns": keys,
            "rows": data[:100], # Limit to 100 rows
            "count": len(data)
        })
    except Exception as e:
        return success_response({"error": str(e)})


# --- Existing Admin Service Routes ---

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
        return JSONResponse(status_code=400, content=error_response(str(exc), code=14020))
    return success_response(result)


@router.get("/ai/summary")
def admin_ai_summary_data(
    admin_service: AdminService = Depends(get_admin_service),
    _: None = Depends(verify_admin_access),
) -> dict:
    summary = admin_service.get_ai_summary()
    return success_response(summary)


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


@router.get("/health")
async def admin_health(admin_service: AdminService = Depends(get_admin_service)) -> dict:
    health = await admin_service.get_health_summary()
    return success_response(health)


@router.get("/db/stats")
async def admin_db_stats(admin_service: AdminService = Depends(get_admin_service)) -> dict:
    stats = await admin_service.get_db_stats()
    return success_response(stats)