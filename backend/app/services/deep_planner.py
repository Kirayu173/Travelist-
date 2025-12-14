from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date as dt_date
from datetime import datetime, timedelta
from datetime import time as dt_time
from time import perf_counter
from typing import Any

from app.agents.itinerary import ItineraryToolCallingAgent
from app.agents.tools.itinerary import ItinerarySession
from app.ai import AiClientError
from app.ai.memory_models import MemoryLevel
from app.core.logging import get_logger
from app.core.settings import settings
from app.models.plan_schemas import (
    DEFAULT_INTERESTS,
    PlanDayCardSchema,
    PlanRequest,
    PlanTripSchema,
)
from app.services.fast_planner import FastPlanner
from app.services.geocode_service import GeocodeService, get_geocode_service
from app.services.memory_service import MemoryService, get_memory_service
from app.services.poi_service import PoiService, get_poi_service
from pydantic import ValidationError


class DeepPlannerError(Exception):
    def __init__(self, message: str, *, code: int = 14089) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class _PoiRef:
    provider: str
    provider_id: str

    @classmethod
    def from_any(cls, payload: Any) -> "_PoiRef | None":
        if not isinstance(payload, dict):
            return None
        provider = str(payload.get("provider") or "").strip()
        provider_id = str(payload.get("provider_id") or "").strip()
        if not provider or not provider_id:
            return None
        return cls(provider=provider, provider_id=provider_id)

    @property
    def key(self) -> tuple[str, str]:
        return (self.provider, self.provider_id)


TraceFn = Callable[
    [str, str, float | None, dict[str, Any] | None],
    None,
]


def _parse_hhmm(value: str) -> dt_time:
    raw = str(value or "").strip()
    return datetime.strptime(raw, "%H:%M").time()


def _to_minutes(t: dt_time) -> int:
    return t.hour * 60 + t.minute


