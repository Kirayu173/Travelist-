---
# 阶段 1 规格说明书（Spec-1）


## 1. 概述


### 1.1 阶段编号与名称


* 阶段编号：**Stage-1**
* 阶段名称：**后端管理界面基础版（监控与诊断中心 v1）**


### 1.2 背景


在 Stage-0 中，后端工程已完成基础骨架搭建，包括：


* FastAPI 应用工厂、基础路由与 `/healthz`；
* `/admin/ping`、`/admin/api/summary`、`/admin/health` 等 JSON 级别的监控接口；
* 请求统计中间件与 CI / 容器化基础。


但当前监控能力仅停留在“接口存在 + 返回 JSON”，缺乏：


* 面向开发者的 **可视化后台界面** ；
* 一键执行的 **API 在线测试能力** （用于快速验证后端接口）；
* 对数据库和 Redis 的 **真实连通性与状态检查** ；
* 为后续“数据质量检查（Data Check）”预留的统一框架。


本阶段的任务是把这些能力补齐，形成一个可在开发与联调阶段高频使用的“后端管理中控台”。


### 1.3 阶段目标


本阶段完成后，应达到：


1. 提供一个 `/admin/dashboard` Web 页面，可视化展示基础运行信息与监控数据；
1. 提供在线  **API 测试工具** （通过 Admin 页面调用后端 API，并可查看请求/响应）；
1. 对数据库与 Redis 做真实的 **连通性检测** ，并以统一 JSON/页面形式展示；
1. 提供基础的“数据检查（Data Check）”框架，哪怕当前只有少量检查项，也要保证接口与结构稳定，为后续阶段（建表后做更复杂检查）预留扩展点；
1. 保持与 Stage-0 一致的技术栈与代码规范，并补充单元测试与集成测试，保证新增模块的可测试性。
---
## 2. 范围说明

### 2.1 本阶段实现范围

1. **Admin 页面与模板框架**
   * 实现 `/admin/dashboard` 页面，使用 Jinja2（或等价模板引擎）+ 简单 CSS；
   * 页面展示内容包括：
     * 应用基本信息（版本、环境、启动时间等）；
     * API 调用统计概览；
     * 数据库 / Redis 连接状态；
     * API 测试工具入口；
     * 数据检查（Data Check）结果列表。
2. **API 调用统计与展示增强**
   * 在 Stage-0 的请求统计中间件基础上：
     * 增加统计时间窗口（最近 5 分钟 / 15 分钟）与总计；
     * 提供更结构化的统计接口，便于 Admin 页面渲染。
3. **API 在线测试能力**
   * 新增 `POST /admin/api/test` 等接口，用于在后端发起对自身 API 的测试调用；
   * 在 `/admin/dashboard` 上提供简单表单：
     * 请求方法（GET/POST…）、URL 路径、可选请求体；
     * 展示测试结果（状态码、耗时、响应体摘录）；
   * 支持一组预设“烟雾测试用例”（例如：`/healthz`、`/admin/ping`）。
4. **数据库与 Redis 状态检测**
   * 提供统一的后台探测逻辑：
     * DB：使用 SQLAlchemy Engine 尝试 `SELECT 1`；
     * Redis：使用 `PING`；
   * 新增或增强 `/admin/health`，使 `data.db` / `data.redis` 不再是纯占位，而是包含真实状态与额外信息（如延迟、错误原因）；
   * 提供专门的 `/admin/db/status`、`/admin/redis/status` JSON 接口。
5. **数据检查（Data Check）框架**
   * 定义统一检查项模型（例如：`name`、`status`、`level`、`detail`、`suggestion`）；
   * 新增 `/admin/checks` 接口返回所有检查项结果；
   * 当前阶段可实现以下最小检查：
     * 是否能连接数据库；
     * 是否能连接 Redis；
     * Alembic 是否已配置（检查 `env.py` 与迁移目录存在情况，或 `alembic_version` 表是否存在 —— 若无法确定，可显式标记为 “unknown” 状态）；
   * 在 `/admin/dashboard` 中展示这些检查项，为后续 Stage-2 建表后增加“表行数异常、孤儿记录”等检查留出结构。

