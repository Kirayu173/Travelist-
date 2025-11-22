from __future__ import annotations

from typing import Any, Dict, List

from app.agents.tools.common.logging import tool_logger
from langchain_core.tools.structured import StructuredTool
from pydantic import BaseModel, Field, field_validator

logger = tool_logger("deep_extract")


class DeepExtractInput(BaseModel):
    urls: List[str] = Field(..., description="要抓取的网页 URL 列表，最多 10 条")
    query: str = Field(..., description="提取的关键信息需求描述")

    @field_validator("urls")
    @classmethod
    def ensure_urls(cls, value: List[str]) -> List[str]:
        if not value:
            msg = "urls cannot be empty"
            raise ValueError(msg)
        if len(value) > 10:
            msg = "urls must not exceed 10 items"
            raise ValueError(msg)
        return value


class DeepExtractTool(StructuredTool):
    """Summarise a set of URLs without external calls (offline stub)."""

    def __init__(self, **kwargs):
        super().__init__(
            func=self._run,
            coroutine=self._arun,
            name="deep_extract",
            description="从多个 URL 提取关键信息的结构化结果（本地模拟），用于快速摘要。",
            args_schema=DeepExtractInput,
            return_direct=False,
            handle_tool_error=True,
            **kwargs,
        )

    def _run(self, **kwargs) -> Dict[str, Any]:
        try:
            payload = DeepExtractInput(**kwargs)
        except Exception as exc:
            return {"error": f"参数错误: {exc}"}

        records: list[dict[str, Any]] = []
        for url in payload.urls:
            records.append(
                {
                    "url": url,
                    "status": "success",
                    "title": url.split("/")[-1] or url,
                    "content": f"围绕 {payload.query} 的模拟摘要，来源 {url}",
                }
            )
        summary = {
            "query": payload.query,
            "total_urls": len(records),
            "success_count": len(records),
            "failed_count": 0,
        }
        return {"summary": summary, "records": records}

    async def _arun(self, **kwargs) -> Dict[str, Any]:
        return self._run(**kwargs)


def create_tool() -> DeepExtractTool:
    return DeepExtractTool()
