
## 1. 概述

### 1.1 阶段编号与名称

* 阶段编号：**Stage-3**
* 阶段名称：**行程 CRUD & Admin 可视化增强（业务基础版）**

### 1.2 背景

在前两阶段中，项目已完成：

* Stage-1：建立了后端管理界面 `/admin/dashboard` 的基础框架，实现了 API 调用统计与在线 API 测试工具雏形，以及基础健康检查（DB/Redis 仍多为占位数据）。
* Stage-2：按照数据库与后端设计文档，在 PostgreSQL 中创建了 `users / trips / day_cards / sub_trips / pois / favorites` 等核心业务表；通过 Alembic 迁移与 SQLAlchemy ORM 完成实体建模；在 Admin 中新增了 `/admin/db/health`、`/admin/db/stats`、数据库相关 Data Check，并将 Dashboard 上 DB 卡片替换为真实数据。

根据整体阶段开发计划，Stage-3 的目标是：在已有数据基础设施上，实现完整的  **行程 CRUD API（无智能，纯业务）** ，并将这些 API 与数据库信息更系统地挂载到 Admin 可视化后台中，构建一个“可视化 + 可测试”的后端监控与调试中心。

本阶段完成后，应达到：

1. 行程相关业务（Trip / DayCard / SubTrip）的接口能够稳定支撑“行程卡片 + 子行程 + 跨天调整”的基础操作；
2. Admin 中新增行程统计信息（数量、最近修改等），并将所有公开 API 接口、核心数据库表信息以可视化方式统一展现；
3. Admin 中提供类似 FastAPI Docs 的接口自动化文档与测试能力：可以在浏览器中选择任意 API，查看请求/响应结构，并直接发起测试请求，查看响应与耗时；
4. 为后续“智能行程规划”“POI 服务”“智能助手”等功能提供清晰的业务 API 基线。

---

## 2. 范围说明

### 2.1 本阶段实现范围

1. **行程 CRUD REST API（无智能）**
   * `GET /api/trips`：行程列表（可按用户过滤）。
   * `GET /api/trips/{trip_id}`：行程详情（包含 DayCard / SubTrip 嵌套结构）。
   * `POST /api/trips`：创建行程（可同时创建 DayCard / SubTrip）。
   * `PUT /api/trips/{trip_id}`：更新行程基础信息（标题、目的地、日期等）。
   * `DELETE /api/trips/{trip_id}`：删除行程及其所有关联 DayCard / SubTrip。
   * 补充子路由或接口处理：
     * DayCard 的新增/编辑/删除；
     * SubTrip 的新增/编辑/删除；
     * 同一天内子行程换序；
     * 子行程跨天移动。
2. **Admin 行程统计与可视化**
   * 新增 `GET /admin/trips/summary` 等接口；
   * 在 `/admin/dashboard` 中增加“行程概览”区域：展示行程总数、最近修改行程、平均每日子行程序等。
3. **Admin API 注册表 & 自动化文档 + 在线测试工具（增强版）**
   * 后端提供 API 元信息接口（如 `/admin/api/routes` / `/admin/api/schema` / `/admin/api/test`），基于 FastAPI 路由与 Pydantic 模型自动生成；
   * Admin UI 中新增“API 文档与测试”页面：
     * 类似 FastAPI 自带 Docs 的接口分组、展开、查看请求/响应 Schema；
     * “一键尝试（Try it out）”：填写参数、发送请求，查看返回 JSON、状态码与耗时。
4. **Admin 数据库信息可视化增强**
   * 在现有 `/admin/db/health`、`/admin/db/stats` 基础上，新增：
     * 核心业务表的结构描述（字段、类型、主键/外键、索引等）接口；
     * Admin UI 中的“数据库结构”视图。

### 2.2 非本阶段范围（但需兼容）

* 不在本阶段实现任何“智能生成行程”“LLM 深度模式规划”等功能（属于后续 AI 规划阶段）。
* 不在本阶段实现 POI 附近搜索、地图服务接口（属于 Stage-4）；需保证行程 API 与数据库结构兼容这些后续功能。
* 不在本阶段实现 Android 前端功能（行程列表、行程编辑页面将在后续阶段集成）。
* 不在本阶段修改现有 LLM 接入与 LangGraph 结构，仅为后续 AI 调用预留 API 形态（例如行程详情结构一致）。

---

