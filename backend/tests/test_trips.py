from __future__ import annotations

import uuid
from datetime import date

from app.core.db import session_scope
from app.models.orm import User


def _create_user(email_suffix: str | None = None) -> int:
    suffix = email_suffix or uuid.uuid4().hex
    with session_scope() as session:
        user = User(email=f"trip_test_{suffix}@example.com", name="Trip API Tester")
        session.add(user)
        session.flush()
        return user.id


def test_trip_crud_flow(client):
    user_id = _create_user()

    payload = {
        "user_id": user_id,
        "title": "集成测试行程",
        "destination": "广州",
        "status": "draft",
        "start_date": date.today().isoformat(),
        "end_date": date.today().isoformat(),
        "day_cards": [
            {
                "day_index": 0,
                "date": date.today().isoformat(),
                "note": "抵达",
                "sub_trips": [
                    {
                        "order_index": 0,
                        "activity": "午餐",
                    }
                ],
            }
        ],
    }

    create_resp = client.post("/api/trips", json=payload)
    assert create_resp.status_code == 200
    created = create_resp.json()["data"]
    trip_id = created["trip_id"]

    list_resp = client.get(f"/api/trips?user_id={user_id}")
    assert list_resp.status_code == 200
    trips = list_resp.json()["data"]
    assert trips and trips[0]["title"] == "集成测试行程"

    detail_resp = client.get(f"/api/trips/{trip_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()["data"]
    assert detail["day_cards"][0]["sub_trips"][0]["activity"] == "午餐"

    update_resp = client.put(f"/api/trips/{trip_id}", json={"title": "更新后的行程"})
    assert update_resp.status_code == 200
    assert update_resp.json()["data"]["title"] == "更新后的行程"

    delete_resp = client.delete(f"/api/trips/{trip_id}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["data"]["deleted"] is True

    missing_resp = client.get(f"/api/trips/{trip_id}")
    assert missing_resp.status_code == 400
    assert missing_resp.json()["code"] == 14004


def test_day_card_and_sub_trip_endpoints(client):
    user_id = _create_user()
    create_resp = client.post(
        "/api/trips",
        json={"user_id": user_id, "title": "DayCard 测试", "destination": "上海"},
    )
    trip_id = create_resp.json()["data"]["trip_id"]

    day_resp = client.post(
        f"/api/trips/{trip_id}/day_cards",
        json={
            "day_index": 0,
            "note": "第一天",
            "date": date.today().isoformat(),
        },
    )
    assert day_resp.status_code == 200
    day_card_id = day_resp.json()["data"]["id"]

    sub_resp = client.post(
        f"/api/day_cards/{day_card_id}/sub_trips",
        json={
            "activity": "参观博物馆",
            "order_index": 0,
        },
    )
    assert sub_resp.status_code == 200
    sub_trip_id = sub_resp.json()["data"]["id"]

    sub_update = client.put(
        f"/api/sub_trips/{sub_trip_id}",
        json={"activity": "夜间巡游", "order_index": 1},
    )
    assert sub_update.status_code == 200
    assert sub_update.json()["data"]["activity"] == "夜间巡游"

    sub_delete = client.delete(f"/api/sub_trips/{sub_trip_id}")
    assert sub_delete.status_code == 200

    day_delete = client.delete(f"/api/day_cards/{day_card_id}")
    assert day_delete.status_code == 200


def test_sub_trip_reorder_across_days(client):
    user_id = _create_user()
    create_resp = client.post(
        "/api/trips",
        json={
            "user_id": user_id,
            "title": "重排行程",
            "destination": "杭州",
            "day_cards": [
                {
                    "day_index": 0,
                    "sub_trips": [
                        {"order_index": 0, "activity": "早餐"},
                        {"order_index": 1, "activity": "午餐"},
                    ],
                },
                {
                    "day_index": 1,
                    "sub_trips": [
                        {"order_index": 0, "activity": "徒步"},
                    ],
                },
            ],
        },
    )
    trip_payload = create_resp.json()["data"]["trip"]
    day0 = next(card for card in trip_payload["day_cards"] if card["day_index"] == 0)
    day1 = next(card for card in trip_payload["day_cards"] if card["day_index"] == 1)
    sub_trip_id = day0["sub_trips"][0]["id"]

    reorder = client.post(
        f"/api/sub_trips/{sub_trip_id}/reorder",
        json={"day_card_id": day1["id"], "order_index": 0},
    )
    assert reorder.status_code == 200
    payload = reorder.json()["data"]
    assert payload["target_day_card_id"] == day1["id"]
    assert payload["target_sub_trips"][0]["id"] == sub_trip_id

    detail = client.get(f"/api/trips/{trip_payload['id']}")
    data = detail.json()["data"]
    updated_day0 = next(card for card in data["day_cards"] if card["day_index"] == 0)
    updated_day1 = next(card for card in data["day_cards"] if card["day_index"] == 1)
    assert len(updated_day0["sub_trips"]) == 1
    assert updated_day1["sub_trips"][0]["id"] == sub_trip_id
    assert updated_day1["sub_trips"][0]["order_index"] == 0


def test_update_sub_trip_allows_reorder(client):
    user_id = _create_user()
    create_resp = client.post(
        "/api/trips",
        json={
            "user_id": user_id,
            "title": "更新排序",
            "destination": "北京",
            "day_cards": [
                {
                    "day_index": 0,
                    "sub_trips": [
                        {"order_index": 0, "activity": "早饭"},
                        {"order_index": 1, "activity": "午饭"},
                    ],
                }
            ],
        },
    )
    trip_payload = create_resp.json()["data"]["trip"]
    trip_id = trip_payload["id"]
    day_card = trip_payload["day_cards"][0]
    first_id = day_card["sub_trips"][0]["id"]

    update_resp = client.put(
        f"/api/sub_trips/{first_id}",
        json={"order_index": 1},
    )
    assert update_resp.status_code == 200

    detail = client.get(f"/api/trips/{trip_id}").json()["data"]
    sub_trips = detail["day_cards"][0]["sub_trips"]
    assert [item["activity"] for item in sub_trips[:2]] == ["午饭", "早饭"]
    assert [item["order_index"] for item in sub_trips[:2]] == [0, 1]


def test_create_sub_trip_respects_order_index(client):
    user_id = _create_user()
    create_resp = client.post(
        "/api/trips",
        json={
            "user_id": user_id,
            "title": "Order 测试",
            "destination": "深圳",
            "day_cards": [
                {
                    "day_index": 0,
                    "sub_trips": [
                        {"order_index": 0, "activity": "早餐"},
                        {"order_index": 1, "activity": "午餐"},
                    ],
                }
            ],
        },
    )
    trip_payload = create_resp.json()["data"]["trip"]
    day0 = trip_payload["day_cards"][0]
    day_card_id = day0["id"]
    trip_id = trip_payload["id"]

    # insert at head with explicit 0
    insert_resp = client.post(
        f"/api/day_cards/{day_card_id}/sub_trips",
        json={"activity": "早茶", "order_index": 0},
    )
    assert insert_resp.status_code == 200

    detail = client.get(f"/api/trips/{trip_id}").json()["data"]
    day0_detail = next(
        card for card in detail["day_cards"] if card["id"] == day_card_id
    )
    names = [item["activity"] for item in day0_detail["sub_trips"]]
    order_indexes = [item["order_index"] for item in day0_detail["sub_trips"]]
    assert names[:3] == ["早茶", "早餐", "午餐"]
    assert order_indexes[:3] == [0, 1, 2]

    # append when order_index omitted
    append_resp = client.post(
        f"/api/day_cards/{day_card_id}/sub_trips",
        json={"activity": "晚餐"},
    )
    assert append_resp.status_code == 200
    detail = client.get(f"/api/trips/{trip_id}").json()["data"]
    day0_detail = next(
        card for card in detail["day_cards"] if card["id"] == day_card_id
    )
    assert day0_detail["sub_trips"][-1]["activity"] == "晚餐"
    assert day0_detail["sub_trips"][-1]["order_index"] == 3


def test_trip_creation_requires_existing_user(client):
    resp = client.post(
        "/api/trips",
        json={
            "user_id": 999999,
            "title": "孤立行程",
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 14003
