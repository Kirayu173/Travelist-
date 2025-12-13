from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from app.core.db import session_scope
from app.core.settings import settings
from app.models.orm import User


def _create_user() -> int:
    with session_scope() as session:
        user = User(email=f"plan_{uuid.uuid4().hex}@example.com", name="Plan Tester")
        session.add(user)
        session.flush()
        return user.id


def _fast_payload(*, user_id: int, days: int = 2) -> dict:
    start = date.today()
    end = start + timedelta(days=max(days, 1) - 1)
    return {
        "user_id": user_id,
        "destination": "广州",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "mode": "fast",
        "save": False,
        "seed": 7,
        "preferences": {"interests": ["food", "sight", "museum"], "pace": "normal"},
        "async": False,
        "request_id": None,
        "seed_mode": None,
    }


def test_plan_fast_returns_trip_schema(client):
    user_id = _create_user()
    payload = _fast_payload(user_id=user_id, days=2)
    resp = client.post("/api/ai/plan", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["mode"] == "fast"
    assert isinstance(data.get("trace_id"), str)
    assert data["plan"]["destination"] == "广州"
    assert data["plan"]["day_count"] == 2
    assert len(data["plan"]["day_cards"]) == 2
    assert data["plan"]["sub_trip_count"] >= 2
    assert "metrics" in data and "latency_ms" in data["metrics"]
    nodes = [t.get("node") for t in (data.get("tool_traces") or [])]
    assert {"plan_input", "planner_fast", "plan_validate", "plan_output"} <= set(nodes)


def test_plan_fast_is_deterministic_with_same_seed(client):
    user_id = _create_user()
    payload = _fast_payload(user_id=user_id, days=2)
    first = client.post("/api/ai/plan", json=payload).json()["data"]["plan"]
    second = client.post("/api/ai/plan", json=payload).json()["data"]["plan"]
    assert first == second


def test_plan_deep_returns_not_implemented(client):
    user_id = _create_user()
    start = date.today().isoformat()
    payload = {
        "user_id": user_id,
        "destination": "广州",
        "start_date": start,
        "end_date": start,
        "mode": "deep",
        "save": False,
        "preferences": {"interests": ["food"]},
        "async": True,
        "request_id": "pytest_deep",
        "seed_mode": "fast",
    }
    resp = client.post("/api/ai/plan", json=payload)
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 14071
    assert body["data"]["trace_id"].startswith("plan-")
    assert body["data"]["mode"] == "deep"


def test_plan_rejects_too_many_days(client):
    user_id = _create_user()
    max_days = settings.plan_max_days
    payload = _fast_payload(user_id=user_id, days=max_days + 1)
    resp = client.post("/api/ai/plan", json=payload)
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 14070


def test_plan_fast_save_persists_trip(client):
    user_id = _create_user()
    payload = _fast_payload(user_id=user_id, days=2)
    payload["save"] = True
    resp = client.post("/api/ai/plan", json=payload)
    assert resp.status_code == 200
    data = resp.json()["data"]
    trip_id = data["plan"]["id"]
    assert isinstance(trip_id, int) and trip_id > 0
    detail = client.get(f"/api/trips/{trip_id}")
    assert detail.status_code == 200


@pytest.mark.parametrize("missing_field", ["destination", "start_date", "end_date"])
def test_plan_request_validation_missing_fields_returns_422(client, missing_field: str):
    user_id = _create_user()
    payload = _fast_payload(user_id=user_id, days=1)
    payload.pop(missing_field, None)
    resp = client.post("/api/ai/plan", json=payload)
    assert resp.status_code == 422