## 3. 总体技术与通用约定

### 3.1 技术栈与基础设施

* 后端框架： **FastAPI（ASGI）** ；
* 数据库： **PostgreSQL + PostGIS** ，核心表结构已在 Stage-2 落地；
* ORM： **SQLAlchemy** （与 Stage-2 一致）；
* Schema：**Pydantic** 模型 `TripSchema / DayCardSchema / SubTripSchema` 等，在本阶段按需补充字段与校验；
* Admin 模块：继续使用 Jinja2 模板 + `AdminService` 作为服务层统一入口。

### 3.2 API 设计与约定

* 所有业务 API 继续采用统一响应格式：
  ```json
  {
    "code": 0,
    "msg": "ok",
    "data": {...}
  }
  ```
* 错误码：
  * 1xxx：业务错误（如行程不存在、参数非法）；
  * 2xxx：权限/鉴权错误（本阶段可先简单处理或预留）；
  * 3xxx：外部依赖错误（本阶段主要是 DB 相关）。
* 路径命名：
  * 行程列表/详情：`/api/trips`；
  * 若有子资源，可采用 `/api/trips/{trip_id}/day_cards` / `/api/trips/{trip_id}/sub_trips` 等形式。
* 接口文档：
  * 以本阶段新增的 Admin “API 文档”页面为主；
  * FastAPI 原生 OpenAPI / Docs 仍保留于开发环境，但不对最终用户暴露。

### 3.3 领域模型与一致性约定

* 表结构继续沿用数据库设计文档的约定：`trips / day_cards / sub_trips` 多级关系；`UNIQUE(trip_id, day_index)`、`UNIQUE(day_card_id, order_index)` 等约束必须在业务操作中显式维护。
* Pydantic Schema 中的嵌套结构与后端设计文档保持一致，支持一次性返回“行程 + 每日卡片 + 子行程”的 DTO。
* 所有涉及排序与跨天移动的操作必须在单事务中完成，遵循数据库设计文档中的重排示例，避免空洞与顺序冲突。

### 3.4 Admin 模块与目录结构

在 Stage-1/2 的基础上继续扩展：

```text
backend/app/
  admin/
    routes.py              # 扩展行程、API 文档、DB 结构相关路由
    service.py             # 新增 TripSummaryService / ApiDocService / DbMetaService 等方法
    templates/
      dashboard.html       # 增强：行程概览、API & DB 卡片
      api_docs.html        # 新增：API 文档 + 在线测试 UI
      db_schema.html       # 可选：数据库结构查看页面
  core/
    db.py                  # 继续复用 Stage-2 Session 管理
  models/
    orm.py                 # Trip / DayCard / SubTrip 等 ORM 已存在，按需小幅扩展
    schemas.py             # TripSchema / DayCardSchema / SubTripSchema 补充字段/校验
  api/
    trips.py               # 新增：行程相关路由
    ...
```

---

## 4. 详细功能与实现要求

本阶段拆分为 6 个主要任务：

* **T3-1：行程领域 Schema & DTO 完整化**
* **T3-2：行程 CRUD API 实现**
* **T3-3：子行程排序与跨天移动**
* **T3-4：Admin 行程统计与可视化**
* **T3-5：Admin API 注册表 & 自动化文档 + 在线测试**
* **T3-6：Admin 数据库结构可视化增强**

---

### 4.1 任务 T3-1：行程领域 Schema & DTO 完整化

#### 4.1.1 功能概述

在 Stage-2 基础上，完善与行程相关的 Pydantic Schema，使其能够完整表达：

* 行程基本信息（目的地、起止日期、状态等）；
* 每日行程卡片（DayCard）的索引与日期；
* 子行程（SubTrip）的顺序、活动、地点、交通方式、备注等。

这些 Schema 将在：

* 行程 CRUD 接口中作为请求/响应模型；
* Admin API 文档自动化生成中被解析并展示。

#### 4.1.2 具体要求

* 在 `models/schemas.py` 中定义或完善：
  * `SubTripSchema`
    * 字段示例：`id`（可选）、`day_card_id`（可选）、`order_index`、`activity`、`poi_id`（可选）、`loc_name`、`note`（可选）、`transport`（walk/bike/drive/transit）、`start_time`、`end_time`、`lat`、`lng` 等；
  * `DayCardSchema`
    * 字段示例：`id`（可选）、`trip_id`（可选）、`day_index`、`date`、`note`、`sub_trips: List[SubTripSchema]`；
  * `TripSchema`
    * 字段示例：`id`（可选）、`user_id`、`title`、`destination`、`start_date`、`end_date`、`status`、`day_cards: List[DayCardSchema]`。
