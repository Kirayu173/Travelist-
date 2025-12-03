# 阶段 6 开发工作报告（POI & 缓存 & LangGraph 工具接入）

## 1. 开发概览
- 新增 **POI 服务**：`/api/poi/around` 支持经纬度/类型/半径查询，按 Redis → 本地 `pois` 表 → 第三方（高德/Mock）回源的 cache-aside 模式返回距离排序结果。
- 完成 **缓存与计数**：缓存键 `poi:around:{lat}:{lng}:{type}:{radius}`（经纬度归一化），记录命中/未命中/回源次数，Admin 可观测。
- **LangGraph 接入 PoiNode**：`AssistantState` 增加位置/POI 查询字段，新增 `poi` 节点，意图识别支持 POI 类问题，回答自动融合附近兴趣点。
- **Admin 监控**：新增 `/admin/poi/summary` 与 `/admin/poi/overview` 页面，Dashboard 卡片展示 POI 缓存命中率与 API 调用。
- **配置与文档**：`.env.example` 增加 POI 相关变量；新增 Phase6 Code 文档；完善测试覆盖 POI 服务、API、LangGraph、Admin 鉴权。

## 2. 目录与关键文件
- POI 服务与 API：`backend/app/services/poi_service.py`，`backend/app/api/poi.py`。
- LangGraph 扩展：`backend/app/agents/assistant/state.py`、`nodes.py`、`graph.py`，`backend/app/services/assistant_service.py`。
- Admin 监控与模板：`backend/app/admin/service.py`、`backend/app/api/admin.py`、`backend/app/admin/templates/poi_overview.html`、`dashboard.html`。
- 配置与环境：`backend/app/core/settings.py`、`.env.example`。
- 测试：`backend/tests/test_poi_service.py`、`test_poi_api.py`、`test_assistant_poi.py`、`test_admin.py` 补充。

## 3. 核心实现说明
### 3.1 POI Service（cache-aside）
- 输入校验：纬度[-90,90]、经度[-180,180]，半径默认 `POI_DEFAULT_RADIUS_M`，上限 `POI_MAX_RADIUS_M`，类型可选。
- 缓存：优先 Redis（不可用时自动降级内存 `_MemoryCache`），TTL `POI_CACHE_TTL_SECONDS`，命中/未命中计数保存在 `PoiMetrics`。
- DB 查询：PostGIS `ST_DWithin` + `ST_Distance` 排序，返回距离字段 `distance_m`，并附 source=db。
- 回源：当结果不足 `POI_MIN_RESULTS`，调用 Provider（默认 Mock，`poi_provider=gaode` 且配置 key 时用高德）。回源结果按 provider/provider_id 去重，使用 `ST_GeogFromText` 写入 `pois` 表，最终按距离合并排序。
- 输出：`(results, meta)`，结果含 `name/category/addr/rating/lat/lng/distance_m/source`。

### 3.2 `/api/poi/around`
- 路由：`GET /api/poi/around?lat&lng&type&radius&limit`，参数使用 FastAPI 校验，错误返回 400 + 业务码 `14040`。
- 响应：`{"items": [...], "meta": {"source": "cache|db|api"}}`，配合前端/发现模块可直接消费。

### 3.3 LangGraph PoiNode
- 状态扩展：`AssistantState` 增加 `location`、`poi_query`、`poi_results`。
- 意图识别：`_infer_intent` 增加 “附近/周边/吃/景点/酒店” 关键词 → `poi_nearby`，并通过 `_guess_poi_type` 自动推测类型。
- 图路由：`memory_read -> assistant -> poi -> trip_query -> tool_agent -> response`，非 POI 意图在 `poi_node` 中跳过。
- 响应格式化：`response_formatter_node` 在存在 `poi_results` 时输出前 5 个兴趣点摘要，空结果有兜底提示。

