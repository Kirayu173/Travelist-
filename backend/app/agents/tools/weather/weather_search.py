from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from app.agents.tools.common.logging import get_tool_logger, log_tool_event
from langchain_core.tools.structured import StructuredTool
from langchain_tavily import TavilySearch
from pydantic import BaseModel, Field

logger = get_tool_logger("weather_search")


class WeatherSearchInput(BaseModel):
    destination: str = Field(..., description="目标地点，如 Paris")
    month: str = Field(..., description="月份或时间范围，如 2025-11")
    max_results: Optional[int] = Field(default=5, ge=1, le=10)


class WeatherSearchTool(StructuredTool):
    """基于 Tavily 的天气查询，返回摘要与引用链接。"""

    def __init__(self, **kwargs):
        super().__init__(
            func=self._run,
            coroutine=self._arun,
            name="weather_search",
            description="使用 Tavily 搜索指定地点和月份的天气摘要，返回引用链接。",
            args_schema=WeatherSearchInput,
            return_direct=False,
            handle_tool_error=True,
            **kwargs,
        )
        # Validate Tavily API key on init
        try:
            TavilySearch()
        except Exception:
            # defer key errors to runtime
            pass

    def _build_query(self, destination: str, month: str) -> str:
        return (
            f"{destination} {month} 的历史或典型气温、降雨量和气候特征，"
            "给出总体天气概况与出行建议。"
        )

    def _process_results(
        self, results: Dict[str, Any]
    ) -> tuple[str, List[Dict[str, Any]]]:
        if results.get("answer"):
            summary = results["answer"]
        else:
            summary = "未获取直接答案，以下为搜索摘要：\n"
            for i, item in enumerate(results.get("results", [])[:3], 1):
                title = item.get("title", "")
                content = (item.get("content") or "")[:150]
                summary += f"{i}. {title}: {content}...\n"
        web_results = []
        for item in results.get("results", [])[:5]:
            web_results.append(
                {
                    "title": item.get("title", ""),
                    "link": item.get("url", ""),
                    "snippet": (item.get("content") or "")[:200],
                }
            )
        return summary, web_results

    def _run(self, **kwargs) -> Dict[str, Any]:
        try:
            payload = WeatherSearchInput(**kwargs)
        except Exception as exc:
            log_tool_event(
                "weather_search",
                event="invoke",
                status="invalid_args",
                request=kwargs,
                error_code="invalid_params",
                message=str(exc),
            )
            return {"error": f"参数错误: {exc}"}

        try:
            query = self._build_query(payload.destination, payload.month)
            tavily = TavilySearch(
                max_results=payload.max_results or 5,
                include_answer=True,
            )
            results = tavily.invoke({"query": query})
            summary, web_results = self._process_results(results)
            response = {
                "weather_summary": summary,
                "destination": payload.destination,
                "month": payload.month,
                "web_results": web_results,
                "raw": results,
            }
            log_tool_event(
                "weather_search",
                event="invoke",
                status="ok",
                request=kwargs,
                response=results,
                raw_input=kwargs,
                output=response,
            )
            return response
        except Exception as exc:
            log_tool_event(
                "weather_search",
                event="invoke",
                status="error",
                request=kwargs,
                error_code="tavily_error",
                message=str(exc),
            )
            return {"error": f"搜索失败: {exc}"}

    async def _arun(self, **kwargs) -> Dict[str, Any]:
        return await asyncio.to_thread(self._run, **kwargs)


def create_tool() -> WeatherSearchTool:
    return WeatherSearchTool()
