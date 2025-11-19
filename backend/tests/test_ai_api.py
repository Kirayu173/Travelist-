from __future__ import annotations

from fastapi.testclient import TestClient


def _chat_payload() -> dict:
    return {
        "user_id": 7,
        "level": "user",
        "query": "记住我喜欢早起去广州塔",
        "use_memory": True,
        "return_memory": True,
    }


def test_chat_demo_returns_answer(client: TestClient) -> None:
    payload = _chat_payload()
    resp = client.post("/api/ai/chat_demo", json=payload)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["answer"].startswith("mock:")
    assert data["ai_meta"]["trace_id"].startswith("ai-")
    assert data["memory_record_id"]


def test_chat_demo_reuses_memory_on_second_call(client: TestClient) -> None:
    payload = _chat_payload()
    client.post("/api/ai/chat_demo", json=payload)
    resp = client.post("/api/ai/chat_demo", json=payload)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["used_memory"], "second call should surface prior memory"