* 校验规则：
  * `day_index`、`order_index` 为非负整数；
  * `start_date <= end_date`；
  * `start_time < end_time`（可选）；
  * `transport` 仅允许 Enum 中的值。
* 提供用于列表/摘要场景的轻量 Schema（例如 `TripSummarySchema`），避免在 `/api/trips` 列表中一次性返回所有子行程。

---

### 4.2 任务 T3-2：行程 CRUD API 实现

#### 4.2.1 功能概述

为 Trip / DayCard / SubTrip 提供基础 CRUD 接口，使后端成为一个“行程记事本”，支持后续 AI 与前端联调。

#### 4.2.2 路由与行为

**建议路由设计：**

* `GET /api/trips`
  * 查询参数：`user_id`（必填或通过鉴权推导）、`destination`（可选）、分页参数等；
  * 返回：`List[TripSummarySchema]`。
* `GET /api/trips/{trip_id}`
  * 返回：完整 `TripSchema`（含 day_cards + sub_trips）。
* `POST /api/trips`
  * 请求体：`TripSchema`（可允许不带 id / 子行程）；
  * 行为：
    * 创建 `trips` 记录；
    * 可选：同时创建 `day_cards` / `sub_trips`；
    * 返回 `{"trip_id": ...}`。
* `PUT /api/trips/{trip_id}`
  * 请求体：允许部分字段更新（title/destination/date/status 等）；
  * 不建议在此接口中直接更新嵌套的 DayCard/SubTrip（交由专门接口处理）。
* `DELETE /api/trips/{trip_id}`
  * 逻辑：删除行程及其关联的 DayCard/SubTrip；依赖 DB 级联 `ON DELETE CASCADE`。

**DayCard/SubTrip 建议接口（可选）：**

* `POST /api/trips/{trip_id}/day_cards`
* `PUT /api/day_cards/{day_card_id}`
* `DELETE /api/day_cards/{day_card_id}`
* `POST /api/day_cards/{day_card_id}/sub_trips`
* `PUT /api/sub_trips/{sub_trip_id}`
* `DELETE /api/sub_trips/{sub_trip_id}`

实际可以根据实现复杂度选择少量“批量更新”接口（例如一次性更新某天所有子行程）。

#### 4.2.3 实现要求

* 在 `TripService` 中集中处理业务逻辑，路由层只做参数解析与响应封装；
* 所有数据库操作使用 Stage-2 定义的 Session 管理工具（`session_scope` 等）；
* 对违法状态（如删除不存在行程）返回业务错误码与明确错误信息，而非 500；
* 为 `/api/trips*` 接口编写单元测试与基础集成测试，验证：
  * 创建行程后，数据库中表关系正确；
  * 删除行程后，DayCard/SubTrip 被正确级联删除；
  * 多次调用不会违反唯一约束或导致异常。

---

### 4.3 任务 T3-3：子行程排序与跨天移动

#### 4.3.1 功能概述

支持用户在同一天内拖拽调整子行程序顺序，以及将子行程从一天移动到另一天下，同时保持 `UNIQUE(day_card_id, order_index)` 约束不被破坏。

#### 4.3.2 功能与接口建议

* `POST /api/sub_trips/{sub_trip_id}/reorder`
  * 请求体：`{"day_card_id": <目标 day_card_id>, "order_index": <目标顺序>}`；
  * 若目标 `day_card_id` 与当前相同，则为同日换序；
  * 若不同，则表示跨天移动。

#### 4.3.3 实现要求

* 按数据库设计文档中“排序与换天事务示例”实现：
  * 使用单事务；
  * 对涉及的 `sub_trips` 行使用行级锁或 advisory lock，避免并发冲突；
  * 重新计算同一 `day_card_id` 下所有 `order_index`，确保无空洞且从 0/1 开始连续。
* 在 Service 层实现独立的重排函数，便于测试：
  * 输入：原列表、目标元素及目标位置；
  * 输出：新的 `order_index` 映射；
  * 通过单次批量 `UPDATE` 完成。
