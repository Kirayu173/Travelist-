from __future__ import annotations

from datetime import time as dt_time
from typing import Literal

from app.agents.tools.common.base import TravelistBaseTool
from app.agents.tools.itinerary.session import (
    ItinerarySession,
    add_minutes,
    minutes_between,
    parse_hhmm,
)
from pydantic import BaseModel, Field
from pydantic.v1 import PrivateAttr

Slot = Literal["morning", "afternoon", "evening"]


def _slot_start(slot: str) -> dt_time:
    if slot == "morning":
        return parse_hhmm("09:00")
    if slot == "afternoon":
        return parse_hhmm("13:30")
    return parse_hhmm("18:00")


class ItineraryAdjustTimesInput(BaseModel):
    day_index: int = Field(..., ge=0)
    policy: str = Field(
        default="sequential",
        description="sequential: 按 order_index 顺延；slot: 按 slot 分段顺延",
    )


class ItineraryAdjustTimesTool(TravelistBaseTool):
    """修复某天 sub_trips 的时间连续性（避免重叠/缺失）。"""

    name: str = "itinerary_adjust_times"
    description: str = (
        "修复某一天时间段：为缺失/冲突的 sub_trips 重新计算 start_time/end_time。"
    )
    args_schema: type[BaseModel] = ItineraryAdjustTimesInput

    _session: ItinerarySession = PrivateAttr()

    def __init__(self, session: ItinerarySession, **kwargs):
        super().__init__(**kwargs)
        self._session = session

    def _run(self, **kwargs) -> dict:
        payload = ItineraryAdjustTimesInput(**kwargs)
        if payload.day_index != self._session.day_index:
            return {"ok": False, "error": "day_index mismatch"}

        sub_trips = list(self._session.day_card.sub_trips)
        sub_trips.sort(
            key=lambda s: (s.order_index if s.order_index is not None else 0)
        )

        if payload.policy == "slot":
            slot_order = {"morning": 0, "afternoon": 1, "evening": 2}
            sub_trips.sort(
                key=lambda s: (
                    slot_order.get((s.ext or {}).get("slot") or "morning", 0),
                    s.order_index if s.order_index is not None else 0,
                )
            )

        cursor: dt_time | None = None
        for sub in sub_trips:
            slot = (sub.ext or {}).get("slot") or "morning"
            slot_start = _slot_start(slot)
            if cursor is None:
                cursor = slot_start
            cursor = max(cursor, slot_start)

            duration = int((sub.ext or {}).get("duration_min") or 90)
            if sub.start_time and sub.end_time:
                duration = max(minutes_between(sub.start_time, sub.end_time), 30)

            sub.start_time = cursor
            sub.end_time = add_minutes(cursor, duration)
            cursor = sub.end_time

        return {
            "ok": True,
            "day_index": self._session.day_index,
            "sub_trip_count": len(sub_trips),
        }

    async def _arun(self, **kwargs) -> dict:
        return self._run(**kwargs)
