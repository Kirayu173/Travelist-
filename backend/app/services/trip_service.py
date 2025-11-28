from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import sqlalchemy as sa
from app.core.cache import build_cache_key, cache_backend
from app.core.db import session_scope
from app.core.logging import get_logger
from app.models.orm import DayCard, SubTrip, Trip
from app.models.schemas import (
    DayCardCreate,
    DayCardSchema,
    DayCardUpdate,
    SubTripCreate,
    SubTripSchema,
    SubTripUpdate,
    TripCreate,
    TripSchema,
    TripSummarySchema,
    TripUpdate,
)
from app.repositories import DayCardRepository, SubTripRepository, TripRepository
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm import attributes as orm_attributes

TRIP_LIST_CACHE_NS = "trip:list"
TRIP_DETAIL_CACHE_NS = "trip:detail"
TRIP_LIST_TTL_SECONDS = 30
TRIP_DETAIL_TTL_SECONDS = 45


class TripServiceError(Exception):
    """Base class for business friendly errors surfaced to API consumers."""

    def __init__(self, message: str, code: int = 14000) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class ResourceNotFoundError(TripServiceError):
    pass


class TripValidationError(TripServiceError):
    pass


def _ensure_positive_limit(
    limit: int, *, default: int = 20, max_limit: int = 100
) -> int:
    if limit <= 0:
        return default
    return min(limit, max_limit)


@dataclass
class ReorderResult:
    moved_id: int
    source_day_card_id: int
    target_day_card_id: int
    source_sub_trips: list[SubTrip]
    target_sub_trips: list[SubTrip]


def _invalidate_trip_list_cache() -> None:
    cache_backend.invalidate(TRIP_LIST_CACHE_NS)


def _invalidate_trip_detail_cache(trip_id: int | None = None) -> None:
    if trip_id is None:
        cache_backend.invalidate(TRIP_DETAIL_CACHE_NS)
        return
    cache_backend.invalidate(TRIP_DETAIL_CACHE_NS, str(trip_id))


