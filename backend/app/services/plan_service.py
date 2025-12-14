from __future__ import annotations

import uuid
from time import perf_counter
from typing import Any

from app.agents.planner.graph import build_planner_graph
from app.agents.planner.nodes import PlannerNodes
from app.agents.planner.state import PlannerState
from app.core.db import session_scope
from app.core.logging import get_logger
from app.models.orm import User
from app.models.plan_schemas import PlanRequest, PlanResponseData, PlanTripSchema
from app.models.schemas import DayCardCreate, SubTripCreate, TripCreate, TripSchema
from app.services.deep_planner import DeepPlanner
from app.services.fast_planner import FastPlanner
from app.services.plan_metrics import get_plan_metrics
from app.services.poi_service import PoiService, get_poi_service
from app.services.trip_service import TripService


class PlanServiceError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: int = 14070,
        trace_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.trace_id = trace_id
        self.data = data or {}


class PlanService:
    """Unified planning entrypoint for Stage-7 fast and Stage-8 deep planning."""

    def __init__(
        self,
        *,
        poi_service: PoiService | None = None,
        trip_service: TripService | None = None,
    ) -> None:
        self._poi_service = poi_service or get_poi_service()
        self._trip_service = trip_service or TripService()
        self._fast_planner = FastPlanner(poi_service=self._poi_service)
        self._deep_planner = DeepPlanner(
            fast_planner=self._fast_planner,
            poi_service=self._poi_service,
        )
        self._nodes = PlannerNodes(
            fast_planner=self._fast_planner,
            deep_planner=self._deep_planner,
        )
        self._graph = build_planner_graph(self._nodes)
        self._metrics = get_plan_metrics()
        self._logger = get_logger(__name__)

    async def plan(
        self,
        request: PlanRequest,
        *,
        trace_id: str | None = None,
    ) -> tuple[PlanResponseData, int | None]:
        trace_id = trace_id or f"plan-{uuid.uuid4().hex[:12]}"
        t0 = perf_counter()
        if request.mode == "fast":
            request = request.model_copy(update={"async_": False})
        if request.mode == "deep" and request.async_:
            elapsed_ms = (perf_counter() - t0) * 1000
            self._metrics.record(
                trace_id=trace_id,
                mode=request.mode,
                destination=request.destination,
                days=request.day_count,
                latency_ms=elapsed_ms,
                success=False,
                error="async_not_implemented",
            )
            raise PlanServiceError(
                "mode=deep async 尚未启用（Stage-8 task worker 未初始化）",
                code=14088,
                trace_id=trace_id,
                data={
                    "mode": request.mode,
                    "async": True,
                    "request_id": request.request_id,
                },
            )

        state = PlannerState(
            user_id=request.user_id,
            destination=request.destination,
            start_date=request.start_date,
            end_date=request.end_date,
            mode=request.mode,
            save=request.save,
            preferences=request.preferences,
            people_count=request.people_count,
            seed=request.seed,
            async_=request.async_,
            request_id=request.request_id,
            seed_mode=request.seed_mode,
            trace_id=trace_id,
        )

        trip_id: int | None = None
        try:
            result_state = await self._graph.ainvoke(state)
            if isinstance(result_state, dict):
                result_state = PlannerState(**result_state)

            if result_state.result is None:
                message = (
                    result_state.errors[0].get("message")
                    if result_state.errors
                    else "规划失败"
                )
                error_code = (
                    result_state.errors[0].get("code") if result_state.errors else 14079
                )
                raise PlanServiceError(
                    message,
                    code=error_code,
                    trace_id=trace_id,
                    data={"errors": result_state.errors},
                )

            plan_trip: PlanTripSchema = result_state.result
            if request.save:
                persisted = self._persist_trip(user_id=request.user_id, plan=plan_trip)
                trip_id = persisted.id
                plan_trip = _merge_persisted_ids(plan_trip, persisted)

            elapsed_ms = (perf_counter() - t0) * 1000
            metrics = dict(result_state.metrics)
            metrics.setdefault(
                "planner",
                getattr(self._fast_planner, "RULES_VERSION", "fast"),
            )
            metrics["latency_ms"] = round(elapsed_ms, 3)
            metrics["saved"] = bool(request.save)

            response = PlanResponseData(
                mode=request.mode,
                async_=request.async_,
                request_id=request.request_id,
                seed_mode=request.seed_mode,
                task_id=None,
                plan=plan_trip,
                metrics=metrics,
                tool_traces=list(result_state.tool_traces),
                trace_id=trace_id,
            )
            self._metrics.record(
                trace_id=trace_id,
                mode=request.mode,
                destination=request.destination,
                days=request.day_count,
                latency_ms=elapsed_ms,
                success=True,
                error=None,
                llm_tokens_total=metrics.get("llm_tokens_total"),
                fallback_to_fast=bool(metrics.get("fallback_to_fast")),
            )
            return response, trip_id
        except PlanServiceError as exc:
            elapsed_ms = (perf_counter() - t0) * 1000
            self._metrics.record(
                trace_id=trace_id,
                mode=request.mode,
                destination=request.destination,
                days=request.day_count,
                latency_ms=elapsed_ms,
                success=False,
                error=exc.message,
                llm_tokens_total=None,
                fallback_to_fast=None,
            )
            raise
        except Exception as exc:  # pragma: no cover - defensive
            elapsed_ms = (perf_counter() - t0) * 1000
            self._metrics.record(
                trace_id=trace_id,
                mode=request.mode,
                destination=request.destination,
                days=request.day_count,
                latency_ms=elapsed_ms,
                success=False,
                error=str(exc),
                llm_tokens_total=None,
                fallback_to_fast=None,
            )
            self._logger.exception("plan.unhandled_error", extra={"trace_id": trace_id})
            raise PlanServiceError(
                "规划失败",
                code=14079,
                trace_id=trace_id,
                data={"error": str(exc)},
            ) from exc

    def _persist_trip(self, *, user_id: int, plan: PlanTripSchema) -> TripSchema:
        with session_scope() as session:
            user = session.get(User, user_id)
            if user is None:
                raise PlanServiceError(
                    "user_id 不存在，无法保存行程",
                    code=14072,
                )

        day_cards: list[DayCardCreate] = []
        for card in plan.day_cards:
            sub_trips: list[SubTripCreate] = []
            for sub in card.sub_trips:
                sub_trips.append(SubTripCreate(**sub.model_dump()))
            day_cards.append(
                DayCardCreate(
                    day_index=card.day_index,
                    date=card.date,
                    note=card.note,
                    sub_trips=sub_trips,
                )
            )
        payload = TripCreate(
            user_id=user_id,
            title=plan.title,
            destination=plan.destination,
            start_date=plan.start_date,
            end_date=plan.end_date,
            status=plan.status,
            meta=plan.meta,
            day_cards=day_cards,
        )
        return self._trip_service.create_trip(payload)


