from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from app.core.db import session_scope
from app.core.settings import settings
from app.models.orm import AiTask, User


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": settings.admin_api_token}


def _create_user() -> int:
    with session_scope() as session:
        user = User(
            email=f"admin_tasks_{uuid.uuid4().hex}@example.com",
            name="Admin Tasks User",
        )
        session.add(user)
        session.flush()
        return int(user.id)


def test_admin_ai_tasks_summary_requires_auth(client):
    resp = client.get("/admin/ai/tasks/summary")
    assert resp.status_code == 401


def test_admin_ai_tasks_summary_returns_payload(client):
    user_id = _create_user()
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        session.add(
            AiTask(
                id=f"at_{uuid.uuid4().hex}",
                user_id=user_id,
                status="succeeded",
                payload={
                    "kind": "plan:deep",
                    "request_id": "pytest_admin_tasks_1",
                    "trace_id": "plan-admin-tasks-1",
                },
                result={"ok": True},
                error=None,
                started_at=now,
                finished_at=now,
            )
        )
        session.add(
            AiTask(
                id=f"at_{uuid.uuid4().hex}",
                user_id=user_id,
                status="failed",
                payload={
                    "kind": "plan:deep",
                    "request_id": "pytest_admin_tasks_2",
                    "trace_id": "plan-admin-tasks-2",
                },
                result=None,
                error=json.dumps({"type": "plan_error", "message": "x"}),
                started_at=now,
                finished_at=now,
            )
        )
        session.commit()

    resp = client.get("/admin/ai/tasks/summary", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["kind"] == "plan:deep"
    assert data["counts"]["succeeded"] >= 1
    assert data["counts"]["failed"] >= 1
    assert "latency_ms_p95" in data
    assert isinstance(data.get("recent_tasks"), list)


def test_admin_ai_tasks_page_renders(client):
    resp = client.get("/admin/ai/tasks", headers=_admin_headers())
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "AI 任务监控" in resp.text
