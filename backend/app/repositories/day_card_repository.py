from __future__ import annotations

from typing import Iterable

from app.models.orm import DayCard
from sqlalchemy.orm import Session, selectinload

from .base import BaseRepository


class DayCardRepository(BaseRepository):
    """Data access helpers for DayCard aggregates."""

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def get(self, day_card_id: int) -> DayCard | None:
        return (
            self.session.query(DayCard)
            .options(selectinload(DayCard.sub_trips))
            .filter(DayCard.id == day_card_id)
            .one_or_none()
        )

    def get_plain(self, day_card_id: int) -> DayCard | None:
        return self.session.get(DayCard, day_card_id)

    def delete(self, day_card_id: int) -> int:
        return self.session.query(DayCard).filter(DayCard.id == day_card_id).delete()

    def add(self, day_card: DayCard) -> DayCard:
        self.session.add(day_card)
        self.session.flush()
        return day_card

    def list_for_trip(self, trip_id: int) -> Iterable[DayCard]:
        return (
            self.session.query(DayCard)
            .filter(DayCard.trip_id == trip_id)
            .order_by(DayCard.day_index)
            .all()
        )
