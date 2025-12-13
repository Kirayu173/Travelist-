# 阶段 7 审查报告（Review）

## 1. 审查概述
- 审查时间：2025-12-14
- 输入材料：`_docs/Phase7/Spec.md`、`_docs/Phase7/Code.md`、`_docs/Phase7/Tests.md`、源代码、pytest 结果、生产数据烟囱测试结果
- 目标：评估 Stage-7（行程规划 fast 规则版 + LangGraph Planner + Admin 指标）在需求对齐、架构设计、性能、可维护性、安全性与文档完整性方面的质量与风险

## 2. 审查范围与方法
1) 需求对齐：对照 Spec-7 的 API/Schema/预留字段、可复现性、降级策略与 Admin 可观测性  
2) 架构设计：PlanService 分发、FastPlanner 规则规划、PlannerGraph(tool_traces) 链路、与 POI/Trip 现有模块的耦合边界  
3) 性能：POI 查询路径（PostGIS/缓存）、规划生成复杂度、响应体大小与关键指标  
4) 安全：Admin 鉴权覆盖、危险接口控制、输入校验与错误处理  
5) 可维护性：模块职责、测试隔离、配置项可控性、可扩展性（Stage-8 deep）  
6) 文档：Spec/Code/Tests/Review 是否闭环、运行方式与风险提示是否充分

## 3. 审查结论概览
| 维度 | 评价 | 说明 |
| --- | --- | --- |
| 需求覆盖 | ✅ 满足 | `POST /api/ai/plan`(fast) 可用；deep 明确未实现并保留字段；Admin summary/overview 可用 |
| 架构设计 | ✅ 清晰 | PlanService 统一入口 + LangGraph PlannerGraph；FastPlanner 保持非 LLM 依赖 |
| 性能 | ⚠️ 可接受 | 依赖 PostGIS 空间索引与缓存；规则规划复杂度低，但目的地中心点为伪定位存在质量上限 |
| 安全 | ⚠️ 已修复关键问题 | 修复 `/admin/api/sql_test` 鉴权缺失并加多语句防护；其余 Admin 继续由 token/IP 控制 |
| 可维护性 | ✅ 良好 | Schema/Service/Graph 分层明确；提供测试与生产数据烟囱测试开关 |
| 文档完整性 | ✅ 完整 | Spec/Code/Tests/Review 形成闭环，并记录缺陷与回归结果 |

## 4. 详细发现
### 4.1 需求与实现
- 统一接口 `POST /api/ai/plan`：fast 路径返回结构化 plan；deep 返回明确未实现错误，并保留 `async/request_id/seed_mode/task_id` 等字段用于 Stage-8 扩展
- 可复现性：测试与生产数据验证均表明相同 seed 下 `data.plan` 可复现；指标字段（如缓存命中来源、latency）会随运行环境变化而变化，属于合理差异
- 降级策略：候选 POI 不足时按半天生成“自由探索”子行程，避免 500，符合 Spec-7 兜底要求

### 4.2 代码质量与可维护性
- PlanRequest/PlanResponseData/PlanTripSchema 对齐清晰，字段别名（`async`）处理规范
- FastPlanner 规则规划逻辑集中、可读性较好，关键行为通过 pytest 覆盖（fast/deep/边界/保存）
- 新增 `backend/prod_tests` 作为真实数据烟囱测试，默认禁用避免误跑，提升测试可靠性

### 4.3 架构设计
- PlanService 作为统一入口，内部按 mode 分发并维护 trace_id/metrics 记录，便于后续扩展 deep/async
- PlannerGraph 将规划链路纳入 LangGraph，可统一输出 tool_traces 供 Admin/排障使用
- 与 POI 模块的依赖为 “候选供给”，边界清晰；Trip 持久化仅在 `save=true` 时触发

### 4.4 性能与体验
- POI 查询：依赖 PostGIS `GIST` 空间索引（`ix_pois_geom`）与 cache-aside，可支撑 7w+ POI 的查询回放
- 规划耗时：fast 路径主要开销在 POI 查询与去重排序，规则生成本身开销较低；Admin summary 提供 p95 等指标可用于后续对比 deep
- 体验风险：当前“城市中心点”使用伪定位（hash 映射），可能导致候选偏离真实城市地理中心；建议 Stage-8 引入真实 geocode/中心点策略提升质量

### 4.5 安全性
- 已修复：`/admin/api/sql_test` 接口增加 `verify_admin_access`，并禁止 `;` 多语句，降低越权/误用风险
- 建议：对 Admin 调试接口增加更严格的审计与限流（例如：仅允许白名单库/表、限制返回行数与执行时间）

### 4.6 风险评估与改进建议
1. **规划质量上限（中）**：伪中心点导致候选偏离，建议引入 geocode 与多中心点采样  
2. **指标跨实例聚合（中）**：当前 PlanMetrics 为进程内统计，多实例部署需迁移到 Redis/DB 做聚合  
3. **Admin 调试能力（中）**：SQL 调试虽已加鉴权，仍需最小权限与审计策略，避免线上误操作  
4. **写入型生产测试（低）**：`save=true` 在真实数据环境默认禁用，建议仅在隔离库/快照库中开启并配套清理脚本

## 5. 结论
Stage-7 的 fast 规则规划与可观测性目标达成，测试覆盖包含测试库自动化与生产数据烟囱验证；关键安全缺陷已修复并回归通过。后续阶段建议优先补齐真实地理中心点与跨实例指标聚合，以提升规划质量与线上可运维性。

