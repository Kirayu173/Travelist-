from __future__ import annotations

from typing import Any, Dict

from app.agents.tools.common.logging import tool_logger
from langchain_core.tools.structured import StructuredTool
from pydantic import BaseModel, Field

logger = tool_logger("fast_search")


class FastSearchInput(BaseModel):
    query: str = Field(..., description="搜索关键词或问题")
    time_range: str = Field(
        default="week",
        description="时间范围，可选 day/week/month/year，仅用于提示",
    )


class FastSearchTool(StructuredTool):
    """Quick, offline-friendly search stub."""

    def __init__(self, **kwargs):
        super().__init__(
            func=self._run,
            coroutine=self._arun,
            name="fast_search",
            description="快速事实搜索（本地模拟），返回摘要与若干来源链接。",
            args_schema=FastSearchInput,
            return_direct=False,
            handle_tool_error=True,
            **kwargs,
        )

    def _run(self, **kwargs) -> Dict[str, Any]:
        try:
            payload = FastSearchInput(**kwargs)
        except Exception as exc:
            return {"error": f"参数错误: {exc}"}

        summary = (
            f"针对“{payload.query}”的快速搜索摘要（时间范围: {payload.time_range}）。"
            "这是基于缓存语料的模拟结果，可用于为 LLM 提供上下文。"
        )
        results = [
            {
                "title": f"{payload.query} - 参考 {idx+1}",
                "snippet": f"与“{payload.query}”相关的要点摘要示例 {idx+1}。",
                "url": f"https://example.com/search/{idx+1}",
            }
            for idx in range(3)
        ]
        return {"query": payload.query, "summary": summary, "results": results}

    async def _arun(self, **kwargs) -> Dict[str, Any]:
        return self._run(**kwargs)


def create_tool() -> FastSearchTool:
    return FastSearchTool()