class TripServiceBase:
    """Shared helpers used by specialized Trip services."""

    def __init__(self) -> None:
        self.logger = get_logger(self.__class__.__name__)

    def _load_trip(self, session: Session, trip_id: int) -> Trip | None:
        repo = TripRepository(session)
        trip = repo.get_with_details(trip_id)
        if trip is None:
            return None
        trip.day_cards.sort(key=lambda card: (card.day_index or 0, card.id))
        for day_card in trip.day_cards:
            day_card.sub_trips.sort(key=lambda item: (item.order_index, item.id))
        return trip

    def _count_day_card_sub_trips(self, session: Session, day_card_id: int) -> int:
        return (
            session.query(sa.func.count(SubTrip.id))
            .filter(SubTrip.day_card_id == day_card_id)
            .scalar()
            or 0
        )

    def _load_day_card_sub_trips(
        self,
        session: Session,
        day_card_id: int,
    ) -> list[SubTrip]:
        items = (
            session.query(SubTrip)
            .options(selectinload(SubTrip.poi))
            .filter(SubTrip.day_card_id == day_card_id)
            .order_by(SubTrip.order_index, SubTrip.id)
            .all()
        )
        for sub_trip in items:
            self._hydrate_sub_trip(sub_trip)
        return items

    def _persist_sub_trips(
        self,
        session: Session,
        day_card: DayCard,
        payloads: Iterable[SubTripCreate],
    ) -> None:
        payload_list = list(payloads or [])
        sub_trip_repo = SubTripRepository(session)
        for position, subtrip_payload in enumerate(payload_list):
            order_index = (
                subtrip_payload.order_index
                if subtrip_payload.order_index is not None
                else position
            )
            sub_trip = self._build_sub_trip(
                subtrip_payload,
                day_card_id=day_card.id,
                order_index=order_index,
            )
            sub_trip_repo.add(sub_trip)

    def _build_day_card(
        self,
        trip: Trip,
        payload: DayCardCreate,
        *,
        fallback_index: int | None = None,
    ) -> DayCard:
        existing_indexes = {
            card.day_index for card in trip.day_cards if card.day_index is not None
        }
        if payload.day_index is not None:
            resolved_index = payload.day_index
        elif fallback_index is not None:
            resolved_index = fallback_index
        else:
            resolved_index = (max(existing_indexes) + 1) if existing_indexes else 0

        if resolved_index in existing_indexes:
            raise TripValidationError("day_index 已存在", code=14010)
        return DayCard(
            trip=trip,
            day_index=resolved_index,
            date=payload.date,
            note=payload.note,
        )

    def _build_sub_trip(
        self,
        payload: SubTripCreate,
        *,
        day_card_id: int,
        order_index: int,
    ) -> SubTrip:
        sub_trip = SubTrip(
            day_card_id=day_card_id,
            order_index=order_index,
            activity=payload.activity,
            poi_id=payload.poi_id,
            loc_name=payload.loc_name,
            transport=payload.transport,
            start_time=payload.start_time,
            end_time=payload.end_time,
            ext=dict(payload.ext or {}),
        )
        self._sync_coordinates(sub_trip, payload.lat, payload.lng)
        return sub_trip

    def _sync_coordinates(
        self,
        sub_trip: SubTrip,
        lat: float | None,
        lng: float | None,
    ) -> None:
        ext = dict(sub_trip.ext or {})
        if lat is not None and lng is not None:
            ext["lat"] = lat
            ext["lng"] = lng
            sub_trip.lat = lat
            sub_trip.lng = lng
        else:
            ext.pop("lat", None)
            ext.pop("lng", None)
            sub_trip.lat = None
            sub_trip.lng = None
        sub_trip.ext = ext

    def _reindex(self, session: Session, items: list[SubTrip]) -> None:
        temp_values: list[tuple[SubTrip, int]] = []
        base = len(items) + 1
        for idx, item in enumerate(items):
            temp_index = -(idx + base)
            temp_values.append((item, idx))
            session.execute(
                sa.update(SubTrip)
                .where(SubTrip.id == item.id)
                .values(order_index=temp_index)
            )
            orm_attributes.set_committed_value(item, "order_index", temp_index)
        for item, final_index in temp_values:
            session.execute(
                sa.update(SubTrip)
                .where(SubTrip.id == item.id)
                .values(order_index=final_index)
            )
            orm_attributes.set_committed_value(item, "order_index", final_index)

    def _hydrate_trip_coordinates(self, trip: Trip) -> None:
        for day_card in trip.day_cards:
            self._hydrate_day_card(day_card)

    def _hydrate_day_card(self, day_card: DayCard) -> None:
        for sub_trip in day_card.sub_trips:
            self._hydrate_sub_trip(sub_trip)

    def _hydrate_sub_trip(self, sub_trip: SubTrip) -> None:
        lat = None
        lng = None
        if isinstance(sub_trip.ext, dict):
            lat = sub_trip.ext.get("lat")
            lng = sub_trip.ext.get("lng")
        sub_trip.lat = lat
        sub_trip.lng = lng


