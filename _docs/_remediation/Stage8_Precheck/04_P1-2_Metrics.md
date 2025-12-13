# P1-2：指标持久化（PlanMetrics Redis 可选）

## 整改目标
- Plan 指标支持跨进程/多实例汇总，避免进程重启导致统计丢失（Stage-8 异步任务与对比实验必需）。

## 实施步骤
1. 重构 `PlanMetrics`：`backend/app/services/plan_metrics.py`
   - 保留现有接口：`record/snapshot/reset`
   - 新增 backend 选择：`memory`（默认）/ `redis`（可选）
2. 新增配置项：`backend/app/core/settings.py`、`.env.example`
   - `PLAN_METRICS_BACKEND=memory|redis`
   - `PLAN_METRICS_NAMESPACE`、`PLAN_METRICS_HISTORY_LIMIT`、`PLAN_METRICS_LATENCY_LIMIT`
3. 兼容性：若 Redis 不可用，自动回退 memory backend，不影响 Stage-7 fast 链路。

## 完成时限
- 2025-12-13（已完成）

## 效果验证
- `GET /admin/plan/summary` 正常返回指标字段（calls/failures/avg_days/p95/top_destinations）。
- 当 `PLAN_METRICS_BACKEND=redis` 且 Redis 可用时，重启服务后指标仍可读取（指标不清零）。

## 证据材料
- 变更文件：
  - `backend/app/services/plan_metrics.py`
  - `backend/app/core/settings.py`
  - `.env.example`

