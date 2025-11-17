from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import sqlalchemy as sa
from app.core.db import session_scope
from app.models.orm import DayCard, SubTrip, Trip, User
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
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy.orm import attributes as orm_attributes


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


class TripService:
    """Domain service encapsulating Trip / DayCard / SubTrip operations."""

    def list_trips(
        self,
        *,
        user_id: int | None,
        destination: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[TripSummarySchema]:
        with session_scope() as session:
            query = (
                session.query(
                    Trip,
                    func.count(sa.distinct(DayCard.id)).label("day_count"),
                    func.count(SubTrip.id).label("sub_trip_count"),
                )
                .outerjoin(DayCard, DayCard.trip_id == Trip.id)
                .outerjoin(SubTrip, SubTrip.day_card_id == DayCard.id)
                .group_by(Trip.id)
                .order_by(Trip.updated_at.desc())
            )
            if user_id:
                query = query.filter(Trip.user_id == user_id)
            if destination:
                like_pattern = f"%{destination}%"
                query = query.filter(Trip.destination.ilike(like_pattern))

            page_size = _ensure_positive_limit(limit)
            rows = query.offset(max(offset, 0)).limit(page_size).all()

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

    def get_trip(self, trip_id: int) -> TripSchema:
        with session_scope() as session:
            trip = self._load_trip(session, trip_id)
            if trip is None:
                raise ResourceNotFoundError("行程不存在", code=14004)
            self._hydrate_trip_coordinates(trip)
            return TripSchema.model_validate(trip)

    def create_trip(self, payload: TripCreate) -> TripSchema:
        with session_scope() as session:
            user = session.get(User, payload.user_id)
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
            session.add(trip)
            session.flush()

            for position, day_card_payload in enumerate(payload.day_cards or []):
                day_card = self._build_day_card(
                    trip, day_card_payload, fallback_index=position
                )
                session.add(day_card)
                session.flush()
                self._persist_sub_trips(session, day_card, day_card_payload.sub_trips)

            session.flush()
            session.refresh(trip)
            trip = self._load_trip(session, trip.id)
            assert trip is not None  # for mypy
            self._hydrate_trip_coordinates(trip)
            return TripSchema.model_validate(trip)

    def update_trip(self, trip_id: int, payload: TripUpdate) -> TripSchema:
        with session_scope() as session:
            trip = self._load_trip(session, trip_id)
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
            self._hydrate_trip_coordinates(trip)
            return TripSchema.model_validate(trip)

    def delete_trip(self, trip_id: int) -> None:
        with session_scope() as session:
            deleted = session.query(Trip).filter(Trip.id == trip_id).delete()
            if not deleted:
                raise ResourceNotFoundError("行程不存在", code=14004)

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
            return DayCardSchema.model_validate(day_card)

    def update_day_card(
        self, day_card_id: int, payload: DayCardUpdate
    ) -> DayCardSchema:
        with session_scope() as session:
            day_card = (
                session.query(DayCard)
                .options(selectinload(DayCard.sub_trips).selectinload(SubTrip.poi))
                .filter(DayCard.id == day_card_id)
                .one_or_none()
            )
            if day_card is None:
                raise ResourceNotFoundError("DayCard 不存在", code=14005)
            if payload.day_index is not None:
                conflict = (
                    session.query(DayCard)
                    .filter(
                        DayCard.trip_id == day_card.trip_id,
                        DayCard.day_index == payload.day_index,
                        DayCard.id != day_card.id,
                    )
                    .count()
                )
                if conflict:
                    raise TripValidationError("该 day_index 已存在", code=14010)
                day_card.day_index = payload.day_index
            if payload.date is not None:
                day_card.date = payload.date
            if payload.note is not None:
                day_card.note = payload.note
            session.flush()
            self._hydrate_day_card(day_card)
            return DayCardSchema.model_validate(day_card)

    def delete_day_card(self, day_card_id: int) -> None:
        with session_scope() as session:
            deleted = session.query(DayCard).filter(DayCard.id == day_card_id).delete()
            if not deleted:
                raise ResourceNotFoundError("DayCard 不存在", code=14005)

    def create_sub_trip(
        self, day_card_id: int, payload: SubTripCreate
    ) -> SubTripSchema:
        with session_scope() as session:
            day_card = (
                session.query(DayCard)
                .options(selectinload(DayCard.sub_trips))
                .filter(DayCard.id == day_card_id)
                .one_or_none()
            )
            if day_card is None:
                raise ResourceNotFoundError("DayCard 不存在", code=14005)

            order = payload.order_index
            if order is None or order < 0:
                order = len(day_card.sub_trips)
            sub_trip = self._build_sub_trip(
                payload, day_card_id=day_card.id, order_index=order
            )
            day_card.sub_trips.insert(order, sub_trip)
            self._reindex(session, day_card.sub_trips)
            session.add(sub_trip)
            session.flush()
            self._hydrate_sub_trip(sub_trip)
            return SubTripSchema.model_validate(sub_trip)

    def update_sub_trip(
        self, sub_trip_id: int, payload: SubTripUpdate
    ) -> SubTripSchema:
        with session_scope() as session:
            sub_trip = (
                session.query(SubTrip)
                .options(joinedload(SubTrip.day_card))
                .filter(SubTrip.id == sub_trip_id)
                .one_or_none()
            )
            if sub_trip is None:
                raise ResourceNotFoundError("子行程不存在", code=14006)

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
            if payload.order_index is not None:
                all_subs = (
                    session.query(SubTrip)
                    .filter(SubTrip.day_card_id == sub_trip.day_card_id)
                    .order_by(SubTrip.order_index, SubTrip.id)
                    .all()
                )
                # Remove current and insert at target
                filtered = [item for item in all_subs if item.id != sub_trip.id]
                target_index = min(max(payload.order_index, 0), len(filtered))
                filtered.insert(target_index, sub_trip)
                self._reindex(session, filtered)

            coord_fields = {"lat", "lng"} & payload.model_fields_set
            if coord_fields:
                if payload.lat is None or payload.lng is None:
                    raise TripValidationError("lat 与 lng 需同时提供", code=14012)
                self._sync_coordinates(sub_trip, payload.lat, payload.lng)
            session.flush()
            self._hydrate_sub_trip(sub_trip)
            return SubTripSchema.model_validate(sub_trip)

    def delete_sub_trip(self, sub_trip_id: int) -> None:
        with session_scope() as session:
            sub_trip = session.get(SubTrip, sub_trip_id)
            if sub_trip is None:
                raise ResourceNotFoundError("子行程不存在", code=14006)
            day_card_id = sub_trip.day_card_id
            session.delete(sub_trip)
            session.flush()
            remaining = (
                session.query(SubTrip)
                .filter(SubTrip.day_card_id == day_card_id)
                .order_by(SubTrip.order_index, SubTrip.id)
                .all()
            )
            self._reindex(session, remaining)

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

            return ReorderResult(
                moved_id=moved_sub_trip_id,
                source_day_card_id=source_day_id,
                target_day_card_id=target_day_id,
                source_sub_trips=source_list,
                target_sub_trips=target_list,
            )

    # Helpers -----------------------------------------------------------------

    def _load_trip(self, session: Session, trip_id: int) -> Trip | None:
        return (
            session.query(Trip)
            .options(
                selectinload(Trip.day_cards)
                .selectinload(DayCard.sub_trips)
                .selectinload(SubTrip.poi)
            )
            .filter(Trip.id == trip_id)
            .one_or_none()
        )

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

    def _persist_sub_trips(
        self,
        session: Session,
        day_card: DayCard,
        payloads: Iterable[SubTripCreate],
    ) -> None:
        payload_list = list(payloads or [])
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
            session.add(sub_trip)

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
        for idx, item in enumerate(items):
            temp_index = -(idx + 1)
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
]
