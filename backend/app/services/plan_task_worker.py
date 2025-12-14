from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from app.core.db import session_scope
from app.core.logging import get_logger
from app.core.settings import settings
from app.models.orm import AiTask
from app.models.plan_schemas import PlanRequest
from app.services.plan_service import PlanServiceError, get_plan_service
from sqlalchemy.exc import SQLAlchemyError


class PlanTaskWorker:
    """In-process async worker executing deep planning tasks from ai_tasks."""

    KIND = "plan:deep"

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] | None = None
        self._workers: list[asyncio.Task[None]] = []
        self._logger = get_logger(__name__)
        self._started = False
        self._disabled_reason: str | None = None
        self._lock = asyncio.Lock()

    @property
    def started(self) -> bool:
        return self._started

    @property
    def disabled_reason(self) -> str | None:
        return self._disabled_reason

    async def start(self) -> None:
        async with self._lock:
            if self._started:
                return

            self._disabled_reason = None
            maxsize = max(int(settings.plan_task_queue_maxsize), 1)
            self._queue = asyncio.Queue(maxsize=maxsize)
            try:
                await self._recover_tasks()
            except SQLAlchemyError as exc:
                self._disabled_reason = str(exc)
                self._queue = None
                self._logger.warning(
                    "plan_task_worker.disabled",
                    extra={"error": str(exc)},
                )
                return

            concurrency = max(int(settings.plan_task_worker_concurrency), 1)
            for idx in range(concurrency):
                self._workers.append(asyncio.create_task(self._worker_loop(idx)))

            self._started = True
            self._logger.info(
                "plan_task_worker.started",
                extra={"concurrency": concurrency, "queue_maxsize": maxsize},
            )

    async def stop(self) -> None:
        async with self._lock:
            if not self._started:
                return
            for task in self._workers:
                task.cancel()
            for task in self._workers:
                try:
                    await task
                except asyncio.CancelledError:
                    continue
                except Exception as exc:  # pragma: no cover - defensive
                    self._logger.warning(
                        "plan_task_worker.stop_failed",
                        extra={"error": str(exc)},
                    )
            self._workers.clear()
            self._queue = None
            self._started = False
            self._logger.info("plan_task_worker.stopped")

    def enqueue(self, task_id: str) -> None:
        if not self._queue:
            raise RuntimeError("worker queue is not initialized")
        self._queue.put_nowait(str(task_id))

    async def _recover_tasks(self) -> None:
        if not self._queue:
            return

        with session_scope() as session:
            query = session.query(AiTask).filter(
                AiTask.status.in_(["queued", "pending", "running"])
            )
            try:
                query = query.filter(AiTask.payload["kind"].astext == self.KIND)
            except Exception:
                pass
            rows: list[AiTask] = query.order_by(AiTask.created_at.asc()).all()

            queued_ids: list[str] = []
            running_ids: list[str] = []
            for row in rows:
                status = str(row.status or "")
                if status in {"queued", "pending"}:
                    queued_ids.append(str(row.id))
                elif status == "running":
                    running_ids.append(str(row.id))

            if running_ids:
                now = datetime.now(timezone.utc)
                for task_id in running_ids:
                    row = session.get(AiTask, task_id)
                    if row is None:
                        continue
                    row.status = "failed"
                    row.error = json.dumps(
                        {
                            "type": "worker_restart",
                            "message": "worker restarted before task finished",
                        },
                        ensure_ascii=False,
                    )
                    row.finished_at = now
                session.commit()

        for task_id in queued_ids:
            try:
                self.enqueue(task_id)
            except asyncio.QueueFull:  # pragma: no cover - unlikely
                self._logger.warning(
                    "plan_task_worker.recover_queue_full",
                    extra={"task_id": task_id},
                )
                break

    async def _worker_loop(self, worker_index: int) -> None:
        assert self._queue is not None
        while True:
            task_id = await self._queue.get()
            try:
                await self._execute_task(task_id, worker_index=worker_index)
            finally:
                self._queue.task_done()

    async def _execute_task(self, task_id: str, *, worker_index: int) -> None:
        payload: dict[str, Any] | None = None
        trace_id: str | None = None

        with session_scope() as session:
            row: AiTask | None = session.get(AiTask, task_id)
            if row is None:
                return
            if str(row.status) not in {"queued", "pending"}:
                return
            row.status = "running"
            row.started_at = datetime.now(timezone.utc)
            session.commit()
            payload = row.payload if isinstance(row.payload, dict) else {}
            trace_id = str(payload.get("trace_id") or "").strip() or None

        plan_request = PlanRequest(**{**payload, "async": False, "mode": "deep"})
        service = get_plan_service()
        try:
            response, _trip_id = await service.plan(plan_request, trace_id=trace_id)
            result = response.model_dump(mode="json", by_alias=True)
            result["task_id"] = str(task_id)
            self._mark_task_succeeded(task_id, result=result)
            self._logger.info(
                "plan_task_worker.succeeded",
                extra={
                    "task_id": task_id,
                    "worker": worker_index,
                    "trace_id": trace_id,
                },
            )
        except PlanServiceError as exc:
            self._mark_task_failed(
                task_id,
                error={
                    "type": "plan_error",
                    "message": exc.message,
                    "code": exc.code,
                    "trace_id": exc.trace_id,
                },
            )
            self._logger.warning(
                "plan_task_worker.failed",
                extra={
                    "task_id": task_id,
                    "worker": worker_index,
                    "trace_id": trace_id,
                    "error": exc.message,
                },
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._mark_task_failed(
                task_id,
                error={"type": exc.__class__.__name__, "message": str(exc)[:500]},
            )
            self._logger.exception(
                "plan_task_worker.crash",
                extra={
                    "task_id": task_id,
                    "worker": worker_index,
                    "trace_id": trace_id,
                },
            )

    @staticmethod
    def _mark_task_succeeded(
        task_id: str,
        *,
        result: dict[str, Any],
    ) -> None:
        finished_at = datetime.now(timezone.utc)
        with session_scope() as session:
            row: AiTask | None = session.get(AiTask, task_id)
            if row is None:
                return
            row.status = "succeeded"
            row.result = result
            row.error = None
            row.finished_at = finished_at
            session.commit()

    @staticmethod
    def _mark_task_failed(
        task_id: str,
        *,
        error: dict[str, Any],
    ) -> None:
        finished_at = datetime.now(timezone.utc)
        with session_scope() as session:
            row: AiTask | None = session.get(AiTask, task_id)
            if row is None:
                return
            row.status = "failed"
            row.error = json.dumps(error, ensure_ascii=False)
            row.finished_at = finished_at
            session.commit()


_plan_task_worker: PlanTaskWorker | None = None


def get_plan_task_worker() -> PlanTaskWorker:
    global _plan_task_worker
    if _plan_task_worker is None:
        _plan_task_worker = PlanTaskWorker()
    return _plan_task_worker
