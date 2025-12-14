from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from app.models.plan_schemas import PlanRequest, PlanTripSchema


@dataclass(frozen=True)
class PlanValidationIssue:
    message: str
    detail: dict[str, Any] | None = None


class PlanValidationError(Exception):
    def __init__(
        self,
        message: str,
        *,
        issues: list[PlanValidationIssue] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.issues = issues or []


class PlanValidator:
    def validate(self, *, request: PlanRequest, plan: PlanTripSchema) -> None:
        issues: list[PlanValidationIssue] = []

        expected_days = request.day_count
        if plan.day_count != expected_days:
            issues.append(
                PlanValidationIssue(
                    "day_count mismatch",
                    {"expected": expected_days, "got": plan.day_count},
                )
            )

        if len(plan.day_cards) != expected_days:
            issues.append(
                PlanValidationIssue(
                    "day_cards length mismatch",
                    {"expected": expected_days, "got": len(plan.day_cards)},
                )
            )

        for idx, card in enumerate(plan.day_cards):
            if card.day_index != idx:
                issues.append(
                    PlanValidationIssue(
                        "day_index mismatch",
                        {"expected": idx, "got": card.day_index},
                    )
                )
            expected_date = request.start_date + timedelta(days=idx)
            if card.date != expected_date:
                issues.append(
                    PlanValidationIssue(
                        "day_card date mismatch",
                        {
                            "expected": expected_date.isoformat(),
                            "got": card.date.isoformat(),
                        },
                    )
                )
            order_indices: list[int] = []
            seen_order: set[int] = set()
            for sub in card.sub_trips:
                if sub.order_index is None:
                    issues.append(
                        PlanValidationIssue(
                            "sub_trip.order_index missing",
                            {"day_index": idx, "activity": sub.activity},
                        )
                    )
                    continue
                if sub.order_index in seen_order:
                    issues.append(
                        PlanValidationIssue(
                            "duplicate order_index",
                            {"day_index": idx, "order_index": sub.order_index},
                        )
                    )
                else:
                    seen_order.add(sub.order_index)
                    order_indices.append(sub.order_index)

            if order_indices:
                expected = list(range(len(order_indices)))
                if sorted(order_indices) != expected:
                    issues.append(
                        PlanValidationIssue(
                            "order_index not continuous",
                            {
                                "day_index": idx,
                                "expected": expected,
                                "got": sorted(order_indices),
                            },
                        )
                    )

        expected_sub_trips = sum(len(card.sub_trips) for card in plan.day_cards)
        if plan.sub_trip_count != expected_sub_trips:
            issues.append(
                PlanValidationIssue(
                    "sub_trip_count mismatch",
                    {"expected": expected_sub_trips, "got": plan.sub_trip_count},
                )
            )

        # Cross-day POI de-dup (best-effort via ext.poi.provider/provider_id)
        seen_pois: set[tuple[str, str]] = set()
        for card in plan.day_cards:
            for sub in card.sub_trips:
                ext = sub.ext if isinstance(sub.ext, dict) else {}
                poi = ext.get("poi") if isinstance(ext, dict) else None
                if not isinstance(poi, dict):
                    continue
                provider = str(poi.get("provider") or "").strip()
                provider_id = str(poi.get("provider_id") or "").strip()
                if not provider or not provider_id:
                    continue
                key = (provider, provider_id)
                if key in seen_pois:
                    issues.append(
                        PlanValidationIssue(
                            "poi duplicated across days",
                            {"provider": provider, "provider_id": provider_id},
                        )
                    )
                else:
                    seen_pois.add(key)

        if issues:
            raise PlanValidationError("plan validation failed", issues=issues)
