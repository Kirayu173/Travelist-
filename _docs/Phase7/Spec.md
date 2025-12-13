## 1. 概述

### 1.1 阶段编号与名称

* 阶段编号：**Stage-7**
* 阶段名称：**行程规划 Fast 模式（规则版）+ LangGraph Planner**

### 1.2 背景

前置阶段已完成：

* Stage-1～3：行程 CRUD、排序/跨天移动、Admin 基础统计与健康检查，具备稳定的行程结构化数据读写能力；
* Stage-4：LLM Provider（`AiClient`）与 mem0 记忆层（`MemoryService`）接入，提供 AI Demo 与 Admin AI 指标；
* Stage-5：LangGraph 智能助手 v1（`/api/ai/chat`），支持意图识别、工具调用、记忆读写、会话持久化；
* Stage-6：POI & 地理服务（`/api/poi/around`）+ Redis 缓存 + `PoiNode` 工具接入，为规划阶段提供可复用的 POI 能力与缓存策略。

按阶段开发规划，Stage-7 的定位是：在 **不依赖 LLM** 的前提下，先落地一个“绝对可控、可复现、可解释”的 **规则规划（`mode=fast`）**，并把规划能力通过统一的 `POST /api/ai/plan` 暴露给前端与后续阶段使用。同时，Stage-7 需要为 Stage-8 的 LLM 深度规划（`mode=deep`）预留清晰边界，避免后续 schema、接口、状态流转混乱。

### 1.3 阶段目标（Stage-7 完成时应达到）

1. **Fast 规则规划可用**
   * 提供 `mode=fast` 的行程规划能力，能在给定目的地与日期范围内生成结构化 Trip（按天/半天组织子行程）；
   * 规划结果稳定、可复现、可解释：同输入在同版本规则下输出保持一致（允许受随机种子控制）。
2. **统一规划 API 与 Schema 稳定**
   * 实现 `POST /api/ai/plan`（至少支持 `mode=fast`），请求/响应结构与设计文档中的 TripSchema 对齐；
   * 为 Stage-8 预留 `mode=deep`、`async=true`、`task_id` 等字段但不在本阶段实现深度规划。
3. **PlannerNode / LangGraph 接入完成（Fast 路径）**
   * 将规划能力作为独立“规划图”或节点集成到现有 LangGraph 体系，形成可追踪的 `tool_traces`/日志；
   * `mode=fast` 时只走规则路径，不触发 LLM 调用。
4. **Admin 规划监控可观测**
   * Admin 侧新增规划统计接口/页面：调用次数、平均天数、失败率、常见目的地等；
   * 便于后续对比 Stage-8 的 deep 模式（成本/延迟/质量）。
5. **质量与文档**
   * 提供覆盖 FastPlanner、规划 API、PlannerNode 的测试；
   * 产出与阶段交付一致的 Spec/Code/Tests/Review 文档骨架（本文件为 Spec）。

---

## 2. 范围说明

### 2.1 本阶段实现范围

本阶段聚焦 **规则规划（fast）** 的端到端落地：

* 规划请求模型与响应模型（TripSchema / PlanSchema）落地为可执行的 Pydantic Schema；
* 规则规划核心：FastPlanner（纯规则）+ 必要的数据获取（POI 查询、行程约束）；
* `POST /api/ai/plan`（`mode=fast`）接口实现：
  * `save=false`：仅返回规划结果，不落库；
  * `save=true`（可选）：将规划结果落库为 trips/day_cards/sub_trips；
* LangGraph 规划节点（PlannerNode）接入 fast 路径；
* Admin 规划 summary（JSON）与 overview（HTML，可选）；
* 基础性能基线：提供 bench 脚本或最小压测/耗时统计口径（用于与 Stage-8 对比）。

### 2.2 非本阶段范围（但需兼容/预留）

以下内容不在 Stage-7 实现，但必须在接口与代码结构上 **显式预留**：

