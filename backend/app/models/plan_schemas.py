from __future__ import annotations

from datetime import date as dt_date
from datetime import datetime as dt_datetime
from typing import Any, Literal

from app.models.orm import TransportMode
from app.models.schemas import DayCardBase, SubTripBase, TripBase
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PlanMode = Literal["fast", "deep"]
SeedMode = Literal["fast"]

DEFAULT_INTERESTS: list[str] = ["sight", "food"]


def _normalize_interests(value: Any) -> list[str]:
    if not isinstance(value, list):
        return DEFAULT_INTERESTS.copy()
    normalized: list[str] = []
    for raw in value:
        text = str(raw).strip()
        if text:
            normalized.append(text)
    return normalized or DEFAULT_INTERESTS.copy()


class PlanRequest(BaseModel):
    user_id: int = Field(..., ge=1)
    destination: str = Field(..., min_length=1, max_length=255)
    start_date: dt_date
    end_date: dt_date
    mode: PlanMode = "fast"
    save: bool = False
    preferences: dict[str, Any] = Field(default_factory=dict)
    people_count: int | None = Field(default=None, ge=1, le=20)
    seed: int | None = Field(default=None, ge=0)
    async_: bool = Field(
        default=False,
        validation_alias="async",
        serialization_alias="async",
        description="Stage-8 预留：deep 规划异步任务开关；Stage-7 fast 忽略该字段。",
    )
    request_id: str | None = Field(
        default=None,
        max_length=64,
        description="Stage-8 预留：幂等/追踪 ID。",
    )
    seed_mode: SeedMode | None = Field(
        default=None,
        description="Stage-8 预留：deep 可用 fast 作为草案种子。",
    )

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("destination")
    @classmethod
    def strip_destination(cls, value: str) -> str:
        value = value.strip()
        if not value:
            msg = "destination must not be empty"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_dates_and_prefs(self) -> "PlanRequest":
        if self.end_date < self.start_date:
            msg = "end_date must be >= start_date"
            raise ValueError(msg)

        prefs = self.preferences if isinstance(self.preferences, dict) else {}
        prefs = dict(prefs)
        prefs["interests"] = _normalize_interests(prefs.get("interests"))
        self.preferences = prefs
        return self

    @property
    def day_count(self) -> int:
        return (self.end_date - self.start_date).days + 1


class PlanSubTripSchema(SubTripBase):
    id: int | None = None
    day_card_id: int | None = None
    transport: TransportMode | None = None


class PlanDayCardSchema(DayCardBase):
    id: int | None = None
    trip_id: int | None = None
    day_index: int = Field(ge=0)
    date: dt_date
    sub_trips: list[PlanSubTripSchema] = Field(default_factory=list)


class PlanTripSchema(TripBase):
    id: int | None = None
    user_id: int = Field(ge=1)
    destination: str = Field(min_length=1, max_length=255)
    start_date: dt_date
    end_date: dt_date
    day_cards: list[PlanDayCardSchema] = Field(default_factory=list)
    day_count: int = Field(ge=1)
    sub_trip_count: int = Field(ge=0)


class PlanResponseData(BaseModel):
    mode: PlanMode
    async_: bool = Field(
        default=False,
        validation_alias="async",
        serialization_alias="async",
    )
    request_id: str | None = None
    seed_mode: SeedMode | None = None
    task_id: str | None = None
    plan: PlanTripSchema | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    tool_traces: list[dict[str, Any]] = Field(default_factory=list)
    trace_id: str

    model_config = ConfigDict(populate_by_name=True)


PlanTaskStatus = Literal["queued", "running", "succeeded", "failed", "canceled"]


class PlanTaskSchema(BaseModel):
    """Stage-8 预设：异步 deep 规划任务状态结构（Stage-7 不落库、不执行）。"""

    task_id: str
    status: PlanTaskStatus
    mode: PlanMode
    async_: bool = Field(
        default=True,
        validation_alias="async",
        serialization_alias="async",
    )
    request_id: str | None = None
    seed_mode: SeedMode | None = None
    created_at: dt_datetime
    updated_at: dt_datetime
    result: PlanTripSchema | None = None
    error: dict[str, Any] | None = None

    model_config = ConfigDict(populate_by_name=True)
