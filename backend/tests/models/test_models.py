from __future__ import annotations

from app.core.db import session_scope
from app.models.orm import (
    DayCard,
    Favorite,
    Poi,
    SubTrip,
    TransportMode,
    Trip,
    User,
)


def test_orm_can_persist_full_trip_graph() -> None:
    with session_scope() as session:
        user = User(email="user@example.com", name="Stage2 Tester")
        trip = Trip(title="Stage 2 Trip", destination="Shanghai", user=user)
        day_card = DayCard(day_index=0, note="抵达", trip=trip)
        poi = Poi(provider="manual", provider_id="poi-1", name="陆家嘴")
        session.add(
            SubTrip(
                activity="参观陆家嘴",
                order_index=0,
                poi=poi,
                day_card=day_card,
                transport=TransportMode.WALK,
            )
        )
        favorite = Favorite(user=user, poi=poi)

        session.add(user)
        session.add(favorite)

    with session_scope() as session:
        persisted = session.query(User).filter_by(email="user@example.com").one()
        assert persisted.trips[0].day_cards[0].sub_trips[0].activity == "参观陆家嘴"
        assert persisted.favorites[0].poi.name == "陆家嘴"
