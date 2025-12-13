from __future__ import annotations

import pytest
from app.core.db import session_scope
from app.services.poi_service import PoiService
from sqlalchemy import text


@pytest.mark.asyncio
async def test_poi_service_queries_db(monkeypatch):
    service = PoiService(cache_ttl_seconds=30)
    # 确保使用本地缓存，避免 redis 依赖
    monkeypatch.setattr(service, "_redis", None)
    with session_scope() as session:
        session.execute(
            text(
                """
                INSERT INTO pois(
                    provider, provider_id, name, category, addr, rating, geom
                )
                VALUES (:provider, :pid, :name, :cat, :addr, :rating,
                        ST_GeogFromText('SRID=4326;POINT(113.26436 23.12908)'))
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "provider": "mock",
                "pid": "test-1",
                "name": "测试POI",
                "cat": "food",
                "addr": "测试地址",
                "rating": 4.5,
            },
        )
        session.commit()

    results, meta = await service.get_poi_around(
        lat=23.12908,
        lng=113.26436,
        poi_type="food",
        radius=800,
        limit=5,
    )
    assert results, "DB 应返回附近结果"
    assert meta["source"] in {"db", "cache", "api"}
    assert "distance_m" in results[0]


@pytest.mark.asyncio
async def test_poi_service_cache_hit(monkeypatch):
    service = PoiService(cache_ttl_seconds=10)
    monkeypatch.setattr(service, "_redis", None)
    data = [
        {
            "name": "缓存POI",
            "provider": "mock",
            "provider_id": "cache",
            "lat": 0,
            "lng": 0,
        }
    ]
    key = service._build_cache_key(0, 0, None, 1000, 50)
    await service._cache_set(key, data)
    results, meta = await service.get_poi_around(
        lat=0,
        lng=0,
        poi_type=None,
        radius=1000,
    )
    assert meta["source"] == "cache"
    assert results[0]["name"] == "缓存POI"
