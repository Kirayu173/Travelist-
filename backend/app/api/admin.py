from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.admin import AdminService, get_admin_service, templates
from app.admin.schemas import ApiTestRequest
from app.core.settings import settings
from app.utils.responses import error_response, success_response

router = APIRouter()


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
    description="渲染包含 API 指标、行程统计、在线文档/测试/数据库结构等模块的主界面。",
)
async def admin_dashboard(
    request: Request,
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> HTMLResponse:
    context = await admin_service.get_dashboard_context(request.app)
    context["request"] = request
    return templates.TemplateResponse("dashboard.html", context)


@router.get(
    "/api/summary",
    summary="API 调用统计",
    description="返回当前或指定时间窗口内的 API 请求次数与耗时指标。",
)
async def admin_api_summary(
    window: int | None = Query(default=None, ge=1, description="时间窗口（秒）"),
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    summary = await admin_service.get_api_summary(window_seconds=window)
    return success_response(summary)


@router.get(
    "/api/testcases",
    summary="预设 API 示例",
    description="返回仪表盘中展示的预设测试请求列表。",
)
async def admin_api_testcases(
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    testcases = [case.model_dump() for case in admin_service.get_predefined_testcases()]
    return success_response(testcases)


@router.post(
    "/api/test",
    summary="在线调用 API",
    description="在当前 FastAPI 应用内部执行 HTTP 请求，仅支持 /api/* 路径。",
)
async def admin_api_test(
    payload: ApiTestRequest,
    request: Request,
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
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


@router.get(
    "/api/routes",
    summary="API 元信息",
    description="遍历 FastAPI OpenAPI 文档，返回 /api/* 接口的描述、参数、Schema 等元数据。",
)
def admin_api_routes(
    request: Request,
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    routes = admin_service.get_api_routes(request.app)
    return success_response({"routes": routes})


@router.get(
    "/api/schemas",
    summary="API Schema 集合",
    description="返回 OpenAPI 中注册的所有 Pydantic Schema，便于了解字段结构。",
)
def admin_api_schemas(
    request: Request,
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    data = admin_service.get_api_schemas(request.app)
    return success_response(data)


@router.get(
    "/health",
    summary="依赖健康状况",
    description="返回应用、数据库、Redis 的综合健康信息。",
)
async def admin_health(
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    health = await admin_service.get_health_summary()
    return success_response(health)


@router.get(
    "/db/health",
    summary="数据库连通性",
    description="实时检测数据库连通状态与延迟。",
)
async def admin_db_health(
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    status = await admin_service.get_db_health()
    return success_response(status)


@router.get(
    "/db/stats",
    summary="核心数据行数",
    description="统计用户、行程、DayCard、子行程等核心表的行数。",
)
async def admin_db_stats(
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    stats = await admin_service.get_db_stats()
    return success_response(stats)


@router.get(
    "/db/schema",
    summary="数据库结构",
    description="返回（或渲染）核心表的字段、主键、外键、索引等结构信息。",
)
async def admin_db_schema(
    request: Request,
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
):
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


@router.get(
    "/db/status",
    summary="数据库状态（兼容）",
    description="与 /db/health 等价，保留旧地址方便兼容。",
)
async def admin_db_status(
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    status = await admin_service.get_db_status()
    return success_response(status)


@router.get(
    "/redis/status",
    summary="Redis 状态",
    description="返回 Redis 的连通情况与延迟。",
)
async def admin_redis_status(
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    status = await admin_service.get_redis_status()
    return success_response(status)


@router.get(
    "/checks",
    summary="数据检查",
    description="列出所有内置/注册的数据检查结果及建议。",
)
async def admin_data_checks(
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    checks = await admin_service.list_data_checks()
    payload = [check.model_dump(mode="json") for check in checks]
    return success_response(payload)


@router.get(
    "/trips/summary",
    summary="行程综述",
    description="返回行程、DayCard、子行程数量以及最近修改的行程。",
)
async def admin_trip_summary(
    admin_service: AdminService = Depends(get_admin_service),  # noqa: B008
) -> dict:
    summary = await admin_service.get_trip_summary()
    return success_response(summary)


@router.get(
    "/api-docs",
    response_class=HTMLResponse,
    summary="（保留）API 文档页",
    description="保留的独立 API 文档页面，主界面已嵌入可视化卡片。",
)
async def admin_api_docs(request: Request) -> HTMLResponse:
    context = {"request": request}
    return templates.TemplateResponse("api_docs.html", context)
