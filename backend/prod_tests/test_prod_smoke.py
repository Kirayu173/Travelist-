from __future__ import annotations

import os
import time
from datetime import date, timedelta

import pytest
from app.core.app import create_app
from app.core.db import session_scope
from app.core.settings import settings
from app.models.orm import Poi, User
from app.services.plan_metrics import reset_plan_metrics
from fastapi.testclient import TestClient
from sqlalchemy import text


def _allow_writes() -> bool:
    return os.environ.get("PROD_TEST_ALLOW_WRITES", "").strip() == "1"


def _allow_task_writes() -> bool:
    return (
        _allow_writes()
        or os.environ.get("PROD_TEST_ALLOW_TASK_WRITES", "").strip() == "1"
    )


def _pick_user_id() -> int:
    with session_scope() as session:
        user = session.query(User).order_by(User.id.asc()).first()
        if user is None:
            pytest.skip("No users in production database")
        return int(user.id)


def _pick_destination() -> str:
    with session_scope() as session:
        row = session.execute(
            text(
                """
                SELECT COALESCE(
                    NULLIF(ext->>'city',''),
                    NULLIF(ext #>> '{amap,city}','')
                ) AS city
                FROM pois
                WHERE ext IS NOT NULL
                LIMIT 200
                """
            )
        ).first()
        if row and row[0]:
            return str(row[0]).strip()

    with session_scope() as session:
        poi = (
            session.query(Poi)
            .filter(Poi.name.isnot(None))
            .order_by(Poi.id.asc())
            .first()
        )
        if poi is None or not poi.name:
            pytest.skip("No POI rows available to infer a destination")
        return str(poi.name)[:30]


def _pick_coord() -> tuple[float, float]:
    with session_scope() as session:
        row = session.execute(
            text(
                """
                SELECT ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lng
                FROM pois
                WHERE geom IS NOT NULL
                LIMIT 1
                """
            )
        ).first()
        if not row or row[0] is None or row[1] is None:
            pytest.skip("No POI geom available in production database")
        return float(row[0]), float(row[1])


@pytest.fixture()
def prod_client() -> TestClient:
    reset_plan_metrics()
    app = create_app()
    with TestClient(app) as client:
        yield client


def test_prod_db_has_core_data() -> None:
    with session_scope() as session:
        assert session.query(User).count() >= 1
        assert session.query(Poi).count() >= 1