### 2.2 不在本阶段范围

* 不实现任何业务功能相关页面（例如行程列表、POI 列表等）；
* 不实现复杂的数据质量检查（如跨表一致性检查 —— 留到有业务表之后的阶段）；
* 不做权限控制 / 登录系统（Admin 界面暂时默认仅限开发环境使用）；
* 不接入外部 APM/监控系统（如 Prometheus）—— 仅通过当前项目内部 API + 页面展示。

---

## 3. 总体技术与通用约定

### 3.1 技术栈约定

在 Stage-0 的基础上，本阶段引入/明确：

* 后端框架：**FastAPI**
* 模板引擎： **Jinja2** （通过 `fastapi.templating.Jinja2Templates` 或 Starlette 等价实现）
* HTTP 客户端（用于 API 测试）：推荐  **httpx** （异步版）
* 数据库访问：沿用 Stage-0 约定的 SQLAlchemy Engine（即便尚未建业务表，也要保证能连上 DB）
* Redis 客户端：`redis` / `redis.asyncio`（选一种并统一）

所有新增 JSON 接口继续遵守 Stage-0 的返回格式：

```json
{
  "code": 0,
  "msg": "ok",
  "data": { ... }
}
```

错误场景可使用：

```json
{
  "code": 10001,
  "msg": "error message",
  "data": null
}
```

### 3.2 目录结构约定

在 Stage-0 的基础上，本阶段新增/细化以下模块（路径示例）：

```text
backend/
  app/
    admin/
      __init__.py
      service.py         # AdminService：聚合各种统计、健康检查、数据检查
      templates/
        dashboard.html   # /admin/dashboard 页面模板
    api/
      admin.py           # Admin 路由（扩展）
    core/
      app.py             # create_app，已在 Stage-0 实现
      db.py              # DB Engine / Session 工具（如 Stage-0 未建立，此阶段需补齐）
      redis.py           # Redis 客户端封装
    utils/
      metrics.py         # 请求统计中间件 & 统计数据结构（Stage-0 中已有，可在此阶段拆分整理）
      http_client.py     # httpx 客户端封装（用于 API 测试）
```

目录名允许小幅调整，但需满足：

* Admin 相关业务（统计、健康检查、数据检查）由专门 `admin.service` 或等价模块管理；
* 模板文件集中在 `admin/templates/`（或统一 `templates/` 目录，但需有清晰命名空间）；
* 测试文件放在 `tests/admin/` 下。

### 3.3 代码规范与测试要求

* 继续遵守 Stage-0 中约定的代码规范（`black`、`ruff` 等）；
* 本阶段新增模块需要有相应测试：
  * Admin API 的基本单元测试 / 集成测试；
  * 数据检查逻辑的单元测试（在测试环境可使用 fake DB/Redis 或 mock）。

---

## 4. 详细功能与实现要求

本阶段拆分为 4 个主要任务：

* T1-1：Admin 页面与基础信息展示
* T1-2：API 调用统计与在线 API 测试
* T1-3：数据库 / Redis 状态检测
* T1-4：数据检查（Data Check）框架

### 4.1 任务 T1-1：Admin 页面与基础信息展示

#### 4.1.1 功能概述

实现 `/admin/dashboard` 页面，用于集中展示：

* 应用基本信息：名称、版本、运行环境、启动时间；
* 当前时间（便于确认时区与页面刷新情况）；
* API 调用总量概览；
* 数据库 / Redis 状态摘要（更详细信息通过其他接口获取）；
* API 测试工具入口与数据检查区域。

#### 4.1.2 路由与接口要求

 **需求 T1-1-R1** ：新增 `GET /admin/dashboard` 路由：

