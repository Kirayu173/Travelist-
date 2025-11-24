from __future__ import annotations

from app.models.schemas import (
    DayCardCreate,
    DayCardUpdate,
    SubTripCreate,
    SubTripReorderPayload,
    SubTripSchema,
    SubTripUpdate,
    TripCreate,
    TripUpdate,
)
from app.services.trip_service import (
    ReorderResult,
    TripService,
    TripServiceError,
)
from app.utils.responses import error_response, success_response
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api", tags=["trips"])


def _service() -> TripService:
    return TripService()


def _handle_service_error(exc: TripServiceError) -> JSONResponse:
    payload = error_response(exc.message, code=exc.code)
    return JSONResponse(status_code=400, content=payload)


@router.get(
    "/trips",
    summary="行程列表",
    description="根据用户 ID 返回行程摘要，可选按目的地模糊筛选，并支持分页。",
)
def list_trips(
    user_id: int = Query(..., ge=1, description="所属用户 ID（必填）"),
    destination: str | None = Query(default=None, description="目的地模糊匹配"),
    limit: int = Query(default=20, ge=1, le=100, description="返回条数，默认 20"),
    offset: int = Query(default=0, ge=0, description="偏移量，用于分页"),
) -> dict:
    service = _service()
    summaries = service.list_trips(
        user_id=user_id,
        destination=destination,
        limit=limit,
        offset=offset,
    )
    data = [summary.model_dump(mode="json") for summary in summaries]
    return success_response(data)


@router.get(
    "/trips/{trip_id}",
    summary="行程详情",
    description="根据行程 ID 返回完整的行程信息，包含 DayCard 与子行程嵌套结构。",
)
def get_trip_detail(trip_id: int) -> dict:
    service = _service()
    try:
        trip = service.get_trip(trip_id)
    except TripServiceError as exc:
        return _handle_service_error(exc)
    return success_response(trip.model_dump(mode="json"))


@router.post(
    "/trips",
    summary="创建行程",
    description="创建新的行程，可同时附带 DayCard 与子行程的初始内容。",
)
def create_trip(payload: TripCreate) -> dict:
    service = _service()
    try:
        trip = service.create_trip(payload)
    except TripServiceError as exc:
        return _handle_service_error(exc)
    return success_response({"trip_id": trip.id, "trip": trip.model_dump(mode="json")})


@router.put(
    "/trips/{trip_id}",
    summary="更新行程",
    description="更新行程基础信息（标题、目的地、日期、状态等）。",
)
def update_trip(trip_id: int, payload: TripUpdate) -> dict:
    service = _service()
    try:
        trip = service.update_trip(trip_id, payload)
    except TripServiceError as exc:
        return _handle_service_error(exc)
    return success_response(trip.model_dump(mode="json"))


@router.delete(
    "/trips/{trip_id}",
    summary="删除行程",
    description="删除指定行程以及其下所有 DayCard、子行程。",
)
def delete_trip(trip_id: int) -> dict:
    service = _service()
    try:
        service.delete_trip(trip_id)
    except TripServiceError as exc:
        return _handle_service_error(exc)
    return success_response({"deleted": True})


@router.post(
    "/trips/{trip_id}/day_cards",
    summary="新增 DayCard",
    description="为指定行程追加一张 DayCard，可包含同日的子行程。",
)
def create_day_card(trip_id: int, payload: DayCardCreate) -> dict:
    service = _service()
    try:
        day_card = service.create_day_card(trip_id, payload)
    except TripServiceError as exc:
        return _handle_service_error(exc)
    return success_response(day_card.model_dump(mode="json"))


@router.put(
    "/day_cards/{day_card_id}",
    summary="更新 DayCard",
    description="修改 DayCard 的日期、备注或顺序索引。",
)
def update_day_card(day_card_id: int, payload: DayCardUpdate) -> dict:
    service = _service()
    try:
        day_card = service.update_day_card(day_card_id, payload)
    except TripServiceError as exc:
        return _handle_service_error(exc)
    return success_response(day_card.model_dump(mode="json"))


@router.delete(
    "/day_cards/{day_card_id}",
    summary="删除 DayCard",
    description="删除 DayCard 以及其中的所有子行程。",
)
def delete_day_card(day_card_id: int) -> dict:
    service = _service()
    try:
        service.delete_day_card(day_card_id)
    except TripServiceError as exc:
        return _handle_service_error(exc)
    return success_response({"deleted": True})


@router.post(
    "/day_cards/{day_card_id}/sub_trips",
    summary="新增子行程",
    description="在指定 DayCard 下新增子行程，支持在同一天内指定插入顺序。",
)
def create_sub_trip(day_card_id: int, payload: SubTripCreate) -> dict:
    service = _service()
    try:
        sub_trip = service.create_sub_trip(day_card_id, payload)
    except TripServiceError as exc:
        return _handle_service_error(exc)
    return success_response(sub_trip.model_dump(mode="json"))


@router.put(
    "/sub_trips/{sub_trip_id}",
    summary="更新子行程",
    description="调整子行程的活动内容、时间、顺序或扩展字段。",
)
def update_sub_trip(sub_trip_id: int, payload: SubTripUpdate) -> dict:
    service = _service()
    try:
        sub_trip = service.update_sub_trip(sub_trip_id, payload)
    except TripServiceError as exc:
        return _handle_service_error(exc)
    return success_response(sub_trip.model_dump(mode="json"))


@router.delete(
    "/sub_trips/{sub_trip_id}",
    summary="删除子行程",
    description="删除指定子行程记录。",
)
def delete_sub_trip(sub_trip_id: int) -> dict:
    service = _service()
    try:
        service.delete_sub_trip(sub_trip_id)
    except TripServiceError as exc:
        return _handle_service_error(exc)
    return success_response({"deleted": True})


@router.post(
    "/sub_trips/{sub_trip_id}/reorder",
    summary="子行程排序/跨日迁移",
    description="支持在同一天内调整子行程顺序，或跨 DayCard 移动到新的日期位置。",
)
def reorder_sub_trip(sub_trip_id: int, payload: SubTripReorderPayload) -> dict:
    service = _service()
    try:
        result = service.reorder_sub_trip(
            sub_trip_id,
            target_day_card_id=payload.day_card_id,
            order_index=payload.order_index,
        )
    except TripServiceError as exc:
        return _handle_service_error(exc)

    return success_response(_format_reorder_result(result))


def _format_reorder_result(result: ReorderResult) -> dict:
    def serialize_sub_trips(items: list) -> list[dict]:
        return [
            SubTripSchema.model_validate(item).model_dump(mode="json") for item in items
        ]

    same_day = result.source_day_card_id == result.target_day_card_id
    source_payload = serialize_sub_trips(result.source_sub_trips)
    target_payload = (
        source_payload if same_day else serialize_sub_trips(result.target_sub_trips)
    )
    return {
        "moved_id": result.moved_id,
        "source_day_card_id": result.source_day_card_id,
        "target_day_card_id": result.target_day_card_id,
        "source_sub_trips": source_payload,
        "target_sub_trips": target_payload,
    }
