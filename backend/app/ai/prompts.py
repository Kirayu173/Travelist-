from __future__ import annotations

import time
from dataclasses import dataclass

from app.core.db import session_scope
from app.core.logging import get_logger
from app.core.settings import settings
from app.models.ai_schemas import PromptSchema, PromptUpdatePayload
from app.models.orm import AiPrompt


@dataclass(slots=True)
class PromptTemplate:
    key: str
    title: str
    role: str
    content: str
    version: int = 1
    tags: list[str] | None = None


DEFAULT_PROMPTS: dict[str, PromptTemplate] = {
    "assistant.system.main": PromptTemplate(
        key="assistant.system.main",
        title="助手主提示词",
        role="system",
        content=(
            "你是 Travelist+ 的行程助手，负责解读用户问题、读取行程/记忆，"
            "并以简洁、温和、可执行的方式作答。回答时优先使用已知行程与记忆，"
            "明确告知信息来源；若不确定，请坦诚说明。"
        ),
    ),
    "assistant.intent.classify": PromptTemplate(
        key="assistant.intent.classify",
        title="意图识别与工具选择",
        role="system",
        content=(
            "根据用户的问题判断意图 intent，可选值：trip_query（查询行程）或 "
            "general_qa（常规问答）。仅输出 JSON: "
            '{"intent": "trip_query" | "general_qa", "reason": "..."}'
        ),
    ),
    "assistant.response.formatter": PromptTemplate(
        key="assistant.response.formatter",
        title="回答格式化",
        role="system",
        content=(
            "你正在回复 Travelist+ 用户，请将提供的行程/记忆上下文整合成自然语言。"
            "规则：1) 有行程信息时按时间顺序描述；2) 适当引用召回记忆；"
            "3) 语气友好，尽量给出可执行建议；4) 无相关信息时礼貌说明。"
        ),
    ),
    "assistant.fallback": PromptTemplate(
        key="assistant.fallback",
        title="兜底回答",
        role="system",
        content="直观、简短地回答用户问题，若缺少信息则告知对方需要哪些信息。",
    ),
    "assistant.tools.selector": PromptTemplate(
        key="assistant.tools.selector",
        title="工具选择",
        role="system",
        content=(
            "你是一个工具选择器。依据用户问题、意图与可用工具描述，返回 JSON："
            '{"tool": "<tool_name 或 none>", "arguments": {...}, '
            '"reason": "简述选择原因"}。'
            "只返回 JSON，优先选择最贴切的问题解决工具；若无需工具，tool 填写 none。"
        ),
    ),
    "chat_demo.system": PromptTemplate(
        key="chat_demo.system",
        title="Demo System Prompt",
        role="system",
        content=(
            "你是一名友好且有用的AI助手，耐心、准确、诚实地回答用户问题。"
            "如果不知道答案，请直接说明。"
        ),
    ),
}