* 返回 HTML 页面（`text/html`），使用 Jinja2 模板渲染；
* 模板参数最少包含：
  * `app_name`：应用名；
  * `version`：版本号（与 `/admin/ping` 一致）；
  * `env`：当前运行环境（如 `development` / `production`）；
  * `start_time`：应用启动时间；
  * `now`：当前时间；
  * `api_summary`：由 `AdminService` 提供的 API 统计摘要；
  * `health`：由 `AdminService` 提供的健康状态（`app/db/redis` 三类）。

 **需求 T1-1-R2** ：页面布局要求（简化说明）：

* 顶部：应用名 + 版本号 + 环境；
* 中部：
  * 左侧：API 调用概览（总请求数 / 不同路由数量等）；
  * 右侧：DB/Redis 状态（`ok` / `fail` / `unknown`）；
* 下方：
  * 一块区域预留给“API 测试工具”；
  * 一块区域预留给“数据检查结果列表”。

UI 不要求华丽，但需结构清晰，便于后续扩展样式。

#### 4.1.3 AdminService 基础方法

 **需求 T1-1-R3** ：实现 `AdminService` 基础接口（示例）：

```python
class AdminService:
    def __init__(self, settings, metrics_registry, db, redis_client):
        ...

    async def get_basic_info(self) -> dict: ...
    async def get_health_summary(self) -> dict: ...
    async def get_api_summary(self, window_seconds: int | None = None) -> dict: ...
```

* `get_basic_info()` 返回应用名、版本、环境、启动时间；
* `get_health_summary()` 聚合 `app/db/redis` 状态（内部调用 T1-3 对应逻辑）；
* `get_api_summary()` 聚合 Stage-0 的请求统计数据（详见 T1-2）。

Admin 路由与模板渲染应通过 `AdminService` 获取数据，避免业务逻辑散落在路由函数中。

---

### 4.2 任务 T1-2：API 调用统计与在线 API 测试

#### 4.2.1 请求统计增强

在 Stage-0 中，已有一个简单的中间件记录每个路由的：

* 调用次数 `count`；
* 最近一次耗时 `last_ms`。

本阶段需要对其进行结构化封装与扩展。

 **需求 T1-2-R1** ：将请求统计逻辑抽象为 `MetricsRegistry`（示例）：

```python
class MetricsRegistry:
    def record(self, method: str, path: str, duration_ms: float) -> None: ...
    def snapshot(self) -> dict: ...
    def snapshot_window(self, window_seconds: int) -> dict: ...
```

* `record` 在中间件中调用；
* `snapshot` 返回当前所有路由的累计统计（总 count / 平均耗时等）；
* `snapshot_window` 可选：在简单实现中允许返回与 `snapshot` 相同结果；如有时间精细要求，可实现时间窗口内统计（通过环形缓冲或时间戳队列）。

中间件应仅负责调用 `registry.record`，不直接拼装 JSON。

 **需求 T1-2-R2** ：扩展 `/admin/api/summary` 接口：

* 支持查询参数 `window`（单位秒，可选）：
  * 缺省时返回全量统计；
  * 指定时调用 `snapshot_window(window)`；
* 响应 `data` 内部结构建议：

```json
{
  "total_requests": 123,
  "routes": [
    {
      "method": "GET",
      "path": "/healthz",
      "count": 50,
      "avg_ms": 10.5,
      "p95_ms": 30.0
    },
    ...
  ]
}
```

在实现上，可以先只提供 `avg_ms`，`p95_ms` 可暂用简化算法或先留空字段。

#### 4.2.2 在线 API 测试接口

 **需求 T1-2-R3** ：新增 `POST /admin/api/test`：

* 请求体 Pydantic 模型示例：

