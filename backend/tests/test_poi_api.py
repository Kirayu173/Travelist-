from __future__ import annotations

from fastapi.testclient import TestClient


def test_poi_api_returns_data(client: TestClient):
    resp = client.get("/api/poi/around?lat=23.12908&lng=113.26436&radius=500&type=food")
    assert resp.status_code == 200
    payload = resp.json()["data"]
    assert "items" in payload
    assert isinstance(payload["items"], list)
    # mock provider可能返回空，但接口格式必须存在 meta
    assert "meta" in payload
