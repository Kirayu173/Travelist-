## 1. 概述

### 1.1 阶段编号与名称

* 阶段编号：**Stage-6**
* 阶段名称：**POI & 地理服务 + Redis 缓存（智能体工具层 / 发现模块后端）**

### 1.2 背景

前 5 个阶段已经完成：

* Stage-1：后端管理界面 `/admin/dashboard` 基础版，提供 API 调用统计与基础健康检查。
* Stage-2：落地 PostgreSQL + PostGIS 核心表结构，并在 Admin 中接入真实 DB 健康检查与统计。
* Stage-3：实现行程 CRUD、子行程排序与跨天移动、Admin 行程统计等。
* Stage-4：完成 LLM Provider 层（AiClient）、mem0 记忆接入（MemoryService）、AI Demo 接口 `/api/ai/chat_demo` 以及 Admin AI 监控和在线测试控制台。
* Stage-5：完成 LangGraph 智能助手 v1、多轮对话版 `/api/ai/chat`、Prompt 中心管理、会话持久化与 Admin 智能体测试台 / 提示词管理。

按阶段开发规划，Stage-6 的原始定位是： **POI & 地理服务 + Redis 缓存（为智能规划准备工具层）** ，包括 `/api/poi/around`、Redis 缓存键设计以及将 `PoiNode` 纳入 LangGraph。

同时，在整体设计与数据库设计文档中，已经给出 `pois` 表结构、PostGIS 应用方式以及 Redis 键空间原则，本阶段需要把这些内容真正工程化落地，并与现有 LangGraph 助手 / Admin 后台整合。

### 1.3 阶段目标（Stage-6 完成时应达到）

1. **POI 服务 API 可用**
   * 提供稳定的 `/api/poi/around` 接口，支持按经纬度、类型、半径查询附近兴趣点；
   * 返回结构与 `pois` 表 / 前端需求对齐，可直接为“发现”模块和规划器使用。
2. **Redis 缓存与回源流程落地**
   * 按照 cache-aside 模式实现 POI 缓存： **Redis → 本地 `pois` 表 → 第三方地图 API** ；
   * 设计并实现缓存 Key 与 TTL 规则（`poi:around:{lat}:{lng}:{type}:{radius}`）。
3. **LangGraph 工具层引入 `PoiNode`**
   * 在现有 `AssistantState` / 图结构中新增 `PoiNode` / `poi_query_node` 等，完成“附近 POI / 兴趣点问答”意图的工具调用链路；
   * 新增/扩展 Prompt 与意图分类，使助手能够识别与调用 POI 工具，并在回答中引用结果。
4. **Admin POI 监控与可视化**
   * Admin 侧新增 `/admin/poi/summary` JSON 接口及对应页面，展示 POI 表规模、缓存命中/穿透、第三方 API 调用计数等；
   * 将 POI 统计挂入 `/admin/dashboard` 或独立菜单，保持与行程 / AI / Chat 监控一致风格。
5. **质量与文档**
   * 完成与 Stage-6 强相关的 migration、测试用例与文档（`_docs/Phase6/Spec.md` / `Code.md` / `Tests.md` / `Review.md` 骨架）；
   * 为后续 Stage-7 “行程规划 Fast 模式（规则版）+ LangGraph Planner” 提供可复用的 `PoiService` / `PoiNode`。

---

## 2. 范围说明

### 2.1 本阶段实现范围

本阶段聚焦 **POI & 地理服务后端能力** 与  **智能体工具接入** ，具体包括：

1. **POI 数据模型与数据库层**
   * 校验并补齐 `pois` 表结构、索引、PostGIS 配置，与数据库设计文档保持一致：`provider`、`provider_id`、`name`、`category`、`addr`、`rating`、`geom geography(Point,4326)`、`ext JSONB` 等字段。
   * 若前序阶段尚未创建完整 `pois` 表或索引，本阶段通过 Alembic 迁移补齐。
2. **POI Service + `/api/poi/around`**
   * 实现 `PoiService`：封装 Redis 缓存、本地 PostgreSQL 查询、第三方地图 API（高德/百度）回源逻辑；
   * 设计并实现 REST 接口 `GET /api/poi/around?lat&lng&type&radius`，请求/响应结构与技术选型文档相符。
