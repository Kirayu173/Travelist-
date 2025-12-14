from __future__ import annotations

from typing import Literal

from app.agents.tools.itinerary.session import ItinerarySession, activity_title
from app.agents.tools.common.base import TravelistBaseTool
from pydantic import BaseModel, Field
from pydantic.v1 import PrivateAttr

Slot = Literal["morning", "afternoon", "evening"]


class ItineraryReplacePoiInput(BaseModel):
    day_index: int = Field(..., ge=0)
    order_index: int = Field(..., ge=0)
    poi_provider: str = Field(..., min_length=1)
    poi_provider_id: str = Field(..., min_length=1)


class ItineraryReplacePoiTool(TravelistBaseTool):
    """替换指定 sub_trip 的 POI（用于修复重复/不符合偏好/距离过远）。"""

    name: str = "itinerary_replace_poi"
    description: str = "替换某个 sub_trip 的 POI（保持时间与 order_index 不变）。"
    args_schema: type[BaseModel] = ItineraryReplacePoiInput

    _session: ItinerarySession = PrivateAttr()

    def __init__(self, session: ItinerarySession, **kwargs):
        super().__init__(**kwargs)
        self._session = session

    def _run(self, **kwargs) -> dict:
        payload = ItineraryReplacePoiInput(**kwargs)
        if payload.day_index != self._session.day_index:
            return {"ok": False, "error": "day_index mismatch"}

        target = None
        for sub in self._session.day_card.sub_trips:
            if sub.order_index == payload.order_index:
                target = sub
                break
        if target is None:
            return {"ok": False, "error": "sub_trip_not_found"}

        poi = self._session.find_poi(payload.poi_provider, payload.poi_provider_id)
        if not poi:
            return {"ok": False, "error": "poi_not_found"}

        new_key = (str(poi.get("provider") or ""), str(poi.get("provider_id") or ""))
        if new_key in self._session.used_pois:
            return {"ok": False, "error": "poi_already_used"}

        # release old
        old_ext = target.ext if isinstance(target.ext, dict) else {}
        old_poi = old_ext.get("poi") if isinstance(old_ext.get("poi"), dict) else {}
        old_key = (
            str(old_poi.get("provider") or "").strip(),
            str(old_poi.get("provider_id") or "").strip(),
        )
        if all(old_key) and old_key in self._session.used_pois:
            self._session.used_pois.remove(old_key)

        # apply new
        ext = dict(poi.get("ext") or {})
        target.ext = dict(target.ext or {})
        target.ext["poi"] = {
            "provider": poi.get("provider"),
            "provider_id": poi.get("provider_id"),
            "source": ext.get("source") or "db",
            "category": poi.get("category"),
            "addr": poi.get("addr"),
            "rating": poi.get("rating"),
            "distance_m": poi.get("distance_m"),
        }
        target.loc_name = str(poi.get("name") or target.loc_name or "")
        target.lat = poi.get("lat")
        target.lng = poi.get("lng")
        target.activity = activity_title(str(poi.get("category") or ""))
        self._session.used_pois.add(new_key)
        return {
            "ok": True,
            "day_index": self._session.day_index,
            "order_index": payload.order_index,
            "loc_name": target.loc_name,
        }

    async def _arun(self, **kwargs) -> dict:
        return self._run(**kwargs)
