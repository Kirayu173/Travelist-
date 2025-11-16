---
# 阶段 2 规格说明书（Spec-2）


## 1. 概述


### 1.1 阶段编号与名称


* 阶段编号：**Stage-2**
* 阶段名称：**数据库 & 核心数据模型落地（数据基础设施 v1）**


### 1.2 背景


在 Stage-1 中，项目已经完成：


* 基础的 `/admin/dashboard` 管理页面框架；
* API 调用统计与在线 API 测试工具雏形；
* 对 DB / Redis 的连通性探测与 Data Check 框架（但仍主要停留在“能连通/不可用”层面）。


下一步必须把“智能旅游 APP”的核心数据结构真正落地到数据库中，包括用户、行程、每日行程卡片、子行程、POI、收藏等，并为后续行程 CRUD、POI 搜索、智能规划和聊天记录等能力打好数据基础。相关表结构与约束以《数据库设计文档》和《后端设计文档》为蓝本。


本阶段完成后，应达到：


1. PostgreSQL 中已经创建核心业务表（`users/trips/day_cards/sub_trips/pois/favorites` 等），开启 PostGIS 扩展并建立必要索引和约束；
1. SQLAlchemy ORM 实体与 Pydantic Schema 建立起来，保证后续阶段可以直接基于这些模型进行业务开发；
1. Admin 中新增数据库健康检查与表行数统计接口，能够从真实数据库返回信息，而不是任何硬编码或假数据；
1. Data Check 能基于真实的表结构做更细一点的检查（例如是否存在基础数据、迁移版本是否一致等）；
1. 将 Stage-1 中 Admin UI 上与数据库相关的展示，从“占位信息”替换为基于 Stage-2 新接口返回的 **真实数据库状态** （作为本阶段的补充任务放在最后实现）。
---
## 2. 范围说明

### 2.1 本阶段实现范围

1. **数据库结构落地（PostgreSQL + PostGIS）**
   * 按数据库设计文档创建以下表及其约束、索引：
     * `users`
     * `trips`
     * `day_cards`
     * `sub_trips`
     * `pois`
     * `favorites`
   * 启用 PostGIS 扩展、`transport` ENUM 类型等。
2. **ORM & Schema 建模**
   * 使用 SQLAlchemy（同步或异步版本以 Stage-0/1 既有约定为准）定义与上述表一一对应的 ORM 模型；
   * 定义基础 Pydantic Schema（或在现有 Schema 的基础上对齐字段）：
     * `UserSchema`
     * `TripSchema`
     * `DayCardSchema`
     * `SubTripSchema`
     * `PoiSchema`
     * `FavoriteSchema`
3. **Admin 数据库健康与统计接口**
   * 新增：
     * `GET /admin/db/health`
     * `GET /admin/db/stats`
   * 能够返回数据库连接状态、基础版本信息以及核心表的行数统计。
4. **Data Check 扩展（基于真实 DB）**
   * 在 Stage-1 Data Check 框架上增加基于数据库的检查项，例如：
     * PostGIS 是否启用；
     * 核心表是否存在；
     * `alembic_version` 状态是否正常；
     * 是否存在至少一条测试用户/行程数据（可选）。
5. **Admin UI 中数据库状态展示替换为真实数据（补充）**
   * 在现有 `/admin/dashboard` 页面中，将 DB 相关的展示从“占位状态/固定文案”替换为基于 `GET /admin/db/health` 与 `GET /admin/db/stats` 的真实数据卡片（具体要求在 4.5 详述）。

### 2.2 非本阶段范围（但需兼容）

* 不在本阶段实现任何业务级行程 CRUD API（这属于 Stage-3）；
* 不处理消息、聊天、异步任务相关表（`chat_sessions/messages/ai_tasks` 等）——这些在后续阶段逐步落地；
* 不做复杂的数据库分区、归档与备份策略，仅需按设计文档为后续扩展预留空间。

---

## 3. 总体技术与通用约定

### 3.1 数据库与迁移

* 数据库： **PostgreSQL** （版本以实际部署环境为准，但需支持 PostGIS 3.x）。
* 空间扩展：启用 `postgis` 扩展，用于 `pois.geom`、`sub_trips.geom` 等字段附近检索。
* 迁移工具： **Alembic** ，所有建表逻辑均通过 migration 脚本实现，不直接手写 SQL 到生产环境。
* ENUM 类型：
  * `transport`：`('walk','bike','drive','transit')`，与产品说明保持一致。

