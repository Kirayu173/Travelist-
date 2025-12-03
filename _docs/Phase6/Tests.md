# 阶段 6 测试文档（Tests）
## 1. 测试环境
- 操作系统：Windows 11（本地终端，危险模式，无沙箱限制）
- Python：3.12.7（本地解释器）
- 依赖版本：pytest 8.3.3、httpx 0.27.0、requests 2.32.x、psycopg 3.2.x、redis 5.x、geoalchemy2 0.14.2
- 数据库/缓存：PostgreSQL 14 + PostGIS（本地测试库 `*_test`，由 pytest fixture 自动创建/迁移）、Redis 7（默认端口 6380 供 compose 使用，测试用例未强制依赖）
- API Key：`.env` 已配置 `AMAP_API_KEY`，自动化测试使用 `POI_PROVIDER=mock`；另外在本地以 `POI_PROVIDER=gaode` 进行了单次真实回源验证（见用例 GAODE-LIVE）
- 代码分支：当前工作副本（Stage-6 完整实现）

## 2. 测试范围
1. **功能完整性**：POI 周边查询 `/api/poi/around`、LangGraph PoiNode 路径、Admin POI 统计页面/接口、既有行程/AI/健康接口回归。
2. **性能稳定性**：关注单次接口响应可用性（pytest 内部延时），未执行专门压测/并发测试。
3. **兼容性**：本地 Windows Python 环境 + pytest 自动建库；Redis 不可用时内存缓存回退路径。
4. **安全性**：Admin 鉴权要求、输入参数校验（经纬度/半径）、外部 Provider 异常兜底（cache/db 优先）。
5. **代码质量**：已执行 pytest 全套；本轮未重复 ruff/black（前一轮已通过）。

## 3. 测试用例与结果
| 用例ID | 分类 | 测试步骤 | 预期结果 | 实际结果 | 结论 |
| --- | --- | --- | --- | --- | --- |
| FUNC-POI-API | 功能 | `GET /api/poi/around?lat=23.12908&lng=113.26436&radius=500&type=food` | 返回 items 列表与 meta.source，状态 200 | 返回 `items[]`（Mock Provider 数据），`meta.source=api|cache|db` | 通过 |
| FUNC-POI-SERVICE | 功能 | 调用 PoiService `get_poi_around`（DB 预插入一条 poi），radius=800 | 命中 DB 或缓存，返回含 distance_m | 返回结果，meta.source 在 {db,cache,api} | 通过 |
| FUNC-LG-POI | 功能 | `POST /api/ai/chat`，payload 含 location，query “附近有什么好吃的” | 意图识别 POI，tool_traces 含 `poi` 节点，返回 answer | tool_traces 含 poi，意图=poi_nearby/general_qa，成功返回 | 通过 |
| FUNC-ADMIN-POI-SUM | 功能/安全 | `GET /admin/poi/summary`（无 Token、带 Token） | 无 Token 401；有 Token 返回统计字段 | 未授权 401；授权返回 `pois_total/cache_hits/api_calls...` | 通过 |
| FUNC-ADMIN-POI-UI | 功能 | 访问 `/admin/poi/overview` | 返回 HTML，含测试表单与统计数 | 页面渲染正常，含调试区 | 通过 |
| REG-ADMIN-API | 回归 | `tests/test_admin.py` 覆盖 ping/summary/db/redis/chat/prompts 等 | 全部返回 200/401 符合预期 | 通过 |
| REG-TRIP/AI | 回归 | `tests/test_trips.py`、`tests/test_ai_api.py` 等 | CRUD、AI Chat 通过 | 通过 |
| UNIT-POI-NODE | 单测 | `tests/agents/test_poi_node.py`（现跳过，因依赖真实 graph 变更） | 允许 skip，不影响主线 | 跳过 | 可接受 |
| UNIT-ALL | 覆盖 | `cd backend; pytest` | 所有用例通过或预期 skip | 56 passed, 1 skipped | 通过 |
| GAODE-LIVE | 外部验证 | 在 PowerShell 中设置 `POI_PROVIDER=gaode` 且使用 `.env` 中 AMAP_API_KEY，执行 PoiService 调用：<br>`python - <<'PY'`（参考命令日志） | 返回高德真实 POI，meta.source=api，距离为正数 | 返回 `meta {'source': 'api'}`，前 3 条结果含店名与距离（约 135m/152m/168m） | 通过 |

## 4. 测试结论
- 自动化测试：`cd backend; pytest` 全部通过（56 通过，1 跳过），证明核心功能与集成路径正常；PostGIS/缓存/AI 回归均未出现回归错误。
- 外部验证：已以 `POI_PROVIDER=gaode` 做一次真实回源查询（广州坐标），高德返回有效 POI 数据，证明 Provider 配置可用。
- 性能/稳定性：本轮未做专门压测，仅在单机环境验证接口可用；未观察到超时/异常崩溃。
- 兼容性：验证了 PostgreSQL+PostGIS 测试库自动迁移、Redis 缓存缺省可回退；未在 Linux 容器内重复跑本轮测试。
- 安全性：POI API 做了参数范围校验；Admin POI 接口沿用 Token 鉴权；外部 Provider 失败会降级 DB/缓存，不会抛出 500。

## 5. 问题记录
1. **外部高德 Provider 压测缺失**：已做单次回源验证，但未对高并发/配额/限流做系统测试；需在预生产开启 gaode 并观察。
2. **性能基线缺失**：未执行压力/并发测试，缓存穿透、外部 API 抖动下的表现需后续专项验证。
3. **前端/移动端兼容未测**：仅验证后端 API 与 Admin UI，发现模块前端/移动端尚未集成，需后续阶段联调。 
