import uuid
from datetime import date

from app.core.db import session_scope
from app.core.settings import settings
from app.models.orm import DayCard, SubTrip, Trip, User
from sqlalchemy.engine.url import make_url


def test_admin_ping_returns_version_and_time(client):
    resp = client.get("/admin/ping")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert isinstance(data["version"], str)
    assert isinstance(data["time"], str)


def test_admin_dashboard_returns_html(client):
    resp = client.get("/admin/dashboard")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "管理面板" in resp.text


def test_admin_summary_supports_window_parameter(client):
    client.get("/healthz")
    client.get("/admin/ping")

    resp = client.get("/admin/api/summary?window=60")
    assert resp.status_code == 200
    summary = resp.json()["data"]
    assert summary["total_requests"] >= 2
    assert isinstance(summary.get("routes"), list)


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": settings.admin_api_token}


def test_admin_api_testcases_returns_presets(client):
    resp = client.get("/admin/api/testcases", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) >= 2
    assert any(case["path"] == "/api/trips" for case in data)


def test_admin_api_test_executes_sample_call(client):
    payload = {"method": "GET", "path": "/api/trips", "query": {"user_id": 1}}
    resp = client.post("/admin/api/test", json=payload, headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status_code"] == 200
    assert data["ok"] is True


def test_admin_sql_test_requires_auth(client):
    resp = client.post("/admin/api/sql_test", json={"query": "select 1"})
    assert resp.status_code == 401


def test_admin_sql_test_allows_select_only(client):
    resp = client.post(
        "/admin/api/sql_test",
        json={"query": "select 1 as a"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["columns"] == ["a"]
    assert data["rows"][0]["a"] == 1


def test_admin_sql_test_rejects_multiple_statements(client):
    resp = client.post(
        "/admin/api/sql_test",
        json={"query": "select 1; select 2"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 400


def test_admin_sql_test_rejects_non_select(client):
    resp = client.post(
        "/admin/api/sql_test",
        json={"query": "update users set name='x'"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 400


def test_admin_checks_endpoint_returns_three_items(client):
    resp = client.get("/admin/checks")
    assert resp.status_code == 200
    data = resp.json()["data"]
    names = {item["name"] for item in data}
    expected = {
        "db_connectivity",
        "redis_connectivity",
        "postgis_extension",
        "core_tables",
        "migration_version",
        "seed_data",
        "alembic_initialized",
    }
    assert expected <= names


def test_admin_db_and_redis_status_endpoints_return_payload(client):
    db_resp = client.get("/admin/db/status")
    redis_resp = client.get("/admin/redis/status")
    assert db_resp.status_code == 200
    assert "status" in db_resp.json()["data"]
    assert redis_resp.status_code == 200
    assert "status" in redis_resp.json()["data"]


def test_admin_poi_summary_requires_auth(client):
    resp = client.get("/admin/poi/summary")
    assert resp.status_code == 401


def test_admin_poi_summary_returns_payload(client):
    resp = client.get("/admin/poi/summary", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "pois_total" in data


def test_admin_memory_page_renders(client):
    resp = client.get("/admin/ai/memories")
    assert resp.status_code == 200
    assert "记忆浏览" in resp.text


def test_admin_db_health_endpoint_reports_engine(client):
    resp = client.get("/admin/db/health")
    assert resp.status_code == 200
    data = resp.json()["data"]
    expected_url = make_url(settings.database_url).render_as_string(hide_password=True)
    assert data["engine_url"] == expected_url
    assert "status" in data


def test_admin_db_stats_endpoint_reports_core_tables(client):
    resp = client.get("/admin/db/stats")
    assert resp.status_code == 200
    tables = resp.json()["data"]["tables"]
    for table in ["users", "trips", "day_cards", "sub_trips", "pois", "favorites"]:
        assert table in tables
        assert "row_count" in tables[table]


def _seed_trip_graph() -> None:
    with session_scope() as session:
        user = User(
            email=f"admin_summary_{uuid.uuid4().hex}@example.com",
            name="Admin Summary User",
        )
        session.add(user)
        session.flush()
        trip = Trip(user_id=user.id, title="Admin Summary Trip", destination="测试城市")
        session.add(trip)
        session.flush()
        day_card = DayCard(trip_id=trip.id, day_index=0, date=date.today())
        session.add(day_card)
        session.flush()
        session.add(
            SubTrip(
                day_card_id=day_card.id,
                order_index=0,
                activity="Admin Summary Activity",
            )
        )


def test_admin_trip_summary_endpoint_returns_counts(client):
    _seed_trip_graph()
    resp = client.get("/admin/trips/summary")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total_trips"] >= 1
    assert data["total_day_cards"] >= 1
    assert isinstance(data["recent_trips"], list)


def test_admin_api_routes_only_includes_api_paths(client):
    resp = client.get("/admin/api/routes", headers=_admin_headers())
    assert resp.status_code == 200
    routes = resp.json()["data"]["routes"]
    assert routes, "should expose api routes"
    assert all(route["path"].startswith("/api/") for route in routes)


def test_admin_api_schemas_endpoint_returns_payload(client):
    resp = client.get("/admin/api/schemas", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "schemas" in data


def test_admin_api_routes_requires_token(client):
    resp = client.get("/admin/api/routes")
    assert resp.status_code == 401
    payload = resp.json()
    assert payload["code"] == 2001


def test_admin_ai_summary_requires_auth(client):
    resp = client.get("/admin/ai/summary")
    assert resp.status_code == 401
    body = resp.json()
    assert body["code"] == 2001


def test_admin_ai_summary_returns_metrics(client):
    resp = client.get("/admin/ai/summary", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "ai_calls_total" in data


def test_admin_db_schema_endpoint_returns_tables(client):
    resp = client.get("/admin/db/schema")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "tables" in data
    assert "trips" in data["tables"]


def test_admin_api_docs_page_serves_html(client):
    resp = client.get("/admin/api-docs")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "API 文档与在线测试" in resp.text


def test_admin_db_schema_page_serves_html(client):
    resp = client.get("/admin/db/schema?view=1")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "数据库结构视图" in resp.text


def test_admin_chat_summary_requires_auth(client):
    resp = client.get("/admin/chat/summary")
    assert resp.status_code == 401


def test_admin_chat_summary_counts_sessions(client):
    payload = {"user_id": 55, "query": "测试多轮", "use_memory": False}
    client.post("/api/ai/chat", json=payload)
    resp = client.get("/admin/chat/summary", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["sessions_total"] >= 1


def test_admin_prompt_update_and_reset(client):
    headers = _admin_headers()
    list_resp = client.get("/admin/api/prompts", headers=headers)
    assert list_resp.status_code == 200
    prompts = list_resp.json()["data"]
    key = prompts[0]["key"]
    update_resp = client.put(
        f"/admin/api/prompts/{key}",
        headers=headers,
        json={"content": "test content", "updated_by": "pytest"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["data"]["content"] == "test content"
    reset_resp = client.post(f"/admin/api/prompts/{key}/reset", headers=headers)
    assert reset_resp.status_code == 200