class TripQueryService(TripServiceBase):
    def list_trips(
        self,
        *,
        user_id: int | None,
        destination: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[TripSummarySchema]:
        cache_key = build_cache_key(user_id or "all", destination or "*", limit, offset)

        def _loader() -> list[TripSummarySchema]:
            with session_scope() as session:
                repo = TripRepository(session)
                page_size = _ensure_positive_limit(limit)
                rows = repo.list_summaries(
                    user_id=user_id,
                    destination=destination,
                    limit=page_size,
                    offset=max(offset, 0),
                )
            summaries: list[TripSummarySchema] = []
            for trip, day_count, sub_trip_count in rows:
                summaries.append(
                    TripSummarySchema.model_validate(
                        {
                            "id": trip.id,
                            "user_id": trip.user_id,
                            "title": trip.title,
                            "destination": trip.destination,
                            "start_date": trip.start_date,
                            "end_date": trip.end_date,
                            "status": trip.status,
                            "day_count": int(day_count or 0),
                            "sub_trip_count": int(sub_trip_count or 0),
                            "updated_at": trip.updated_at,
                        }
                    )
                )
            return summaries

        return cache_backend.remember(
            TRIP_LIST_CACHE_NS,
            cache_key,
            TRIP_LIST_TTL_SECONDS,
            _loader,
        )

    def get_trip(self, trip_id: int) -> TripSchema:
        cache_key = str(trip_id)

        def _loader() -> TripSchema:
            with session_scope() as session:
                trip = self._load_trip(session, trip_id)
                if trip is None:
                    raise ResourceNotFoundError("行程不存在", code=14004)
                self._hydrate_trip_coordinates(trip)
                return TripSchema.model_validate(trip)

        return cache_backend.remember(
            TRIP_DETAIL_CACHE_NS,
            cache_key,
            TRIP_DETAIL_TTL_SECONDS,
            _loader,
        )


class TripCommandService(TripServiceBase):
    def create_trip(self, payload: TripCreate) -> TripSchema:
        with session_scope() as session:
            trip_repo = TripRepository(session)
            user = trip_repo.get_user(payload.user_id)
            if user is None:
                raise TripValidationError("用户不存在，无法创建行程", code=14003)
            trip = Trip(
                user_id=payload.user_id,
                title=payload.title,
                destination=payload.destination,
                start_date=payload.start_date,
                end_date=payload.end_date,
                status=payload.status,
                meta=payload.meta or {},
            )
            trip_repo.add(trip)

            for position, day_card_payload in enumerate(payload.day_cards or []):
                day_card = self._build_day_card(
                    trip, day_card_payload, fallback_index=position
                )
                session.add(day_card)
                session.flush()
                self._persist_sub_trips(session, day_card, day_card_payload.sub_trips)

            session.flush()
            session.refresh(trip)
            loaded = self._load_trip(session, trip.id)
            assert loaded is not None
            self._hydrate_trip_coordinates(loaded)
            schema = TripSchema.model_validate(loaded)
        _invalidate_trip_list_cache()
        _invalidate_trip_detail_cache(schema.id)
        self.logger.info("trip.created", extra={"trip_id": schema.id})
        return schema

    def update_trip(self, trip_id: int, payload: TripUpdate) -> TripSchema:
        with session_scope() as session:
            repo = TripRepository(session)
            trip = repo.get(trip_id)
            if trip is None:
                raise ResourceNotFoundError("行程不存在", code=14004)

            if payload.title is not None:
                trip.title = payload.title
            if payload.destination is not None:
                trip.destination = payload.destination
            if payload.start_date is not None:
                trip.start_date = payload.start_date
            if payload.end_date is not None:
                trip.end_date = payload.end_date
            if payload.status is not None:
                trip.status = payload.status
            if payload.meta is not None:
                trip.meta = payload.meta

            session.add(trip)
            session.flush()
            loaded = self._load_trip(session, trip_id)
            assert loaded is not None
            self._hydrate_trip_coordinates(loaded)
            schema = TripSchema.model_validate(loaded)
        _invalidate_trip_list_cache()
        _invalidate_trip_detail_cache(trip_id)
        self.logger.info("trip.updated", extra={"trip_id": trip_id})
        return schema

    def delete_trip(self, trip_id: int) -> None:
        with session_scope() as session:
            repo = TripRepository(session)
            deleted = repo.delete(trip_id)
            if not deleted:
                raise ResourceNotFoundError("行程不存在", code=14004)
        _invalidate_trip_list_cache()
        _invalidate_trip_detail_cache(trip_id)
        self.logger.info("trip.deleted", extra={"trip_id": trip_id})


class DayCardService(TripServiceBase):
    def create_day_card(self, trip_id: int, payload: DayCardCreate) -> DayCardSchema:
        with session_scope() as session:
            trip = session.get(Trip, trip_id)
            if trip is None:
                raise ResourceNotFoundError("行程不存在", code=14004)
            fallback = len(trip.day_cards)
            day_card = self._build_day_card(trip, payload, fallback_index=fallback)
            session.add(day_card)
            session.flush()
            self._persist_sub_trips(session, day_card, payload.sub_trips)
            session.refresh(day_card)
            self._hydrate_day_card(day_card)
            schema = DayCardSchema.model_validate(day_card)
            trip_id = day_card.trip_id
        _invalidate_trip_detail_cache(trip_id)
        _invalidate_trip_list_cache()
        self.logger.info(
            "day_card.created", extra={"trip_id": trip_id, "day_card_id": schema.id}
        )
        return schema

    def update_day_card(
        self, day_card_id: int, payload: DayCardUpdate
    ) -> DayCardSchema:
        with session_scope() as session:
            repo = DayCardRepository(session)
            day_card = repo.get(day_card_id)
            if day_card is None:
                raise ResourceNotFoundError("DayCard 不存在", code=14005)
            if payload.day_index is not None:
                day_card.day_index = payload.day_index
            if payload.date is not None:
                day_card.date = payload.date
            if payload.note is not None:
                day_card.note = payload.note

            session.add(day_card)
            session.flush()
            self._hydrate_day_card(day_card)
            schema = DayCardSchema.model_validate(day_card)
            trip_id = day_card.trip_id
        _invalidate_trip_detail_cache(trip_id)
        _invalidate_trip_list_cache()
        self.logger.info(
            "day_card.updated",
            extra={"trip_id": trip_id, "day_card_id": day_card_id},
        )
        return schema

    def delete_day_card(self, day_card_id: int) -> None:
        with session_scope() as session:
            repo = DayCardRepository(session)
            day_card = repo.get_plain(day_card_id)
            if day_card is None:
                raise ResourceNotFoundError("DayCard 不存在", code=14005)
            trip_id = day_card.trip_id
            repo.delete(day_card_id)
            session.flush()
        _invalidate_trip_detail_cache(trip_id)
        _invalidate_trip_list_cache()
        self.logger.info(
            "day_card.deleted",
            extra={"trip_id": trip_id, "day_card_id": day_card_id},
        )


class SubTripService(TripServiceBase):
    def create_sub_trip(
        self,
        day_card_id: int,
        payload: SubTripCreate,
    ) -> SubTripSchema:
        with session_scope() as session:
            day_card = session.get(DayCard, day_card_id)
            if day_card is None:
                raise ResourceNotFoundError("DayCard 不存在", code=14005)
            existing = (
                session.query(SubTrip)
                .filter(SubTrip.day_card_id == day_card_id)
                .order_by(SubTrip.order_index, SubTrip.id)
                .all()
            )
            target_index = (
                len(existing) if payload.order_index is None else payload.order_index
            )
            target_index = max(0, min(target_index, len(existing)))
            sub_trip = self._build_sub_trip(
                payload, day_card_id=day_card_id, order_index=len(existing)
            )
            session.add(sub_trip)
            session.flush()
            session.refresh(sub_trip)
            # Insert into in-memory list and reindex in two phases to avoid unique collisions
            existing.insert(target_index, sub_trip)
            self._reindex(session, existing)
            # reload with relationships for response
            loaded = self._load_day_card_sub_trips(session, day_card_id)
            sub_trip = next(item for item in loaded if item.id == sub_trip.id)
            schema = SubTripSchema.model_validate(sub_trip)
            trip_id = day_card.trip_id
        _invalidate_trip_detail_cache(trip_id)
        _invalidate_trip_list_cache()
        self.logger.info(
            "sub_trip.created",
            extra={
                "trip_id": trip_id,
                "day_card_id": day_card_id,
                "sub_trip_id": schema.id,
            },
        )
        return schema


    def update_sub_trip(
        self, sub_trip_id: int, payload: SubTripUpdate
    ) -> SubTripSchema:
        with session_scope() as session:
            sub_trip = session.get(SubTrip, sub_trip_id)
            if sub_trip is None:
                raise ResourceNotFoundError("子行程不存在", code=14006)

            new_order_index = payload.order_index
            if payload.activity is not None:
                sub_trip.activity = payload.activity
            if payload.poi_id is not None:
                sub_trip.poi_id = payload.poi_id
            if payload.loc_name is not None:
                sub_trip.loc_name = payload.loc_name
            if payload.transport is not None:
                sub_trip.transport = payload.transport
            if payload.start_time is not None:
                sub_trip.start_time = payload.start_time
            if payload.end_time is not None:
                sub_trip.end_time = payload.end_time
            if payload.ext is not None:
                sub_trip.ext = payload.ext

            coord_fields = {"lat", "lng"} & payload.model_fields_set
            if coord_fields:
                if payload.lat is None or payload.lng is None:
                    raise TripValidationError("lat ? lng ?????", code=14012)
                self._sync_coordinates(sub_trip, payload.lat, payload.lng)

            if new_order_index is not None:
                existing = (
                    session.query(SubTrip)
                    .filter(SubTrip.day_card_id == sub_trip.day_card_id)
                    .order_by(SubTrip.order_index, SubTrip.id)
                    .all()
                )
                remaining = [item for item in existing if item.id != sub_trip.id]
                target_index = max(0, min(new_order_index, len(remaining)))
                remaining.insert(target_index, sub_trip)
                self._reindex(session, remaining)

            session.flush()
            self._hydrate_sub_trip(sub_trip)
            schema = SubTripSchema.model_validate(sub_trip)
            trip_id = sub_trip.day_card.trip_id
        _invalidate_trip_detail_cache(trip_id)
        _invalidate_trip_list_cache()
        self.logger.info(
            "sub_trip.updated",
            extra={"trip_id": trip_id, "sub_trip_id": sub_trip_id},
        )
        return schema

    def delete_sub_trip(self, sub_trip_id: int) -> None:
        with session_scope() as session:
            sub_trip = session.get(SubTrip, sub_trip_id)
            if sub_trip is None:
                raise ResourceNotFoundError("子行程不存在", code=14006)
            day_card_id = sub_trip.day_card_id
            trip_id = sub_trip.day_card.trip_id
            session.delete(sub_trip)
            session.flush()
            remaining = (
                session.query(SubTrip)
                .filter(SubTrip.day_card_id == day_card_id)
                .order_by(SubTrip.order_index, SubTrip.id)
                .all()
            )
            self._reindex(session, remaining)
        _invalidate_trip_detail_cache(trip_id)
        _invalidate_trip_list_cache()
        self.logger.info(
            "sub_trip.deleted",
            extra={"trip_id": trip_id, "sub_trip_id": sub_trip_id},
        )

    def reorder_sub_trip(
        self,
        sub_trip_id: int,
        *,
        target_day_card_id: int | None,
        order_index: int,
    ) -> ReorderResult:
        with session_scope() as session:
            source_sub_trip = (
                session.execute(
                    select(SubTrip)
                    .options(
                        selectinload(SubTrip.day_card).selectinload(DayCard.trip),
                        selectinload(SubTrip.poi),
                    )
                    .where(SubTrip.id == sub_trip_id)
                    .with_for_update()
                )
                .scalars()
                .one_or_none()
            )
            if source_sub_trip is None:
                raise ResourceNotFoundError("子行程不存在", code=14006)
            moved_sub_trip_id = source_sub_trip.id
            target_day_card = source_sub_trip.day_card
            if (
                target_day_card_id is not None
                and target_day_card_id != source_sub_trip.day_card_id
            ):
                target_day_card = (
                    session.execute(
                        select(DayCard)
                        .where(DayCard.id == target_day_card_id)
                        .with_for_update()
                    )
                    .scalars()
                    .one_or_none()
                )
                if target_day_card is None:
                    raise ResourceNotFoundError("目标 DayCard 不存在", code=14005)
                if target_day_card.trip_id != source_sub_trip.day_card.trip_id:
                    raise TripValidationError("禁止跨行程移动子行程", code=14011)

            source_day_id = source_sub_trip.day_card_id
            target_day_id = target_day_card.id
            same_day = source_day_id == target_day_id
            target_count = self._count_day_card_sub_trips(session, target_day_id)
            position = min(max(order_index, 0), target_count)

            _reserve_sub_trip_slot(session, moved_sub_trip_id)
            if same_day:
                if position > source_sub_trip.order_index:
                    _shift_same_day_left(
                        session,
                        day_card_id=source_day_id,
                        source_idx=source_sub_trip.order_index,
                        target_idx=position,
                    )
                elif position < source_sub_trip.order_index:
                    _shift_same_day_right(
                        session,
                        day_card_id=source_day_id,
                        source_idx=source_sub_trip.order_index,
                        target_idx=position,
                    )
            else:
                _close_gap_after_removal(
                    session,
                    day_card_id=source_day_id,
                    source_idx=source_sub_trip.order_index,
                )
                _open_slot_in_target(
                    session, day_card_id=target_day_id, target_idx=position
                )
                _assign_sub_trip_day(
                    session, sub_trip_id=moved_sub_trip_id, day_card_id=target_day_id
                )

            _assign_sub_trip_position(
                session,
                sub_trip_id=moved_sub_trip_id,
                day_card_id=target_day_id,
                order_index=position,
            )

            source_list = self._load_day_card_sub_trips(session, source_day_id)
            target_list = (
                source_list
                if same_day
                else self._load_day_card_sub_trips(session, target_day_id)
            )
            trip_id = target_day_card.trip_id

        _invalidate_trip_detail_cache(trip_id)
        _invalidate_trip_list_cache()
        self.logger.info(
            "sub_trip.reordered",
            extra={
                "trip_id": trip_id,
                "sub_trip_id": sub_trip_id,
                "source_day_card_id": source_day_id,
                "target_day_card_id": target_day_id,
            },
        )
        return ReorderResult(
            moved_id=moved_sub_trip_id,
            source_day_card_id=source_day_id,
            target_day_card_id=target_day_id,
            source_sub_trips=source_list,
            target_sub_trips=target_list,
        )


class TripService:
    """Facade used by API layer to interact with specialized services."""

    def __init__(self) -> None:
        self.query_service = TripQueryService()
        self.command_service = TripCommandService()
        self.day_card_service = DayCardService()
        self.sub_trip_service = SubTripService()

    def list_trips(
        self,
        *,
        user_id: int | None,
        destination: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[TripSummarySchema]:
        return self.query_service.list_trips(
            user_id=user_id,
            destination=destination,
            limit=limit,
            offset=offset,
        )

    def get_trip(self, trip_id: int) -> TripSchema:
        return self.query_service.get_trip(trip_id)

    def create_trip(self, payload: TripCreate) -> TripSchema:
        return self.command_service.create_trip(payload)

    def update_trip(self, trip_id: int, payload: TripUpdate) -> TripSchema:
        return self.command_service.update_trip(trip_id, payload)

    def delete_trip(self, trip_id: int) -> None:
        self.command_service.delete_trip(trip_id)

    def create_day_card(self, trip_id: int, payload: DayCardCreate) -> DayCardSchema:
        return self.day_card_service.create_day_card(trip_id, payload)

    def update_day_card(
        self, day_card_id: int, payload: DayCardUpdate
    ) -> DayCardSchema:
        return self.day_card_service.update_day_card(day_card_id, payload)

    def delete_day_card(self, day_card_id: int) -> None:
        self.day_card_service.delete_day_card(day_card_id)

    def create_sub_trip(
        self,
        day_card_id: int,
        payload: SubTripCreate,
    ) -> SubTripSchema:
        return self.sub_trip_service.create_sub_trip(day_card_id, payload)

    def update_sub_trip(
        self,
        sub_trip_id: int,
        payload: SubTripUpdate,
    ) -> SubTripSchema:
        return self.sub_trip_service.update_sub_trip(sub_trip_id, payload)

    def delete_sub_trip(self, sub_trip_id: int) -> None:
        self.sub_trip_service.delete_sub_trip(sub_trip_id)

    def reorder_sub_trip(
        self,
        sub_trip_id: int,
        *,
        target_day_card_id: int | None,
        order_index: int,
    ) -> ReorderResult:
        return self.sub_trip_service.reorder_sub_trip(
            sub_trip_id,
            target_day_card_id=target_day_card_id,
            order_index=order_index,
        )


def _reserve_sub_trip_slot(session: Session, sub_trip_id: int) -> None:
    session.execute(
        sa.text("UPDATE sub_trips SET order_index = -1 WHERE id = :sub_trip_id"),
        {"sub_trip_id": sub_trip_id},
    )


def _shift_same_day_left(
    session: Session,
    *,
    day_card_id: int,
    source_idx: int,
    target_idx: int,
) -> None:
    session.execute(
        sa.text(
            "UPDATE sub_trips SET order_index = order_index - 1 "
            "WHERE day_card_id = :day_id "
            "AND order_index > :source_idx AND order_index <= :target_idx"
        ),
        {
            "day_id": day_card_id,
            "source_idx": source_idx,
            "target_idx": target_idx,
        },
    )


def _shift_same_day_right(
    session: Session,
    *,
    day_card_id: int,
    source_idx: int,
    target_idx: int,
) -> None:
    session.execute(
        sa.text(
            "UPDATE sub_trips SET order_index = order_index + 1 "
            "WHERE day_card_id = :day_id "
            "AND order_index >= :target_idx AND order_index < :source_idx"
        ),
        {
            "day_id": day_card_id,
            "source_idx": source_idx,
            "target_idx": target_idx,
        },
    )


def _close_gap_after_removal(
    session: Session,
    *,
    day_card_id: int,
    source_idx: int,
) -> None:
    session.execute(
        sa.text(
            "UPDATE sub_trips SET order_index = order_index - 1 "
            "WHERE day_card_id = :day_id AND order_index > :source_idx"
        ),
        {"day_id": day_card_id, "source_idx": source_idx},
    )


def _open_slot_in_target(
    session: Session,
    *,
    day_card_id: int,
    target_idx: int,
) -> None:
    session.execute(
        sa.text(
            "UPDATE sub_trips SET order_index = order_index + 1 "
            "WHERE day_card_id = :day_id AND order_index >= :target_idx"
        ),
        {"day_id": day_card_id, "target_idx": target_idx},
    )


def _assign_sub_trip_day(
    session: Session,
    sub_trip_id: int,
    day_card_id: int,
) -> None:
    session.execute(
        sa.text(
            "UPDATE sub_trips SET day_card_id = :day_card_id WHERE id = :sub_trip_id"
        ),
        {"day_card_id": day_card_id, "sub_trip_id": sub_trip_id},
    )


def _assign_sub_trip_position(
    session: Session,
    *,
    sub_trip_id: int,
    day_card_id: int,
    order_index: int,
) -> None:
    session.execute(
        sa.text(
            "UPDATE sub_trips "
            "SET day_card_id = :day_card_id, order_index = :order_index "
            "WHERE id = :sub_trip_id"
        ),
        {
            "day_card_id": day_card_id,
            "order_index": order_index,
            "sub_trip_id": sub_trip_id,
        },
    )


__all__ = [
    "TripService",
    "TripServiceError",
    "ResourceNotFoundError",
    "TripValidationError",
    "ReorderResult",
    "TripQueryService",
    "TripCommandService",
    "DayCardService",
    "SubTripService",
]
