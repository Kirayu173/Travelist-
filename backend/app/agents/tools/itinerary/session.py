from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as dt_date
from datetime import datetime, timedelta
from datetime import time as dt_time
from typing import Any

from app.models.plan_schemas import PlanDayCardSchema, PlanRequest, PlanSubTripSchema


def parse_hhmm(value: str) -> dt_time:
    raw = str(value or "").strip()
    return datetime.strptime(raw, "%H:%M").time()


def to_hhmm(value: dt_time) -> str:
    return value.strftime("%H:%M")


def add_minutes(value: dt_time, minutes: int) -> dt_time:
    dt = datetime.combine(dt_date.today(), value) + timedelta(minutes=int(minutes))
    return dt.time()


def minutes_between(start: dt_time, end: dt_time) -> int:
    dt1 = datetime.combine(dt_date.today(), start)
    dt2 = datetime.combine(dt_date.today(), end)
    return int((dt2 - dt1).total_seconds() // 60)


def activity_title(category: str) -> str:
    key = str(category or "").strip().lower()
    mapping = {
        "food": "美食探索",
        "sight": "景点游览",
        "museum": "博物馆参观",
        "park": "公园漫步",
        "hotel": "住宿安排",
        "shopping": "购物休闲",
    }
    return mapping.get(key, f"{category}体验" if category else "行程安排")


@dataclass(slots=True)
class ItinerarySession:
    request: PlanRequest
    day_index: int
    date: dt_date
    candidate_pois: list[dict[str, Any]]
    used_pois: set[tuple[str, str]]
    day_card: PlanDayCardSchema = field(init=False)
    done: bool = False

    def __post_init__(self) -> None:
        self.day_card = PlanDayCardSchema(day_index=self.day_index, date=self.date)

    def find_poi(self, provider: str, provider_id: str) -> dict[str, Any] | None:
        p = str(provider or "").strip()
        pid = str(provider_id or "").strip()
        if not p or not pid:
            return None
        for poi in self.candidate_pois:
            if (
                str(poi.get("provider") or "").strip() == p
                and str(poi.get("provider_id") or "").strip() == pid
            ):
                return poi
        return None

    def next_order_index(self) -> int:
        existing = [
            sub.order_index
            for sub in self.day_card.sub_trips
            if sub.order_index is not None
        ]
        return (max(existing) + 1) if existing else 0

    def add_sub_trip(
        self,
        *,
        slot: str,
        poi: dict[str, Any],
        start_time: dt_time,
        duration_min: int,
        transport: str | None = None,
    ) -> PlanSubTripSchema:
        provider = str(poi.get("provider") or "").strip()
        provider_id = str(poi.get("provider_id") or "").strip()
        key = (provider, provider_id)
        if key in self.used_pois:
            raise ValueError(f"poi already used across days: {provider}/{provider_id}")

        end_time = add_minutes(start_time, duration_min)
        ext = dict(poi.get("ext") or {})
        ext_poi = {
            "provider": provider,
            "provider_id": provider_id,
            "source": (ext.get("source") or "db"),
            "category": poi.get("category"),
            "addr": poi.get("addr"),
            "rating": poi.get("rating"),
            "distance_m": poi.get("distance_m"),
        }
        sub_ext: dict[str, Any] = {
            "slot": slot,
            "duration_min": int(duration_min),
            "poi": ext_poi,
            "planner": {"mode": "deep_tool_v1"},
        }

        sub_trip = PlanSubTripSchema(
            order_index=self.next_order_index(),
            activity=activity_title(str(poi.get("category") or "")),
            poi_id=poi.get("id"),
            loc_name=str(poi.get("name") or poi.get("loc_name") or ""),
            transport=transport or "walk",
            start_time=start_time,
            end_time=end_time,
            lat=poi.get("lat"),
            lng=poi.get("lng"),
            ext=sub_ext,
        )
        self.day_card.sub_trips.append(sub_trip)
        self.used_pois.add(key)
        return sub_trip
