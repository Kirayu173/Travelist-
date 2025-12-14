# 阶段 8 开发工作报告（行程规划 Deep 模式 + 异步任务 ai_tasks）

## 1. 开发概要
- Deep 规划落地（`mode=deep`）：新增 `DeepPlanner`，按天多轮生成（每轮仅生成当天 `day_card/sub_trips` JSON），每轮先做 schema/单日校验，聚合后再做全局校验；失败时按配置回退 fast 或返回明确错误，避免 500/模糊成功。
- 异步任务闭环（`ai_tasks`）：新增任务表/ORM/迁移与进程内 worker，支持 `POST /api/ai/plan` 的 `mode=deep, async=true` 快速返回 `task_id`，并通过 `GET /api/ai/plan/tasks/{task_id}` 轮询状态与结果；支持 `request_id` 幂等与单用户并发限制。
- LangGraph 深度路径接入：规划图按 `mode` 分流（fast/deep），deep 链路输出按天 `planner_deep_day` 轨迹、全局 `plan_validate_global` 轨迹与统一 `trace_id/tool_traces/metrics`，便于排障与实验复现。
- Admin 可观测增强：扩展 `/admin/plan/summary` 支持 deep 指标（calls/failures/p95/tokens/fallback_rate）；新增 `/admin/ai/tasks` 任务监控页与 `/admin/ai/tasks/summary` 数据接口；并在 `/admin/plan/overview` 补齐 deep 同步/异步测试台（含 task_id 轮询）。
- 测试与质量：补齐 deep 同步、异步任务状态流转、幂等冲突、限流边界、ai_tasks ORM/migration 的单元/集成测试；并确保 `ruff`/`black`/`pytest` 通过。

## 2. 目录与关键文件
- Deep 规划核心：
  - `backend/app/services/deep_planner.py`：按天多轮生成、单日校验、聚合、回退策略与 mem0 摘要写入。
  - `backend/app/agents/planner/graph.py`：按 `mode` 分流，新增 `planner_deep` 与 `plan_validate_global` 节点。
  - `backend/app/agents/planner/nodes.py`：新增 `planner_deep_node`（含 `planner_seed_fast / planner_deep_day / plan_validate` traces）与 `plan_validate_global_node`。
- 异步任务（ai_tasks）：
  - `backend/app/models/orm.py`：新增 `AiTask` ORM（对齐生产库 legacy `ai_tasks`：`id/request_json/result_json/started_at/finished_at`）。
  - `backend/migrations/versions/20251214_03_stage8_ai_tasks.py`：新增迁移（若表不存在则创建；若已存在则不重复创建，避免与生产库历史表冲突）。
  - `backend/app/services/plan_task_worker.py`：进程内队列 + worker 协程、重启恢复策略、结果写回。
  - `backend/app/services/plan_task_service.py`：任务创建/幂等冲突检测/并发限制/任务查询与 Admin 读权限判定。
- API & Admin：
  - `backend/app/api/ai.py`：扩展 `POST /api/ai/plan` 支持 deep async；新增 `GET /api/ai/plan/tasks/{task_id}`。
  - `backend/app/services/plan_metrics.py`：扩展 deep 指标口径（calls/failures/mean/p95/tokens_total/fallback_rate）。
  - `backend/app/api/admin.py`：新增 `/admin/ai/tasks` 页面与 `/admin/ai/tasks/summary` 数据接口。
  - `backend/app/admin/service.py`：新增 `get_ai_tasks_summary()`（状态分布/耗时/失败原因聚合）。
  - `backend/app/admin/templates/plan_overview.html`：补齐 deep 测试台（同步/异步/轮询）与 fast vs deep 指标展示。
  - `backend/app/admin/templates/ai_tasks.html`、`backend/app/admin/templates/base.html`：新增任务监控页面与侧边栏入口。
- 配置：
  - `backend/app/core/settings.py`：补齐 `PLAN_DEEP_*` 与 `PLAN_TASK_*` 配置项。
  - `.env.example`：补齐 Deep/任务相关示例配置。
- LLM 可测性增强：
  - `backend/app/ai/models.py`：`AiChatRequest` 支持 `model/temperature/max_tokens`（可选）。
  - `backend/app/ai/client.py`：mock provider 在 `response_format=json` 时返回可解析的确定性 JSON（用于 deep 测试）。
- 实验复现（T8-7）：
  - `scripts/experiment_stage8_fast_vs_deep.py`：生成 fast vs deep 的输入/输出样例（支持 `--local` 免启动服务复现）。
  - `_docs/Phase8/experiments/`：固定一组输入与输出文件（input/fast/deep，含 trace_id/tool_traces/metrics）。
- 测试：
  - `backend/tests/test_plan_api.py`：deep 同步/异步、轮询、幂等冲突、限流与 user_id 隔离。
  - `backend/tests/test_admin_ai_tasks.py`：Admin 任务监控接口/页面测试。

## 3. 技术实现要点
### 3.1 DeepPlanner（按天多轮 + 最小闭环）
- Seed/骨架：`seed_mode=fast` 时先生成 fast 草案作为骨架摘要与去重参考（trace：`planner_seed_fast`）。
- 按天生成：对 `day_index=0..day_count-1` 循环调用 LLM（mock 可替代），每轮只生成当天 JSON（`PlanDayCardSchema`），并执行单日校验（trace：`planner_deep_day` + `plan_validate`）。
- 聚合与全局校验：聚合为 `PlanTripSchema`，并在图中通过 `plan_validate_global` 做全局一致性校验（日期连续、order_index 连续、sub_trip_count 一致、跨天 POI 去重等）。
- 失败处理：单日失败仅重试当前天（`PLAN_DEEP_RETRIES`）；当 deep 失败时按 `PLAN_DEEP_FALLBACK_TO_FAST` 决定回退 fast，并在 `metrics.fallback_to_fast` 标记。

