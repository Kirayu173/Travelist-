from __future__ import annotations

from datetime import date

from app.agents.tools.itinerary import (
    ItineraryAddSubTripTool,
    ItinerarySession,
    ItineraryValidateDayTool,
)
from app.models.plan_schemas import PlanRequest


def test_itinerary_tools_keep_session_private_attr() -> None:
    request = PlanRequest(
        user_id=1,
        destination="Guangzhou",
        start_date=date.today(),
        end_date=date.today(),
        mode="deep",
        preferences={"interests": ["sight"]},
        async_=False,
        seed_mode="fast",
        seed=7,
        save=False,
    )
    candidate_pois = [
        {
            "provider": "osm",
            "provider_id": "1",
            "name": "Test POI",
            "category": "sight",
            "addr": "Somewhere",
            "rating": 4.5,
            "lat": 23.1,
            "lng": 113.3,
            "distance_m": 120.0,
            "ext": {"source": "db"},
        }
    ]
    session = ItinerarySession(
        request=request,
        day_index=0,
        date=request.start_date,
        candidate_pois=candidate_pois,
        used_pois=set(),
    )

    add_tool = ItineraryAddSubTripTool(session)
    resp = add_tool._run(
        day_index=0,
        slot="morning",
        poi_provider="osm",
        poi_provider_id="1",
        start_time="09:00",
        duration_min=90,
        transport="walk",
    )
    assert resp["ok"] is True

    validate_tool = ItineraryValidateDayTool(session)
    report = validate_tool._run(day_index=0)
    assert report["ok"] is True
    assert report["issue_count"] == 0