```python
class ApiTestRequest(BaseModel):
    method: Literal["GET", "POST", "PUT", "DELETE"]
    path: str              # 仅支持相对路径，例如 "/healthz"
    query: dict[str, Any] | None = None
    headers: dict[str, str] | None = None
    json_body: dict[str, Any] | None = None
    timeout_ms: int = 5000
```

* 行为：
  * 使用 httpx 在后端直接调用自身 API，例如：`http://127.0.0.1:{port}{path}`；
  * 记录请求开始与结束时间，计算耗时；
  * 返回结果中包含：
    * `status_code`
    * `duration_ms`
    * `ok`（布尔值）
    * `response_headers`（可裁剪）
    * `response_body_excerpt`（字符串，截断到约 2KB）
* 响应示例：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "status_code": 200,
    "duration_ms": 12.3,
    "ok": true,
    "response_body_excerpt": "{\"code\":0,\"msg\":\"ok\",\"data\":{...}}"
  }
}
```

 **需求 T1-2-R4** ：为常用接口提供一组预置 API 测试用例：

* 例如在 AdminService 中维护：

```python
PREDEFINED_TESTS = [
    {"name": "healthz", "method": "GET", "path": "/healthz"},
    {"name": "admin_ping", "method": "GET", "path": "/admin/ping"},
    {"name": "admin_api_summary", "method": "GET", "path": "/admin/api/summary"},
]
```

* 新增 `GET /admin/api/testcases`，返回可用测试用例列表；
* `/admin/dashboard` 页面中列出这些用例，并提供“一键运行”按钮；
* 一键运行时前端可通过 JS 调 `POST /admin/api/test`，并将结果展示在页面上。

---

### 4.3 任务 T1-3：数据库 / Redis 状态检测

#### 4.3.1 DB / Redis 工具封装

 **需求 T1-3-R1** ：实现 `core/db.py` 中的数据库工具：

* 保证存在可复用的 `get_engine()` / `get_session()` 函数或等价实现；
* 数据库连接信息来自 `Settings.database_url`；
* 提供一个简单的异步/同步探测函数：

```python
async def check_db_health() -> dict:
    # 示例返回结构
    return {
        "status": "ok" | "fail",
        "latency_ms": 1.23,
        "error": None | "error message"
    }
```

 **需求 T1-3-R2** ：实现 `core/redis.py` 中的 Redis 客户端封装：

* 按 `Settings.redis_url` 建立 Redis 连接；
* 提供 `async def check_redis_health() -> dict`，返回结构类似 DB 健康检查。

#### 4.3.2 健康接口增强

 **需求 T1-3-R3** ：增强 `/admin/health` 接口：

* 通过 `AdminService.get_health_summary()` 汇总：
  * `app`: 始终为 `"ok"`，表示进程本身可服务；
  * `db`: 来自 `check_db_health()`；
  * `redis`: 来自 `check_redis_health()`；
* 响应 `data` 示例：

```json
{
  "app": "ok",
  "db": {
    "status": "ok",
    "latency_ms": 2.1
  },
  "redis": {
    "status": "fail",
    "error": "Connection refused"
  }
}
```

 **需求 T1-3-R4** ：新增 `GET /admin/db/status` 与 `GET /admin/redis/status`：

* 分别返回更详细的状态信息：
  * DB：数据库名称、驱动类型、服务器版本（如果能方便获取）；
  * Redis：Redis 版本、使用内存、角色（master/slave），在复杂实现中可以通过 `INFO` 命令获取；当前阶段可以先只返回 `status`、`latency_ms` 和 `error`。

---

### 4.4 任务 T1-4：数据检查（Data Check）框架

#### 4.4.1 检查项模型

 **需求 T1-4-R1** ：定义统一的数据检查项模型，例如：

```python
class DataCheckResult(BaseModel):
    name: str          # 检查项名称，如 "db_connectivity"
    level: Literal["info", "warn", "error"]
    status: Literal["pass", "fail", "unknown"]
    detail: str        # 具体说明
    suggestion: str | None = None  # 修复建议
