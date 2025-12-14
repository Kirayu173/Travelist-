# 阶段 8 审查报告（Review）

## 1. 审查概述
- 审查时间：2025-12-14
- 输入材料：`_docs/Phase8/Spec.md`、`_docs/Phase8/Code.md`、`_docs/Phase8/Tests.md`、`_docs/Phase8/experiments/*`、源代码、pytest 结果、生产数据烟囱测试结果
- 目标：评估 Stage-8（Deep 规划 + 异步任务 ai_tasks）在需求对齐、架构设计、性能、可维护性、安全性与文档完整性方面的质量与风险

## 2. 审查范围与方法
1) 需求对齐：对照 Spec-8 的 `mode=deep`（按天多轮 + 全局校验）、`async/task_id/request_id`、回退策略与 Admin 可观测要求  
2) 架构设计：PlanService/PlannerGraph 分发、DeepPlanner 流程、ai_tasks + worker 的职责边界与事务边界  
3) 性能：deep 链路 LLM 调用次数与 tokens 指标口径、任务并发控制、DB 访问与响应体大小  
4) 安全：任务查询 user_id 隔离、Admin 鉴权覆盖、错误信息脱敏与结果存储的敏感信息控制  
5) 可维护性：模块内聚、测试隔离、配置项可控性、对生产库差异（legacy ai_tasks）的兼容性  
6) 文档：Spec/Code/Tests/Review/实验样例是否闭环，是否提供复现与风险提示

## 3. 审查结论概览
| 维度 | 评价 | 说明 |
| --- | --- | --- |
| 需求覆盖 | ✅ 满足 | deep 同步/异步闭环可用；按天多轮 + 全局校验；失败回退 fast；Admin tasks + 指标对比完成 |
| 架构设计 | ✅ 清晰 | PlanService 统一入口 + LangGraph 分流；DeepPlanner/TaskService/Worker 职责明确、事务边界清晰 |
| 性能 | ⚠️ 可接受 | deep 端到端成本受天数与候选 POI 影响；已提供 tokens/latency 指标与并发上限，但仍需长期压测与清理策略 |
| 安全 | ✅ 可控 | 任务查询做 user_id 隔离；Admin 继续由 token/IP 控制；结果存储为安全子集与脱敏错误 |
| 可维护性 | ✅ 良好 | 代码分层明确、测试覆盖含真实数据 smoke；配置项齐全；兼容 legacy `ai_tasks` 后启动稳定 |
| 文档完整性 | ✅ 完整 | Spec/Code/Tests/Review + 实验样例闭环，支持后续迭代与论文实验复现 |

## 4. 详细发现
### 4.1 需求与实现对齐
- Deep 规划：按天多轮生成（每轮仅生成当天 day_card JSON），单日校验 + 聚合全局校验，符合 Spec-8 的“结构稳定优先”目标
- 回退策略：deep 失败可配置回退 fast，并在 metrics 标记 `fallback_to_fast`，避免 500/模糊成功
- 异步任务：`mode=deep, async=true` 返回 `task_id`，轮询接口提供状态与结果；幂等键 `request_id` 支持重复提交复用同任务

### 4.2 生产库兼容性（关键）
- 发现：真实生产库存在 legacy `ai_tasks` 表（`id/request_json/result_json/started_at` 等），与 Stage-8 初版设计冲突导致应用启动即失败
- 处理：将任务 ORM/迁移/worker/service 统一对齐 legacy schema，并将 `kind/request_id/trace_id` 写入 payload JSON；生产数据 smoke 测试与回归验证通过
- 风险提示：若后续需要更强约束（如 DB 层唯一约束/索引优化），建议以增量 migration 方式扩展列或增加 JSONB 表达式索引，避免再次发生 schema 冲突

### 4.3 性能与稳定性
- 成本控制：已提供 `PLAN_TASK_MAX_RUNNING_PER_USER` 并发上限与 queue 最大长度，降低 deep 成本失控风险
- 指标口径：`/admin/plan/summary` 与 `plan_metrics` 提供 fast vs deep 的 calls/failures/latency/tokens/fallback_rate，可用于论文实验与线上观测
- 稳定性：worker 执行期间不持有 DB 长事务，状态更新为短事务；重启恢复对 running 任务明确标记失败原因

### 4.4 安全性
- 任务查询：非 Admin 必须提供 `user_id` 且只能读取自己的任务；Admin 可读全量任务状态用于排障
- 错误处理：deep/任务失败返回明确错误码与 trace_id；任务结果不落完整 prompt/API Key 等敏感信息

### 4.5 可维护性与测试
- 测试覆盖：测试库 pytest 覆盖 deep 同步/异步、幂等冲突、限流与 Admin tasks；生产数据 smoke 覆盖 POI/fast/deep、Admin 页面、任务监控（写入型受开关控制）
- 文档闭环：`_docs/Phase8/Code.md`、`_docs/Phase8/Tests.md`、`_docs/Phase8/Review.md`、`_docs/Phase8/experiments/*` 形成闭环，便于后续查阅与维护

## 5. 风险评估与改进建议
1. **任务清理策略（中）**：`ai_tasks` 会持续增长；建议在 Stage-9 引入保留期清理（`PLAN_TASK_RETENTION_DAYS`）与后台清理任务  
2. **索引与查询性能（中）**：若按 `payload.kind/request_id` 查询频繁，建议增加 JSONB 表达式索引或显式列以提升性能  
3. **多实例部署（中）**：当前 worker 为进程内队列，适用于单进程；多实例需引入 Redis/RQ/Celery 等分布式队列并统一幂等/限流口径  
4. **deep 质量提升（中）**：候选 POI 城市过滤、评分/距离权重、多样性约束可进一步提升可用性；建议结合实验样例做对比评估  
5. **任务进度回写（低）**：可选增加 `progress`（天数/当前天）便于轮询与 Admin 观察

## 6. 结论
Stage-8 已实现 deep 规划与异步任务的端到端闭环，并具备可观测与可复现实验数据；关键的生产库 `ai_tasks` legacy schema 兼容问题已修复并回归验证通过。后续阶段建议优先补齐任务清理与分布式队列能力，以提升线上可运维性与扩展性。

