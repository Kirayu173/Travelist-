from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import List

from app.admin.schemas import DataCheckResult

CheckCallable = Callable[[], Awaitable[DataCheckResult]]


class DataCheckRegistry:
    """Registry that keeps admin data checks pluggable for future stages."""

    def __init__(self) -> None:
        self._checks: List[CheckCallable] = []

    def register(self, check: CheckCallable) -> None:
        self._checks.append(check)

    async def run_all(self) -> list[DataCheckResult]:
        results: list[DataCheckResult] = []
        for check in self._checks:
            result = await check()
            results.append(result)
        return results