* `mode=deep` 的 LLM 规划实现（Stage-8）；
* 异步任务体系（`ai_tasks` 表、后台任务执行器、任务轮询/WS 推送）；
* 更复杂的个性化（深度偏好建模、多轮澄清、预算/亲子/无障碍等强约束）；
* 前端/Android 的完整 UI 联调与体验优化（可用 Postman/脚本验证即可）。

---

## 3. 总体技术与通用约定

### 3.1 技术栈与依赖

延续现有技术栈：

* FastAPI + Pydantic：规划接口与 Schema；
* PostgreSQL（PostGIS）+ SQLAlchemy：行程落库与 POI 数据；
* Redis：沿用缓存与后续任务/状态预留（本阶段可不强依赖）；
* LangGraph：规划节点/图编排；
* pytest：自动化测试。

### 3.2 配置与环境变量约定

Stage-7 新增/补充建议（具体命名以 `settings.py` 约定为准）：

* `PLAN_DEFAULT_DAY_START`：默认日程开始时间（如 `09:00`）；
* `PLAN_DEFAULT_DAY_END`：默认日程结束时间（如 `18:00`）；
* `PLAN_DEFAULT_SLOT_MINUTES`：每个活动默认时长（如 90min）；
* `PLAN_MAX_DAYS`：最大规划天数上限（防止超大请求）；
* `PLAN_FAST_RANDOM_SEED`：默认随机种子（可被请求覆盖）；
* `PLAN_FAST_POI_LIMIT_PER_DAY`：每天候选 POI 上限；
* `PLAN_FAST_TRANSPORT_MODE`：默认交通方式（walk/drive/transit 等枚举）。

约定：所有规划相关配置均以 `PLAN_*` 命名前缀集中管理，避免与 Stage-8 的 `AI_*`/`LLM_*` 混用。

### 3.3 Graph 状态与节点约定（Planner 相关）

为避免与 Stage-5 助手图混淆，Stage-7 规划建议采用独立的 State：

* `PlannerState`（建议）：`user_id`、`destination`、`start_date`、`end_date`、`preferences`、`mode`、`save`、`result`、`errors`、`metrics`、`trace_id`；
* `PlannerNode`：根据 `mode` 分流（本阶段仅 `fast`），输出标准化 TripSchema；
* `PlannerValidatorNode`：对生成结果做结构校验与基础业务校验（日期连续、天数匹配、活动顺序等）。

约定：规划链路必须输出 `metrics`（如耗时、候选 POI 数、生成活动数），用于 Admin 统计与 Stage-8 对比。

### 3.4 规则规划策略与一致性约定（Fast）

FastPlanner 必须满足以下一致性原则：

1. **确定性**：默认使用固定随机种子；若使用随机打散/抽样，需显式以 `seed` 控制；
2. **可解释性**：规划结果应包含最少的 `meta` 字段（如来源 POI、选择理由/规则命中项）；
3. **约束优先**：先满足硬约束（天数、日期、每日日程时间窗、活动数量上限），再优化软约束（距离、兴趣匹配、评分）；
4. **失败可降级**：POI 不足时可降级为“自由活动/推荐列表”或减少活动数，但不得 500；应返回可读错误信息与可用的部分结果（若允许）。

### 3.5 Stage-8（Deep/LLM）预留与边界（必须遵守）

为防止 Stage-8 引入后接口/代码混乱，本阶段必须提前约束“可变部分”与“稳定部分”：

1) **稳定部分（Stage-7 起即冻结，Stage-8 不应破坏）**

* `POST /api/ai/plan` 的核心请求/响应字段语义（`destination/date_range/mode/save/preferences`）；
* TripSchema 的主结构（trip/day_cards/sub_trips 的层级与关键字段命名）；
* `metrics` 与 `trace_id` 的存在与基本口径（至少包含 planner 名称与耗时）。

2) **可变部分（Stage-8 可以扩展，但需向后兼容）**

* `preferences`：允许添加新字段，但 fast 必须忽略未知字段；
* `plan.meta`/`sub_trips.ext`：允许注入 LLM 解释、置信度、引用来源等；
* `tool_traces`：允许追加 LLM 相关节点与工具调用记录。

