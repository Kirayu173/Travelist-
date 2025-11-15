def test_admin_ping_returns_version_and_time(client):
    resp = client.get("/admin/ping")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert isinstance(data["version"], str)
    assert isinstance(data["time"], str)


def test_admin_summary_tracks_basic_routes(client):
    client.get("/healthz")
    client.get("/healthz")
    client.get("/admin/ping")

    resp = client.get("/admin/api/summary")
    assert resp.status_code == 200
    summary = resp.json()["data"]
    assert summary["total_requests"] >= 3
    assert "GET /healthz" in summary["routes"]
    assert "GET /admin/ping" in summary["routes"]


def test_admin_health_contains_required_keys(client):
    resp = client.get("/admin/health")
    assert resp.status_code == 200
    data = resp.json()["data"]
    for key in ("app", "db", "redis"):
        assert key in data