3. **Redis 缓存策略落地**
   * 设计并实现 `poi:around:{lat}:{lng}:{type}:{radius}` 形式的键值，包含坐标归一化策略（经纬度保留精度）与 TTL（默认 600s，可配置）；
   * 统计缓存 hit/miss 与第三方 API 调用次数，用于 Admin 观测。
4. **LangGraph `PoiNode` / 工具接入**
   * 在 `backend/app/ai/graph` 图中新增 `PoiNode` / `poi_query_node`，支持根据 `location` / `poi_query` / `type` 字段调用 `PoiService`；
   * 更新 `AssistantState`，增加 `location`（lat/lng）、`poi_query`、`poi_results` 等字段；
   * 更新意图分类 Prompt / 逻辑，新增与 POI 相关的意图（如 `poi_nearby`, `poi_food`, `poi_attraction`），并在图路由中接入 `PoiNode`。
5. **Admin 监控与页面**
   * 新增 `/admin/poi/summary` JSON 接口，返回 POI 表规模、缓存状态、第三方 API 调用统计；
   * 新增 `/admin/poi/overview`（或集成在 dashboard 的卡片）模板页面，直观展示上述指标；
   * 与现有 Admin 鉴权机制保持一致。
6. **测试与文档**
   * 为 `PoiService`、`/api/poi/around`、`PoiNode`、`/admin/poi/summary` 编写单元/集成测试；
   * 更新 Phase6 文档集（Spec / Code / Tests / Review），与前几个阶段格式统一。

### 2.2 非本阶段范围（但需兼容）

以下内容不在 Stage-6 的交付范围，但设计需与之兼容：

* **行程规划 Fast/Deep 模式** ：`PlannerNode`、`/api/ai/plan` 的规则规划与深度规划逻辑仍由 Stage-7 / Stage-8 实现，本阶段只提供可复用的 POI 工具。
* **Android 地图与发现 UI** ：Stage-6 不实现 Android 端 UI 集成，仅通过 Postman / Admin 验证接口；移动端集成在 Stage-10 / Stage-11 中完成。
* **复杂 POI 排序与个性化推荐** ：当前仅实现基础过滤与距离排序；基于用户偏好、历史行为的高级推荐算法属于后续可选扩展。
* **路线规划 / 多点路径绘制** ：本阶段聚焦“兴趣点检索”，路线规划 API 与前端绘制逻辑留在后续阶段实现。

---

## 3. 总体技术与通用约定

### 3.1 技术栈与依赖

沿用既有后端技术栈：

* 框架：FastAPI（ASGI）
* 数据库：PostgreSQL + PostGIS（已在前期启用）
* ORM：SQLAlchemy (+ geoalchemy2)
* 缓存：Redis
* 智能体编排：LangGraph（已有 Assistant 图基础）
* 记忆层：mem0（通过 MemoryService）
* LLM：通过 AiClient 抽象

新增/强调依赖：

* 地图/POI 提供方：高德地图 Web 服务（或可插拔 Provider 抽象）
* 地理空间库：`geoalchemy2`（若此前尚未引用，则在本阶段确认映射实现）

### 3.2 配置与环境变量约定

新增或需强调的配置（命名可在 Code 阶段微调，但语义需一致）：

**POI / 地理服务**

* `POI_PROVIDER`：POI 服务提供方（默认 `gaode`，也可以是 `mock` 用于测试）。
* `POI_GAODE_API_KEY`：高德 Web 服务 Key（后端独享，前端不可见）。
* `POI_DEFAULT_RADIUS_M`：默认检索半径（米），如 2000。
* `POI_MAX_RADIUS_M`：最大允许半径，用于输入限制。
* `POI_CACHE_TTL_SECONDS`：`poi:around` 缓存 TTL（默认 600 秒）。
* `POI_COORD_PRECISION`：缓存 Key 中纬经度保留位数（如 4 位小数）。

**Redis / 观测**

* `REDIS_URL` 已存在，本阶段需要确保可用；
* 可选：`POI_CACHE_ENABLED`（用于在开发环境下快速关闭缓存调试）。

配置规则：

* 所有环境变量仍通过 `.env` 注入，并在 `.env.example` 中增加示例与说明；
* 高德 / 外部 API Key 不允许出现在前端代码中，只能在服务端配置。

