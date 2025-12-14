from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.agents.tools.itinerary import (
    ItineraryAddSubTripTool,
    ItineraryAdjustTimesTool,
    ItineraryReplacePoiTool,
    ItinerarySession,
    ItineraryValidateDayTool,
)
from app.agents.tools.itinerary.session import parse_hhmm
from app.agents.tools.registry import ToolExecutionError, ToolRegistry
from app.ai import AiChatRequest, AiChatResult, AiClient, AiMessage, get_ai_client
from app.core.settings import settings
from app.utils.json_utils import json_dumps


@dataclass(slots=True)
class ToolCallingMetrics:
    llm_calls: int = 0
    tool_calls: int = 0
    steps: int = 0
    llm_latency_ms: float = 0.0
    llm_tokens_total: int = 0


def _schema_for_tool(args_schema: Any) -> dict[str, Any]:
    if not args_schema:
        return {"type": "object", "properties": {}, "additionalProperties": True}
    schema = args_schema.model_json_schema()
    return {
        "type": schema.get("type") or "object",
        "properties": schema.get("properties") or {},
        "required": schema.get("required") or [],
        "additionalProperties": schema.get("additionalProperties", False),
    }


def _build_ollama_tools(registry: ToolRegistry) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for tool in registry.available():
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": _schema_for_tool(tool.args_schema),
                },
            }
        )
    return tools


def _extract_tool_calls(result: AiChatResult) -> list[dict[str, Any]]:
    raw = result.raw if isinstance(result.raw, dict) else {}
    message = raw.get("message") if isinstance(raw.get("message"), dict) else {}
    calls = message.get("tool_calls")
    return list(calls) if isinstance(calls, list) else []


def _parse_tool_args(raw_args: Any) -> dict[str, Any]:
    if raw_args is None:
        return {}
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str):
        text = raw_args.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


