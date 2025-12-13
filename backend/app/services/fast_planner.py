from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from time import perf_counter
from typing import Any

import sqlalchemy as sa
from app.core.db import session_scope
from app.core.logging import get_logger
from app.core.settings import settings
from app.models.orm import TransportMode
from app.models.plan_schemas import PlanRequest, PlanTripSchema
from app.models.schemas import DayCardCreate, SubTripCreate, TripCreate
from app.services.geocode_service import GeocodeService, get_geocode_service
from app.services.poi_service import PoiService, get_poi_service


class FastPlannerError(Exception):
    def __init__(self, message: str, *, code: int = 14070) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class CandidatePoi:
    provider: str
    provider_id: str
    name: str
    category: str | None
    addr: str | None
    rating: float | None
    lat: float | None
    lng: float | None
    poi_id: int | None = None
    source: str | None = None
    distance_m: float | None = None
    ext: dict[str, Any] | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.provider, self.provider_id)


def _parse_hhmm(value: str) -> time:
    raw = value.strip()
    try:
        return datetime.strptime(raw, "%H:%M").time()
    except ValueError as exc:
        raise FastPlannerError(f"Invalid time config: {value}") from exc


def _to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _minutes_to_time(minutes: int) -> time:
    minutes = max(minutes, 0)
    hour = min(minutes // 60, 23)
    minute = min(minutes % 60, 59)
    return time(hour=hour, minute=minute)


def _transport_mode(value: str | None) -> TransportMode | None:
    if not value:
        return None
    try:
        return TransportMode(value)
    except ValueError:
        return None


class FastPlanner:
    """Deterministic, non-LLM itinerary planner (mode=fast)."""

    RULES_VERSION = "fast_rules_v1"

    def __init__(
        self,
        *,
        poi_service: PoiService | None = None,
        geocode_service: GeocodeService | None = None,
    ) -> None:
        self._poi_service = poi_service or get_poi_service()
        self._geocode_service = geocode_service or get_geocode_service()
        self._logger = get_logger(__name__)

    async def plan(self, request: PlanRequest) -> tuple[PlanTripSchema, dict[str, Any]]:
        if request.day_count <= 0:
            raise FastPlannerError("Invalid date range", code=14070)
        max_days = max(int(getattr(settings, "plan_max_days", 14)), 1)
        if request.day_count > max_days:
            raise FastPlannerError(
                f"day_count exceeds PLAN_MAX_DAYS ({max_days})",
                code=14070,
            )

        seed = (
            request.seed if request.seed is not None else settings.plan_fast_random_seed
        )
        rng = random.Random(seed)

        interests: list[str] = []
        prefs = request.preferences if isinstance(request.preferences, dict) else {}
        raw_interests = prefs.get("interests")
        if isinstance(raw_interests, list):
            interests = [str(x).strip() for x in raw_interests if str(x).strip()]
        if not interests:
            interests = ["sight", "food"]

        day_start = _parse_hhmm(settings.plan_default_day_start)
        day_end = _parse_hhmm(settings.plan_default_day_end)
        slot_minutes = max(int(settings.plan_default_slot_minutes), 15)
        mid_minutes = (_to_minutes(day_start) + _to_minutes(day_end)) // 2
        half_day_windows = [
            ("morning", day_start, _minutes_to_time(mid_minutes)),
            ("afternoon", _minutes_to_time(mid_minutes), day_end),
        ]

        candidates, poi_metrics = await self._load_candidates(
            destination=request.destination,
            interests=interests,
            day_count=request.day_count,
            seed=seed,
        )

        activities_per_half_day = 1
        pace = str(prefs.get("pace") or "").strip().lower()
        if pace in {"fast", "packed"}:
            activities_per_half_day = 2
        if request.day_count <= 2:
            activities_per_half_day = max(activities_per_half_day, 2)

        used: set[tuple[str, str]] = set()
        interest_cursor = rng.randrange(len(interests)) if interests else 0
        interest_order = interests[interest_cursor:] + interests[:interest_cursor]

        day_cards: list[DayCardCreate] = []
        total_sub_trips = 0
        for day_idx in range(request.day_count):
            current_date = request.start_date + timedelta(days=day_idx)
            sub_trips: list[SubTripCreate] = []
            order_index = 0
            prev_category: str | None = None
            for slot_name, slot_start, slot_end in half_day_windows:
                slot_capacity = max(
                    1,
                    (_to_minutes(slot_end) - _to_minutes(slot_start)) // slot_minutes,
                )
                per_slot = min(activities_per_half_day, max(1, slot_capacity))
                slot_start_min = _to_minutes(slot_start)
                for local_idx in range(per_slot):
                    candidate = self._pick_candidate(
                        candidates,
                        interest_order,
                        used,
                        prev_category=prev_category,
                    )
                    if candidate is None:
                        fallback = self._build_fallback_sub_trip(
                            destination=request.destination,
                            order_index=order_index,
                            slot_name=slot_name,
                            start_min=slot_start_min + local_idx * slot_minutes,
                            slot_minutes=slot_minutes,
                            transport=settings.plan_fast_transport_mode,
                        )
                        sub_trips.append(fallback)
                        order_index += 1
                        continue

                    used.add(candidate.key)
                    prev_category = candidate.category or prev_category
                    sub_trips.append(
                        self._build_sub_trip(
                            candidate,
                            order_index=order_index,
                            slot_name=slot_name,
                            start_min=slot_start_min + local_idx * slot_minutes,
                            slot_minutes=slot_minutes,
                            transport=settings.plan_fast_transport_mode,
                        )
                    )
                    order_index += 1

            total_sub_trips += len(sub_trips)
            day_cards.append(
                DayCardCreate(
                    day_index=day_idx,
                    date=current_date,
                    note=None,
                    sub_trips=sub_trips,
                )
            )

        title = f"{request.destination} 行程规划"
        trip_payload = TripCreate(
            user_id=request.user_id,
            title=title,
            destination=request.destination,
            start_date=request.start_date,
            end_date=request.end_date,
            status="draft",
            meta={
                "planner": {
                    "mode": "fast",
                    "rules_version": self.RULES_VERSION,
                    "seed": seed,
                    "interests": interests,
                }
            },
            day_cards=day_cards,
        )

        plan_trip = PlanTripSchema(
            id=None,
            user_id=trip_payload.user_id,
            title=trip_payload.title,
            destination=trip_payload.destination or request.destination,
            start_date=trip_payload.start_date,
            end_date=trip_payload.end_date,
            status=trip_payload.status,
            meta=trip_payload.meta,
            day_cards=[
                {
                    "id": None,
                    "trip_id": None,
                    "day_index": card.day_index or 0,
                    "date": card.date or request.start_date,
                    "note": card.note,
                    "sub_trips": [
                        {
                            "id": None,
                            "day_card_id": None,
                            **sub.model_dump(mode="json"),
                        }
                        for sub in card.sub_trips
                    ],
                }
                for card in day_cards
            ],
            day_count=request.day_count,
            sub_trip_count=total_sub_trips,
        )

        metrics: dict[str, Any] = {
            "planner": self.RULES_VERSION,
            "seed": seed,
            "day_count": request.day_count,
            "candidate_pois": len(candidates),
            "activities": total_sub_trips,
            "poi_sources": poi_metrics.get("sources", {}),
        }
        return plan_trip, metrics

    async def _load_candidates(
        self,
        *,
        destination: str,
        interests: list[str],
        day_count: int,
        seed: int,
    ) -> tuple[list[CandidatePoi], dict[str, Any]]:
        t0 = perf_counter()
        limit_per_day = max(int(settings.plan_fast_poi_limit_per_day), 1)
        limit = min(limit_per_day * max(day_count, 1), 200)

        db_candidates = self._query_destination_candidates(destination, limit=limit * 2)

        center = await self._geocode_service.resolve_city_center(destination)
        lat, lng = center.lat, center.lng
        sources_counter: dict[str, int] = {}
        api_candidates: list[dict[str, Any]] = []
        for interest in interests[:6]:
            results, meta = await self._poi_service.get_poi_around(
                lat=lat,
                lng=lng,
                poi_type=interest,
                radius=settings.poi_default_radius_m,
                limit=min(limit, 30),
            )
            api_candidates.extend(results)
            source = str(meta.get("source") or "unknown")
            sources_counter[source] = sources_counter.get(source, 0) + 1

        merged: list[CandidatePoi] = []
        seen: set[tuple[str, str]] = set()

        for item in db_candidates:
            if item.key in seen:
                continue
            seen.add(item.key)
            merged.append(item)

        for raw in api_candidates:
            provider = str(raw.get("provider") or "unknown")
            provider_id = str(raw.get("provider_id") or "")
            key = (provider, provider_id)
            if key in seen or not provider_id:
                continue
            seen.add(key)
            merged.append(
                CandidatePoi(
                    poi_id=int(raw["id"]) if raw.get("id") else None,
                    provider=provider,
                    provider_id=provider_id,
                    name=str(raw.get("name") or ""),
                    category=(str(raw.get("category") or "").strip() or None),
                    addr=(str(raw.get("addr") or "").strip() or None),
                    rating=(
                        float(raw["rating"]) if raw.get("rating") is not None else None
                    ),
                    lat=float(raw["lat"]) if raw.get("lat") is not None else None,
                    lng=float(raw["lng"]) if raw.get("lng") is not None else None,
                    source=str(raw.get("source") or "api"),
                    distance_m=(
                        float(raw["distance_m"])
                        if raw.get("distance_m") is not None
                        else None
                    ),
                    ext=raw.get("ext") if isinstance(raw.get("ext"), dict) else None,
                )
            )

        def _sort_key(item: CandidatePoi) -> tuple[float, str, str, str]:
            return (
                -(item.rating or 0.0),
                item.name,
                item.provider,
                item.provider_id,
            )

        merged.sort(key=_sort_key)
        elapsed_ms = (perf_counter() - t0) * 1000
        return merged[:limit], {
            "sources": sources_counter,
            "latency_ms": round(elapsed_ms, 3),
            "destination_center": {
                "lat": lat,
                "lng": lng,
                "provider": center.provider,
                "source": center.source,
            },
        }

    def _query_destination_candidates(
        self, destination: str, *, limit: int
    ) -> list[CandidatePoi]:
        if limit <= 0:
            return []
        dest = destination.strip()
        if not dest:
            return []
        pattern = f"%{dest}%"
        rows: list[dict[str, Any]] = []
        with session_scope() as session:
            dialect = session.bind.dialect.name if session.bind else "postgresql"
            if dialect != "postgresql":
                return []
            stmt = sa.text(
                """
                SELECT id, provider, provider_id, name, category, addr, rating,
                       ST_Y(geom::geometry) AS lat,
                       ST_X(geom::geometry) AS lng,
                       ext
                FROM pois
                WHERE (ext->>'city' = :dest OR ext #>> '{amap,city}' = :dest
                       OR name ILIKE :pattern OR addr ILIKE :pattern)
                ORDER BY rating DESC NULLS LAST, id ASC
                LIMIT :limit
                """
            )
            rows = (
                session.execute(
                    stmt,
                    {"dest": dest, "pattern": pattern, "limit": min(limit, 500)},
                )
                .mappings()
                .all()
            )
        candidates: list[CandidatePoi] = []
        for row in rows:
            candidates.append(
                CandidatePoi(
                    poi_id=int(row["id"]) if row.get("id") else None,
                    provider=str(row.get("provider") or ""),
                    provider_id=str(row.get("provider_id") or ""),
                    name=str(row.get("name") or ""),
                    category=(str(row.get("category") or "").strip() or None),
                    addr=(str(row.get("addr") or "").strip() or None),
                    rating=(
                        float(row["rating"]) if row.get("rating") is not None else None
                    ),
                    lat=float(row["lat"]) if row.get("lat") is not None else None,
                    lng=float(row["lng"]) if row.get("lng") is not None else None,
                    source="db",
                    ext=row.get("ext") if isinstance(row.get("ext"), dict) else None,
                )
            )
        return candidates

    @staticmethod
    def _pick_candidate(
        candidates: list[CandidatePoi],
        interests: list[str],
        used: set[tuple[str, str]],
        *,
        prev_category: str | None,
    ) -> CandidatePoi | None:
        if not candidates:
            return None

        interest_set = {str(x).strip() for x in interests if str(x).strip()}
        for item in candidates:
            if item.key in used:
                continue
            if (
                item.category
                and item.category in interest_set
                and item.category != prev_category
            ):
                return item

        for item in candidates:
            if item.key in used:
                continue
            if item.category and item.category != prev_category:
                return item

        for item in candidates:
            if item.key in used:
                continue
            return item
        return None

    @staticmethod
    def _build_sub_trip(
        candidate: CandidatePoi,
        *,
        order_index: int,
        slot_name: str,
        start_min: int,
        slot_minutes: int,
        transport: str | None,
    ) -> SubTripCreate:
        start_time = _minutes_to_time(start_min)
        end_time = _minutes_to_time(start_min + slot_minutes)
        category = candidate.category or "activity"
        activity = _activity_title(category)
        ext = {
            "slot": slot_name,
            "poi": {
                "provider": candidate.provider,
                "provider_id": candidate.provider_id,
                "source": candidate.source,
                "category": candidate.category,
                "addr": candidate.addr,
                "rating": candidate.rating,
                "distance_m": candidate.distance_m,
            },
            "planner": {"rules_version": FastPlanner.RULES_VERSION},
        }
        return SubTripCreate(
            order_index=order_index,
            activity=activity,
            poi_id=candidate.poi_id,
            loc_name=candidate.name,
            transport=_transport_mode(transport),
            start_time=start_time,
            end_time=end_time,
            lat=candidate.lat,
            lng=candidate.lng,
            ext=ext,
        )

    @staticmethod
    def _build_fallback_sub_trip(
        *,
        destination: str,
        order_index: int,
        slot_name: str,
        start_min: int,
        slot_minutes: int,
        transport: str | None,
    ) -> SubTripCreate:
        start_time = _minutes_to_time(start_min)
        end_time = _minutes_to_time(start_min + slot_minutes)
        return SubTripCreate(
            order_index=order_index,
            activity="自由探索",
            poi_id=None,
            loc_name=destination,
            transport=_transport_mode(transport),
            start_time=start_time,
            end_time=end_time,
            ext={
                "slot": slot_name,
                "fallback": True,
                "planner": {"rules_version": FastPlanner.RULES_VERSION},
                "hint": (
                    "POI 数据不足，已降级为自由探索；"
                    "可补充 POI 数据或扩大兴趣类型后重试。"
                ),
            },
        )


def _activity_title(category: str) -> str:
    key = category.strip().lower()
    mapping = {
        "food": "美食探索",
        "sight": "景点游览",
        "museum": "博物馆参观",
        "park": "公园漫步",
        "hotel": "住宿安排",
        "shopping": "购物休闲",
    }
    return mapping.get(key, f"{category}体验")