### 3.3 Graph 状态与节点约定（POI 相关）

在 Stage-5 的 `AssistantState` 基础上扩展：

```python
class AssistantState(BaseModel):
    user_id: int
    trip_id: int | None = None
    session_id: int | None = None

    query: str
    intent: str | None = None

    history: list[dict] = []
    memories: list[MemoryItem] = []
    trip_data: dict | None = None

    # 新增字段（Stage-6）
    location: dict | None = None   # {"lat": float, "lng": float}
    poi_query: dict | None = None  # {"type": "food|sight|hotel|...", "radius": int, ...}
    poi_results: list[dict] = []   # 经过 Service 处理后的 POI 列表

    answer_text: str | None = None
    tool_traces: list[dict] = []
    ai_meta: dict | None = None
```

**PoiNode 行为约定：**

* 输入：
  * `state.location`：调用方提供的坐标信息；
  * `state.poi_query`：意图解析节点填充的检索条件（类型、半径等）。
* 行为：
  * 调用 `PoiService.get_poi_around(location, query)`；
  * 写入 `state.poi_results`；
  * 在 `state.tool_traces` 中增加一条记录：包含 provider、来源（cache / db / api）等。
* 错误处理：
  * 当第三方 API 失败时，若本地 `pois` 中仍有可用数据，则降级到“仅 DB/缓存结果”；
  * 若无任何结果，则 `poi_results` 为空，同时在 `tool_traces` 中标记错误信息，供 Admin 调试。

**意图路由约定：**

* intent 示例：`"poi_nearby"`, `"poi_food"`, `"poi_attraction"` 等；
* 当 intent 属于 POI 类别时，图路径为：

```text
memory_read_node → assistant_node(intent 判定) 
  → poi_node (调用 PoiService)
  → response_formatter_node(整合 poi_results 生成回答)
```

其他 intent（如纯行程问答、通用 QA）保持 Stage-5 行为不变。

### 3.4 缓存策略与一致性约定

* 使用 **cache-aside** 模式：
  * 请求 → 查 Redis（基于归一化后的 key）；
  * miss → 查本地 `pois` 表 / 回源高德 API；
  * 将结果写入 Redis，并视情况插入/更新 `pois` 表。
* 数据一致性：
  * POI 数据视为“半静态”，短时间内无需强一致；
  * 本地 `pois` 作为中长期缓存，Redis 作为短期热缓存。
* 防御性设计：
  * 半径限制与输入校验，防止异常请求导致缓存穿透或高德 API 滥用；
  * 对第三方 API 调用加简单限流与超时设置。

---

## 4. 详细功能与实现要求

本阶段拆分为 4 个主要任务：

* **T6-1：POI 数据模型与迁移补充**
* **T6-2：POI Service 与 `/api/poi/around`（含 Redis 缓存）**
* **T6-3：LangGraph `PoiNode` 工具接入**
* **T6-4：Admin POI 监控与质量保障**

### 4.1 任务 T6-1：POI 数据模型与迁移补充

#### 4.1.1 功能目标

确保 `pois` 表与相关索引、PostGIS 扩展在当前数据库中正确创建，并与数据库设计文档完全对齐，为 POI 服务提供可靠数据存储基础。

#### 4.1.2 实现要求

1. **PostGIS / 类型检查**
   * 确认数据库已启用 `postgis` 扩展；
   * 确认 ENUM / 必要函数可用。
2. **`pois` 表结构**
   * 字段建议（与现有文档保持一致）：
     * `id BIGSERIAL PRIMARY KEY`
     * `provider TEXT`
     * `provider_id TEXT`
     * `name TEXT NOT NULL`
     * `category TEXT`
     * `addr TEXT`
     * `rating NUMERIC(3,2)`
     * `geom geography(Point,4326)`
     * `ext JSONB DEFAULT '{}'::jsonb`
     * 时间戳：`created_at`, `updated_at`
   * 索引：
     * `GIST (geom)` 用于附近检索；
     * `(provider, provider_id)`，避免重复插入同一第三方 POI；
     * 可选：`tsvector` 或 `GIN` 索引用于名称搜索。