* 提供测试用例覆盖：
  * 同一日内拖拽到列表前/后；
  * 跨日移动后，源日/目标日的顺序均无冲突；
  * 并发场景（可用伪并发测试或注释说明，至少确认事务逻辑正确）。

---

### 4.4 任务 T3-4：Admin 行程统计与可视化

#### 4.4.1 功能概述

在 Admin 中新增行程统计接口与 UI，使开发者/调试者可以一眼看到当前数据规模与近期活跃。

#### 4.4.2 接口设计

* `GET /admin/trips/summary`
  * 返回示例：
    ```json
    {
      "code": 0,
      "msg": "ok",
      "data": {
        "total_trips": 12,
        "total_day_cards": 30,
        "total_sub_trips": 120,
        "recent_trips": [
          {
            "trip_id": 1,
            "title": "广州周末游",
            "updated_at": "2025-11-16T12:34:56Z",
            "day_count": 2,
            "sub_trip_count": 10
          }
        ],
        "avg_sub_trips_per_day": 4.0
      }
    }
    ```
* 查询逻辑：
  * 使用简单 `COUNT(*)` 或视图统计；
  * `recent_trips` 可按 `updated_at DESC LIMIT 10` 查询。

#### 4.4.3 UI 要求

* 在 `/admin/dashboard` 中增加“行程概览”卡片区域：
  * 显示行程总数、DayCard 总数、SubTrip 总数；
  * 简要列出最近修改的若干行程（标题 + 更新时间）；
* 与已有 DB 状态卡片（Stage-2）风格保持一致。

---

### 4.5 任务 T3-5：Admin API 注册表 & 自动化文档 + 在线测试

#### 4.5.1 功能概述

在 Stage-1 的“在线 API 测试工具雏形”基础上，建设一个更系统的 Admin API 中心，具备：

* 自动从 FastAPI 应用中收集所有路由信息（方法、路径、标签、摘要、请求/响应模型）；
* 在 Admin 页面中按模块展示接口列表，类似 FastAPI Docs；
* 为每个接口提供“在线测试”能力：填写参数与请求体，直接在浏览器中调用后端并查看结果与耗时。

#### 4.5.2 接口设计

**1）API 元信息**

* `GET /admin/api/routes`
  * 功能：返回所有需要展示的 API 列表（过滤掉 `/admin/*` 自身或内部接口）；
  * 内容示例：
    ```json
    {
      "code": 0,
      "msg": "ok",
      "data": {
        "routes": [
          {
            "path": "/api/trips",
            "methods": ["GET", "POST"],
            "summary": "行程列表 / 创建行程",
            "tags": ["trips"],
            "has_request_body": true,
            "request_model": "TripSchema",
            "response_model": "TripSummarySchema[]"
          }
        ]
      }
    }
    ```
  * 实现建议：
    * 遍历 FastAPI `app.routes`，读取 `path` / `methods` / `endpoint.__doc__` / `tags` / `response_model` 等元数据；
    * 对复杂模型仅返回模型名，由前端或另一个接口拉取详细 Schema。
* `GET /admin/api/schemas`
  * 可选：返回所有 Pydantic 模型的字段定义，用于前端展示参数结构。

**2）API 在线测试**

* `POST /admin/api/test`
  * 请求体示例：
    ```json
    {
      "method": "POST",
      "path": "/api/trips",
      "path_params": {},
      "query_params": {},
      "headers": {},
      "json_body": {
        "user_id": 1,
        "destination": "广州",
        "start_date": "2025-12-01",
        "end_date": "2025-12-03",
        "day_cards": []
      }
    }
    ```
  * 返回示例：
    ```json
    {
      "code": 0,
      "msg": "ok",
      "data": {
        "status_code": 200,
        "latency_ms": 12.5,
        "response_headers": {
          "content-type": "application/json"
        },
        "response_body": {
          "code": 0,
          "msg": "ok",
          "data": {
            "trip_id": 123
          }
        }
      }
    }
    ```
  * 实现建议：
    * 使用内部 HTTP 客户端（如 `httpx.AsyncClient` 指向同一应用）或 FastAPI TestClient；
    * 强制限制为仅调用 `/api/*` 路径，避免递归调用 `/admin/*`；
    * 在 Admin 环境下不做鉴权或使用内置 Admin Token 防止非开发环境滥用。

#### 4.5.3 Admin UI 要求

