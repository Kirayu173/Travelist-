from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class WeatherQuerySpec:
    locations: list[str]
    target_date: dt.date | None
    day_offset: int | None
    day_label: str | None


_DATE_RE = re.compile(r"(20\d{2})[.\-/年](\d{1,2})[.\-/月](\d{1,2})日?")


def resolve_weather_date(query: str, *, base_date: dt.date) -> tuple[dt.date | None, int | None, str | None]:
    """
    Resolve target date for CN queries like 今天/明天/后天/大后天 or explicit YYYY-MM-DD.

    Returns (target_date, day_offset, day_label). Offsets are relative to base_date.
    """
    text = (query or "").strip()
    if not text:
        return None, None, None

    match = _DATE_RE.search(text)
    if match:
        year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        try:
            target = dt.date(year, month, day)
        except ValueError:
            target = None
        if target is None:
            return None, None, None
        offset = (target - base_date).days
        if offset == 0:
            return target, 0, "今天"
        if offset == 1:
            return target, 1, "明天"
        if offset == 2:
            return target, 2, "后天"
        if offset == 3:
            return target, 3, "大后天"
        return target, offset, None

    relative_map: list[tuple[str, int, str]] = [
        ("大后天", 3, "大后天"),
        ("后天", 2, "后天"),
        ("明天", 1, "明天"),
        ("明日", 1, "明天"),
        ("明早", 1, "明天"),
        ("明晚", 1, "明天"),
        ("今天", 0, "今天"),
        ("今日", 0, "今天"),
        ("现在", 0, "今天"),
        ("今晚", 0, "今天"),
        ("今夜", 0, "今天"),
    ]
    for token, offset, label in relative_map:
        if token in text:
            return base_date + dt.timedelta(days=offset), offset, label
    return None, None, None


def extract_weather_locations(query: str) -> list[str]:
    """
    Best-effort extraction of location names from Chinese weather queries.

    Examples:
    - "明天广州天气怎么样" -> ["广州"]
    - "广州明天的天气" -> ["广州"]
    """
    text = (query or "").strip()
    if not text:
        return []

    text = _DATE_RE.sub("", text)
    text = re.sub(
        r"(今天|今日|现在|今晚|今夜|明天|明日|明早|明晚|后天|大后天|本周|这周|下周|周末|这个周末|未来\d+天|接下来\d+天)",
        "",
        text,
    )
    text = re.sub(
        r"(天气预报|天气情况|天气|气温|温度|下雨|降雨|风力|风向|空气质量|冷不冷|热不热|怎么样|如何|咋样|呢|呀|吧)",
        "",
        text,
    )
    text = re.sub(r"[\s，,。．.？！?!：:；;（）()【】\[\]“”\"'<>《》、/\\-]+", " ", text).strip()
    if not text:
        return []

    parts = re.split(r"\s+|和|与|及|、", text)
    locations = [p.strip("的 ") for p in parts if p and p.strip()]
    return [loc for loc in locations if loc]


def build_weather_query_spec(query: str, *, base_date: dt.date) -> WeatherQuerySpec:
    target_date, day_offset, day_label = resolve_weather_date(query, base_date=base_date)
    locations = extract_weather_locations(query)
    return WeatherQuerySpec(
        locations=locations,
        target_date=target_date,
        day_offset=day_offset,
        day_label=day_label,
    )

