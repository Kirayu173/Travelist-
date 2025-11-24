from __future__ import annotations

import pytest


@pytest.mark.skip(reason="PoiNode not implemented yet; placeholder for Stage-6 tests.")
def test_poi_node_placeholder():
    """
    标准化占位测试：待 Stage-6 落地后补充 PoiNode 工具链的集成/契约测试。
    预期结构：
    - 构建包含 PoiNode 的 LangGraph
    - stub 外部 POI API 与 Redis 缓存
    - 验证工具选择、缓存命中、回源行为
    """
    assert True