### 3.4 Admin 监控
- 新增接口：`GET /admin/poi/summary`（鉴权），返回 `pois_total/pois_recent_7d/cache_hits/cache_misses/api_calls/api_failures`。
- 新增页面：`/admin/poi/overview` 用于展示统计与快速调试 POI 接口。
- Dashboard 卡片：展示 POI 缓存命中率与 API 调用总数，脚本同时拉取 AI 与 POI 摘要。

### 3.5 配置
- 新增环境变量：`POI_PROVIDER`（mock/gaode）、`POI_GAODE_API_KEY`、`POI_DEFAULT_RADIUS_M`、`POI_MAX_RADIUS_M`、`POI_CACHE_TTL_SECONDS`、`POI_COORD_PRECISION`、`POI_CACHE_ENABLED`。
- 默认使用 Mock Provider，避免无 Key 场景阻塞；可根据部署环境切换至高德。

## 4. 接口与使用示例
### 4.1 附近 POI
```
GET /api/poi/around?lat=23.12908&lng=113.26436&type=food&radius=800
Response:
{
  "code": 0,
  "msg": "ok",
  "data": {
    "items": [
      {"name": "Mock Food 1", "distance_m": 120.5, "source": "cache|db|api", ...}
    ],
    "meta": {"source": "api"}
  }
}
```

### 4.2 LangGraph 聊天（携带位置）
```
POST /api/ai/chat
{
  "user_id": 1,
  "query": "附近有什么好吃的？",
  "location": {"lat": 23.12908, "lng": 113.26436},
  "poi_radius": 500,
  "use_memory": false
}
```
当意图判定为 `poi_nearby` 时，将调用 PoiNode 并在回答中返回 POI 摘要与 `tool_traces` 记录。

### 4.3 Admin POI 监控
- JSON：`GET /admin/poi/summary`（需 X-Admin-Token）。
- 页面：浏览器访问 `/admin/poi/overview`，可查看统计并在线测试 `/api/poi/around`。

## 5. 核心代码位置
- POI 服务与缓存：`backend/app/services/poi_service.py`
- POI API：`backend/app/api/poi.py`
- LangGraph 节点：`backend/app/agents/assistant/nodes.py`（poi_node、意图识别、格式化），`graph.py`（路由）
- Assistant 服务注入：`backend/app/services/assistant_service.py`
- Admin 统计：`backend/app/admin/service.py`、`backend/app/api/admin.py`、`backend/app/admin/templates/poi_overview.html`、`dashboard.html`
- 配置：`backend/app/core/settings.py`、`.env.example`

## 6. 注意事项
- 依赖 PostGIS：`pois` 查询使用 `ST_DWithin`/`ST_Distance`，请确保已启用 `postgis` 扩展，测试数据库通过 Alembic 迁移自动创建。
- 缓存回退：Redis 不可用时自动使用进程内缓存，计数仍会记录；生产建议启用 Redis 以提升多实例一致性。
- Provider 切换：无高德 Key 时保持 `POI_PROVIDER=mock` 以避免外网依赖；切换高德需设置 `POI_GAODE_API_KEY`。
- 安全：Admin 相关接口仍需 `X-Admin-Token`，POI API 做了经纬度/半径范围校验。

## 7. 测试
- 单元测试：`test_poi_service.py`（缓存/DB 路径）、`test_assistant_poi.py`（LangGraph 路由）、`test_poi_api.py`（API 返回格式）。
- 集成/系统：现有 pytest 套件自动创建测试 Postgres，并执行 Alembic 迁移；`test_admin.py` 覆盖 POI Summary 鉴权与数据。运行方式：
```
cd backend
python -m pytest
```

## 8. 后续建议
- 如需更精细的意图分类，可在 Prompt Center 中更新 `assistant.intent.classify` 提示词并增加类型白名单。
- 在生产环境开启 Redis provider，并考虑为缓存命中率/API 失败率增加报警。
- 可继续丰富 Provider 抽象（百度/Google Places），并为 POI 数据加全文索引/评分权重。 