def test_prod_poi_api_around_returns_results(prod_client: TestClient) -> None:
    lat, lng = _pick_coord()
    resp = prod_client.get(
        "/api/poi/around",
        params={"lat": lat, "lng": lng, "radius": 500, "type": "food", "limit": 10},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["code"] == 0
    assert isinstance(payload["data"]["items"], list)
    assert len(payload["data"]["items"]) >= 1
    assert payload["data"]["meta"]["source"] in {"cache", "db", "api"}


def test_prod_plan_fast_happy_path_is_deterministic(prod_client: TestClient) -> None:
    user_id = _pick_user_id()
    destination = _pick_destination()
    start = date.today()
    end = start + timedelta(days=1)
    body = {
        "user_id": user_id,
        "destination": destination,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "mode": "fast",
        "save": False,
        "preferences": {"interests": ["sight", "food"], "pace": "normal"},
        "seed": 7,
    }
    r1 = prod_client.post("/api/ai/plan", json=body)
    r2 = prod_client.post("/api/ai/plan", json=body)
    assert r1.status_code == 200
    assert r2.status_code == 200
    d1 = r1.json()["data"]
    d2 = r2.json()["data"]

    plan1 = d1["plan"]
    plan2 = d2["plan"]
    assert plan1["day_count"] == 2
    assert len(plan1["day_cards"]) == 2
    assert plan1["day_cards"][0]["sub_trips"]
    assert plan1 == plan2

    assert isinstance(d1.get("tool_traces"), list)
    nodes = [t.get("node") for t in (d1.get("tool_traces") or [])]
    assert {"plan_input", "planner_fast", "plan_validate", "plan_output"} <= set(nodes)


def test_prod_plan_deep_sync_happy_path_or_fallback(prod_client: TestClient) -> None:
    user_id = _pick_user_id()
    destination = _pick_destination()
    start = date.today()
    end = start
    resp = prod_client.post(
        "/api/ai/plan",
        json={
            "user_id": user_id,
            "destination": destination,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "mode": "deep",
            "save": False,
            "seed_mode": "fast",
            "async": False,
        },
    )
    payload = resp.json()
    assert resp.status_code in {200, 400}
    if resp.status_code == 400:
        assert payload["code"] in {14089, 14070}
        return
    assert payload["code"] == 0
    assert payload["data"]["mode"] == "deep"


def test_prod_plan_max_days_limit(prod_client: TestClient) -> None:
    user_id = _pick_user_id()
    destination = _pick_destination()
    start = date.today()
    end = start + timedelta(days=max(settings.plan_max_days, 14))
    resp = prod_client.post(
        "/api/ai/plan",
        json={
            "user_id": user_id,
            "destination": destination,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "mode": "fast",
            "save": False,
        },
    )
    assert resp.status_code == 400


def test_prod_admin_plan_summary_auth(prod_client: TestClient) -> None:
    resp = prod_client.get("/admin/plan/summary")
    if not settings.admin_api_token and not settings.admin_allowed_ips:
        assert resp.status_code == 200
        return
    assert resp.status_code == 401

    token = settings.admin_api_token
    if token:
        resp2 = prod_client.get("/admin/plan/summary", headers={"X-Admin-Token": token})
        assert resp2.status_code == 200


def test_prod_admin_plan_overview_renders(prod_client: TestClient) -> None:
    token = settings.admin_api_token
    headers = {"X-Admin-Token": token} if token else {}
    resp = prod_client.get("/admin/plan/overview", headers=headers)
    if token or (not settings.admin_api_token and not settings.admin_allowed_ips):
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        return
    assert resp.status_code == 401


def test_prod_admin_plan_summary_reflects_calls(prod_client: TestClient) -> None:
    user_id = _pick_user_id()
    destination = _pick_destination()
    start = date.today()
    resp = prod_client.post(
        "/api/ai/plan",
        json={
            "user_id": user_id,
            "destination": destination,
            "start_date": start.isoformat(),
            "end_date": start.isoformat(),
            "mode": "fast",
            "save": False,
            "seed": 7,
        },
    )
    assert resp.status_code == 200

    token = settings.admin_api_token
    headers = {"X-Admin-Token": token} if token else {}
    summary_resp = prod_client.get("/admin/plan/summary", headers=headers)
    if token or (not settings.admin_api_token and not settings.admin_allowed_ips):
        assert summary_resp.status_code == 200
        payload = summary_resp.json()
        assert payload["code"] == 0
        data = payload["data"]
        assert data["plan_fast_calls"] >= 1
        return
    assert summary_resp.status_code == 401


def test_prod_admin_ai_tasks_summary_auth(prod_client: TestClient) -> None:
    resp = prod_client.get("/admin/ai/tasks/summary")
    if not settings.admin_api_token and not settings.admin_allowed_ips:
        assert resp.status_code == 200
        return
    assert resp.status_code == 401

    token = settings.admin_api_token
    if token:
        resp2 = prod_client.get(
            "/admin/ai/tasks/summary",
            headers={"X-Admin-Token": token},
        )
        assert resp2.status_code == 200


def test_prod_admin_ai_tasks_page_renders(prod_client: TestClient) -> None:
    token = settings.admin_api_token
    headers = {"X-Admin-Token": token} if token else {}
    resp = prod_client.get("/admin/ai/tasks", headers=headers)
    if token or (not settings.admin_api_token and not settings.admin_allowed_ips):
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        return
    assert resp.status_code == 401


@pytest.mark.skipif(not _allow_task_writes(), reason="PROD_TEST_ALLOW_TASK_WRITES!=1")
def test_prod_plan_deep_async_task_roundtrip(prod_client: TestClient) -> None:
    user_id = _pick_user_id()
    destination = _pick_destination()
    start = date.today()
    end = start
    request_id = f"prod_deep_async_{start.isoformat()}_{user_id}"
    resp = prod_client.post(
        "/api/ai/plan",
        json={
            "user_id": user_id,
            "destination": destination,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "mode": "deep",
            "save": False,
            "seed_mode": "fast",
            "async": True,
            "request_id": request_id,
            "preferences": {"interests": ["sight", "food"], "pace": "normal"},
            "seed": 7,
        },
    )
    assert resp.status_code == 200
    created = resp.json()
    assert created["code"] == 0
    data = created["data"]
    task_id = data.get("task_id")
    assert isinstance(task_id, str) and task_id

    task_payload: dict | None = None
    status: str | None = None
    for _ in range(120):
        poll = prod_client.get(
            f"/api/ai/plan/tasks/{task_id}",
            params={"user_id": user_id},
        )
        assert poll.status_code == 200
        task_payload = poll.json()
        assert task_payload["code"] == 0
        status = (task_payload.get("data") or {}).get("status")
        if status in {"succeeded", "failed", "canceled"}:
            break
        time.sleep(0.1)

    assert task_payload is not None
    assert status in {"succeeded", "failed", "canceled"}
    if status == "succeeded":
        result = (task_payload.get("data") or {}).get("result") or {}
        assert result.get("mode") == "deep"
        assert result.get("plan") is not None
    if status == "failed":
        error = (task_payload.get("data") or {}).get("error") or {}
        assert isinstance(error, dict)


@pytest.mark.skipif(not _allow_writes(), reason="PROD_TEST_ALLOW_WRITES!=1")
def test_prod_plan_save_true_roundtrip(prod_client: TestClient) -> None:
    user_id = _pick_user_id()
    destination = _pick_destination()
    start = date.today()
    end = start
    resp = prod_client.post(
        "/api/ai/plan",
        json={
            "user_id": user_id,
            "destination": destination,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "mode": "fast",
            "save": True,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert payload["plan"]["id"] is not None
