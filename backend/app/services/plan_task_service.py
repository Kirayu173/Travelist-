from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.db import session_scope
from app.core.settings import settings
from app.models.orm import AiTask
from app.models.plan_schemas import PlanRequest, PlanResponseData, PlanTaskSchema
from app.services.plan_task_worker import PlanTaskWorker, get_plan_task_worker
from fastapi import Request
from sqlalchemy.exc import IntegrityError


class PlanTaskServiceError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: int = 14080,
        trace_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.trace_id = trace_id
        self.data = data or {}


def _build_trace_id() -> str:
    return f"plan-{uuid.uuid4().hex[:12]}"


def _build_task_id(*, user_id: int, request_id: str | None) -> str:
    if request_id:
        stable = uuid.uuid5(
            uuid.NAMESPACE_DNS,
            f"travelist+:ai_task:{PlanTaskWorker.KIND}:{user_id}:{request_id}",
        )
        return f"at_{stable.hex}"
    return f"at_{uuid.uuid4().hex}"


def _normalize_task_status(status: str) -> str:
    mapping = {"pending": "queued", "done": "succeeded"}
    normalized = mapping.get(status, status)
    if normalized in {"queued", "running", "succeeded", "failed", "canceled"}:
        return normalized
    return "failed" if normalized else "failed"


def _compute_updated_at(task: AiTask) -> datetime:
    return task.finished_at or task.started_at or task.created_at


def _parse_error_payload(payload: str | None) -> dict[str, Any] | None:
    if not payload:
        return None
    raw = str(payload).strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {"type": "task_error", "message": raw[:200]}


