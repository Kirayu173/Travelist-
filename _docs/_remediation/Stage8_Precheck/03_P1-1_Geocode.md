# P1-1：目的地中心点真实化（Geocode）

## 整改目标
- 用可配置的 geocode 解析目的地中心点，替代 FastPlanner 的伪中心点（hash 映射），提升候选 POI 的地理相关性。
- 保持“可控/可复现”：无 key/无网络时可稳定回退到确定性伪中心点。

## 实施步骤
1. 新增 `GeocodeService`：`backend/app/services/geocode_service.py`
   - 支持 `GEOCODE_PROVIDER=mock|amap|disabled`
   - 对同一目的地做缓存（`GEOCODE_CACHE_TTL_SECONDS`）
2. 更新 `FastPlanner`：`backend/app/services/fast_planner.py`
   - `_load_candidates` 中通过 `GeocodeService.resolve_city_center()` 获取 `lat/lng`
   - 在 metrics 中输出 `destination_center.provider/source`
3. 配置项对齐：`backend/app/core/settings.py`、`.env.example`

## 完成时限
- 2025-12-13（已完成）

## 效果验证
- `POST /api/ai/plan` 返回的 `data.metrics.destination_center` 包含 `lat/lng/provider/source`。
- 在 `GEOCODE_PROVIDER=amap` 且配置 `AMAP_API_KEY` 时，中心点应来自高德 Geocode；缺失 key 时自动回退且可追踪 source。

## 证据材料
- 变更文件：
  - `backend/app/services/geocode_service.py`
  - `backend/app/services/fast_planner.py`
  - `backend/app/core/settings.py`
  - `.env.example`

