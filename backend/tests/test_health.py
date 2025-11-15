def test_healthz_endpoint(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["status"] == "ok"
