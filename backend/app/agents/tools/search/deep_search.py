from __future__ import annotations

from typing import Any, Dict, List

from app.agents.tools.common.logging import get_tool_logger, log_tool_event
from langchain_core.tools.structured import StructuredTool
from langchain_tavily import TavilySearch
from pydantic import BaseModel, Field

logger = get_tool_logger("deep_search")


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
    """基于 Tavily 的行程搜索（酒店/交通/活动）。"""

    def __init__(self, **kwargs):
        super().__init__(
            func=self._run,
            coroutine=self._arun,
            name="deep_search",
            description="生成酒店、交通、活动的候选信息（Tavily 实时搜索），用于行程规划。",
            args_schema=DeepSearchInput,
            return_direct=False,
            handle_tool_error=True,
            **kwargs,
        )

    def _run(self, **kwargs) -> Dict[str, Any]:
        try:
            payload = DeepSearchInput(**kwargs)
        except Exception as exc:
            log_tool_event(
                "deep_search",
                event="invoke",
                status="invalid_args",
                request=kwargs,
                error_code="invalid_params",
                message=str(exc),
            )
            return {"error": f"参数错误: {exc}"}

        try:
            tavily = TavilySearch(max_results=5, include_answer=True, search_depth="advanced")
            categories = []
            if payload.search_type in ("all", "hotel"):
                categories.append(
                    {
                        "type": "hotel",
                        "label": "酒店信息",
                        "items": self._search_category(
                            tavily,
                            f"best hotels in {payload.destination_city} from {payload.start_date} to {payload.end_date} for {payload.num_travelers} travelers",
                        ),
                    }
                )
            if payload.search_type in ("all", "transport"):
                categories.append(
                    {
                        "type": "transport",
                        "label": "交通信息",
                        "items": self._search_category(
                            tavily,
                            f"transport options from {payload.origin_city} to {payload.destination_city} between {payload.start_date} and {payload.end_date}",
                        ),
                    }
                )
            if payload.search_type in ("all", "activity"):
                categories.append(
                    {
                        "type": "activity",
                        "label": "活动信息",
                        "items": self._search_category(
                            tavily,
                            f"things to do in {payload.destination_city} for travelers during {payload.start_date} to {payload.end_date}",
                        ),
                    }
                )
            response = {
                "metadata": {
                    "search_type": payload.search_type,
                    "origin_city": payload.origin_city,
                    "destination_city": payload.destination_city,
                    "date_range": f"{payload.start_date} ~ {payload.end_date}",
                    "num_travelers": payload.num_travelers,
                },
                "categories": categories,
            }
            log_tool_event(
                "deep_search",
                event="invoke",
                status="ok",
                request=kwargs,
                response=response,
                raw_input=kwargs,
                output=response,
            )
            return response
        except Exception as exc:
            log_tool_event(
                "deep_search",
                event="invoke",
                status="error",
                request=kwargs,
                error_code="tavily_error",
                message=str(exc),
            )
            return {"error": f"搜索失败: {exc}"}

    async def _arun(self, **kwargs) -> Dict[str, Any]:
        return self._run(**kwargs)

    @staticmethod
    def _search_category(tavily: TavilySearch, query: str) -> List[Dict[str, Any]]:
        data = tavily.invoke({"query": query})
        items: List[Dict[str, Any]] = []
        for item in data.get("results", [])[:5]:
            items.append(
                {
                    "title": item.get("title", ""),
                    "snippet": item.get("content", ""),
                    "link": item.get("url", ""),
                    "score": item.get("score"),
                }
            )
        return items


def create_tool() -> DeepSearchTool:
    return DeepSearchTool()
