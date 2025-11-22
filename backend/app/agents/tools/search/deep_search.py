from __future__ import annotations

from typing import Any, Dict, List

from app.agents.tools.common.logging import tool_logger
from langchain_core.tools.structured import StructuredTool
from pydantic import BaseModel, Field

logger = tool_logger("deep_search")


class DeepSearchInput(BaseModel):
    origin_city: str = Field(..., description="出发城市")
    destination_city: str = Field(..., description="目的地城市")
    start_date: str = Field(..., description="开始日期 YYYY-MM-DD")
    end_date: str = Field(..., description="结束日期 YYYY-MM-DD")
    num_travelers: int = Field(default=1, ge=1, description="出行人数")
    search_type: str = Field(
        default="all",
        description="搜索类型：all/hotel/transport/activity",
    )


class DeepSearchTool(StructuredTool):
    """Trip-focused search stub producing structured suggestions."""

    def __init__(self, **kwargs):
        super().__init__(
            func=self._run,
            coroutine=self._arun,
            name="deep_search",
            description="生成酒店、交通、活动的候选信息（离线示例），用于行程规划。",
            args_schema=DeepSearchInput,
            return_direct=False,
            handle_tool_error=True,
            **kwargs,
        )

    def _run(self, **kwargs) -> Dict[str, Any]:
        try:
            payload = DeepSearchInput(**kwargs)
        except Exception as exc:
            return {"error": f"参数错误: {exc}"}

        categories = []
        if payload.search_type in ("all", "hotel"):
            categories.append(
                {
                    "type": "hotel",
                    "label": "酒店信息",
                    "items": self._sample_hotels(payload.destination_city),
                }
            )
        if payload.search_type in ("all", "transport"):
            categories.append(
                {
                    "type": "transport",
                    "label": "交通信息",
                    "items": self._sample_transport(
                        payload.origin_city, payload.destination_city
                    ),
                }
            )
        if payload.search_type in ("all", "activity"):
            categories.append(
                {
                    "type": "activity",
                    "label": "活动信息",
                    "items": self._sample_activities(payload.destination_city),
                }
            )
        return {
            "metadata": {
                "search_type": payload.search_type,
                "origin_city": payload.origin_city,
                "destination_city": payload.destination_city,
                "date_range": f"{payload.start_date} ~ {payload.end_date}",
                "num_travelers": payload.num_travelers,
            },
            "categories": categories,
        }

    async def _arun(self, **kwargs) -> Dict[str, Any]:
        return self._run(**kwargs)

    @staticmethod
    def _sample_hotels(city: str) -> List[Dict[str, Any]]:
        return [
            {
                "title": f"{city} 市中心舒适酒店",
                "snippet": "3 晚含早餐，步行可达主要景点。",
                "link": "https://example.com/hotel/1",
            },
            {
                "title": f"{city} 车站附近快捷酒店",
                "snippet": "适合转场或短暂停留，性价比高。",
                "link": "https://example.com/hotel/2",
            },
        ]

    @staticmethod
    def _sample_transport(origin: str, destination: str) -> List[Dict[str, Any]]:
        return [
            {
                "title": f"{origin} → {destination} 高铁候选",
                "snippet": "约 2 小时，建议提前订票。",
                "link": "https://example.com/transport/rail",
            },
            {
                "title": f"{origin} → {destination} 航班候选",
                "snippet": "早晚航班充足，可根据行程灵活选择。",
                "link": "https://example.com/transport/air",
            },
        ]

    @staticmethod
    def _sample_activities(city: str) -> List[Dict[str, Any]]:
        return [
            {
                "title": f"{city} 老城徒步",
                "snippet": "2 小时城市漫步路线，涵盖经典地标。",
                "link": "https://example.com/activity/walk",
            },
            {
                "title": f"{city} 美食市场打卡",
                "snippet": "推荐当地特色小吃与开放时段。",
                "link": "https://example.com/activity/food",
            },
        ]


def create_tool() -> DeepSearchTool:
    return DeepSearchTool()