class PlanTaskService:
    """Create/query deep planning tasks backed by ai_tasks + in-process worker."""

    KIND = PlanTaskWorker.KIND

    def __init__(self, *, worker: PlanTaskWorker | None = None) -> None:
        self._worker = worker or get_plan_task_worker()

    def enqueue_deep_task(self, request: PlanRequest) -> PlanResponseData:
        if request.mode != "deep" or not request.async_:
            raise PlanTaskServiceError(
                "only deep async requests can be enqueued", code=14080
            )

        if not self._worker.started:
            reason = getattr(self._worker, "disabled_reason", None)
            raise PlanTaskServiceError(
                "task worker is not started",
                code=14088,
                data={"reason": reason} if reason else {},
            )

        payload = self._build_safe_payload(request)
        task_id = _build_task_id(user_id=request.user_id, request_id=request.request_id)

        existing = self._find_idempotent_task(task_id, request, payload)
        if existing is not None:
            trace_id = str(existing.payload.get("trace_id") or "").strip() or None
            return PlanResponseData(
                mode="deep",
                async_=True,
                request_id=request.request_id,
                seed_mode=request.seed_mode,
                task_id=str(existing.id),
                plan=None,
                metrics={"queued": True, "idempotent": True},
                tool_traces=[{"node": "plan_task_enqueue", "status": "ok"}],
                trace_id=trace_id,
            )

        trace_id = _build_trace_id()
        max_running = max(int(settings.plan_task_max_running_per_user), 1)
        with session_scope() as session:
            query = session.query(AiTask).filter(
                AiTask.user_id == request.user_id,
                AiTask.status.in_(["queued", "pending", "running"]),
            )
            try:
                query = query.filter(AiTask.payload["kind"].astext == self.KIND)
            except Exception:
                pass
            running = query.count()
            if running >= max_running:
                raise PlanTaskServiceError(
                    "too many running tasks for user",
                    code=14087,
                    trace_id=trace_id,
                    data={"limit": max_running, "running": running},
                )

        with session_scope() as session:
            row = AiTask(
                id=task_id,
                user_id=request.user_id,
                status="queued",
                payload={**payload, "trace_id": trace_id, "kind": self.KIND},
                result=None,
                error=None,
                started_at=None,
                finished_at=None,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                existing = session.get(AiTask, task_id)
                if existing is None:
                    raise PlanTaskServiceError(
                        "failed to create task",
                        code=14088,
                        trace_id=trace_id,
                        data={"error": "integrity_error"},
                    ) from exc
                stored = existing.payload if isinstance(existing.payload, dict) else {}
                expected_payload = {
                    **payload,
                    "trace_id": stored.get("trace_id"),
                    "kind": self.KIND,
                }
                if stored != expected_payload:
                    raise PlanTaskServiceError(
                        "request_id conflict with different payload",
                        code=14086,
                        trace_id=str(stored.get("trace_id") or trace_id),
                        data={"task_id": str(existing.id)},
                    ) from exc
                return PlanResponseData(
                    mode="deep",
                    async_=True,
                    request_id=request.request_id,
                    seed_mode=request.seed_mode,
                    task_id=str(existing.id),
                    plan=None,
                    metrics={"queued": True, "idempotent": True},
                    tool_traces=[{"node": "plan_task_enqueue", "status": "ok"}],
                    trace_id=str(stored.get("trace_id") or trace_id),
                )

        try:
            self._worker.enqueue(str(task_id))
        except Exception as exc:
            self._mark_queue_failed(str(task_id), error=str(exc))
            raise PlanTaskServiceError(
                "failed to enqueue task",
                code=14087,
                trace_id=trace_id,
                data={"error": str(exc)},
            ) from exc

        return PlanResponseData(
            mode="deep",
            async_=True,
            request_id=request.request_id,
            seed_mode=request.seed_mode,
            task_id=str(task_id),
            plan=None,
            metrics={"queued": True},
            tool_traces=[{"node": "plan_task_enqueue", "status": "ok"}],
            trace_id=trace_id,
        )

    def get_task(
        self,
        task_id: str,
        *,
        request: Request,
        user_id: int | None,
    ) -> PlanTaskSchema:
        task_pk = self._parse_task_id(task_id)
        with session_scope() as session:
            row: AiTask | None = session.get(AiTask, task_pk)
            kind = None
            if row and isinstance(row.payload, dict):
                kind = row.payload.get("kind")
            if row is None or kind != self.KIND:
                raise PlanTaskServiceError("task not found", code=14084)

        is_admin = self._is_admin_request(request)
        if not is_admin:
            if user_id is None:
                raise PlanTaskServiceError("user_id is required", code=14080)
            if int(row.user_id) != int(user_id):
                raise PlanTaskServiceError("task not found", code=14084)

        payload = row.payload if isinstance(row.payload, dict) else {}
        seed_mode = payload.get("seed_mode")
        request_id = payload.get("request_id")
        trace_id = payload.get("trace_id")

        result = row.result if isinstance(row.result, dict) else None
        created_at = row.created_at
        updated_at = _compute_updated_at(row)
        finished_at = row.finished_at

        return PlanTaskSchema(
            task_id=str(row.id),
            status=_normalize_task_status(str(row.status)),
            mode="deep",
            async_=True,
            request_id=request_id,
            seed_mode=seed_mode,
            trace_id=trace_id,
            created_at=created_at,
            updated_at=updated_at,
            finished_at=finished_at,
            result=result,
            error=_parse_error_payload(row.error),
        )

    @staticmethod
    def _parse_task_id(task_id: str) -> str:
        raw = str(task_id or "").strip()
        if not raw or len(raw) > 64:
            raise PlanTaskServiceError("invalid task_id", code=14080)
        return raw

    @staticmethod
    def _build_safe_payload(request: PlanRequest) -> dict[str, Any]:
        prefs = request.preferences if isinstance(request.preferences, dict) else {}
        return {
            "user_id": request.user_id,
            "destination": request.destination,
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
            "mode": "deep",
            "save": bool(request.save),
            "preferences": prefs,
            "people_count": request.people_count,
            "seed": request.seed,
            "async": True,
            "request_id": request.request_id,
            "seed_mode": request.seed_mode,
            "kind": PlanTaskWorker.KIND,
            "trace_id": None,
        }

    def _find_idempotent_task(
        self,
        task_id: str,
        request: PlanRequest,
        payload: dict[str, Any],
    ) -> AiTask | None:
        if not request.request_id:
            return None
        with session_scope() as session:
            row = session.get(AiTask, task_id)
            if row is None:
                return None
            stored = row.payload if isinstance(row.payload, dict) else {}
            normalized = {
                **payload,
                "trace_id": stored.get("trace_id"),
                "kind": self.KIND,
            }
            if stored != normalized:
                stored_trace_id = str(stored.get("trace_id") or "").strip() or None
                raise PlanTaskServiceError(
                    "request_id conflict with different payload",
                    code=14086,
                    trace_id=stored_trace_id,
                    data={"task_id": str(row.id)},
                )
            return row

    @staticmethod
    def _mark_queue_failed(task_id: str, *, error: str) -> None:
        now = datetime.now(timezone.utc)
        with session_scope() as session:
            row: AiTask | None = session.get(AiTask, task_id)
            if row is None:
                return
            row.status = "failed"
            row.error = json.dumps(
                {"type": "queue_error", "message": error[:200]}, ensure_ascii=False
            )
            row.finished_at = now
            session.commit()

    @staticmethod
    def _is_admin_request(request: Request) -> bool:
        token = settings.admin_api_token
        allowed_ips = set(settings.admin_allowed_ips)
        client_ip = request.client.host if request.client else None

        if not token and not allowed_ips:
            return True

        provided = (
            request.headers.get("X-Admin-Token")
            or request.query_params.get("token")
            or request.cookies.get("admin_token")
        )
        token_valid = token is not None and provided == token
        ip_valid = bool(allowed_ips) and client_ip in allowed_ips
        return bool(token_valid or ip_valid)


_plan_task_service: PlanTaskService | None = None


def get_plan_task_service() -> PlanTaskService:
    global _plan_task_service
    if _plan_task_service is None:
        _plan_task_service = PlanTaskService()
    return _plan_task_service
