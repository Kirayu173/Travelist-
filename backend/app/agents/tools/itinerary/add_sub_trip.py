from __future__ import annotations

from datetime import time as dt_time
from typing import Literal

from app.agents.tools.itinerary.session import ItinerarySession, parse_hhmm
from app.agents.tools.common.base import TravelistBaseTool
from pydantic import BaseModel, Field, field_validator
from pydantic.v1 import PrivateAttr

Slot = Literal["morning", "afternoon", "evening"]


def _slot_default_start(slot: str) -> dt_time:
    if slot == "morning":
        return parse_hhmm("09:00")
    if slot == "afternoon":
        return parse_hhmm("13:30")
    return parse_hhmm("18:00")


class ItineraryAddSubTripInput(BaseModel):
    day_index: int = Field(..., ge=0)
    slot: Slot = Field(default="morning")
    poi_provider: str = Field(..., min_length=1)
    poi_provider_id: str = Field(..., min_length=1)
    start_time: str | None = Field(
        default=None, description="可选，格式 HH:MM；缺省按 slot 与当前已排内容自动推算"
    )
    duration_min: int = Field(default=90, ge=30, le=300)
    transport: str | None = Field(default="walk")

    @field_validator("start_time")
    @classmethod
    def normalize_start_time(cls, value: str | None) -> str | None:
        text = (value or "").strip()
        return text or None


class ItineraryAddSubTripTool(TravelistBaseTool):
    """向指定 day_card 追加一个 sub_trip（按 slot 自动排时段，可指定 POI）。"""

    name: str = "itinerary_add_sub_trip"
    description: str = "给某一天添加一个 POI 子行程，并自动生成 order_index 与时间段。"
    args_schema: type[BaseModel] = ItineraryAddSubTripInput

    _session: ItinerarySession = PrivateAttr()

    def __init__(self, session: ItinerarySession, **kwargs):
        super().__init__(**kwargs)
        self._session = session

    def _run(self, **kwargs) -> dict:
        payload = ItineraryAddSubTripInput(**kwargs)
        if payload.day_index != self._session.day_index:
            return {
                "ok": False,
                "error": "day_index mismatch",
                "expected": self._session.day_index,
                "got": payload.day_index,
            }

        poi = self._session.find_poi(payload.poi_provider, payload.poi_provider_id)
        if not poi:
            return {
                "ok": False,
                "error": "poi_not_found",
                "poi_provider": payload.poi_provider,
                "poi_provider_id": payload.poi_provider_id,
            }

        existing = list(self._session.day_card.sub_trips)
        start_time: dt_time
        if payload.start_time:
            start_time = parse_hhmm(payload.start_time)
        else:
            start_time = _slot_default_start(payload.slot)
            if existing:
                last = max(
                    (sub.end_time for sub in existing if sub.end_time),
                    default=None,
                )
                if last:
                    start_time = max(start_time, last)

        try:
            sub = self._session.add_sub_trip(
                slot=payload.slot,
                poi=poi,
                start_time=start_time,
                duration_min=payload.duration_min,
                transport=payload.transport,
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:200]}

        return {
            "ok": True,
            "day_index": self._session.day_index,
            "order_index": sub.order_index,
            "loc_name": sub.loc_name,
            "start_time": sub.start_time.isoformat() if sub.start_time else None,
            "end_time": sub.end_time.isoformat() if sub.end_time else None,
            "slot": (sub.ext or {}).get("slot"),
        }

    async def _arun(self, **kwargs) -> dict:
        return self._run(**kwargs)
