from __future__ import annotations

from datetime import date as dt_date
from typing import Any

from app.models.plan_schemas import PlanTripSchema
from pydantic import BaseModel, ConfigDict, Field


class PlannerState(BaseModel):
    user_id: int
    destination: str
    start_date: dt_date
    end_date: dt_date
    mode: str = "fast"
    save: bool = False
    preferences: dict[str, Any] = Field(default_factory=dict)
    people_count: int | None = None
    seed: int | None = None
    async_: bool = Field(default=False, alias="async")
    request_id: str | None = None
    seed_mode: str | None = None

    result: PlanTripSchema | None = None
    errors: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    trace_id: str
    tool_traces: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow", populate_by_name=True)