```

#### 4.4.2 最小检查项集合

 **需求 T1-4-R2** ：本阶段至少实现以下检查：

1. `db_connectivity`
   * 尝试调用 `check_db_health()`；
   * 成功则 `status="pass"`，失败则 `status="fail"`；
2. `redis_connectivity`
   * 类似 DB；
3. `alembic_initialized`
   * 行为可简化为：
     * 检查 Alembic 迁移目录是否存在；
     * 或检查数据库中是否存在 `alembic_version` 表；
   * 若无法确认，则 `status="unknown"`，`detail` 写明原因。

这些检查的实现逻辑放在 `AdminService` 或单独模块 `admin/checks.py` 中，由 AdminService 统一协调。

#### 4.4.3 数据检查接口与页面展示

 **需求 T1-4-R3** ：新增 `GET /admin/checks`：

* 返回所有检查项结果列表；
* 响应示例：

```json
{
  "code": 0,
  "msg": "ok",
  "data": [
    {
      "name": "db_connectivity",
      "level": "error",
      "status": "fail",
      "detail": "Cannot connect to DB: timeout",
      "suggestion": "Check DATABASE_URL and ensure DB service is running."
    },
    ...
  ]
}
```

 **需求 T1-4-R4** ：在 `/admin/dashboard` 上展示检查项列表：

* 以表格或卡片形式展示 `name / status / level / detail`；
* 不要求前端按钮“重新运行”，但留出对应 JS 钩子会更方便后续扩展；
* 页面加载时可通过前端脚本请求 `/admin/checks`，避免模板渲染时阻塞整体响应。

---

## 5. 阶段 1 整体验收标准

Stage-1 视为完成时，应满足以下条件：

1. **路由与接口**
   * `GET /admin/dashboard` 返回 200 且 Content-Type 为 `text/html`；
   * `GET /admin/api/summary` 支持 `window` 参数并返回结构化统计数据；
   * `GET /admin/api/testcases` 返回预设 API 测试用例列表；
   * `POST /admin/api/test` 能对 `/healthz`、`/admin/ping` 等接口发起测试并返回结果；
   * `GET /admin/health` 中 `data.db` 与 `data.redis` 包含真实状态字段，而非统一 `"unknown"` 占位；
   * `GET /admin/db/status`、`GET /admin/redis/status` 能正常返回；
   * `GET /admin/checks` 返回至少 3 个检查项结果。
2. **功能验证（手动）**
   * 浏览器访问 `/admin/dashboard`：
     * 能看到应用基本信息与当前时间；
     * 能看到 API 调用总量以及至少 2 条路由统计信息；
     * 能看到 DB/Redis 状态摘要（ok/fail/unknown）；
     * 在 API 测试区域中，选择预设用例（如 `/healthz`），点击“运行”后，能在页面上看到测试结果（状态码与耗时）；
     * 能看到数据检查表格，检查项状态与 `/admin/checks` JSON 一致。
   * 在 DB 或 Redis 关闭的情况下：
     * `/admin/health` 中对应部分显示 `status="fail"` 并说明错误；
     * `/admin/checks` 中对应检查项状态从 `pass` 变为 `fail` 或 `error` 等级。
3. **自动化测试**
   * 新增的 Admin 相关接口在 `tests/admin/` 中具备基本测试用例；
   * 所有已有测试 + 新增测试在 CI 中全部通过；
   * 总体单元测试覆盖率不低于  **Stage-0 要求** （如 Stage-0 要求为 ≥ 80%，则 Stage-1 不得降低）。
4. **代码与结构**
   * Admin 功能集中在预期模块中（`admin.service` / `core/db.py` / `core/redis.py` 等），没有严重的循环依赖；
   * 不破坏 Stage-0 既有 API 的接口约定（所有 `/healthz`、`/admin/ping` 等旧接口仍能正常工作）。
