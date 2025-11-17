from __future__ import annotations

from typing import Iterable

import sqlalchemy as sa
from app.models.orm import DayCard, SubTrip, Trip, User
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, selectinload

from .base import BaseRepository


class TripRepository(BaseRepository):
    """Encapsulates Trip level data operations."""

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def list_summaries(
        self,
        *,
        user_id: int | None,
        destination: str | None,
        limit: int,
        offset: int,
    ) -> list[tuple[Trip, int, int]]:
        query = (
            self.session.query(
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
            query = query.filter(Trip.destination.ilike(f"%{destination}%"))
        return query.offset(offset).limit(limit).all()

    def get_with_details(self, trip_id: int) -> Trip | None:
        return (
            self.session.query(Trip)
            .options(
                selectinload(Trip.day_cards)
                .selectinload(DayCard.sub_trips)
                .selectinload(SubTrip.poi),
                joinedload(Trip.user),
            )
            .filter(Trip.id == trip_id)
            .one_or_none()
        )

    def get(self, trip_id: int) -> Trip | None:
        return self.session.get(Trip, trip_id)

    def add(self, trip: Trip) -> Trip:
        self.session.add(trip)
        self.session.flush()
        return trip

    def delete(self, trip_id: int) -> int:
        return self.session.query(Trip).filter(Trip.id == trip_id).delete()

    def get_user(self, user_id: int) -> User | None:
        return self.session.get(User, user_id)

    def refresh(self, trip: Trip) -> Trip:
        self.session.refresh(trip)
        return trip