### 3.2 ORM 与 Schema 约定

* ORM 使用 SQLAlchemy（与 Stage-0/1 一致的 Engine/Session 管理方式）；
* 每个核心表均有对应 ORM 类，命名约定：`User`, `Trip`, `DayCard`, `SubTrip`, `Poi`, `Favorite`；
* Pydantic Schema 与 ORM 的字段尽量一一对应，日期/时间采用 ISO8601 字符串，在 API 层转换；
* `geom` 字段在 Schema 中通常表现为 `lat` / `lng`，在 ORM 中使用 `geoalchemy2` 的 `Geography` 类型。

### 3.3 Admin 模块与目录结构

在 Stage-1 的目录结构基础上，建议按如下方式扩展（类比 Stage-1 约定）：

```text
backend/app/
  admin/
    routes.py          # 保持不变或小幅扩展
    service.py         # 新增 DB 相关服务方法
    templates/
      dashboard.html   # 增强 DB 状态展示
  core/
    db.py              # 增强：提供 get_engine(), get_session()
  models/
    orm.py             # ORM 实体定义
    schemas.py         # Pydantic Schema 定义
  migrations/
    versions/
      xxxx_stage2_core_tables.py   # 本阶段 Alembic 脚本
```

要求：

* Admin 与 DB 逻辑通过 `AdminService` 访问，不直接在路由中拼写 SQL；
* 所有 ORM 与迁移文件按照单一职责拆分，便于后续维护与回滚。

---

## 4. 详细功能与实现要求

本阶段拆分为 5 个主要任务：

* T2-1：核心业务表建表（Alembic 迁移）
* T2-2：SQLAlchemy ORM 与 Pydantic Schema 实现
* T2-3：Admin 数据库健康检查接口
* T2-4：Admin 数据库统计与 Data Check 扩展
* T2-5：Admin UI 数据库状态展示替换为真实数据（补充任务）

---

### 4.1 任务 T2-1：核心业务表建表（Alembic 迁移）

#### 4.1.1 功能概述

使用 Alembic 创建本阶段的迁移脚本，实现以下内容：

* 启用 PostGIS 扩展；
* 创建 `transport` ENUM 类型；
* 创建核心表：`users/trips/day_cards/sub_trips/pois/favorites`；
* 为部分字段添加索引与唯一约束，保证后续拖拽排序与查询性能。

#### 4.1.2 表结构与约束要求（概要）

**users**

* 关键字段：`id`, `email`, `name`, `preferences JSONB`, `created_at`, `updated_at`；
* 要求：`email` 唯一索引，可选大小写不敏感索引。

**trips**

* 字段：`id`, `user_id`, `title`, `destination`, `start_date`, `end_date`, `status`, `meta JSONB`, `created_at`, `updated_at`；
* 外键：`user_id` → `users.id`，`ON DELETE CASCADE`；
* 索引：`user_id` 普通索引，必要时可加 `destination` 组合索引。

**day_cards**

* 字段：`id`, `trip_id`, `day_index`, `date`, `note`；
* 约束：`UNIQUE(trip_id, day_index)` 保证每个行程每天只有一张卡片；
* 外键：`trip_id` → `trips.id`，`ON DELETE CASCADE`。

**sub_trips**

* 字段：`id`, `day_card_id`, `order_index`, `activity`, `poi_id`, `loc_name`, `transport`, `start_time`, `end_time`, `geom`, `ext JSONB`, `created_at`, `updated_at`；
* 约束：`UNIQUE(day_card_id, order_index)` 用于子行程拖拽换序；
* 外键：
  * `day_card_id` → `day_cards.id`，`ON DELETE CASCADE`；
  * `poi_id` → `pois.id`（可选）。
* 索引：`(day_card_id, order_index)` BTree 索引，`geom` GiST 索引。

**pois**

* 字段：`id`, `provider`, `provider_id`, `name`, `category`, `addr`, `rating`, `geom`, `ext JSONB`, `created_at`, `updated_at`；
* 索引：
  * `provider + provider_id` 唯一或普通索引用于去重；
  * `geom` GiST 索引用于附近检索；
  * 可选文本搜索索引（tsvector 或 trigram）。

**favorites**

* 字段：`id`, `user_id`, `poi_id`, `created_at`；
* 约束：`UNIQUE(user_id, poi_id)`；
* 外键：`user_id` / `poi_id` 分别指向 `users` / `pois`，`ON DELETE CASCADE`。