class PromptRegistry:
    """Unified prompt storage with DB overrides and in-memory cache."""

    def __init__(self, cache_ttl: int = 60) -> None:
        self._cache_ttl = max(cache_ttl, 1)
        self._cache: dict[str, tuple[float, PromptSchema]] = {}
        self._logger = get_logger(__name__)

    def get_prompt(self, key: str) -> PromptSchema:
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and cached[0] > now:
            return cached[1]

        prompt = self._load_from_db(key) or self._load_default(key)
        if prompt is None:
            msg = f"prompt not found for key={key}"
            raise KeyError(msg)
        self._cache[key] = (now + self._cache_ttl, prompt)
        return prompt

    def list_prompts(self) -> list[PromptSchema]:
        prompts: dict[str, PromptSchema] = {}
        for key, template in DEFAULT_PROMPTS.items():
            prompts[key] = self._template_to_schema(template)

        with session_scope() as session:
            rows = (
                session.query(AiPrompt)
                .order_by(AiPrompt.updated_at.desc(), AiPrompt.version.desc())
                .all()
            )
            for row in rows:
                prompts[row.key] = self._row_to_schema(row)

        for schema in prompts.values():
            schema.default_content = DEFAULT_PROMPTS.get(
                schema.key,
                PromptTemplate(
                    key=schema.key,
                    title=schema.title,
                    role=schema.role,
                    content=schema.content,
                ),
            ).content
        return sorted(prompts.values(), key=lambda item: item.key)

    def reset_prompt(self, key: str) -> PromptSchema:
        with session_scope() as session:
            session.query(AiPrompt).filter(AiPrompt.key == key).delete()
            session.commit()
        self.invalidate(key)
        return self.get_prompt(key)

    def update_prompt(self, key: str, payload: PromptUpdatePayload) -> PromptSchema:
        default = DEFAULT_PROMPTS.get(key)
        with session_scope() as session:
            row: AiPrompt | None = (
                session.query(AiPrompt).filter(AiPrompt.key == key).one_or_none()
            )
            if payload.reset_default:
                session.query(AiPrompt).filter(AiPrompt.key == key).delete()
                session.commit()
                self.invalidate(key)
                return self.get_prompt(key)

            if row is None:
                default_tags = list(default.tags or []) if default else []
                row = AiPrompt(
                    key=key,
                    title=payload.title or (default.title if default else key),
                    role=payload.role or (default.role if default else "system"),
                    content=payload.content
                    or (default.content if default else "请补充提示词内容"),
                    tags=payload.tags if payload.tags is not None else default_tags,
                )
                session.add(row)
            else:
                if payload.title:
                    row.title = payload.title
                if payload.role:
                    row.role = payload.role
                if payload.content is not None:
                    row.content = payload.content
                    row.version = (row.version or 0) + 1
                if payload.tags is not None:
                    row.tags = payload.tags
                if payload.is_active is not None:
                    row.is_active = payload.is_active
            row.updated_by = payload.updated_by or row.updated_by
            session.commit()
            session.refresh(row)
        self.invalidate(key)
        return self.get_prompt(key)

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._cache.clear()
        else:
            self._cache.pop(key, None)

    def _load_from_db(self, key: str) -> PromptSchema | None:
        with session_scope() as session:
            row = (
                session.query(AiPrompt)
                .filter(AiPrompt.key == key, AiPrompt.is_active.is_(True))
                .order_by(AiPrompt.version.desc(), AiPrompt.updated_at.desc())
                .first()
            )
            if row is None:
                return None
            return self._row_to_schema(row)

    def _load_default(self, key: str) -> PromptSchema | None:
        template = DEFAULT_PROMPTS.get(key)
        if template is None:
            return None
        return self._template_to_schema(template)

    @staticmethod
    def _row_to_schema(row: AiPrompt) -> PromptSchema:
        tags: list[str] = []
        if isinstance(row.tags, list):
            tags = row.tags
        elif isinstance(row.tags, dict):
            tags = [f"{k}:{v}" for k, v in row.tags.items()]
        return PromptSchema(
            key=row.key,
            title=row.title,
            role=row.role,
            content=row.content,
            version=row.version or 1,
            tags=tags,
            is_active=bool(row.is_active),
            updated_at=row.updated_at,
            updated_by=row.updated_by,
            default_content=DEFAULT_PROMPTS.get(
                row.key,
                PromptTemplate(
                    key=row.key,
                    title=row.title,
                    role=row.role,
                    content=row.content,
                ),
            ).content,
        )

    @staticmethod
    def _template_to_schema(template: PromptTemplate) -> PromptSchema:
        return PromptSchema(
            key=template.key,
            title=template.title,
            role=template.role,
            content=template.content,
            version=template.version,
            tags=list(template.tags) if template.tags else [],
            is_active=True,
            updated_at=None,
            updated_by=None,
            default_content=template.content,
        )


_registry: PromptRegistry | None = None


def get_prompt_registry() -> PromptRegistry:
    global _registry
    if _registry is None:
        _registry = PromptRegistry(cache_ttl=settings.ai_prompt_cache_ttl)
    return _registry
