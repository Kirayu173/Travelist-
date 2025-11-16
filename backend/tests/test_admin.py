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


def test_admin_api_testcases_returns_presets(client):
    resp = client.get("/admin/api/testcases")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) >= 2
    assert any(case["path"] == "/healthz" for case in data)


def test_admin_api_test_executes_healthz(client):
    payload = {"method": "GET", "path": "/healthz"}
    resp = client.post("/admin/api/test", json=payload)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status_code"] == 200
    assert data["ok"] is True
    assert '"status":"ok"' in data["response_body_excerpt"]


def test_admin_checks_endpoint_returns_three_items(client):
    resp = client.get("/admin/checks")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 3
    names = {item["name"] for item in data}
    assert {"db_connectivity", "redis_connectivity", "alembic_initialized"} <= names


def test_admin_db_and_redis_status_endpoints_return_payload(client):
    db_resp = client.get("/admin/db/status")
    redis_resp = client.get("/admin/redis/status")
    assert db_resp.status_code == 200
    assert "status" in db_resp.json()["data"]
    assert redis_resp.status_code == 200
    assert "status" in redis_resp.json()["data"]
