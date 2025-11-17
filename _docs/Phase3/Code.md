# 阶段 3 开发工作报告

## 1. 开发概述
- 按 Stage-3 Spec 完成 Trip/DayCard/SubTrip CRUD API，支持列表、详情、创建、部分更新、删除以及跨 DayCard 的排序迁移。
- 构建 `TripService` 业务层封装（批量事务、数据校验、错误码），统一管理行程领域逻辑与 ORM。
- Admin 端新增行程统计接口、API 注册表/在线测试增强版、数据库结构视图，并扩展 Dashboard + 新页面（`/admin/api-docs`、`/admin/db/schema?view=1`）。
- Trip API 与 Admin 新接口均补充测试，`pytest` 全量 22 用例通过，覆盖迁移、ORM、Admin、Trip CRUD、排序等关键路径。

## 2. 目录与关键文件
- `backend/app/models/schemas.py`：补齐 Trip/DayCard/SubTrip 请求与响应 Schema、校验逻辑、新的 Summary/Reorder Payload。
- `backend/app/services/trip_service.py`：TripService 业务实现（CRUD、排序、跨天移动、子资源操作、坐标同步等）。
- `backend/app/api/trips.py`：`/api/trips*` REST 路由与统一响应/错误处理。
- `backend/app/api/admin.py`、`backend/app/admin/service.py`、`backend/app/admin/templates/*.html`：Admin 行程统计、API 元信息、在线测试、DB Schema API 与 UI。
- `backend/tests/test_trips.py`、`backend/tests/test_admin.py`：新增 Trip API / 排序 / Admin 新接口用例。
- `_docs/Phase3/Code.md`：本阶段报告。

## 3. 技术实现要点
1. **TripService 与 Schema 扩展**
   - 新增 `TripCreate/TripUpdate/DayCardCreate/...` Pydantic 模型，使用 `model_validator` 保证日期/时间/坐标合法，`TripSummarySchema` 支撑列表视图。
   - TripService 封装 `list/get/create/update/delete`、DayCard/SubTrip 子接口与 `session_scope`，统一抛出业务异常（1400+）供 API 层处理。
   - 子行程排序/跨天移动使用 SQL 事务 + 行级锁，针对 PostgreSQL enum/唯一约束通过 `with_variant Enum` 与中间态顺序（-1）消除冲突，并在 Service 中维护 `ext`/坐标同步。
2. **Trip API**
   - `/api/trips` 支持 `user_id` 过滤、分页（limit/max 100）、摘要 Schema，详情接口嵌套 DayCard/SubTrip。
   - POST/PUT/DELETE 统一返回 `{code,msg,data}`，错误通过 `JSONResponse` + `error_response` 封装，确保业务异常（不存在/字段冲突）不抛 500。
   - 日程/子日程子路由、`/api/sub_trips/{id}/reorder` 快速路由，返回受影响 DayCard 序列。
3. **Admin 扩展**
   - `AdminService.get_trip_summary/get_api_routes/get_api_schemas/get_db_schema_overview` 汇总行程统计、FASTAPI 路由信息、Pydantic Schema、数据库结构。
   - `/admin/api/routes|schemas|test|trips/summary|db/schema` 新增 JSON API，Dashboard 新行程概览卡片展示统计 + 最近修改，手动测试区增加 Query/Path JSON。
   - 新模板 `api_docs.html`（自研 API 文档/分组/Online Try）与 `db_schema.html`（表结构可视化、导航 + 字段/索引列表）。
   - `/admin/api/test` 加强：仅允许 `/api/*`，支持 path/query/body JSON，内部通过 `httpx` ASGI client 调用。
4. **数据库结构与排序实现**
   - `get_db_schema_overview` 基于 `inspect` + `information_schema` 构造字段/索引/外键描述，Jinja 渲染交互视图。
   - SubTrip 排序跨天采用“先占位 -1 / SQL 批量位移 / 最后写入目标位置”策略，保证 `UNIQUE(day_card_id, order_index)` 不冲突。
5. **测试与工具**
   - `test_trips.py` 覆盖行程生命周期、DayCard/SubTrip CRUD、跨天排序，使用 fixtures 创建用户并走 API。
   - `test_admin.py` 针对新预设用例、在线测试、行程 summary、API docs/DB schema 页返回 HTML/JSON。
   - 全量 `pytest` 22 用例通过，输出记录在报告末尾。

## 4. 遇到的问题与解决方案
- **PostgreSQL Enum/Transport 插入 None 报错**：ORM Enum 改为 `with_variant`（PG 使用 native enum，SQLite 仍字符串）避免类型冲突。
- **SubTrip 排序导致 UNIQUE(day_card_id, order_index) 冲突**：排序逻辑重写为 SQL 批量更新 + 临时 `-1` 占位 / window reindex，确保在跨天/同天移动时不会出现重复索引。
- **Admin API Test 需限制 `/api/*`**：`ApiTestRequest` 新增 `path_params`，Service 中解析并拒绝非 `/api/` 请求，同时更新预设用例为 Trip API。
- **Dashboard/API Docs UI 增强**：为自研文档页实现 Tag 分组、Schema 预览、JSON 编辑器与 Try it out；Dashboard 手动测试面板新增 Query/Path JSON 输入与结果日志。

## 5. 测试与验证
- 运行 `pytest`：
  ```
  ============================= test session starts =============================
  collected 22 items

  backend/tests/models/test_migrations.py .                                
  backend/tests/models/test_models.py .                                    
  backend/tests/test_admin.py ...............                              
  backend/tests/test_health.py .                                           
  backend/tests/test_trips.py ....                                         

  ======================= 22 passed, 17 warnings in 3.12s =======================
  ```
- 新 Trip/DayCard/SubTrip 接口、排序、Admin 扩展均有对应断言，保证 Stage-3 功能具备回归防护。

## 6. 后续建议
1. 将 `TripService` 中的 SQL 逻辑提取为单元函数，方便未来 Stage-4/AI Agent 直接复用。
2. Admin API Docs 可以增量支持鉴权/多环境切换或导出 OpenAPI；`/admin/api/routes` 目前简单分组，可考虑后续 Cache。
3. 排序接口后续若需审计，可记录 Logging/History 以便追踪行程调整。
