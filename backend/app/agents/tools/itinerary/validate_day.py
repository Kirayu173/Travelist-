from __future__ import annotations

from datetime import time as dt_time
from typing import Any

from app.agents.tools.common.base import TravelistBaseTool
from app.agents.tools.itinerary.session import ItinerarySession
from app.core.settings import settings
from pydantic import BaseModel, Field
from pydantic.v1 import PrivateAttr


class ItineraryValidateDayInput(BaseModel):
    day_index: int = Field(..., ge=0)


def _to_minutes(t: dt_time) -> int:
    return t.hour * 60 + t.minute


class ItineraryValidateDayTool(TravelistBaseTool):
    """校验当天 day_card 的基本一致性与 POI 去重约束。"""

    name: str = "itinerary_validate_day"
    description: str = (
        "检查某天 day_card 是否满足 order_index 连续、时间不重叠、POI 不重复等约束。"
    )
    args_schema: type[BaseModel] = ItineraryValidateDayInput

    _session: ItinerarySession = PrivateAttr()

    def __init__(self, session: ItinerarySession, **kwargs):
        super().__init__(**kwargs)
        self._session = session

    def _run(self, **kwargs) -> dict[str, Any]:
        payload = ItineraryValidateDayInput(**kwargs)
        if payload.day_index != self._session.day_index:
            return {"ok": False, "error": "day_index mismatch"}

        issues: list[dict[str, Any]] = []
        card = self._session.day_card
        if not card.sub_trips:
            issues.append({"code": "empty_day", "message": "sub_trips is empty"})
            return {"ok": True, "issues": issues, "issue_count": len(issues)}
        min_required = max(int(getattr(settings, "plan_deep_day_min_sub_trips", 3)), 1)
        if len(card.sub_trips) < min_required:
            issues.append(
                {
                    "code": "too_few_sub_trips",
                    "message": f"need at least {min_required} sub_trips",
                    "min_required": min_required,
                    "current": len(card.sub_trips),
                }
            )

        orders = [
            sub.order_index for sub in card.sub_trips if sub.order_index is not None
        ]
        if len(orders) != len(card.sub_trips):
            issues.append(
                {"code": "missing_order", "message": "some order_index missing"}
            )
        else:
            if len(set(orders)) != len(orders):
                issues.append(
                    {"code": "duplicate_order", "message": "duplicate order_index"}
                )
            else:
                expected = list(range(min(orders), min(orders) + len(orders)))
                if sorted(orders) != expected:
                    issues.append(
                        {
                            "code": "non_contiguous_order",
                            "message": "order_index not contiguous",
                            "expected": expected,
                            "got": sorted(orders),
                        }
                    )

        # time range validation + overlap
        time_items = []
        for sub in card.sub_trips:
            if not sub.start_time or not sub.end_time:
                issues.append(
                    {
                        "code": "missing_time",
                        "message": (
                            "missing start_time/end_time for "
                            f"order_index={sub.order_index}"
                        ),
                    }
                )
                continue
            time_items.append((sub.order_index or 0, sub.start_time, sub.end_time))

        time_items.sort(key=lambda t: _to_minutes(t[1]))
        for idx in range(1, len(time_items)):
            prev = time_items[idx - 1]
            cur = time_items[idx]
            if _to_minutes(cur[1]) < _to_minutes(prev[2]):
                issues.append(
                    {
                        "code": "overlap",
                        "message": "sub_trips time overlap",
                        "prev_order": prev[0],
                        "cur_order": cur[0],
                    }
                )

        # POI duplication within day
        seen: set[tuple[str, str]] = set()
        for sub in card.sub_trips:
            ext = sub.ext if isinstance(sub.ext, dict) else {}
            poi = ext.get("poi") if isinstance(ext.get("poi"), dict) else {}
            key = (
                str(poi.get("provider") or "").strip(),
                str(poi.get("provider_id") or "").strip(),
            )
            if not all(key):
                continue
            if key in seen:
                issues.append(
                    {
                        "code": "duplicate_poi_day",
                        "message": f"poi duplicated in day: {key[0]}/{key[1]}",
                    }
                )
            seen.add(key)

        return {"ok": True, "issues": issues, "issue_count": len(issues)}

    async def _arun(self, **kwargs) -> dict[str, Any]:
        return self._run(**kwargs)