#### 4.1.3 实现要求

* 编写单一 Alembic 迁移脚本完成上述所有建表与扩展；
* 迁移脚本需可回滚（`downgrade()` 实现表与类型删除）；
* 在本地执行 `alembic upgrade head` 不报错，且所有表与索引成功创建。

---

### 4.2 任务 T2-2：SQLAlchemy ORM 与 Pydantic Schema 实现

#### 4.2.1 功能概述

在 `models/orm.py` 中定义核心 ORM 模型，在 `models/schemas.py` 中定义对应的 Pydantic Schema，保证：

* 能够通过 ORM 进行基本的增删改查；
* Schema 可作为后续 API 请求/响应的基础。

#### 4.2.2 ORM 实体要求（示例）

* `class User(Base)`：
  * 属性：`id`, `email`, `name`, `preferences`, `created_at`, `updated_at`；
  * 关系：`trips = relationship("Trip", back_populates="user")`。
* `class Trip(Base)`：
  * 属性：`id`, `user_id`, `title`, `destination`, `start_date`, `end_date`, `status`, `meta`；
  * 关系：`user`, `day_cards`。
* `class DayCard(Base)`：
  * 属性：`id`, `trip_id`, `day_index`, `date`, `note`；
  * 关系：`trip`, `sub_trips`。
* `class SubTrip(Base)`：
  * 属性：`id`, `day_card_id`, `order_index`, `activity`, `poi_id`, `loc_name`, `transport`, `start_time`, `end_time`, `geom`, `ext`。
* `class Poi(Base)` / `class Favorite(Base)` 类似处理。

#### 4.2.3 Schema 要求

* `TripSchema` / `DayCardSchema` / `SubTripSchema` 至少包含：
  * 标识字段（`id` 等）；
  * 与业务描述相关的字段（目的地、活动、地点、备注、交通方式、经纬度等）；
* Schema 间支持嵌套，满足后续一次性返回 “行程 + 每日卡片 + 子行程” 的场景；
* Schema 校验规则简单清晰（例如日期必填、`day_index`/`order_index` 为非负整数等）。

---

### 4.3 任务 T2-3：Admin 数据库健康检查接口

#### 4.3.1 功能概述

在 Stage-1 的 `/admin/health` 基础上，将数据库部分从“占位状态”升级为真实健康检查逻辑，并补充独立的 DB/Redis 状态接口。

#### 4.3.2 路由与返回格式

* `GET /admin/db/health`
  * 返回示例：
    ```json
    {
      "code": 0,
      "msg": "ok",
      "data": {
        "db": {
          "status": "ok",
          "latency_ms": 5.3,
          "engine_url": "postgresql://.../travelist",
          "error": null
        }
      }
    }
    ```
* `GET /admin/health`
  * 在原有结构中，将 `data.db` 部分改为调用 `AdminService.get_db_health()` 的结果；
  * Redis 部分沿 Stage-1 已有实现或占位逻辑。

#### 4.3.3 实现要求

* 在 `AdminService` 中实现 `get_db_health()`：
  * 执行一次 `SELECT 1` 测试；
  * 记录耗时（毫秒级）；
  * 捕获异常并返回 `status="fail"` 与错误信息；
* 所有错误必须被封装成安全的文本，不泄露敏感连接信息（例如密码）。

---

### 4.4 任务 T2-4：Admin 数据库统计与 Data Check 扩展

#### 4.4.1 功能概述

在 Admin 中提供简洁的数据库统计信息用于观察当前数据规模，并在 Data Check 中增加更多针对数据库的检查项。

#### 4.4.2 `/admin/db/stats` 接口

* 路由：`GET /admin/db/stats`
* 返回示例：
  ```json
  {
    "code": 0,
    "msg": "ok",
    "data": {
      "tables": {
        "users": { "row_count": 1 },
        "trips": { "row_count": 0 },
        "day_cards": { "row_count": 0 },
        "sub_trips": { "row_count": 0 },
        "pois": { "row_count": 0 },
        "favorites": { "row_count": 0 }
      }
    }
  }
  ```
* 实现建议：
  * 简单版本可直接对每张表执行 `SELECT COUNT(*)`；
  * 若担心性能，可后续调整为基于 `pg_stat_user_tables` 的估算值（本阶段可以先直接 `COUNT(*)`）。

#### 4.4.3 Data Check 扩展