* 新增页面：`/admin/api-docs`
  * 左侧：按 Tag 分组的路由树；
  * 右侧：选中路由的详细信息（方法、路径、描述、请求参数/体结构、返回结构）；
  * 点击“测试”按钮展开测试表单：
    * 自动生成 query/path/body 的 JSON 编辑框；
    * 提交后显示响应状态码、耗时、响应 JSON。
* 与 FastAPI 自带 Docs 保持类似使用体验，但局限于内部调试场景，不面向普通用户。

---

### 4.6 任务 T3-6：Admin 数据库结构可视化增强

#### 4.6.1 功能概述

在 Stage-2 已有 DB 健康与行数统计的基础上，进一步提供数据库结构信息的可视化，使开发者可在 Admin 中快速了解当前核心表结构。

#### 4.6.2 接口设计

* `GET /admin/db/schema`
  * 返回示例：
    ```json
    {
      "code": 0,
      "msg": "ok",
      "data": {
        "tables": {
          "trips": {
            "columns": [
              {"name": "id", "type": "bigint", "nullable": false, "default": "nextval(...)"},
              {"name": "user_id", "type": "bigint", "nullable": false, "fk": "users.id"},
              {"name": "destination", "type": "text", "nullable": false}
            ],
            "primary_key": ["id"],
            "indexes": [
              {"name": "idx_trips_user", "columns": ["user_id"], "unique": false}
            ]
          },
          "day_cards": { ... },
          "sub_trips": { ... }
        }
      }
    }
    ```
  * 实现建议：
    * 基于 `information_schema.columns` 与 `pg_catalog.pg_constraint/pg_index` 查询；
    * 只需覆盖核心业务表和部分辅助表（如 `ai_tasks`、`chat_sessions` 等可后续补充）。

#### 4.6.3 UI 要求

* 在 `/admin/dashboard` 中，DB 卡片支持一个“查看结构”链接，跳转到 `/admin/db/schema` 的视觉页面（如 `db_schema.html`）；
* 页面基本能力：
  * 左侧列出所有核心表名；
  * 右侧展示选中表的字段列表（字段名、类型、是否必填、默认值）、主键、外键、索引；
  * 对于带有地理类型（如 `geom geography(Point,4326)`）的字段，明确标注为地理字段。

---

## 5. 阶段 3 整体验收标准

Stage-3 视为完成时，应满足以下条件：

### 5.1 行程业务功能

1. 可以通过 `POST /api/trips` 创建行程，并通过 `GET /api/trips/{trip_id}` 正确读取，包含 DayCard / SubTrip 嵌套结构；
2. 可以通过接口增删改 DayCard / SubTrip；
3. 可以通过排序接口完成同日内子行程换序与跨天移动，数据库中 `UNIQUE(day_card_id, order_index)` 不被破坏，顺序连续；
4. 删除行程后，相关 DayCard / SubTrip 在数据库中不再存在。

### 5.2 Admin 行程统计

1. `GET /admin/trips/summary` 返回行程数、DayCard 数、SubTrip 数，以及最近修改行程列表；
2. `/admin/dashboard` 中能看到行程概览卡片，且数据在进行 CRUD 操作后会实时变化。

### 5.3 Admin API 文档与在线测试

1. `GET /admin/api/routes` 能列出所有 `/api/*` 业务接口信息；
2. `/admin/api-docs` 页面可按路径/Tag 浏览接口详情；
3. 对任一 `/api/trips*` 接口，在 UI 中填写参数后，点击“测试”可以获得真实响应与耗时；
4. 在线测试仅对开发/测试环境开放（至少在文档中有明确说明与配置开关）。

### 5.4 Admin 数据库可视化

1. `GET /admin/db/schema` 能返回核心表的字段、主键、外键和索引信息；
2. `/admin/db/schema` 页面可以选择并查看 `trips / day_cards / sub_trips` 等表的结构；
3. `/admin/db/health`、`/admin/db/stats` 保持 Stage-2 行为不变，且与新结构视图相互补充。

### 5.5 测试与 CI

1. 新增的行程 CRUD、排序与 Admin 接口均有对应测试用例（单元 + 基本集成），所有测试在本地和 CI 中通过；
2. 迁移脚本、数据库结构未破坏 Stage-2 的既有能力（尤其是 Admin DB 健康检查与表统计接口）；
3. 与 Stage-2 相比，整体测试覆盖率不下降。
