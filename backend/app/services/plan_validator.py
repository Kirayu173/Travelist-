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
                seen_order.add(sub.order_index)

        if issues:
            raise PlanValidationError("plan validation failed", issues=issues)
