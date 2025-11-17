from __future__ import annotations

from typing import Iterable

from app.models.orm import SubTrip
from sqlalchemy.orm import Session

from .base import BaseRepository


class SubTripRepository(BaseRepository):
    """Data access helpers for SubTrip records."""

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def get(self, sub_trip_id: int) -> SubTrip | None:
        return self.session.get(SubTrip, sub_trip_id)

    def add(self, sub_trip: SubTrip) -> SubTrip:
        self.session.add(sub_trip)
        self.session.flush()
        return sub_trip

    def delete(self, sub_trip_id: int) -> int:
        return self.session.query(SubTrip).filter(SubTrip.id == sub_trip_id).delete()

    def list_for_day_card(self, day_card_id: int) -> Iterable[SubTrip]:
        return (
            self.session.query(SubTrip)
            .filter(SubTrip.day_card_id == day_card_id)
            .order_by(SubTrip.order_index)
            .all()
        )