3. **Alembic 迁移**
   * 编写/更新 Alembic 版本脚本，包含：
     * 如果表已存在，仅校验并补加缺失索引 / 列；
     * 若不存在，则完整创建（含扩展 / 类型 / 索引）。
4. **ORM 映射**
   * 在 `backend/app/models/orm.py` 中定义 `Poi` 模型；
   * 使用 `geoalchemy2` 将 `geom` 映射为 `Geography(POINT, 4326)`。

#### 4.1.3 测试要求

* 迁移层：
  * pytest 时自动执行 `alembic upgrade head`，确保 `pois` 表成功创建；
  * 对 `geom` 列插入示例点并进行简单 `ST_DWithin` 查询验证。
* ORM 层：
  * 通过 SQLAlchemy 插入/查询 POI，验证字段类型与映射正确。

---

### 4.2 任务 T6-2：POI Service 与 `/api/poi/around`（含 Redis 缓存）

#### 4.2.1 功能目标

实现可在生产环境使用的 POI 检索 API：`GET /api/poi/around`，同时落地 Redis 缓存与回源逻辑，为“发现”模块与后续规划器提供高性能的附近兴趣点查询能力。

#### 4.2.2 目录结构建议

```text
backend/app/
  services/
    poi_service.py      # PoiService 实现
  api/
    poi.py              # /api/poi/around 路由
```

#### 4.2.3 接口定义（草案）

* 路由：`GET /api/poi/around`
* 请求参数（query）：| 参数名 | 类型   | 必填 | 说明                                                                 |
  | ------ | ------ | ---- | -------------------------------------------------------------------- |
  | lat    | float  | 是   | 纬度                                                                 |
  | lng    | float  | 是   | 经度                                                                 |
  | type   | string | 否   | POI 类型（food/sight/hotel/...）                                     |
  | radius | int    | 否   | 半径（米），默认 `POI_DEFAULT_RADIUS_M`，上限 `POI_MAX_RADIUS_M` |
* 响应示例：

```json
{
  "code": 0,
  "msg": "ok",
  "data": [
    {
      "id": 123,
      "name": "某餐厅",
      "category": "food",
      "addr": "广州市天河区...",
      "lat": 23.12345,
      "lng": 113.12345,
      "rating": 4.5,
      "source": "db",        // 或 "cache", "api"
      "distance_m": 230
    }
  ]
}
```

#### 4.2.4 行为与约束

1. **参数校验**
   * 使用 Pydantic 模型校验：
     * lat ∈ [-90, 90]，lng ∈ [-180, 180]；
     * radius 严格限制在 `(0, POI_MAX_RADIUS_M]`；
   * type 使用白名单（`food/sight/hotel/shopping/...`），非法值视为 `all` 或直接返回错误。
2. **缓存 Key 设计**
   * key 形如：`poi:around:{lat_q}:{lng_q}:{type}:{radius}`；
   * `{lat_q}` / `{lng_q}` 为经纬度按 `POI_COORD_PRECISION` 舍入后的字符串；
   * value 为 JSON 序列化的 POI 列表 + 简单元信息（生成时间、provider）。
3. **cache-aside 流程**
   * 读取：
     1. 构造 key；
     2. Redis `GET`，命中则直接返回；
   * miss：
     1. 先尝试从 `pois` 表中按 `ST_DWithin` 查询附近 POI；
     2. 如果结果不足（例如 < N 条），再调用外部地图 API 回源；
     3. 将新获取到的 POI 写入 `pois` 表（使用 `provider/provider_id` 去重）；
     4. 把合并结果写入 Redis，并返回。
4. **第三方 API 封装**
   * 在 `PoiService` 内部或单独模块中实现 `GaodePoiClient`；
   * 所有外部 HTTP 调用使用 async client（如 httpx），设置超时时间与基础重试策略；
   * 记录调用次数与失败次数，供 Admin 统计。
5. **排序与过滤**
   * 默认按距离升序排序；
   * 过滤：
     * 若传入 type，仅返回匹配类型的 POI；
     * rating / 开放状态等高级过滤可预留字段但不强制实现。
6. **安全与限流**
   * 对 `/api/poi/around` 加简单用户级限流（可在中间件或 `PoiService` 内实现），避免被恶意打爆；
   * 输入校验失败返回 `code=1001` 之类的业务错误码，而非 500。

