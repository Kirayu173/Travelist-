# 阶段 7 开发工作报告（行程规划 Fast 模式 + LangGraph Planner）

## 1. 开发概要
- 规则规划落地（`mode=fast`）：实现可控、可复现、可解释的 FastPlanner，在给定目的地与日期范围内生成结构化 Trip（按天/半天组织子行程），POI 不足时自动降级为“自由探索”，避免 500。
- 统一规划入口：新增 `POST /api/ai/plan`，Stage-7 支持 `mode=fast` 同步规划；`mode=deep` 明确返回“未实现”错误，同时预留 `async/request_id/seed_mode/task_id` 字段以便 Stage-8 无痛扩展。
- LangGraph 接入：新增独立规划图（`plan_input → planner_fast → plan_validate → plan_output`），统一输出 `tool_traces`（node/status/latency_ms/detail）与 `trace_id`，便于复现实验与排障。
- Admin 可观测与测试台：新增 `/admin/plan/summary` 指标接口与 `/admin/plan/overview` 规划管理页；提供 Fast 便捷测试台（含详细测试指导）并预留 Deep 测试台占位。
- 测试与质量：补齐 FastPlanner/PlanService/规划 API/Admin 页面与鉴权的单元测试/集成测试；并修复并统一通过 `ruff`/`black`/`pytest`（Stage-7 交付口径）。

## 2. 目录与关键文件
- 规划 Schema：`backend/app/models/plan_schemas.py`
  - `PlanRequest`（含 `async`/`request_id`/`seed_mode` 预留）
  - `PlanTripSchema`（规划输出 Trip 结构）、`PlanResponseData`（统一返回结构）
- Fast 规划器与校验：
  - `backend/app/services/fast_planner.py`（规则规划核心）
  - `backend/app/services/plan_validator.py`（输出结构/约束校验）
- 统一服务入口与指标：
  - `backend/app/services/plan_service.py`（按 `mode` 分发，Stage-7 仅 fast，deep 占位报错；可选 `save=true` 落库）
  - `backend/app/services/plan_metrics.py`（进程内指标：calls/failures/avg_days/latency_p95/top_destinations）
- LangGraph Planner：
  - `backend/app/agents/planner/state.py`、`backend/app/agents/planner/nodes.py`、`backend/app/agents/planner/graph.py`
  - `backend/app/agents/__init__.py` 增加 planner 导出（与 assistant 保持一致入口风格）
- API & Admin：
  - `backend/app/api/ai.py`：新增 `POST /api/ai/plan`
  - `backend/app/admin/service.py`：新增 `get_plan_summary`
  - `backend/app/api/admin.py`：新增 `GET /admin/plan/summary`、`GET /admin/plan/overview`
  - `backend/app/admin/templates/plan_overview.html`：规划管理与测试台（fast 指导 + deep 占位）
  - `backend/app/admin/templates/base.html`、`backend/app/admin/templates/dashboard.html`：导航与入口卡片补齐
- 配置：
  - `backend/app/core/settings.py`：新增 `PLAN_*` 配置项（时间窗/slot/天数上限/seed/候选 POI 上限/交通方式）
  - `.env.example`：补齐并对齐 `PLAN_*` 示例
- 测试：
  - `backend/tests/test_plan_api.py`：fast happy path、可复现性、deep 未实现、上限校验、save 落库
  - `backend/tests/test_admin_plan.py`：plan summary 鉴权与页面渲染
  - `backend/tests/conftest.py`：引入 `reset_plan_metrics()` 保证测试隔离

## 3. 技术实现要点
### 3.1 统一契约（PlanRequest/PlanResponse）
- 统一入口 `POST /api/ai/plan` 固定字段语义（destination/date_range/mode/save/preferences），并为 deep/async/task_id/request_id/seed_mode 预留明确含义。
- `async` 作为关键字通过 `async_` 字段映射（Pydantic alias），保证 JSON 字段名与 Spec 对齐。

### 3.2 FastPlanner（纯规则、可复现）
- 输入校验：日期范围合法、`PLAN_MAX_DAYS` 上限、兴趣偏好缺失时默认补齐（`["sight","food"]`）。
- POI 候选获取：
  - 目的地关键字 DB 搜索（`ext.city / ext.amap.city / name / addr`），同时复用 Stage-6 `PoiService.get_poi_around`（mock/第三方）构造候选集。
  - provider/provider_id 去重，记录来源统计（cache/db/api）到 metrics。
- 行程生成：
  - 按天生成 `day_cards`；每天划分上/下午两个半天窗口；每个半天 1~2 个活动（受 pace/天数影响且受时间窗容量约束）。
  - 选择策略：优先兴趣匹配与多样性（避免连续同类），并保证输出稳定（固定 seed，不写入动态时间戳）。
  - POI 不足：按半天降级生成 activity=“自由探索”子行程，并提供可读 hint（避免 500）。

### 3.3 LangGraph PlannerNode 与可追踪性
- 规划链路采用独立图：`plan_input → planner_fast → plan_validate → plan_output`。
- 每个节点写入 `tool_traces`：`node/status/latency_ms/detail`，并以 `trace_id` 贯穿日志与返回数据，便于后续论文复现实验。

### 3.4 Admin 可观测与测试台
- 指标接口：`GET /admin/plan/summary` 输出 fast 调用次数、失败率、平均天数、延迟均值与 P95、top destinations、最近调用列表（last_10_calls）。
- 规划管理页：`/admin/plan/overview`
  - Fast 测试台：一键填充示例、可视化 Request/Response、展示 tool_traces，并内置详细测试指导（复现/降级/错误用例）。
  - Deep 测试台（预留）：允许发起 `mode=deep` 占位请求并展示“未实现”返回，为 Stage-8 异步 task_id 流程预留 UI 框架。

## 4. 遇到的问题与解决方案
- **可复现性被动态时间戳破坏**：初版在 `trip.meta` 写入 `generated_at` 导致同输入输出不一致；改为移除动态字段，仅保留 rules_version/seed/interests 等确定性信息。
- **save=true 合并 ID 逻辑错误**：`PlanTripSchema(**plan_dump, id=...)` 触发重复关键字；改为先构造 dict 再覆盖 id/day_cards，避免重复传参。
- **历史代码 ruff/black 不通过**：集中修复 line-too-long、未使用变量、`warnings.warn` 缺少 stacklevel、以及 admin service 中 `_extract_schema_name` 误粘贴导致的未定义变量问题；统一通过格式化与 lint。

## 5. 测试与验证
- 质量工具：
  - `ruff check backend/app backend/tests`：通过
  - `black --check backend/app backend/tests`：通过
- 自动化测试：
  - `pytest`：`67 passed, 1 skipped`
  - 覆盖范围：FastPlanner（happy path/上限/降级）、`/api/ai/plan`（fast/deep/save）、LangGraph tool_traces、Admin plan summary 鉴权与页面渲染。
- 手工验证（Admin 测试台）：
  - 访问 `/admin/plan/overview`，运行 Fast 示例用例，核对 day_count/day_cards/tool_traces/metrics；切换 deep 占位请求验证未实现返回。

## 6. 后续建议
1. Deep 模式（Stage-8）建议引入异步任务体系（task_id/轮询/存储），复用本阶段的 `PlanRequest/PlanResponseData` 与 `PlanValidator`，保证向后兼容。
2. POI 候选可进一步增强：基于地理中心点的真实 geocode、引入距离/评分综合权重与去重策略（同类聚合/多样性约束）。
3. Admin 指标可选落盘（Redis/DB）以支持多实例统计与更长窗口的 P50/P95 计算。 

