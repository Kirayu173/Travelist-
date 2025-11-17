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


@router.get("/trips")
def list_trips(
    user_id: int = Query(..., ge=1, description="所属用户 ID"),
    destination: str | None = Query(default=None, description="按目的地模糊过滤"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
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


@router.get("/trips/{trip_id}")
def get_trip_detail(trip_id: int) -> dict:
    service = _service()
    try:
        trip = service.get_trip(trip_id)
    except TripServiceError as exc:
        return _handle_service_error(exc)
    return success_response(trip.model_dump(mode="json"))


@router.post("/trips")
def create_trip(payload: TripCreate) -> dict:
    service = _service()
    try:
        trip = service.create_trip(payload)
    except TripServiceError as exc:
        return _handle_service_error(exc)
    return success_response({"trip_id": trip.id, "trip": trip.model_dump(mode="json")})


@router.put("/trips/{trip_id}")
def update_trip(trip_id: int, payload: TripUpdate) -> dict:
    service = _service()
    try:
        trip = service.update_trip(trip_id, payload)
    except TripServiceError as exc:
        return _handle_service_error(exc)
    return success_response(trip.model_dump(mode="json"))


@router.delete("/trips/{trip_id}")
def delete_trip(trip_id: int) -> dict:
    service = _service()
    try:
        service.delete_trip(trip_id)
    except TripServiceError as exc:
        return _handle_service_error(exc)
    return success_response({"deleted": True})


@router.post("/trips/{trip_id}/day_cards")
def create_day_card(trip_id: int, payload: DayCardCreate) -> dict:
    service = _service()
    try:
        day_card = service.create_day_card(trip_id, payload)
    except TripServiceError as exc:
        return _handle_service_error(exc)
    return success_response(day_card.model_dump(mode="json"))


@router.put("/day_cards/{day_card_id}")
def update_day_card(day_card_id: int, payload: DayCardUpdate) -> dict:
    service = _service()
    try:
        day_card = service.update_day_card(day_card_id, payload)
    except TripServiceError as exc:
        return _handle_service_error(exc)
    return success_response(day_card.model_dump(mode="json"))


@router.delete("/day_cards/{day_card_id}")
def delete_day_card(day_card_id: int) -> dict:
    service = _service()
    try:
        service.delete_day_card(day_card_id)
    except TripServiceError as exc:
        return _handle_service_error(exc)
    return success_response({"deleted": True})


@router.post("/day_cards/{day_card_id}/sub_trips")
def create_sub_trip(day_card_id: int, payload: SubTripCreate) -> dict:
    service = _service()
    try:
        sub_trip = service.create_sub_trip(day_card_id, payload)
    except TripServiceError as exc:
        return _handle_service_error(exc)
    return success_response(sub_trip.model_dump(mode="json"))


@router.put("/sub_trips/{sub_trip_id}")
def update_sub_trip(sub_trip_id: int, payload: SubTripUpdate) -> dict:
    service = _service()
    try:
        sub_trip = service.update_sub_trip(sub_trip_id, payload)
    except TripServiceError as exc:
        return _handle_service_error(exc)
    return success_response(sub_trip.model_dump(mode="json"))


@router.delete("/sub_trips/{sub_trip_id}")
def delete_sub_trip(sub_trip_id: int) -> dict:
    service = _service()
    try:
        service.delete_sub_trip(sub_trip_id)
    except TripServiceError as exc:
        return _handle_service_error(exc)
    return success_response({"deleted": True})


@router.post("/sub_trips/{sub_trip_id}/reorder")
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