#### 4.2.5 测试要求

* 单元测试：
  * `PoiService` 在 cache hit / miss / DB hit / API 回源等路径的行为；
  * 第三方 API 抽象应可 mock。
* 集成测试：
  * 启动测试 Redis + 测试 PostgreSQL，调用 `/api/poi/around` 多次，验证缓存行为：
    * 首次 miss，后续 hit；
    * `admin/poi/summary` 中的计数同步更新（见 T6-4）。
* 异常场景：
  * 模拟外部 API 超时/失败，确认仍能返回 DB 中已有数据，或者优雅返回空列表 + 错误信息。

---

### 4.3 任务 T6-3：LangGraph `PoiNode` 工具接入

#### 4.3.1 功能目标

在现有 LangGraph 智能助手图中接入 `PoiNode`，使助手能够识别“附近兴趣点”类意图并调用 POI 服务，将结果用于回答，形成“意图 → 工具调用 → 回答”的闭环。

#### 4.3.2 目录结构建议

```text
backend/app/ai/graph/
  state.py           # AssistantState 扩展
  nodes.py           # 新增 poi_node 实现
  graph_builder.py   # 将 PoiNode 接入现有图
```

#### 4.3.3 实现要求

1. **AssistantState 扩展**
   * 按 3.3 小节增加 `location` / `poi_query` / `poi_results` 字段；
   * 修改必要的 Pydantic 校验，确保默认值与序列化行为合理。
2. **PoiNode 实现**
   伪代码示意：
   ```python
   async def poi_node(state: AssistantState, poi_service: PoiService) -> AssistantState:
       if not state.location:
           # 没有位置信息，直接返回，不中断主流程
           state.tool_traces.append({"node": "poi", "status": "skipped", "reason": "no_location"})
           return state

       query = state.poi_query or {}
       try:
           results, meta = await poi_service.get_around(
               lat=state.location["lat"],
               lng=state.location["lng"],
               type=query.get("type"),
               radius=query.get("radius"),
           )
       except PoiError as e:
           state.tool_traces.append({"node": "poi", "status": "error", "error": str(e)})
           return state

       state.poi_results = results
       state.tool_traces.append({"node": "poi", "status": "ok", "meta": meta})
       return state
   ```
3. **意图解析与路由**
   * 在 `assistant_node` 的 Prompt 与解析逻辑中增加 POI 相关说明：
     * 指导模型在用户提问“附近有什么好吃的”、“附近景点”等时输出对应 intent 与必要参数（type/radius 等）；
     * 把解析得到的坐标 / 类型填充进 `state.location` / `state.poi_query`，坐标来源：
       * REST `/api/ai/chat`：由前端在请求体中传入当前经纬度；
       * Admin Console：可以手动输入或使用默认值。
   * 在 `graph_builder` 中，增加 intent→PoiNode 的条件路由：
     * intent ∈ {`poi_nearby`, `poi_food`, `poi_sight`} 时，走 `poi_node`；
     * 其他 intent 保持原有分支。
4. **ResponseFormatter 扩展**
   * 当 `poi_results` 非空时，回答中应包含：
     * 至少若干 POI 的名称 / 简介 / 距离；
     * 适当提到“可以加入行程”或“可导航前往”等建议；
   * 同时保留 Stage-5 中对 `trip_data` / `memories` 的使用逻辑。
5. **错误与降级策略**
   * 若 `poi_results` 为空但 intent 为 POI 类：
     * 返回“当前附近没有找到合适的 X”，同时给出通用建议（如调整半径、尝试其他类型）；
   * 错误信息不向用户暴露第三方 API 细节，仅用于 `tool_traces` 与日志。

#### 4.3.4 测试要求

* 单元测试：
  * 对 `poi_node` 进行独立测试，覆盖无 location / 正常返回 / 服务异常等场景；
  * 对 intent 解析结果进行解析测试，确保 POI 意图能够正确填充到 state 中。
* 集成测试：
  * 通过 `/api/ai/chat` 发送包含经纬度和 POI 问题的请求（例如“附近有什么好吃的”），确认：
    * intent 分类正确；
    * `tool_traces` 中包含 `poi` 节点调用；
    * answer 中出现预期的 POI 名称信息；
  * 保证非 POI 问题仍按原路径处理。

