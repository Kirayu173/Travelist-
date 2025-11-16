from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.orm import TransportMode


class ORMBaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PoiSchema(ORMBaseSchema):
    id: int
    provider: str
    provider_id: str
    name: str
    category: str | None = None
    addr: str | None = None
    rating: float | None = None
    lat: float | None = None
    lng: float | None = None
    ext: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SubTripSchema(ORMBaseSchema):
    id: int
    day_card_id: int
    order_index: int = Field(ge=0)
    activity: str
    poi_id: int | None = None
    poi: PoiSchema | None = None
    loc_name: str | None = None
    transport: TransportMode | None = None
    start_time: time | None = None
    end_time: time | None = None
    lat: float | None = None
    lng: float | None = None
    ext: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DayCardSchema(ORMBaseSchema):
    id: int
    trip_id: int
    day_index: int = Field(ge=0)
    date: date | None = None
    note: str | None = None
    sub_trips: list[SubTripSchema] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TripSchema(ORMBaseSchema):
    id: int
    user_id: int
    title: str
    destination: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: str
    meta: dict[str, Any] = Field(default_factory=dict)
    day_cards: list[DayCardSchema] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UserSchema(ORMBaseSchema):
    id: int
    email: str
    name: str | None = None
    preferences: dict[str, Any] = Field(default_factory=dict)
    trips: list[TripSchema] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FavoriteSchema(ORMBaseSchema):
    id: int
    user_id: int
    poi_id: int
    poi: PoiSchema | None = None
    created_at: datetime | None = None


__all__ = [
    "UserSchema",
    "TripSchema",
    "DayCardSchema",
    "SubTripSchema",
    "PoiSchema",
    "FavoriteSchema",
]
