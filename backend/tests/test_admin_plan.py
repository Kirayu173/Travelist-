from __future__ import annotations

import uuid
from datetime import date

from app.core.db import session_scope
from app.core.settings import settings
from app.models.orm import User


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": settings.admin_api_token}


def _create_user() -> int:
    with session_scope() as session:
        user = User(
            email=f"admin_plan_{uuid.uuid4().hex}@example.com",
            name="Admin Plan",
        )
        session.add(user)
        session.flush()
        return user.id


def test_admin_plan_summary_requires_auth(client):
    resp = client.get("/admin/plan/summary")
    assert resp.status_code == 401


def test_admin_plan_summary_returns_payload(client):
    user_id = _create_user()
    payload = {
        "user_id": user_id,
        "destination": "广州",
        "start_date": date.today().isoformat(),
        "end_date": date.today().isoformat(),
        "mode": "fast",
        "save": False,
        "preferences": {"interests": ["food", "sight"]},
    }
    client.post("/api/ai/plan", json=payload)

    resp = client.get("/admin/plan/summary", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["plan_fast_calls"] >= 1
    assert "plan_fast_latency_ms_p95" in data


def test_admin_plan_overview_page_renders(client):
    resp = client.get("/admin/plan/overview", headers=_admin_headers())
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Fast 模式便捷测试台" in resp.text