---

### 4.4 任务 T6-4：Admin POI 监控与质量保障

#### 4.4.1 功能目标

在 Admin 界面中提供 POI 相关的监控与诊断能力，包含缓存行为、数据规模与第三方调用情况；同时维持整体代码质量与测试水位。

#### 4.4.2 Admin 接口与页面

1. **JSON 接口：`GET /admin/poi/summary`**
   示例响应：

   ```json
   {
     "code": 0,
     "msg": "ok",
     "data": {
       "pois_total": 10234,
       "pois_recent_7d": 342,
       "cache_hits": 1200,
       "cache_misses": 300,
       "api_calls": 150,
       "api_failures": 5
     }
   }
   ```

   * `pois_total` / `pois_recent_7d`：从 `pois` 表聚合；
   * `cache_hits` / `cache_misses` / `api_calls` / `api_failures`：
     * 从内存计数器或 Redis 统计中读取（与 Stage-1 / Stage-5 中统计方式一致）。
2. **HTML 页面：`/admin/poi/overview`**

   * 使用已有 Jinja2 模板体系，在 Admin 侧边栏增加“POI 监控”入口；
   * 页面内容：
     * 若干统计卡片（总数、近 7 日、命中率等）；
     * 简单折线或表格展示缓存命中情况（可先用表格，图表后续再补）；
     * 高德 API 调用/失败计数展示；
   * 鉴权：
     * 与其他 `/admin/*` 接口一致，需 Admin Token / IP 白名单。
3. **Dashboard 集成**

   * 在 `/admin/dashboard` 中增加一块“POI 概览”卡片，展示最关键的 2~3 个数字（如 POI 总数、缓存命中率、第三方请求数），点击可跳转到 `/admin/poi/overview`。

#### 4.4.3 质量与测试要求

* 质量工具：
  * 继续执行 `ruff` + `black` 全项目检查；
  * pytest 用例数在 Stage-5 基础上增加对 POI / PoiNode / Admin 的覆盖。
* 测试：
  * Admin JSON 接口鉴权测试：未带 Token 应返回 401 / 2xxx 错误码；
  * HTML 页面渲染测试：至少通过简单 HTTP 200 + 关键信息断言；
  * 统计数据在手工调用 `/api/poi/around` 前后发生合理变化。

---

## 5. 阶段 6 整体验收标准

当满足以下条件时，Stage-6 视为完成：

1. **POI 服务与缓存**
   * `/api/poi/around` 能在测试环境下正常返回附近 POI 列表，包含名称/地址/距离等字段；
   * 首次调用会触发 DB/外部 API 查询，后续同类请求命中 Redis 缓存，命中率统计在 Admin 中可见；
   * 对非法参数（经纬度越界、半径过大等）有明确错误响应，不出现 500 级异常。
2. **数据库与数据模型**
   * `pois` 表结构与索引与数据库设计文档一致；PostGIS 功能可正常用于附近检索；
   * ORM 映射正确，能通过 SQLAlchemy 完成插入 / 查询 / 距离排序。
3. **LangGraph 工具层集成**
   * `PoiNode` 已接入现有助手图谱；
   * 在 `/api/ai/chat` 中，当用户提问“附近有什么 XX”且提供经纬度时：
     * intent 分类为 POI 类；
     * `tool_traces` 中出现 `poi` 节点调用记录；
     * 回答中包含来自 POI 服务的真实数据。
   * 非 POI 问题仍按原有流程处理，不受影响。
4. **Admin 监控**
   * `/admin/poi/summary` 返回正确的 POI 规模、缓存行为与第三方 API 调用统计；
   * `/admin/poi/overview` 页面可正常访问，展示数据无明显异常；
   * `/admin/dashboard` 中有 POI 概览卡片，与 summary 数据一致。
5. **质量与文档**
   * 全项目通过 `ruff` + `black` + `pytest`，新增测试覆盖 POI / PoiNode / Admin；
   * `_docs/Phase6/Spec.md`、`Code.md`、`Tests.md`、`Review.md` 已补齐本阶段的设计与实现细节，可直接支撑论文中“POI 服务与智能体工具层”相关章节的撰写。
