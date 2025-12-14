# 阶段 8 测试文档（Tests）

## 1. 测试环境
- 操作系统：Windows 11（本地终端，danger-full-access）
- Python：3.12.7
- 依赖版本：pytest 8.3.3、pytest-asyncio 1.2.0、httpx 0.27.x、requests 2.32.x、SQLAlchemy 2.x、psycopg 3.2.x、Redis 5.x、GeoAlchemy2 0.14.x
- 数据库/缓存：
  - PostgreSQL 14 + PostGIS
    - 测试库：`travelist_test`（pytest 自动创建/迁移）
    - 真实数据：`travelist`（真实生产环境数据快照/生产库数据）
  - Redis：`redis://localhost:6380/0`（不可用时自动回退内存缓存）
- 真实数据基线（执行测试时刻抽样）：`users=3`、`trips=1`、`pois=72026`、`ai_tasks=3`
- 生产数据测试开关：
  - `RUN_PROD_TESTS=1`：启用 `backend/prod_tests`（默认禁用，避免误跑）
  - `PROD_TEST_ALLOW_TASK_WRITES=1`：允许创建/执行异步任务（会写入 `ai_tasks`，默认禁用）
  - `PROD_TEST_ALLOW_WRITES=1`：允许 `save=true` 的写入型用例（默认禁用，避免污染生产数据）

## 2. 测试范围
1. **Stage-8 Deep 规划能力**
   - `POST /api/ai/plan`（`mode=deep, async=false`）：按天多轮生成的结构化输出、全局校验、失败回退/明确报错
   - Deep 指标与 trace：`trace_id/tool_traces/metrics`（按天生成 traces + global validate trace）
2. **Stage-8 异步任务（ai_tasks）闭环**
   - `POST /api/ai/plan`（`mode=deep, async=true`）：快速返回 `task_id`
   - `GET /api/ai/plan/tasks/{task_id}`：轮询状态与结果、用户隔离、幂等语义（`request_id`）
3. **LangGraph Planner 链路回归**
   - `tool_traces` 节点：`plan_input → planner_deep/planner_fast → plan_validate(_global) → plan_output`
4. **Admin 可观测性**
   - `GET /admin/plan/summary`：fast vs deep 指标口径（calls/failures/p95/tokens/fallback_rate）
   - `GET /admin/ai/tasks`、`GET /admin/ai/tasks/summary`：任务状态分布、失败原因聚合、耗时统计与最近任务列表
   - `/admin/plan/overview`：deep 同步/异步测试台（含轮询展示）
5. **安全与错误处理**
   - 任务查询必须做 user_id 隔离（非 Admin 必填 user_id 且仅能读自己的任务）
   - 生产环境数据下 `ai_tasks` 兼容性（legacy schema）与启动稳定性

## 3. 测试方法
- 自动化测试（测试库）：`pytest -q`（默认走 `travelist_test`）
- 生产数据烟囱测试（真实数据，只读为主）：
  - `RUN_PROD_TESTS=1 pytest backend/prod_tests -q`（默认写入型用例 skip）
  - `RUN_PROD_TESTS=1 PROD_TEST_ALLOW_TASK_WRITES=1 pytest backend/prod_tests -q`（允许 task 写入；`save=true` 仍默认 skip）
- 静态检查：`ruff check backend/app backend/tests backend/prod_tests`
- 格式检查：`black --check backend/app backend/tests backend/prod_tests`
- 手工验证（推荐）：
  - 访问 `/admin/plan/overview`，运行 deep 同步/异步示例，核对 tool_traces/metrics 与任务轮询展示
  - 访问 `/admin/ai/tasks`，观察状态分布/耗时与失败原因聚合

## 4. 测试用例与结果
| 用例ID | 分类 | 测试步骤 | 预期结果 | 实际结果 | 结论 |
| --- | --- | --- | --- | --- | --- |
| AUTO-ALL | 覆盖 | `pytest -q` | 全部通过或预期 skip | `79 passed, 1 skipped` | 通过 |
| PROD-ALL-RO | 真实数据 | `RUN_PROD_TESTS=1 pytest backend/prod_tests -q` | 仅读用例通过，写入型默认 skip | `10 passed, 2 skipped` | 通过 |
| PROD-ALL-TASK-WR | 真实数据 | `RUN_PROD_TESTS=1 PROD_TEST_ALLOW_TASK_WRITES=1 pytest backend/prod_tests -q` | 任务写入型用例通过，`save=true` 仍 skip | `11 passed, 1 skipped` | 通过 |
| FUNC-PLAN-DEEP-SYNC | 功能 | `POST /api/ai/plan (mode=deep, async=false)` | 返回结构化 plan 或明确报错/回退 | 通过（200 或合理 400） | 通过 |
| FUNC-PLAN-DEEP-ASYNC | 功能/真实数据 | `POST /api/ai/plan (mode=deep, async=true)` + 轮询任务 | 返回 task_id，最终 succeeded/failed（无 500） | `task roundtrip` 通过 | 通过 |
| ADMIN-AI-TASKS | 功能/安全 | 无 Token / 有 Token 访问 tasks summary/page | 未授权 401；授权 200 | 符合预期 | 通过 |
| REGRESSION-PLAN-FAST | 回归 | fast 同 payload 连续调用两次 | `data.plan` 完全一致 | 一致 | 通过 |

## 5. 缺陷记录与修复情况
| ID | 优先级 | 分类 | 影响范围 | 描述 | 修复 |
| --- | --- | --- | --- | --- | --- |
| T8-BUG-001 | P0 | 兼容性/可用性 | `ai_tasks` + worker 启动 | 真实生产库已存在 legacy `ai_tasks`（`id/request_json/result_json/started_at` 等），Stage-8 初版按新 schema 查询 `kind/payload/updated_at` 导致应用启动即报错 | 调整 `AiTask` ORM/迁移/worker/service/admin summary：对齐 legacy schema（字段映射到 `request_json/result_json`），并将 `kind/request_id/trace_id` 写入 payload JSON；生产数据 smoke 测试恢复通过 |
| T8-TEST-001 | P2 | 测试体系 | `backend/prod_tests` | 生产数据 smoke 初版未覆盖 Stage-8 的 Admin 任务监控与 deep async 任务闭环 | 扩展 `backend/prod_tests/test_prod_smoke.py`：新增 `/admin/ai/tasks`/summary 鉴权与渲染用例；新增 deep async 任务 roundtrip（通过 `PROD_TEST_ALLOW_TASK_WRITES=1` 控制写入） |

## 6. 回归测试
- `ruff check backend/app backend/tests backend/prod_tests`：通过
- `black --check backend/app backend/tests backend/prod_tests`：通过
- `pytest -q`：通过（`79 passed, 1 skipped`）
- `RUN_PROD_TESTS=1 pytest backend/prod_tests -q`：通过（只读为主）
- `RUN_PROD_TESTS=1 PROD_TEST_ALLOW_TASK_WRITES=1 pytest backend/prod_tests -q`：通过（允许任务写入）

## 7. 测试结论
Stage-8 Deep 规划与异步任务闭环在测试库与真实生产数据上均完成验证；修复了生产库 `ai_tasks` legacy schema 兼容导致的启动级 P0 问题，并通过生产数据回归测试确认问题已彻底解决。

