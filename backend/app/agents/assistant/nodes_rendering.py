from __future__ import annotations

from typing import Any

from app.ai.memory_models import MemoryItem
from app.utils.serialization import json_preview


def render_history_block(history: list[dict[str, Any]], *, max_rounds: int) -> str:
    if not history:
        return ""
    lines: list[str] = []
    for item in history[-max(max_rounds, 1) :]:
        role = item.get("role")
        content = item.get("content")
        lines.append(f"{role}: {content}")
    return "近期对话历史：\n" + "\n".join(lines)


def summarize_memories(memories: list[MemoryItem], *, max_items: int = 5) -> str:
    lines = ["记忆摘要："]
    for item in memories[: max(max_items, 1)]:
        prefix = f"[{item.score:.2f}] " if item.score is not None else ""
        lines.append(f"- {prefix}{item.text}")
    return "\n".join(lines)


def summarize_poi_results(
    poi_results: list[dict[str, Any]], *, max_items: int = 5
) -> str:
    lines = ["附近兴趣点："]
    for item in poi_results[: max(max_items, 1)]:
        name = item.get("name") or "POI"
        category = item.get("category") or ""
        distance = item.get("distance_m")
        dist_text = f"（约 {int(distance)} 米）" if distance is not None else ""
        lines.append(f"- {name} {category}{dist_text}".strip())
    return "\n".join(lines)


def summarize_trip(trip_data: dict[str, Any]) -> str:
    if not trip_data:
        return ""
    title = trip_data.get("title") or "行程"
    destination = trip_data.get("destination") or ""
    day_cards = trip_data.get("day_cards") or []
    lines = [f"{title} {destination}".strip()]
    for day in day_cards:
        day_index = day.get("day_index", 0)
        date = day.get("date") or ""
        lines.append(f"Day {day_index} {date}".strip())
        for sub in day.get("sub_trips") or []:
            activity = sub.get("activity") or sub.get("loc_name") or "活动"
            start = sub.get("start_time") or ""
            end = sub.get("end_time") or ""
            lines.append(f"- {activity} {start}-{end}".strip())
    return "\n".join(lines)


def summarize_tool_result(
    *,
    selected_tool: str | None,
    tool_result: Any,
    max_preview_len: int = 400,
) -> str:
    tool_name = selected_tool or "tool"
    if isinstance(tool_result, str):
        return f"工具 {tool_name} 返回：{tool_result}"
    if isinstance(tool_result, dict):
        preview = json_preview(tool_result, max_len=max_preview_len)
        return f"工具 {tool_name} 返回数据：{preview}"
    return f"工具 {tool_name} 已执行。"


def build_fallback_answer(
    *,
    query: str,
    context_text: str,
    poi_results: list[dict[str, Any]] | None,
    tool_result: Any,
    selected_tool: str | None,
    trip_data: dict[str, Any] | None,
    memories: list[MemoryItem],
) -> str:
    if poi_results:
        return f"基于当前位置为你找到的附近地点：\n{context_text}"
    if tool_result:
        return f"基于工具 {selected_tool or ''} 的结果：\n{context_text}"
    if trip_data:
        trip_intro = trip_data.get("title") or "你的行程"
        return f"{trip_intro} 的简要安排如下：\n{context_text}"
    if memories:
        return f"结合你的记忆（{len(memories)} 条），建议：\n{context_text}"
    return f"关于“{query}”暂时没有额外上下文，建议提供更多细节。"


def guess_poi_type(query: str) -> str | None:
    lowered = query.lower()
    if any(keyword in lowered for keyword in ["吃", "餐", "美食", "food"]):
        return "food"
    if any(keyword in lowered for keyword in ["景点", "景区", "游玩", "sight"]):
        return "sight"
    if any(keyword in lowered for keyword in ["住", "酒店", "hotel"]):
        return "hotel"
    return None