3) **Deep 模式的接口预留（Stage-7 必须“占位但不实现”）**

* `mode=deep`：
  * `async=false`：Stage-7 返回明确的“未实现”错误（推荐 400 + 业务码），避免误以为已支持同步 deep；
  * `async=true`：Stage-7 同样返回未实现（或返回占位 task_id 但不落库/不执行，不推荐）。
* `task_id`：仅 Stage-8 引入异步任务后才会返回；Stage-7 不应生成虚假的 task_id。

4) **实现结构预留（建议接口/类边界）**

* `PlannerService`（建议）：统一入口 `plan(request) -> (plan_result, meta)`，内部按 `mode` 分发；
* `FastPlanner`：纯规则，无 LLM 依赖；
* `DeepPlanner`（Stage-8 实现）：允许依赖 `AiClient`/工具调用，但必须输出同一 TripSchema，并通过同一 Validator；
* `PlanValidator`：对 fast/deep 的输出做统一校验（结构 + 业务约束），避免 deep 输出污染 DB。

---

## 4. 详细功能与实现要求

### 4.1 任务 T7-1：规划 Schema 与接口契约（PlanRequest/PlanResult）

**目标**：统一 `POST /api/ai/plan` 的请求/响应结构，稳定到 Stage-8 仍可复用。

1) 请求（`PlanRequest`）建议字段

* `user_id`：必填；
* `destination`：必填；
* `start_date`、`end_date`：必填；
* `mode`：`fast|deep`（本阶段仅实现 `fast`，但字段必须存在）；
* `save`：`true|false`（本阶段建议实现 `false`，`true` 可选）；
* `preferences`：JSON（如 `interests[]`、`pace`、`budget_level` 等，fast 只消费少量字段）；
* `people_count`（可选）：人数；
* `seed`（可选）：规则规划随机种子；
* `async`（预留）：`true|false`（Stage-8 用于 deep 异步任务）；
* `request_id`（预留）：幂等/追踪 ID；
* `seed_mode`（预留）：`fast`（Stage-8 deep 可用 fast 作为草案种子）。

2) 响应（`PlanResponse`）建议结构

* 同一接口返回两种形态（由 `mode`/`async` 决定）：
  * **同步结果**：`data.plan` 为 TripSchema；
  * **异步占位**：`data.task_id`（Stage-8 使用），本阶段返回 501 或明确错误码；
* 统一返回 `metrics`（规划耗时、生成活动数等）与 `trace_id`。

3) 错误码约定

* 参数错误：400 + 业务码（例如 `14070`）；
* 不支持的模式：400/501（建议 400 更符合“客户端可修正”）；
* 规划失败：200 但 `code!=0` 或 422/500（二选一，需与项目现有 `success_response/error_response` 约定一致）。

### 4.2 任务 T7-2：FastPlanner（规则规划核心）

**目标**：实现一个不依赖 LLM 的可复现规划器。

1) 输入校验

* 日期范围合法，`end_date >= start_date`；
* 天数上限（`PLAN_MAX_DAYS`）；
* 目的地不能为空，长度限制；
* `preferences.interests` 为空时给默认兴趣（如 `["sight", "food"]`）。

2) 候选 POI 获取策略（复用 Stage-6）

* 基于目的地（城市）+ 兴趣类型生成候选集合：
  * 优先从本地 `pois` 表筛选 `city=destination`（如无该字段则使用 `ext.city`/模糊匹配，具体以现有表字段为准）；
  * 必要时调用 `PoiService` 的 around 查询（若已有用户定位则更佳，否则使用目的地中心点的近似坐标或“城市中心”策略）；
* 候选 POI 需去重（provider/provider_id）；
* 记录候选数量与来源（db/cache/api）到 `metrics`。

3) 日程生成规则（建议最小可行集）

