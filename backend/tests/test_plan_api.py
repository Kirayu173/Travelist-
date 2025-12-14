from __future__ import annotations

import time
import uuid
from datetime import date, timedelta

import pytest
from app.core.db import session_scope
from app.core.settings import settings
from app.models.orm import AiTask, User


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
        "destination": "Йужн",
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
    assert data["plan"]["destination"] == "Йужн"
    assert data["plan"]["day_count"] == 2
    assert len(data["plan"]["day_cards"]) == 2
    assert data["plan"]["sub_trip_count"] >= 2
    assert "metrics" in data and "latency_ms" in data["metrics"]
    nodes = {t.get("node") for t in (data.get("tool_traces") or [])}
    assert {"plan_input", "planner_fast", "plan_validate", "plan_output"} <= nodes


def test_plan_fast_is_deterministic_with_same_seed(client):
    user_id = _create_user()
    payload = _fast_payload(user_id=user_id, days=2)
    first = client.post("/api/ai/plan", json=payload).json()["data"]["plan"]
    second = client.post("/api/ai/plan", json=payload).json()["data"]["plan"]
    assert first == second


def test_plan_deep_sync_returns_trip_schema(client):
    user_id = _create_user()
    start = date.today().isoformat()
    payload = {
        "user_id": user_id,
        "destination": "Йужн",
        "start_date": start,
        "end_date": start,
        "mode": "deep",
        "save": False,
        "preferences": {"interests": ["food"]},
        "async": False,
        "request_id": "pytest_deep_sync",
        "seed_mode": "fast",
    }
    resp = client.post("/api/ai/plan", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["mode"] == "deep"
    assert data["async"] is False
    assert data["trace_id"].startswith("plan-")
    assert data["plan"]["day_count"] == 1
    nodes = {t.get("node") for t in (data.get("tool_traces") or [])}
    assert {
        "plan_input",
        "planner_deep",
        "plan_validate_global",
        "plan_output",
    } <= nodes


def test_plan_deep_async_returns_task_and_completes(client):
    user_id = _create_user()
    start = date.today().isoformat()
    payload = {
        "user_id": user_id,
        "destination": "Йужн",
        "start_date": start,
        "end_date": start,
        "mode": "deep",
        "save": False,
        "preferences": {"interests": ["food"]},
        "async": True,
        "request_id": "pytest_deep_async",
        "seed_mode": "fast",
    }
    resp = client.post("/api/ai/plan", json=payload)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["mode"] == "deep"
    assert data["async"] is True
    task_id = data.get("task_id")
    assert task_id

    status = None
    task_data = None
    for _ in range(80):
        task_resp = client.get(
            f"/api/ai/plan/tasks/{task_id}", params={"user_id": user_id}
        )
        if task_resp.status_code != 200:
            time.sleep(0.05)
            continue
        task_data = task_resp.json()["data"]
        status = task_data["status"]
        if status in {"succeeded", "failed"}:
            break
        time.sleep(0.05)

    assert status == "succeeded"
    assert task_data is not None
    assert task_data["trace_id"].startswith("plan-")
    result = task_data["result"]
    assert result["mode"] == "deep"
    assert result["plan"]["day_count"] == 1
    traces = result.get("tool_traces") or []
    nodes = {t.get("node") for t in traces}
    assert {"planner_deep_day", "plan_validate_global"} <= nodes


def test_plan_task_requires_user_id_when_not_admin(client):
    user_id = _create_user()
    start = date.today().isoformat()
    resp = client.post(
        "/api/ai/plan",
        json={
            "user_id": user_id,
            "destination": "Йужн",
            "start_date": start,
            "end_date": start,
            "mode": "deep",
            "save": False,
            "preferences": {"interests": ["food"]},
            "async": True,
            "request_id": "pytest_task_user_guard",
            "seed_mode": "fast",
        },
    )
    assert resp.status_code == 200
    task_id = resp.json()["data"]["task_id"]
    task_resp = client.get(f"/api/ai/plan/tasks/{task_id}")
    assert task_resp.status_code == 400
    body = task_resp.json()
    assert body["code"] == 14080


def test_plan_deep_async_same_request_id_is_idempotent(client):
    user_id = _create_user()
    start = date.today().isoformat()
    payload = {
        "user_id": user_id,
        "destination": "Йужн",
        "start_date": start,
        "end_date": start,
        "mode": "deep",
        "save": False,
        "preferences": {"interests": ["food"]},
        "async": True,
        "request_id": "pytest_deep_idempotent",
        "seed_mode": "fast",
    }
    first = client.post("/api/ai/plan", json=payload)
    second = client.post("/api/ai/plan", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["task_id"] == second.json()["data"]["task_id"]


def test_plan_deep_async_request_id_conflict_returns_error(client):
    user_id = _create_user()
    start = date.today().isoformat()
    request_id = "pytest_deep_conflict"
    first = {
        "user_id": user_id,
        "destination": "Йужн",
        "start_date": start,
        "end_date": start,
        "mode": "deep",
        "save": False,
        "preferences": {"interests": ["food"]},
        "async": True,
        "request_id": request_id,
        "seed_mode": "fast",
    }
    resp1 = client.post("/api/ai/plan", json=first)
    assert resp1.status_code == 200

    second = dict(first)
    second["destination"] = "不同城市"
    resp2 = client.post("/api/ai/plan", json=second)
    assert resp2.status_code == 400
    body = resp2.json()
    assert body["code"] == 14086


def test_plan_deep_async_respects_max_running_per_user(client):
    user_id = _create_user()
    with session_scope() as session:
        session.add(
            AiTask(
                id=f"at_running_{uuid.uuid4().hex}",
                user_id=user_id,
                status="running",
                payload={"kind": "plan:deep", "trace_id": "plan-running-fixture"},
                result=None,
                error=None,
                finished_at=None,
            )
        )
        session.commit()

    start = date.today().isoformat()
    resp = client.post(
        "/api/ai/plan",
        json={
            "user_id": user_id,
            "destination": "Йужн",
            "start_date": start,
            "end_date": start,
            "mode": "deep",
            "save": False,
            "preferences": {"interests": ["food"]},
            "async": True,
            "request_id": "pytest_limit",
            "seed_mode": "fast",
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 14087


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