在 Stage-1 `/admin/checks` 的基础上，增加如下检查项：

1. **PostGIS 扩展状态**
   * 通过查询 `pg_extension` 检查 `postgis` 是否已启用；
   * 若未启用，则返回 `status="fail"`，`suggestion` 提示运行 `CREATE EXTENSION postgis;`。
2. **核心表存在性检查**
   * 检查 `users/trips/day_cards/sub_trips/pois/favorites` 是否都在 `information_schema.tables` 中；
   * 任意一张缺失即为 `fail`。
3. **迁移版本检查**
   * 检查 `alembic_version` 表是否存在；
   * 若存在，返回当前版本号；
   * 若不存在，标记为 `status="unknown"` 并给出说明。
4. **基础数据检查（可选）**
   * 若存在 `users` 行数为 0，可提示“当前数据库尚无用户数据，可考虑插入测试用户”。

---

### 4.5 任务 T2-5：Admin UI 数据库状态展示替换为真实数据（补充）

> 这是对 Stage-1 Admin UI 的一次“纠偏升级”：从“写死的占位内容”变成基于 Stage-2 新接口的真实数据展示。

#### 4.5.1 功能概述

在 `/admin/dashboard` 页面中：

1. 替换原有“数据库状态”区域：
   * 原先如果是写死的 `"unknown"` 或简单布尔值，全部改为：
     * DB 状态（ok / fail / unknown）；
     * 延迟（毫秒）；
     * 可选显示当前数据库名/主机（脱敏后的形式）。
2. 新增“数据库表统计”区域：
   * 从 `GET /admin/db/stats` 获取每张表的行数；
   * 以表格或卡片方式展示主要表（`users/trips/day_cards/sub_trips/pois/favorites`）的行数；
   * 对于行数很大的表可以只展示“约 N 条”，实现上可直接用整数。

#### 4.5.2 实现要求

* 模板层不直接执行 SQL，只通过 Admin JSON 接口渲染：
  * Dashboard 加载时在服务器侧调用 `AdminService.get_db_health()` 与 `AdminService.get_db_stats()`，将结果作为模板上下文；
* 页面展示需做到：
  * DB 状态一眼可见（如使用颜色/图标区分 ok/fail）；
  * 行数为 0 时，文案提示“当前暂无线程/POI数据”，方便后续阶段调试；
* 该任务不改变 Stage-1 API 行为，只是用新的真实数据替代原来的占位展示逻辑。

---

## 5. 阶段 2 整体验收标准

Stage-2 视为完成时，应满足以下条件：

1. **数据库与迁移**
   * 本地环境能从空库执行 `alembic upgrade head`，成功创建所有核心表与 ENUM/扩展；
   * 执行 `SELECT * FROM users/trips/day_cards/sub_trips/pois/favorites LIMIT 1` 均不报错（即表存在）；
   * `alembic downgrade -1` 能正常回滚本阶段迁移。
2. **ORM 与 Schema**
   * 通过简单脚本/测试用例可以：
     * 创建一个用户、一个行程、至少一个 day_card 和 sub_trip；
     * 查询时能通过 ORM 正确映射为 Python 对象；
     * 使用对应 Schema 序列化为 JSON 且字段命名与文档一致。
3. **Admin 接口**
   * `GET /admin/db/health` 能正确返回 DB 状态（在 DB 正常/关闭时分别体现 ok/fail）；
   * `GET /admin/db/stats` 至少包含文档中约定的 6 张核心表的行数字段；
   * `GET /admin/checks` 多了至少 3 个与数据库相关的新检查项（PostGIS/核心表/迁移版本等）。
4. **Admin UI**
   * 访问 `/admin/dashboard`：
     * 能看到基于真实数据的数据库状态（包括状态与延迟）；
     * 能看到表行数统计区域；
     * 当关闭 DB 时，页面中 DB 状态明显变为异常（而不是依旧展示“正常”或无变化）。
   * 与 Stage-1 既有功能兼容：
     * API 调用统计区域仍能正常更新；
     * 在线 API 测试工具仍可使用。
5. **测试与 CI**
   * 在 `tests/admin/`、`tests/models/` 下新增至少覆盖：
     * Alembic 迁移是否可执行；
     * `/admin/db/health` 与 `/admin/db/stats` 的基础行为；
   * CI 中所有已有测试 + 新增测试全部通过；
   * 相比 Stage-1 不降低整体测试覆盖率。