class ItineraryToolCallingAgent:
    """Tool-calling itinerary builder (sub_trip granularity) with repair loop."""

    def __init__(self, ai_client: AiClient | None = None) -> None:
        self._ai_client = ai_client or get_ai_client()

    async def plan_day(
        self,
        *,
        session: ItinerarySession,
        outline: dict[str, Any],
        context: list[dict[str, Any]],
        candidate_pois: list[dict[str, Any]],
        used_pois: set[tuple[str, str]],
    ) -> tuple[Any, dict[str, Any]]:
        if (settings.ai_provider or settings.llm_provider) == "mock":
            return self._plan_day_deterministic(session, candidate_pois), {
                "llm_calls": 0,
                "tool_calls": 0,
                "steps": 0,
                "llm_latency_ms": 0.0,
            }

        registry = ToolRegistry()
        add_tool = ItineraryAddSubTripTool(session)
        replace_tool = ItineraryReplacePoiTool(session)
        adjust_tool = ItineraryAdjustTimesTool(session)
        validate_tool = ItineraryValidateDayTool(session)
        for tool in (add_tool, replace_tool, adjust_tool, validate_tool):
            registry.register_structured_tool(
                name=getattr(tool, "name", tool.__class__.__name__),
                description=getattr(tool, "description", tool.__doc__ or "").strip(),
                args_schema=getattr(tool, "args_schema", None),
                category="itinerary",
                loader=lambda inst=tool: inst,
                source="itinerary.agent",
            )

        tools_spec = _build_ollama_tools(registry)
        metrics = ToolCallingMetrics()
        min_sub_trips = max(int(getattr(settings, "plan_deep_day_min_sub_trips", 3)), 1)

        system_prompt = (
            "你是 Travelist+ 行程规划器（工具调用模式）。\n"
            f"目标：为给定日期生成至少 {min_sub_trips} 个 sub_trips（建议 3~5 个），"
            "时间不重叠，order_index 连续，从 0 开始。\n"
            "约束：必须从 candidate_pois 里选择 POI，避免重复使用 POI（used_pois）。\n"
            "输出规则：不要直接输出行程 JSON；只能通过工具调用修改行程。\n"
            "流程建议：优先多次调用 itinerary_add_sub_trip，然后 "
            "itinerary_adjust_times，最后 itinerary_validate_day。\n"
        )

        user_payload = {
            "task": "plan_day_with_tools",
            "destination": session.request.destination,
            "preferences": session.request.preferences,
            "day_index": session.day_index,
            "date": session.date.isoformat(),
            "outline": outline,
            "context": context,
            "candidate_pois": candidate_pois,
            "used_pois": [
                {"provider": p, "provider_id": pid} for p, pid in sorted(used_pois)
            ],
        }

        messages: list[AiMessage] = [
            AiMessage(role="system", content=system_prompt),
            AiMessage(role="user", content=json_dumps(user_payload)),
        ]

        max_steps = max(int(getattr(settings, "plan_deep_tool_max_steps", 18)), 6)
        for step in range(max_steps):
            metrics.steps = step + 1
            request = AiChatRequest(
                messages=messages,
                response_format="text",
                timeout_s=float(getattr(settings, "plan_deep_timeout_s", 30.0)),
                model=str(getattr(settings, "plan_deep_model", "") or "").strip()
                or None,
                temperature=float(getattr(settings, "plan_deep_temperature", 0.2)),
                max_tokens=int(getattr(settings, "plan_deep_max_tokens", 1200)),
                tools=tools_spec,
            )
            result = await self._ai_client.chat(request)
            metrics.llm_calls += 1
            metrics.llm_latency_ms = round(
                metrics.llm_latency_ms + result.latency_ms, 3
            )
            metrics.llm_tokens_total += int(result.usage_tokens or 0)

            tool_calls = _extract_tool_calls(result)
            if tool_calls:
                metrics.tool_calls += len(tool_calls)
                messages.append(
                    AiMessage(
                        role="assistant",
                        content=result.content or "",
                        tool_calls=tool_calls,
                    )
                )
                for idx, call in enumerate(tool_calls):
                    fn = (
                        call.get("function")
                        if isinstance(call.get("function"), dict)
                        else {}
                    )
                    name = str(fn.get("name") or "").strip()
                    args = _parse_tool_args(fn.get("arguments"))
                    tool_id = str(call.get("id") or f"{name}_{idx}")
                    output: Any
                    try:
                        tool = registry.get(name)
                        if not tool:
                            output = {"ok": False, "error": f"unknown_tool:{name}"}
                        else:
                            output = await tool.invoke(args)
                    except ToolExecutionError as exc:
                        output = {"ok": False, "error": str(exc)}
                    except Exception as exc:  # noqa: BLE001
                        output = {"ok": False, "error": str(exc)[:200]}
                    messages.append(
                        AiMessage(
                            role="tool",
                            tool_call_id=tool_id,
                            content=json_dumps(output),
                        )
                    )
                # Encourage validation after tool calls.
                validation = validate_tool._run(day_index=session.day_index)
                if (
                    validation.get("issue_count") == 0
                    and len(session.day_card.sub_trips) >= min_sub_trips
                ):
                    return session.day_card, {
                        "llm_calls": metrics.llm_calls,
                        "tool_calls": metrics.tool_calls,
                        "steps": metrics.steps,
                        "llm_latency_ms": metrics.llm_latency_ms,
                        "llm_tokens_total": metrics.llm_tokens_total,
                    }
                remaining = max(min_sub_trips - len(session.day_card.sub_trips), 0)
                messages.append(
                    AiMessage(
                        role="user",
                        content=(
                            "当前 day_card 校验未通过，请优先调用 "
                            "itinerary_adjust_times / itinerary_replace_poi 进行修复，"
                            "并在最后调用 "
                            "itinerary_validate_day。"
                            f"\nissues={json_dumps(validation)}"
                            + (
                                f"\n还需要再添加 {remaining} 个 sub_trips。"
                                if remaining
                                else ""
                            )
                        ),
                    )
                )
                continue

            # No tool calls: either model thinks it's done or it's off-rails.
            validation = validate_tool._run(day_index=session.day_index)
            if (
                validation.get("issue_count") == 0
                and len(session.day_card.sub_trips) >= min_sub_trips
            ):
                return session.day_card, {
                    "llm_calls": metrics.llm_calls,
                    "tool_calls": metrics.tool_calls,
                    "steps": metrics.steps,
                    "llm_latency_ms": metrics.llm_latency_ms,
                    "llm_tokens_total": metrics.llm_tokens_total,
                }
            remaining = max(min_sub_trips - len(session.day_card.sub_trips), 0)
            messages.append(
                AiMessage(
                    role="user",
                    content=(
                        "请继续使用工具完成规划：先添加 sub_trips，"
                        "再修复时间与重复 POI，最后校验。"
                        f"\nissues={json_dumps(validation)}"
                        + (
                            f"\n还需要再添加 {remaining} 个 sub_trips。"
                            if remaining
                            else ""
                        )
                    ),
                )
            )

        # hard failure: return best-effort but signal invalid
        validation = ItineraryValidateDayTool(session)._run(day_index=session.day_index)
        raise RuntimeError(f"tool_planning_failed: {json_dumps(validation)[:400]}")

    @staticmethod
    def _plan_day_deterministic(
        session: ItinerarySession, candidate_pois: list[dict[str, Any]]
    ):
        interests = []
        prefs = (
            session.request.preferences
            if isinstance(session.request.preferences, dict)
            else {}
        )
        raw = prefs.get("interests")
        if isinstance(raw, list):
            interests = [str(x).strip() for x in raw if str(x).strip()]
        if not interests:
            interests = ["sight", "food"]

        slots = ["morning", "morning", "afternoon", "afternoon"]
        chosen = []
        for cat in interests + ["sight", "food", "museum", "park", "shopping"]:
            for poi in candidate_pois:
                if poi.get("category") != cat:
                    continue
                key = (
                    str(poi.get("provider") or ""),
                    str(poi.get("provider_id") or ""),
                )
                if key in session.used_pois:
                    continue
                chosen.append(poi)
                if len(chosen) >= 4:
                    break
            if len(chosen) >= 4:
                break
        if not chosen:
            chosen = candidate_pois[:2]

        # build via session (reuse time logic)
        start_map = {"morning": "09:00", "afternoon": "13:30", "evening": "18:00"}
        last_end = None
        for idx, poi in enumerate(chosen[:4]):
            slot = slots[idx] if idx < len(slots) else "afternoon"
            start = parse_hhmm(start_map[slot])
            if last_end:
                start = max(start, last_end)
            sub = session.add_sub_trip(
                slot=slot,
                poi=poi,
                start_time=start,
                duration_min=90,
                transport="walk",
            )
            last_end = sub.end_time
        return session.day_card
