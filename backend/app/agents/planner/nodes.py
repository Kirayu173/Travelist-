from __future__ import annotations

from time import perf_counter
from typing import Any

from app.agents.planner.state import PlannerState
from app.core.logging import get_logger
from app.models.plan_schemas import PlanRequest
from app.services.fast_planner import FastPlanner, FastPlannerError
from app.services.plan_validator import PlanValidationError, PlanValidator


class PlannerNodes:
    """LangGraph nodes for Stage-7 planning (mode=fast)."""

    def __init__(
        self,
        *,
        fast_planner: FastPlanner,
        validator: PlanValidator | None = None,
    ) -> None:
        self._fast_planner = fast_planner
        self._validator = validator or PlanValidator()
        self._logger = get_logger(__name__)

    async def plan_input_node(self, state: PlannerState) -> PlannerState:
        return self._trace(
            state,
            "plan_input",
            status="ok",
            detail={"mode": state.mode},
        )

    async def planner_fast_node(self, state: PlannerState) -> PlannerState:
        t0 = perf_counter()
        try:
            request = PlanRequest(
                user_id=state.user_id,
                destination=state.destination,
                start_date=state.start_date,
                end_date=state.end_date,
                mode="fast",
                save=state.save,
                preferences=state.preferences,
                people_count=state.people_count,
                seed=state.seed,
                async_=state.async_,
                request_id=state.request_id,
                seed_mode=state.seed_mode,
            )
            plan, metrics = await self._fast_planner.plan(request)
            state.result = plan
            state.metrics.update(metrics)
            return self._trace(
                state,
                "planner_fast",
                status="ok",
                latency_ms=(perf_counter() - t0) * 1000,
                detail={
                    "activities": metrics.get("activities"),
                    "candidates": metrics.get("candidate_pois"),
                },
            )
        except FastPlannerError as exc:
            state.errors.append(
                {
                    "type": "planner_error",
                    "message": exc.message,
                    "code": exc.code,
                }
            )
            return self._trace(
                state,
                "planner_fast",
                status="error",
                latency_ms=(perf_counter() - t0) * 1000,
                detail={"error": exc.message, "code": exc.code},
            )
        except Exception as exc:  # pragma: no cover - defensive
            state.errors.append(
                {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                    "code": 14079,
                }
            )
            return self._trace(
                state,
                "planner_fast",
                status="error",
                latency_ms=(perf_counter() - t0) * 1000,
                detail={"error": str(exc), "code": 14079},
            )

    async def plan_validate_node(self, state: PlannerState) -> PlannerState:
        t0 = perf_counter()
        if state.result is None:
            return self._trace(
                state,
                "plan_validate",
                status="skipped",
                latency_ms=(perf_counter() - t0) * 1000,
                detail={"reason": "no_result"},
            )
        try:
            request = PlanRequest(
                user_id=state.user_id,
                destination=state.destination,
                start_date=state.start_date,
                end_date=state.end_date,
                mode=state.mode,
                save=state.save,
                preferences=state.preferences,
                people_count=state.people_count,
                seed=state.seed,
                async_=state.async_,
                request_id=state.request_id,
                seed_mode=state.seed_mode,
            )
            self._validator.validate(request=request, plan=state.result)
            return self._trace(
                state,
                "plan_validate",
                status="ok",
                latency_ms=(perf_counter() - t0) * 1000,
                detail={"issues": 0},
            )
        except PlanValidationError as exc:
            state.errors.append(
                {
                    "type": "validation_error",
                    "message": exc.message,
                    "issues": [issue.__dict__ for issue in exc.issues],
                    "code": 14078,
                }
            )
            return self._trace(
                state,
                "plan_validate",
                status="error",
                latency_ms=(perf_counter() - t0) * 1000,
                detail={"error": exc.message, "issues": len(exc.issues)},
            )

    async def plan_output_node(self, state: PlannerState) -> PlannerState:
        return self._trace(
            state,
            "plan_output",
            status="ok",
            detail={"has_plan": state.result is not None, "errors": len(state.errors)},
        )

    def _trace(
        self,
        state: PlannerState,
        node: str,
        *,
        status: str,
        latency_ms: float | None = None,
        detail: dict[str, Any] | None = None,
    ) -> PlannerState:
        payload: dict[str, Any] = {
            "node": node,
            "status": status,
        }
        if latency_ms is not None:
            payload["latency_ms"] = round(float(latency_ms), 3)
        if detail:
            payload["detail"] = detail
        state.tool_traces.append(payload)
        self._logger.info(
            "planner.node",
            extra={
                "trace_id": state.trace_id,
                "node": node,
                "status": status,
                "latency_ms": payload.get("latency_ms"),
            },
        )
        return state
