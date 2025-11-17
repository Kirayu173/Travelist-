from __future__ import annotations

from datetime import date as dt_date
from datetime import datetime, time
from typing import Any

from app.models.orm import TransportMode
from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class SubTripBase(BaseModel):
    order_index: int | None = Field(default=None, ge=0)
    activity: str
    poi_id: int | None = None
    loc_name: str | None = None
    transport: TransportMode | None = None
    start_time: time | None = None
    end_time: time | None = None
    lat: float | None = None
    lng: float | None = None
    ext: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_time_range(self) -> "SubTripBase":
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            msg = "start_time 必须早于 end_time"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def validate_coordinates(self) -> "SubTripBase":
        has_lat = self.lat is not None
        has_lng = self.lng is not None
        if has_lat ^ has_lng:
            msg = "lat 与 lng 需同时提供"
            raise ValueError(msg)
        return self


class SubTripCreate(SubTripBase):
    pass


class SubTripUpdate(BaseModel):
    order_index: int | None = Field(default=None, ge=0)
    activity: str | None = None
    poi_id: int | None = None
    loc_name: str | None = None
    transport: TransportMode | None = None
    start_time: time | None = None
    end_time: time | None = None
    lat: float | None = None
    lng: float | None = None
    ext: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_time_range(self) -> "SubTripUpdate":
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            msg = "start_time 必须早于 end_time"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def validate_coordinates(self) -> "SubTripUpdate":
        provided = {"lat", "lng"} & self.model_fields_set
        if provided and provided != {"lat", "lng"}:
            msg = "lat 与 lng 需同时提供"
            raise ValueError(msg)
        return self


class SubTripSchema(SubTripBase, ORMBaseSchema):
    id: int
    day_card_id: int
    order_index: int = Field(ge=0)
    poi: PoiSchema | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DayCardBase(BaseModel):
    day_index: int | None = Field(default=None, ge=0)
    date: dt_date | None = None
    note: str | None = None


class DayCardCreate(DayCardBase):
    sub_trips: list[SubTripCreate] = Field(default_factory=list)


class DayCardUpdate(BaseModel):
    day_index: int | None = Field(default=None, ge=0)
    date: dt_date | None = None
    note: str | None = None


class DayCardSchema(DayCardBase, ORMBaseSchema):
    id: int
    trip_id: int
    day_index: int = Field(ge=0)
    sub_trips: list[SubTripSchema] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TripBase(BaseModel):
    title: str
    destination: str | None = None
    start_date: dt_date | None = None
    end_date: dt_date | None = None
    status: str = "draft"
    meta: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_dates(self) -> "TripBase":
        if self.start_date and self.end_date and self.start_date > self.end_date:
            msg = "start_date 不能晚于 end_date"
            raise ValueError(msg)
        return self


class TripCreate(TripBase):
    user_id: int
    day_cards: list[DayCardCreate] = Field(default_factory=list)


class TripUpdate(BaseModel):
    title: str | None = None
    destination: str | None = None
    start_date: dt_date | None = None
    end_date: dt_date | None = None
    status: str | None = None
    meta: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> "TripUpdate":
        if self.start_date and self.end_date and self.start_date > self.end_date:
            msg = "start_date 不能晚于 end_date"
            raise ValueError(msg)
        return self


class TripSchema(TripBase, ORMBaseSchema):
    id: int
    user_id: int
    day_cards: list[DayCardSchema] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TripSummarySchema(ORMBaseSchema):
    id: int
    user_id: int
    title: str
    destination: str | None = None
    start_date: dt_date | None = None
    end_date: dt_date | None = None
    status: str
    day_count: int
    sub_trip_count: int
    updated_at: datetime | None = None


class SubTripReorderPayload(BaseModel):
    day_card_id: int | None = Field(
        default=None, description="目标 DayCard，缺省表示在当前卡片内换序"
    )
    order_index: int = Field(ge=0)


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
    "TripSummarySchema",
    "TripCreate",
    "TripUpdate",
    "DayCardSchema",
    "DayCardCreate",
    "DayCardUpdate",
    "SubTripSchema",
    "SubTripCreate",
    "SubTripUpdate",
    "SubTripReorderPayload",
    "PoiSchema",
    "FavoriteSchema",
]