def _merge_persisted_ids(plan: PlanTripSchema, persisted: TripSchema) -> PlanTripSchema:
    day_map = {card.day_index: card for card in persisted.day_cards}
    enriched_cards = []
    for card in plan.day_cards:
        persisted_card = day_map.get(card.day_index)
        sub_trips = []
        if persisted_card:
            sub_map = {sub.order_index: sub for sub in persisted_card.sub_trips}
            for sub in card.sub_trips:
                persisted_sub = (
                    sub_map.get(sub.order_index)
                    if sub.order_index is not None
                    else None
                )
                payload = sub.model_dump(mode="json")
                payload["id"] = persisted_sub.id if persisted_sub else None
                payload["day_card_id"] = persisted_card.id if persisted_card else None
                sub_trips.append(payload)
        else:
            sub_trips = [sub.model_dump(mode="json") for sub in card.sub_trips]

        enriched_cards.append(
            {
                **card.model_dump(mode="json"),
                "id": persisted_card.id if persisted_card else None,
                "trip_id": persisted.id if persisted_card else None,
                "sub_trips": sub_trips,
            }
        )

    payload = plan.model_dump(mode="json")
    payload["id"] = persisted.id
    payload["day_cards"] = enriched_cards
    return PlanTripSchema(**payload)


_plan_service: PlanService | None = None


def get_plan_service() -> PlanService:
    global _plan_service
    if _plan_service is None:
        _plan_service = PlanService()
    return _plan_service
