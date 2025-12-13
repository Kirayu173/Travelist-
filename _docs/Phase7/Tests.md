# 阶段 7 测试文档（Tests）

## 1. 测试环境
- 操作系统：Windows 11（本地终端，danger-full-access）
- Python：3.12.7
- 依赖版本：pytest 8.3.3、pytest-asyncio 1.2.0、httpx 0.27.x、requests 2.32.x、SQLAlchemy 2.x、psycopg 3.2.x、Redis 5.x、GeoAlchemy2 0.14.x
- 数据库/缓存：
  - PostgreSQL 14 + PostGIS（本地 `travelist_test`：pytest 自动创建/迁移；本地 `travelist`：真实生产数据快照/生产库数据）
  - Redis：`redis://localhost:6380/0`（缓存不可用时自动回退内存缓存）
- 真实数据基线（执行测试时刻抽样）：`users=3`、`trips=1`、`pois=72026`
- 生产数据测试开关：
  - `RUN_PROD_TESTS=1`：启用 `backend/prod_tests`（默认禁用，避免误跑）
  - `PROD_TEST_ALLOW_WRITES=1`：允许 `save=true` 的写入型用例（默认禁用，避免污染生产数据）

## 2. 测试范围
1. **Stage-7 规划能力**
   - 统一入口：`POST /api/ai/plan`（`mode=fast`）
   - `mode=deep` 占位返回（Stage-8 预留）
   - 规则规划输出结构（TripSchema/PlanSchema 对齐）
   - 可复现性：相同 seed 下 `data.plan` 内容一致（忽略 `trace_id/latency_ms`）
2. **LangGraph Planner 链路**
   - `tool_traces` 节点：`plan_input → planner_fast → plan_validate → plan_output`
3. **Admin 可观测性**
   - `GET /admin/plan/summary`（鉴权、指标字段、调用计数）
   - `GET /admin/plan/overview`（HTML 渲染）
4. **安全与回归**
   - 管理后台 SQL 调试接口权限控制（`/admin/api/sql_test`）
   - Stage-6 POI/缓存能力回归（规划依赖 POI 候选）

## 3. 测试方法
- 自动化测试（测试库）：`pytest -q`（默认走 `travelist_test`）
- 生产数据烟囱测试（真实数据）：`RUN_PROD_TESTS=1 pytest backend/prod_tests -q`（直连 `travelist`，以只读为主）
- 静态检查：`ruff check backend/app backend/tests backend/prod_tests`
- 格式检查：`black --check backend/app backend/tests backend/prod_tests`
- 手工验证（推荐）：
  - 访问 `/admin/plan/overview`，运行 Fast 示例，核对 day_cards、metrics、tool_traces
  - 切换 Deep（占位），确认返回“未实现”提示

## 4. 测试用例与结果
| 用例ID | 分类 | 测试步骤 | 预期结果 | 实际结果 | 结论 |
| --- | --- | --- | --- | --- | --- |
| AUTO-ALL | 覆盖 | `pytest -q` | 全部通过或预期 skip | `71 passed, 1 skipped` | 通过 |
| PROD-ALL | 真实数据 | `RUN_PROD_TESTS=1 pytest backend/prod_tests -q` | 仅读用例通过，写入型默认 skip | `8 passed, 1 skipped` | 通过 |
| FUNC-PLAN-FAST | 功能 | `POST /api/ai/plan (mode=fast, save=false)` | 返回结构化 plan，day_count 匹配 | 200，结构/数量正确 | 通过 |
| FUNC-PLAN-DETERMINISTIC | 功能 | 相同 payload 连续调用两次 | `data.plan` 一致 | `data.plan` 一致 | 通过 |
| FUNC-PLAN-DEEP | 功能/边界 | `POST /api/ai/plan (mode=deep)` | 400，返回明确未实现与 trace_id | 符合预期 | 通过 |
| FUNC-PLAN-MAXDAYS | 边界 | `end_date-start_date+1 > PLAN_MAX_DAYS` | 400 | 符合预期 | 通过 |
| FUNC-POI-AROUND-PROD | 回归/真实数据 | `GET /api/poi/around`（取 DB 内真实坐标） | items 非空，meta.source 合法 | items≥1，source∈{db,cache,api} | 通过 |
| ADMIN-PLAN-SUMMARY | 功能/安全 | 无 Token / 有 Token 访问 | 未授权 401；授权 200 | 符合预期 | 通过 |
| ADMIN-SQL-TEST | 安全 | 无 Token / 多语句 / 非 SELECT | 401 / 400 / 400 | 修复后符合预期 | 通过 |

## 5. 缺陷记录与修复情况
| ID | 优先级 | 分类 | 影响范围 | 描述 | 修复 |
| --- | --- | --- | --- | --- | --- |
| T7-BUG-001 | P0 | 安全 | `backend/app/api/admin.py` | `/admin/api/sql_test` 标注为 Restricted 但未接入 `verify_admin_access`，存在越权执行风险 | 已加鉴权依赖，并禁止 `;` 多语句 |
| T7-BUG-002 | P2 | 测试可靠性 | `backend/prod_tests` | 在部分运行方式下可能意外收集生产数据测试用例 | 增加 `RUN_PROD_TESTS=1` 显式开关，默认整体 skip |
| T7-BUG-003 | P3 | 工具链/告警 | `pyproject.toml` | pytest-asyncio loop scope 配置弃用告警（影响测试输出稳定性） | 增加 `asyncio_default_fixture_loop_scope=function` |

## 6. 回归测试
- `pytest -q`：通过
- `RUN_PROD_TESTS=1 pytest backend/prod_tests -q`：通过（写入用例默认 skip）
- `ruff check ...`、`black --check ...`：通过

## 7. 测试结论
Stage-7 核心规划链路（fast 规则规划 + LangGraph tool_traces + Admin 指标）在测试库与真实生产数据上均验证通过；已修复 1 个高优先级安全问题，并完成回归验证。