def _minutes_to_time(minutes: int) -> dt_time:
    minutes = max(int(minutes), 0)
    hour = min(minutes // 60, 23)
    minute = min(minutes % 60, 59)
    return dt_time(hour=hour, minute=minute)


def _activity_title(category: str) -> str:
    key = str(category or "").strip().lower()
    mapping = {
        "food": "美食探索",
        "sight": "景点游览",
        "museum": "博物馆参观",
        "park": "公园漫步",
        "hotel": "住宿安排",
        "shopping": "购物休闲",
    }
    return mapping.get(key, f"{category}体验" if category else "行程安排")


class DeepPlanner:
    """LLM-backed itinerary planner (mode=deep) with day-by-day generation."""

    PLANNER_NAME = "deep_llm_v1"

    def __init__(
        self,
        *,
        fast_planner: FastPlanner | None = None,
        poi_service: PoiService | None = None,
        geocode_service: GeocodeService | None = None,
        memory_service: MemoryService | None = None,
    ) -> None:
        self._fast_planner = fast_planner or FastPlanner(
            poi_service=poi_service or get_poi_service()
        )
        self._poi_service = poi_service or get_poi_service()
        self._geocode_service = geocode_service or get_geocode_service()
        self._memory_service = memory_service or get_memory_service()
        self._logger = get_logger(__name__)

    async def plan(
        self,
        request: PlanRequest,
        *,
        trace_id: str,
        trace: TraceFn,
    ) -> tuple[PlanTripSchema, dict[str, Any]]:
        if request.day_count <= 0:
            raise DeepPlannerError("Invalid date range", code=14070)

        max_days = max(
            int(getattr(settings, "plan_deep_max_days", settings.plan_max_days)),
            1,
        )
        if request.day_count > max_days:
            raise DeepPlannerError(
                f"day_count exceeds PLAN_DEEP_MAX_DAYS ({max_days})",
                code=14070,
            )

        merged_prefs = await self._merge_preferences_from_mem0(
            request.preferences,
            user_id=request.user_id,
        )
        request = request.model_copy(update={"preferences": merged_prefs})

        retries = max(int(getattr(settings, "plan_deep_retries", 1)), 0)
        fallback_to_fast = bool(getattr(settings, "plan_deep_fallback_to_fast", True))
        prompt_version = str(getattr(settings, "plan_deep_prompt_version", "v1"))

        metrics: dict[str, Any] = {
            "planner": self.PLANNER_NAME,
            "prompt_version": prompt_version,
            "seed_mode": request.seed_mode,
            "fallback_to_fast": False,
            "llm_calls": 0,
            "llm_retries": 0,
            "llm_latency_ms": 0.0,
            "llm_tokens_total": 0,
            "saved": bool(request.save),
        }

        seed_plan: PlanTripSchema | None = None
        if request.seed_mode == "fast":
            t0 = perf_counter()
            seed_request = request.model_copy(
                update={"mode": "fast", "async_": False, "seed_mode": None}
            )
            seed_plan, seed_metrics = await self._fast_planner.plan(seed_request)
            metrics["seed"] = seed_metrics.get("seed")
            trace(
                "planner_seed_fast",
                "ok",
                (perf_counter() - t0) * 1000,
                {"planner": seed_metrics.get("planner")},
            )

        outline = self._build_outline(seed_plan=seed_plan, request=request)
        candidates = await self._load_candidate_pois(request)
        metrics["candidate_pois"] = len(candidates)

        used_pois: set[tuple[str, str]] = set()
        if seed_plan is not None:
            used_pois |= self._extract_used_pois(seed_plan)

        day_cards: list[PlanDayCardSchema] = []
        day_summaries: list[dict[str, Any]] = []
        try:
            for day_index in range(request.day_count):
                current_date = request.start_date + timedelta(days=day_index)
                day_card, call_metrics = await self._generate_day_with_retries(
                    request=request,
                    trace_id=trace_id,
                    trace=trace,
                    day_index=day_index,
                    date=current_date,
                    outline=outline,
                    context=day_summaries,
                    candidate_pois=candidates,
                    used_pois=used_pois,
                    retries=retries,
                )
                metrics["llm_calls"] += call_metrics.get("llm_calls", 0)
                metrics["llm_retries"] += call_metrics.get("llm_retries", 0)
                metrics["llm_latency_ms"] = round(
                    float(metrics["llm_latency_ms"])
                    + float(call_metrics.get("llm_latency_ms") or 0.0),
                    3,
                )
                metrics["llm_tokens_total"] = int(metrics["llm_tokens_total"]) + int(
                    call_metrics.get("llm_tokens_total") or 0
                )
                day_cards.append(day_card)
                used_pois |= self._extract_used_pois(day_card)
                day_summaries.append(self._summarize_day(day_card))

            plan = self._assemble_trip(
                request=request, day_cards=day_cards, seed_plan=seed_plan
            )
            await self._write_plan_summary_to_mem0(
                request, plan=plan, trace_id=trace_id
            )
            return plan, metrics
        except DeepPlannerError as exc:
            if fallback_to_fast:
                trace(
                    "planner_deep_fallback", "ok", None, {"reason": exc.message[:200]}
                )
                fallback_request = request.model_copy(
                    update={"mode": "fast", "async_": False, "seed_mode": None}
                )
                fallback_plan, fallback_metrics = await self._fast_planner.plan(
                    fallback_request
                )
                metrics["fallback_to_fast"] = True
                metrics["fallback_planner"] = fallback_metrics.get("planner")
                metrics["fallback_reason"] = exc.message
                return fallback_plan, metrics
            raise
        except Exception as exc:
            self._logger.warning(
                "deep_planner.failed",
                extra={"trace_id": trace_id, "error": str(exc)},
            )
            if fallback_to_fast:
                trace("planner_deep_fallback", "ok", None, {"reason": str(exc)[:200]})
                fallback_request = request.model_copy(
                    update={"mode": "fast", "async_": False, "seed_mode": None}
                )
                fallback_plan, fallback_metrics = await self._fast_planner.plan(
                    fallback_request
                )
                metrics["fallback_to_fast"] = True
                metrics["fallback_planner"] = fallback_metrics.get("planner")
                return fallback_plan, metrics
            raise DeepPlannerError("deep planning failed", code=14089) from exc

    async def _merge_preferences_from_mem0(
        self,
        preferences: Any,
        *,
        user_id: int,
    ) -> dict[str, Any]:
        merged: dict[str, Any] = (
            dict(preferences) if isinstance(preferences, dict) else {}
        )

        try:
            items = await self._memory_service.search_memory(
                user_id=user_id,
                level=MemoryLevel.user,
                query="travel_preferences",
                k=3,
            )
        except Exception:  # pragma: no cover - defensive
            items = []

        mem0_prefs: dict[str, Any] = {}
        for item in items:
            metadata = item.metadata if isinstance(item.metadata, dict) else {}
            candidate = metadata.get("preferences")
            if isinstance(candidate, dict) and candidate:
                mem0_prefs = candidate
                break
            # fall back: try parse JSON text
            try:
                text = str(item.text or "")
                parsed = json.loads(text)
                if isinstance(parsed, dict) and isinstance(
                    parsed.get("preferences"), dict
                ):
                    mem0_prefs = parsed["preferences"]
                    break
            except Exception:
                continue

        for key in ("interests", "pace", "budget_level"):
            if key == "interests":
                current = merged.get("interests")
                is_default = current == DEFAULT_INTERESTS
                if is_default and isinstance(mem0_prefs.get("interests"), list):
                    merged["interests"] = mem0_prefs["interests"]
                continue

            if key in merged and merged.get(key) not in (None, "", [], {}):
                continue
            if key in mem0_prefs:
                merged[key] = mem0_prefs[key]

        return merged

    async def _write_plan_summary_to_mem0(
        self,
        request: PlanRequest,
        *,
        plan: PlanTripSchema,
        trace_id: str,
    ) -> None:
        try:
            interests = []
            prefs = request.preferences if isinstance(request.preferences, dict) else {}
            raw = prefs.get("interests")
            if isinstance(raw, list):
                interests = [str(x).strip() for x in raw if str(x).strip()]
            text = json.dumps(
                {
                    "type": "plan_summary",
                    "destination": request.destination,
                    "day_count": request.day_count,
                    "preferences": {
                        "interests": interests,
                        "pace": prefs.get("pace"),
                        "budget_level": prefs.get("budget_level"),
                    },
                    "trace_id": trace_id,
                },
                ensure_ascii=False,
            )
            await self._memory_service.write_memory(
                request.user_id,
                MemoryLevel.user,
                text,
                metadata={
                    "kind": "plan_summary",
                    "destination": request.destination,
                    "day_count": request.day_count,
                    "trace_id": trace_id,
                    "preferences": {
                        "interests": interests,
                        "pace": prefs.get("pace"),
                        "budget_level": prefs.get("budget_level"),
                    },
                },
            )
        except Exception:  # pragma: no cover - best effort
            return

    def _build_outline(
        self,
        *,
        seed_plan: PlanTripSchema | None,
        request: PlanRequest,
    ) -> dict[str, Any]:
        if seed_plan is None:
            return {
                "destination": request.destination,
                "start_date": request.start_date.isoformat(),
                "end_date": request.end_date.isoformat(),
                "day_count": request.day_count,
            }
        days = []
        for card in seed_plan.day_cards:
            days.append(
                {
                    "day_index": card.day_index,
                    "date": card.date.isoformat(),
                    "activities": [sub.activity for sub in card.sub_trips[:4]],
                }
            )
        return {
            "source": "seed_fast",
            "destination": seed_plan.destination,
            "day_count": seed_plan.day_count,
            "days": days,
        }

    async def _load_candidate_pois(self, request: PlanRequest) -> list[dict[str, Any]]:
        max_pois = max(int(getattr(settings, "plan_deep_max_pois", 24)), 1)
        try:
            center = await self._geocode_service.resolve_city_center(
                request.destination
            )
        except Exception:
            center = None

        interests: list[str] = []
        prefs = request.preferences if isinstance(request.preferences, dict) else {}
        raw = prefs.get("interests")
        if isinstance(raw, list):
            interests = [str(x).strip() for x in raw if str(x).strip()]
        if not interests:
            interests = ["sight", "food"]

        if center is None:
            return []

        seen: set[tuple[str, str]] = set()
        candidates: list[dict[str, Any]] = []
        per_type_limit = max(max_pois // max(len(interests), 1), 5)
        for poi_type in interests[:6]:
            try:
                items, meta = await self._poi_service.get_poi_around(
                    lat=center.lat,
                    lng=center.lng,
                    poi_type=poi_type,
                    limit=per_type_limit,
                )
            except Exception as exc:  # pragma: no cover - best effort
                self._logger.warning(
                    "deep_planner.poi_failed",
                    extra={
                        "destination": request.destination,
                        "poi_type": poi_type,
                        "error": str(exc),
                    },
                )
                continue
            for item in items:
                provider = str(item.get("provider") or "").strip()
                provider_id = str(item.get("provider_id") or "").strip()
                if not provider or not provider_id:
                    continue
                key = (provider, provider_id)
                if key in seen:
                    continue
                seen.add(key)
                raw_payload = dict(item)
                payload = {
                    k: raw_payload.get(k)
                    for k in (
                        "provider",
                        "provider_id",
                        "name",
                        "category",
                        "addr",
                        "rating",
                        "lat",
                        "lng",
                        "distance_m",
                        "ext",
                    )
                    if k in raw_payload
                }
                payload.setdefault("ext", {})
                payload["ext"] = dict(payload.get("ext") or {})
                payload["ext"].setdefault("source", meta.get("source"))
                candidates.append(payload)
                if len(candidates) >= max_pois:
                    return candidates
        return candidates

    async def _generate_day_with_retries(
        self,
        *,
        request: PlanRequest,
        trace_id: str,
        trace: TraceFn,
        day_index: int,
        date: dt_date,
        outline: dict[str, Any],
        context: list[dict[str, Any]],
        candidate_pois: list[dict[str, Any]],
        used_pois: set[tuple[str, str]],
        retries: int,
    ) -> tuple[PlanDayCardSchema, dict[str, Any]]:
        attempts = retries + 1
        last_error: str | None = None
        call_metrics = {
            "llm_calls": 0,
            "llm_retries": 0,
            "llm_latency_ms": 0.0,
            "llm_tokens_total": 0,
        }

        for attempt in range(attempts):
            if attempt > 0:
                call_metrics["llm_retries"] += 1
            t0 = perf_counter()
            try:
                day_card, llm_result = await self._call_llm_plan_day(
                    request=request,
                    day_index=day_index,
                    date=date,
                    outline=outline,
                    context=context,
                    candidate_pois=candidate_pois,
                    used_pois=used_pois,
                )
                trace(
                    "planner_deep_day",
                    "ok",
                    (perf_counter() - t0) * 1000,
                    {
                        "day_index": day_index,
                        "attempt": attempt + 1,
                        "llm_calls": llm_result.get("llm_calls"),
                        "tool_calls": llm_result.get("tool_calls"),
                        "steps": llm_result.get("steps"),
                    },
                )
                call_metrics["llm_calls"] += int(llm_result.get("llm_calls") or 0)
                call_metrics["llm_latency_ms"] = round(
                    float(call_metrics["llm_latency_ms"])
                    + float(llm_result.get("latency_ms") or 0.0),
                    3,
                )
                call_metrics["llm_tokens_total"] = int(
                    call_metrics["llm_tokens_total"]
                ) + int(llm_result.get("tokens_total") or 0)
                self._validate_day_card(
                    request=request,
                    day_card=day_card,
                    expected_day_index=day_index,
                    expected_date=date,
                    used_pois=used_pois,
                )
                trace(
                    "plan_validate",
                    "ok",
                    None,
                    {"day_index": day_index},
                )
                return day_card, call_metrics
            except (DeepPlannerError, ValidationError) as exc:
                last_error = getattr(exc, "message", None) or str(exc)
                trace(
                    "planner_deep_day",
                    "error",
                    (perf_counter() - t0) * 1000,
                    {
                        "day_index": day_index,
                        "attempt": attempt + 1,
                        "error": last_error[:200],
                    },
                )
                continue
            except AiClientError as exc:
                last_error = exc.message
                trace(
                    "planner_deep_day",
                    "error",
                    (perf_counter() - t0) * 1000,
                    {
                        "day_index": day_index,
                        "attempt": attempt + 1,
                        "error_type": exc.type,
                        "error": exc.message,
                    },
                )
                continue

        raise DeepPlannerError(
            f"day_index={day_index} generation failed: {last_error or 'unknown'}",
            code=14089,
        )

    async def _call_llm_plan_day(
        self,
        *,
        request: PlanRequest,
        day_index: int,
        date: dt_date,
        outline: dict[str, Any],
        context: list[dict[str, Any]],
        candidate_pois: list[dict[str, Any]],
        used_pois: set[tuple[str, str]],
    ) -> tuple[PlanDayCardSchema, dict[str, Any]]:
        max_context_days = max(
            int(getattr(settings, "plan_deep_context_max_days", 3)), 0
        )
        recent = context[-max_context_days:] if max_context_days else []

        max_pois = max(int(getattr(settings, "plan_deep_max_pois", 24)), 1)
        trimmed_pois = candidate_pois[:max_pois]

        prev_used = set(used_pois)
        session_used = set(used_pois)
        session = ItinerarySession(
            request=request,
            day_index=day_index,
            date=date,
            candidate_pois=trimmed_pois,
            used_pois=session_used,
        )
        agent = ItineraryToolCallingAgent()
        try:
            day_card, tool_metrics = await agent.plan_day(
                session=session,
                outline=outline,
                context=recent,
                candidate_pois=trimmed_pois,
                used_pois=prev_used,
            )
        except AiClientError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise DeepPlannerError(str(exc)[:200]) from exc
        provider_name = str(
            getattr(settings, "ai_provider", None)
            or getattr(settings, "llm_provider", None)
            or ""
        ).strip()
        model_name = str(
            getattr(settings, "plan_deep_model", None)
            or getattr(settings, "ai_model_chat", None)
            or ""
        ).strip()
        llm_metrics = {
            "latency_ms": float(tool_metrics.get("llm_latency_ms") or 0.0),
            "tokens_total": int(tool_metrics.get("llm_tokens_total") or 0),
            "provider": provider_name,
            "model": model_name,
            "llm_calls": int(tool_metrics.get("llm_calls") or 0),
            "tool_calls": int(tool_metrics.get("tool_calls") or 0),
            "steps": int(tool_metrics.get("steps") or 0),
        }
        return day_card, llm_metrics

    def _validate_day_card(
        self,
        *,
        request: PlanRequest,
        day_card: PlanDayCardSchema,
        expected_day_index: int,
        expected_date: dt_date,
        used_pois: set[tuple[str, str]],
    ) -> None:
        if day_card.day_index != expected_day_index:
            msg = (
                f"day_index mismatch: expected={expected_day_index} "
                f"got={day_card.day_index}"
            )
            raise DeepPlannerError(msg)
        if day_card.date != expected_date:
            msg = (
                f"date mismatch: expected={expected_date.isoformat()} "
                f"got={day_card.date.isoformat()}"
            )
            raise DeepPlannerError(msg)

        orders: list[int] = []
        seen_order: set[int] = set()
        seen_pois: set[tuple[str, str]] = set()
        for sub in day_card.sub_trips:
            if sub.order_index is None:
                raise DeepPlannerError("sub_trip.order_index missing")
            if sub.order_index in seen_order:
                raise DeepPlannerError(f"duplicate order_index={sub.order_index}")
            seen_order.add(sub.order_index)
            orders.append(sub.order_index)

            ext = sub.ext if isinstance(sub.ext, dict) else {}
            poi_ref = _PoiRef.from_any(
                (ext.get("poi") if isinstance(ext, dict) else None)
            )
            if poi_ref:
                if poi_ref.key in used_pois:
                    msg = (
                        f"poi reused across days: {poi_ref.provider}/"
                        f"{poi_ref.provider_id}"
                    )
                    raise DeepPlannerError(msg)
                if poi_ref.key in seen_pois:
                    msg = (
                        f"poi duplicated in same day: {poi_ref.provider}/"
                        f"{poi_ref.provider_id}"
                    )
                    raise DeepPlannerError(msg)
                seen_pois.add(poi_ref.key)

        if orders:
            expected = list(range(len(orders)))
            if sorted(orders) != expected:
                raise DeepPlannerError("order_index must start at 0 and be continuous")

        # basic time window sanity (best-effort)
        try:
            day_start = _parse_hhmm(settings.plan_default_day_start)
            day_end = _parse_hhmm(settings.plan_default_day_end)
            start_min = _to_minutes(day_start)
            end_min = _to_minutes(day_end)
            for sub in day_card.sub_trips:
                if sub.start_time and _to_minutes(sub.start_time) < start_min:
                    raise DeepPlannerError("sub_trip.start_time out of day window")
                if sub.end_time and _to_minutes(sub.end_time) > end_min:
                    raise DeepPlannerError("sub_trip.end_time out of day window")
        except DeepPlannerError:
            raise
        except Exception:
            return

    @staticmethod
    def _extract_used_pois(
        plan: PlanTripSchema | PlanDayCardSchema,
    ) -> set[tuple[str, str]]:
        used: set[tuple[str, str]] = set()
        day_cards = plan.day_cards if isinstance(plan, PlanTripSchema) else [plan]
        for card in day_cards:
            for sub in card.sub_trips:
                ext = sub.ext if isinstance(sub.ext, dict) else {}
                poi_ref = _PoiRef.from_any(
                    ext.get("poi") if isinstance(ext, dict) else None
                )
                if poi_ref:
                    used.add(poi_ref.key)
        return used

    @staticmethod
    def _summarize_day(day_card: PlanDayCardSchema) -> dict[str, Any]:
        highlights: list[dict[str, Any]] = []
        used_pois: list[dict[str, str]] = []
        for sub in day_card.sub_trips[:6]:
            ext = sub.ext if isinstance(sub.ext, dict) else {}
            poi_ref = _PoiRef.from_any(
                ext.get("poi") if isinstance(ext, dict) else None
            )
            highlights.append(
                {
                    "activity": sub.activity,
                    "loc_name": sub.loc_name,
                    "poi": (
                        {
                            "provider": poi_ref.provider,
                            "provider_id": poi_ref.provider_id,
                        }
                        if poi_ref
                        else None
                    ),
                }
            )
            if poi_ref:
                used_pois.append(
                    {"provider": poi_ref.provider, "provider_id": poi_ref.provider_id}
                )
        return {
            "day_index": day_card.day_index,
            "date": day_card.date.isoformat(),
            "highlights": highlights,
            "used_pois": used_pois,
        }

    def _assemble_trip(
        self,
        *,
        request: PlanRequest,
        day_cards: list[PlanDayCardSchema],
        seed_plan: PlanTripSchema | None,
    ) -> PlanTripSchema:
        title = f"{request.destination} 行程规划"
        meta: dict[str, Any] = {"planner": {"mode": "deep", "name": self.PLANNER_NAME}}
        if request.seed_mode:
            meta["planner"]["seed_mode"] = request.seed_mode
        if seed_plan and isinstance(seed_plan.meta, dict):
            meta["planner"]["seed_rules_version"] = (
                seed_plan.meta.get("planner") or {}
            ).get("rules_version")

        total_sub_trips = sum(len(card.sub_trips) for card in day_cards)
        return PlanTripSchema(
            id=None,
            user_id=request.user_id,
            title=title,
            destination=request.destination,
            start_date=request.start_date,
            end_date=request.end_date,
            status="draft",
            meta=meta,
            day_cards=day_cards,
            day_count=request.day_count,
            sub_trip_count=total_sub_trips,
        )
