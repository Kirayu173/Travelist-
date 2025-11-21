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


def test_chat_endpoint_creates_session(client: TestClient) -> None:
    payload = {"user_id": 9, "query": "帮我看看行程", "use_memory": False}
    resp = client.post("/api/ai/chat", json=payload)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["session_id"] > 0
    assert data["answer"]


def test_chat_endpoint_reuses_session(client: TestClient) -> None:
    payload = {"user_id": 9, "query": "第一问", "use_memory": False}
    first = client.post("/api/ai/chat", json=payload).json()["data"]
    session_id = first["session_id"]
    second_payload = {
        "user_id": 9,
        "query": "第二问",
        "use_memory": True,
        "session_id": session_id,
    }
    resp = client.post("/api/ai/chat", json=second_payload)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["session_id"] == session_id
    assert len(data["messages"]) >= 2