### 3.2 ai_tasks（持久化 + 进程内 worker）
- 表结构：兼容生产库 legacy `ai_tasks`（`id/user_id/status/request_json/result_json/error/created_at/started_at/finished_at`）。
  - `kind/request_id/trace_id/seed_mode` 等 Stage-8 所需字段写入 `request_json`（payload）中，避免与既有表结构冲突。
- Worker：`asyncio.Queue + N worker`（`PLAN_TASK_WORKER_CONCURRENCY`），执行前后均为短事务写状态/结果，LLM 调用期间不持有 DB 事务；重启时对 `running` 标记为 failed（`worker_restart`），对 `queued` 重新入队。
- 幂等与限流：先判断 `request_id` 幂等（同 payload 返回同 task_id），再做单用户并发限制（`PLAN_TASK_MAX_RUNNING_PER_USER`），避免“幂等键被限流误伤”。

### 3.3 接口与错误处理
- `POST /api/ai/plan`：
  - `mode=fast`：保持 Stage-7 行为，忽略 `async`。
  - `mode=deep, async=false`：同步返回 `plan`（含 metrics/tool_traces/trace_id）。
  - `mode=deep, async=true`：返回 `task_id`（plan 为空）并提供 `trace_id` 便于排障。
- `GET /api/ai/plan/tasks/{task_id}`：轮询任务状态与结果；非 Admin 访问必须提供 `user_id` 且只允许读取所属任务。

### 3.4 Admin 可观测与测试台
- `/admin/plan/summary`：在 fast 指标基础上扩展 deep 指标口径（calls/failures/p95/tokens_total/fallback_rate），并在 `/admin/plan/overview` 展示与刷新。
- `/admin/ai/tasks`：任务状态分布、mean/p95、失败原因 TopN、最近任务列表（task_id/trace_id/request_id）。
- `/admin/plan/overview`：补齐 deep 测试台（同步/异步/轮询），方便后续阶段继续迭代 Deep 策略与任务系统。

## 4. 遇到的问题与解决方案
- **幂等请求被并发限制拦截**：初版先做限流再查幂等，导致重复提交同 request_id 返回 400；调整为“先幂等后限流”，符合 Spec 的幂等语义。
- **mock LLM 输出不可解析**：AiClient mock 默认回显 `mock:<prompt>`，deep 需要 JSON；为 `response_format=json` 增加确定性 JSON 输出，确保 deep/async 测试可稳定运行。
- **任务更新未刷新 updated_at**：bulk update 不触发 `onupdate`，导致 updated_at 不变；改为 ORM 实体更新写回，保证任务监控口径可用。
- **deep 失败不回退**：部分失败路径抛出 `DeepPlannerError` 后直接中断；调整为在可配置条件下同样触发回退 fast，并在 metrics 中标记原因。
- **实验样例难以复现/依赖外部服务**：补齐实验脚本的固定 `start_date`，并增加 `--local`（mock AI + in-memory sqlite）模式以便无服务复现与自动生成样例文件。
- **生产库 ai_tasks schema 冲突导致启动失败**：真实数据中已存在 legacy `ai_tasks`（字段名/类型与 Stage-8 初版不一致），导致 worker 启动查询报错；调整 ORM/迁移/worker/service/admin summary 全面兼容 legacy schema，并将 Stage-8 所需字段写入 payload JSON。

## 5. 测试与验证
- 质量工具：
  - `ruff check backend/app backend/tests`：通过
  - `black backend/app backend/tests`：通过
- 自动化测试：
  - `pytest`：`79 passed, 1 skipped`
  - 覆盖范围：deep 同步与异步任务闭环、任务轮询与 user_id 隔离、request_id 幂等冲突、单用户并发限制、Admin tasks summary/page、ai_tasks ORM/migration。
- 手工验证（Admin 测试台）：
  - `/admin/plan/overview`：运行 fast/deep（同步/异步），验证 tool_traces/metrics 与 task 轮询展示。
  - `/admin/ai/tasks`：观察 queued/running/succeeded/failed 分布与失败原因聚合。
- 实验样例（fast vs deep）：
  - 样例文件：`_docs/Phase8/experiments/input.json`、`_docs/Phase8/experiments/fast_response.json`、`_docs/Phase8/experiments/deep_sync_response.json`。
  - 复现命令（无服务）：`python scripts/experiment_stage8_fast_vs_deep.py --local`（生成/覆盖上述文件，输出包含 trace_id/tool_traces/metrics）。

## 6. 后续建议
1. 为异步任务增加进度写回（`result.progress`），提升轮询与监控体验。
2. 将 deep 的提示词纳入 PromptRegistry（可视化版本/回滚），并补齐 `prompt_version` 与模型配置的实验记录。
3. 增加任务清理策略（`PLAN_TASK_RETENTION_DAYS` 定期清理）与更生产化的队列/worker（Stage-9 可考虑 Redis/RQ/Celery）。
4. 进一步提升 deep 质量：候选 POI 城市过滤、评分/距离权重、多样性约束与更精细的时间窗规划。 
