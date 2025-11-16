from __future__ import annotations

from datetime import date, time
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
for candidate in (PROJECT_ROOT, BACKEND_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

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


def seed() -> None:
    with session_scope() as session:
        user = session.query(User).filter_by(email="stage2@test.travelist").one_or_none()
        if user is None:
            user = User(email="stage2@test.travelist", name="Stage 2 User")
            session.add(user)
            session.flush()

        trip = (
            session.query(Trip)
            .filter_by(user=user, title="示例行程：上海 3 日游")
            .one_or_none()
        )
        if trip is None:
            trip = Trip(
                user=user,
                title="示例行程：上海 3 日游",
                destination="上海",
                start_date=date.today(),
                end_date=date.today(),
                status="planned",
            )
            session.add(trip)
            session.flush()

        day_card = (
            session.query(DayCard)
            .filter_by(trip=trip, day_index=0)
            .one_or_none()
        )
        if day_card is None:
            day_card = DayCard(
                trip=trip,
                day_index=0,
                date=date.today(),
                note="抵达与浦东探索",
            )
            session.add(day_card)

        poi = (
            session.query(Poi)
            .filter_by(provider="manual", provider_id="lujiazui")
            .one_or_none()
        )
        if poi is None:
            poi = Poi(
                provider="manual",
                provider_id="lujiazui",
                name="陆家嘴金融中心",
                category="景点",
                addr="上海市浦东新区世纪大道",
                rating=4.8,
            )
            session.add(poi)
            session.flush()

        sub_trip = (
            session.query(SubTrip)
            .filter_by(day_card=day_card, order_index=0)
            .one_or_none()
        )
        if sub_trip is None:
            sub_trip = SubTrip(
                day_card=day_card,
                order_index=0,
                activity="城市天际线观景",
                poi=poi,
                loc_name="上海中心大厦观光厅",
                transport=None,
                start_time=time(hour=10),
                end_time=time(hour=12),
            )
            session.add(sub_trip)

        favorite = (
            session.query(Favorite)
            .filter_by(user=user, poi=poi)
            .one_or_none()
        )
        if favorite is None:
            session.add(Favorite(user=user, poi=poi))


if __name__ == "__main__":
    seed()
    print("Stage-2 示例数据已就绪。")
