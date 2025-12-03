from __future__ import annotations

from app.services.poi_service import PoiServiceError, get_poi_service
from app.utils.responses import error_response, success_response
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/poi", tags=["poi"])


def _service():
    return get_poi_service()


@router.get(
    "/around",
    summary="附近 POI 检索",
    description="按经纬度/类型/半径返回附近兴趣点，包含距离与来源标记。",
)
async def poi_around(
    lat: float = Query(..., description="纬度，-90~90"),
    lng: float = Query(..., description="经度，-180~180"),
    type: str | None = Query(default=None, description="POI 类型（food/sight/hotel/...）"),
    radius: int | None = Query(default=None, description="半径（米）"),
    limit: int | None = Query(default=20, ge=1, le=50, description="返回数量上限"),
):
    service = _service()
    try:
        results, meta = await service.get_poi_around(
            lat=lat, lng=lng, poi_type=type, radius=radius, limit=limit or 20
        )
    except PoiServiceError as exc:
        return JSONResponse(
            status_code=400, content=error_response(exc.message, code=14040)
        )
    return success_response({"items": results, "meta": meta})

