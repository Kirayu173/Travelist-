from __future__ import annotations

from typing import Any, Dict

from app.agents.tools.common.logging import get_tool_logger, log_tool_event
from langchain_core.tools.structured import StructuredTool
from langchain_tavily import TavilySearch
from pydantic import BaseModel, Field

logger = get_tool_logger("fast_search")


class FastSearchInput(BaseModel):
    query: str = Field(..., description="搜索关键词或问题")
    time_range: str = Field(
        default="week",
        description="时间范围，可选 day/week/month/year，仅用于提示",
    )
    max_results: int = Field(default=5, ge=1, le=10, description="最大返回条数")


class FastSearchTool(StructuredTool):
    """基于 Tavily 的快速事实搜索。"""

    def __init__(self, **kwargs):
        super().__init__(
            func=self._run,
            coroutine=self._arun,
            name="fast_search",
            description="快速事实搜索（Tavily），返回摘要与若干来源链接。",
            args_schema=FastSearchInput,
            return_direct=False,
            handle_tool_error=True,
            **kwargs,
        )

    def _run(self, **kwargs) -> Dict[str, Any]:
        try:
            payload = FastSearchInput(**kwargs)
        except Exception as exc:
            log_tool_event(
                "fast_search",
                event="invoke",
                status="invalid_args",
                request=kwargs,
                error_code="invalid_params",
                message=str(exc),
            )
            return {"error": f"参数错误: {exc}"}

        try:
            tavily = TavilySearch(
                max_results=payload.max_results,
                include_answer=True,
                search_depth="basic",
            )
            results = tavily.invoke(
                {"query": payload.query, "time_range": payload.time_range}
            )
            summary = results.get("answer") or "未获取直接答案，请参考下方结果。"
            formatted = [
                {
                    "title": item.get("title", ""),
                    "summary": item.get("content", ""),
                    "url": item.get("url", ""),
                    "score": item.get("score"),
                }
                for item in results.get("results", [])[:5]
            ]
            response = {
                "query": payload.query,
                "summary": summary,
                "results": formatted,
                "raw": results,
            }
            log_tool_event(
                "fast_search",
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
                "fast_search",
                event="invoke",
                status="error",
                request=kwargs,
                error_code="tavily_error",
                message=str(exc),
            )
            return {"error": f"搜索失败: {exc}"}

    async def _arun(self, **kwargs) -> Dict[str, Any]:
        return self._run(**kwargs)


def create_tool() -> FastSearchTool:
    return FastSearchTool()
