from __future__ import annotations

import re
from typing import Any, Dict, List

import requests
from app.agents.tools.common.base import TravelistBaseTool
from app.agents.tools.common.logging import get_tool_logger, log_tool_event
from pydantic import BaseModel, Field, field_validator

logger = get_tool_logger("deep_extract")


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


class DeepExtractTool(TravelistBaseTool):
    """抓取并摘要指定 URLs 的内容（直接 HTTP 请求 + 简易清洗）。"""

    name: str = "deep_extract"
    description: str = "从多个 URL 提取关键信息的结构化结果（本地模拟），用于快速摘要。"
    args_schema: type[BaseModel] = DeepExtractInput

    def _run(self, **kwargs) -> Dict[str, Any]:
        try:
            payload = DeepExtractInput(**kwargs)
        except Exception as exc:
            log_tool_event(
                "deep_extract",
                event="invoke",
                status="invalid_args",
                request=kwargs,
                error_code="invalid_params",
                message=str(exc),
            )
            return {"error": f"参数错误: {exc}"}

        records: list[dict[str, Any]] = []
        for url in payload.urls:
            record = self._extract_url(url, payload.query)
            records.append(record)
        summary = {
            "query": payload.query,
            "total_urls": len(records),
            "success_count": len(records),
            "failed_count": 0,
        }
        response = {"summary": summary, "records": records}
        log_tool_event(
            "deep_extract",
            event="invoke",
            status="ok",
            request=kwargs,
            response=response,
            raw_input=kwargs,
            output=response,
        )
        return {"summary": summary, "records": records}

    def _extract_url(self, url: str, query: str) -> Dict[str, Any]:
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            text = resp.text
            cleaned = self._clean_html(text)
            snippet = cleaned[:800]
            record = {
                "url": url,
                "status": "success",
                "title": url.split("/")[-1] or url,
                "content": snippet,
            }
            log_tool_event(
                "deep_extract",
                event="fetch",
                status="ok",
                request={"url": url},
                response={"length": len(text)},
                raw_input=query,
                output=record,
            )
            return record
        except Exception as exc:
            log_tool_event(
                "deep_extract",
                event="fetch",
                status="error",
                request={"url": url},
                error_code="fetch_failed",
                message=str(exc),
            )
            return {"url": url, "status": "failed", "error": str(exc)}

    @staticmethod
    def _clean_html(text: str) -> str:
        text = re.sub(r"<script.*?>.*?</script>", "", text, flags=re.S | re.I)
        text = re.sub(r"<style.*?>.*?</style>", "", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    async def _arun(self, **kwargs) -> Dict[str, Any]:
        return self._run(**kwargs)


def create_tool() -> DeepExtractTool:
    return DeepExtractTool()