* 按天生成 `day_count` 天的 `day_cards`；
* 每天划分为上/下午（半天 slot），每个 slot 1～2 个活动（可配置）；
* 活动选择排序权重（示例，可调整）：
  * 兴趣匹配优先；
  * 距离近优先（若具备坐标/距离）；
  * 评分高优先；
  * 避免同类活动连续（多样性）；
* 交通方式：默认值写入 `sub_trips.transport`（或 ext 字段），为 Stage-8/地图联动预留。

4) 输出结构化 Trip（对齐 TripSchema）

* 输出必须包含：trip 基本信息、day_cards 列表、sub_trips 列表（含顺序 order_index）；
* 每个 sub_trip 必须包含最少字段（activity/loc_name/时间或时长信息），不足字段放入 `ext`；
* 允许返回“推荐列表”形式的 sub_trip（activity=“自由探索”）作为降级。

### 4.3 任务 T7-3：`POST /api/ai/plan`（Fast 同步接口）

**目标**：对外提供统一规划入口，屏蔽内部实现细节。

* 路由：`POST /api/ai/plan`
* 行为：
  * `mode=fast`：
    * `save=false`：返回 TripSchema（不写库）；
    * `save=true`：将结果转换为 ORM 并落库（可选实现）；
  * `mode=deep`：
    * 本阶段不实现：返回明确错误提示，并保留字段以便 Stage-8 无痛切换。
* 返回：
  * `plan`：TripSchema；
  * `metrics`：planner 名称、耗时、候选 POI 数、生成活动数；
  * `trace_id`：用于日志与排查。

### 4.4 任务 T7-4：LangGraph PlannerNode 接入（Fast 路径）

**目标**：规划也纳入图编排，支持统一追踪与后续扩展。

* 规划图建议最小节点：
  * `plan_input`（组装 state）→ `planner_fast`（规则规划）→ `plan_validate`（结构/约束校验）→ `plan_output`；
* 在 `planner_fast` 中不得触发 `AiClient` 调用；
* 规划链路的 `tool_traces`/日志记录统一字段：`node`、`status`、`latency_ms`、`detail`。

### 4.5 任务 T7-5：Admin 规划监控（Plan Summary）

**目标**：为 fast/deep 对比实验提供可观测数据。

1) JSON 接口：`GET /admin/plan/summary`

* 指标建议：
  * `plan_fast_calls`、`plan_fast_failures`；
  * `plan_fast_avg_days`；
  * `plan_fast_latency_ms_p50/p95`（可先只做 mean/p95）；
  * `top_destinations`（可选，简单 topN）。

2) HTML 页面（可选）：`/admin/plan/overview`

* 展示 summary 指标与最近 N 次规划记录（若本阶段不落库，可只展示聚合指标）。

3) 统计存储策略（建议）

* 本阶段可先采用进程内计数器（与 Stage-6 POI 类似）；
* 预留 Stage-8/9 的集中化方案：写入 Redis 或数据库表（但不在本阶段强制实现）。

---

## 5. 阶段 7 整体验收标准

当满足以下条件时，Stage-7 视为完成：

1. **Fast 规划可用**
   * `POST /api/ai/plan` 在 `mode=fast` 下返回结构化 Trip，天数与输入日期范围一致；
   * 在 POI 数据不足时可降级返回，但不出现 500。
2. **Schema 与预留字段清晰**
   * 请求/响应中包含 `mode`，并为 `deep/async/task_id/request_id/seed_mode` 预留清晰语义；
   * `mode=deep` 在本阶段返回明确的“不支持/未实现”响应，不产生模糊行为。
3. **LangGraph 接入**
   * 规划链路具备可追踪的节点记录（日志或 `tool_traces`），可用于后续论文复现实验。
4. **Admin 可观测**
   * `/admin/plan/summary` 可返回 fast 规划关键指标；
   * 指标口径与代码一致，可用于 Stage-8 对比。
5. **质量**
   * pytest 覆盖 FastPlanner + API（至少基本 happy path 与参数校验）；
   * `ruff`/`black`/`pytest` 在项目约定下通过（如项目已启用）。
