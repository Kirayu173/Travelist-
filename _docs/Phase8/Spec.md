## 1. 概述

### 1.1 阶段编号与名称

* 阶段编号：**Stage-8**
* 阶段名称：**行程规划 Deep 模式 + 异步任务（ai_tasks）**

### 1.2 背景

前置阶段已完成：

* Stage-1～3：行程 CRUD、排序/跨天移动、Admin 基础统计与健康检查；
* Stage-4：LLM Provider（`AiClient`）与 mem0 记忆层（`MemoryService`）接入；
* Stage-5：LangGraph 智能助手 v1（`/api/ai/chat`），支持意图识别、工具调用、记忆读写、会话持久化；
* Stage-6：POI & 地理服务（`/api/poi/around`）+ Redis 缓存 + `PoiNode` 工具接入；
* Stage-7：统一规划入口 `POST /api/ai/plan` + 规则规划 `mode=fast` 落地（可复现/可解释/可降级），并为 `mode=deep`、`async/task_id/request_id/seed_mode` 预留清晰边界。

按阶段开发规划，Stage-8 的定位是：在 Stage-7 规则规划的“可靠底座”之上，引入 **LLM 深度规划（`mode=deep`）**，并通过 **异步任务体系（`ai_tasks`）** 控制成本与延迟。同时，为降低“LLM 输出不规范/截断/字段缺失”的风险，Stage-8 的 deep 规划采用 **按天多轮生成**：LLM 每轮只输出“当天 itinerary JSON”，由后端聚合为最终 Trip，并补齐 **全局骨架 + 上下文摘要 + 全局校验** 的最小闭环（保持本科毕设可实现的复杂度）。

### 1.3 阶段目标（Stage-8 完成时应达到）

1. **Deep 规划可用且结构稳定（按天多轮）**
   * `POST /api/ai/plan` 在 `mode=deep` 下可生成结构化 Trip（对齐 Stage-7 的 TripSchema/PlanTripSchema）；
   * deep 的 LLM 生成按天进行：每轮仅输出“当前一天的 day_card/sub_trips JSON”，由后端聚合为最终 Trip；
   * 每天输出先做 schema 校验 + 业务校验，聚合后再做一次全局校验；失败时明确报错或回退（不出现模糊行为/不出现 500）。
2. **异步任务体系落地（ai_tasks）**
   * `mode=deep` 支持 `async=true`：快速返回 `task_id`，后台执行并持续更新任务状态；
   * 提供任务查询接口（轮询获取状态/结果），并具备幂等能力（`request_id`）。
3. **LangGraph Deep 路径接入 + 可追踪性**
   * 扩展规划图/节点：支持 deep 节点（LLM 调用、校验、回退），输出统一的 `tool_traces` 与 `trace_id`；
   * 记录 deep 规划关键指标（LLM 耗时、tokens/成本估算、重试次数、是否回退 fast）。
4. **Admin 可观测（Tasks + Deep 指标）**
   * 新增 Admin 任务监控（`/admin/ai/tasks` 或 summary/overview），展示任务状态分布、失败原因聚合、耗时与成本口径；
   * 扩展规划指标（fast vs deep 对比），为论文实验提供数据。
5. **个性化与实验复现最小闭环**
   * deep 规划可读取 mem0 的用户偏好（如兴趣/节奏/预算倾向）并体现在结果中；
   * 产出至少一组“fast vs deep”的可复现实验样例（输入、输出、trace、指标）。

---

## 2. 范围说明

### 2.1 本阶段实现范围

本阶段聚焦 **deep 规划能力 + 异步任务** 的端到端落地，具体包括：

* `mode=deep` 的规划器实现（DeepPlanner）：全局骨架（outline）+ 按天多轮 LLM 生成 + 上下文摘要 +（每天/全局）结构化校验 + 回退策略；
* `ai_tasks` 表、ORM 与 migration：持久化请求、状态、结果与关键指标；
* `POST /api/ai/plan` 扩展：支持 deep 同步/异步；维持 Stage-7 的 fast 行为不变；
* 任务查询接口：按 `task_id` 获取状态与结果（轮询）；
* LangGraph Planner 图扩展：deep 节点接入并输出统一 `tool_traces`；
* Admin 监控：任务状态与 deep 指标（含 tokens/耗时/失败原因）；
* 测试与质量：为 deep/async/ai_tasks 编写可跑通的测试（LLM 相关必须可 mock）。

### 2.2 非本阶段范围（但需兼容/预留）

以下内容不在 Stage-8 强制实现范围，但在接口/结构上需 **兼容或预留**：

* WebSocket 推送任务完成事件（Stage-9）：本阶段以轮询接口为主；
* 分布式 worker/队列（Celery/RQ/Arq 的生产化集群）：本阶段可用“进程内队列 + 后台 worker”最小落地；
* deep 规划的流式输出（边生成边返回）：本阶段不要求；
* 强约束/多轮澄清（预算、亲子、无障碍、开放时间等复杂规则）：本阶段以“最小可用偏好注入 + 校验”优先；
* 前端/Android UI 全量联调：可用 Admin 测试台/脚本验证即可。

---

## 3. 总体技术与通用约定

### 3.1 技术栈与依赖

延续现有技术栈并补齐 deep 所需能力：

* FastAPI + Pydantic：规划接口与 Schema；
* PostgreSQL（PostGIS）+ SQLAlchemy：行程落库、ai_tasks 持久化、POI 数据；
* Redis（可选增强）：任务幂等/限流/队列/短期状态缓存（本阶段允许先仅 DB + 进程内队列）；
* LangGraph：规划节点/图编排（fast/deep 统一输出 `tool_traces`）；
* AiClient：LLM 调用统一封装（超时/重试/trace_id）；
* mem0：偏好读取与结果摘要写入；
* pytest：自动化测试（LLM 路径必须可 mock）。

### 3.2 配置与环境变量约定

Stage-8 建议新增/补充配置（具体命名以 `settings.py` 为准；仍以 `PLAN_*` 为主前缀）：

1) Deep 规划与 LLM

* `PLAN_DEEP_MODEL`：deep 规划使用的模型名；
* `PLAN_DEEP_TEMPERATURE`：生成温度（建议偏低，优先结构稳定）；
* `PLAN_DEEP_MAX_TOKENS`：输出 token 上限；
* `PLAN_DEEP_TIMEOUT_S`：单次 LLM 调用超时；
* `PLAN_DEEP_RETRIES`：结构不合规/超时的重试次数（建议 0～2）；
* `PLAN_DEEP_PROMPT_VERSION`：提示词版本号（写入 metrics/tool_traces，便于复现实验）。

2) Deep 输入裁剪与成本控制

* `PLAN_DEEP_MAX_POIS`：传入 LLM 的候选 POI 上限（避免 prompt 过大）；
* `PLAN_DEEP_MAX_DAYS`：deep 最大支持天数（可复用 `PLAN_MAX_DAYS`，或另设更小上限）；
* `PLAN_DEEP_FALLBACK_TO_FAST`：deep 失败是否回退 fast（建议默认 true）。

2.1) 按天生成与上下文摘要（推荐）

* `PLAN_DEEP_DAY_MAX_TOKENS`：单天输出 token 上限（若不单独配置，可复用 `PLAN_DEEP_MAX_TOKENS`）；
* `PLAN_DEEP_CONTEXT_MAX_DAYS`：上下文摘要最多携带前 N 天游记摘要（建议 2～5，避免 prompt 膨胀）；
* `PLAN_DEEP_CONTEXT_MAX_CHARS`：上下文摘要字符上限（避免把“前几天完整 JSON”塞进 prompt）；
* `PLAN_DEEP_OUTLINE_SOURCE`：全局骨架来源（建议 `fast`；可选 `llm_outline`，但本阶段不强制）。

3) 异步任务与 worker

* `PLAN_TASK_WORKER_CONCURRENCY`：后台并发数；
* `PLAN_TASK_QUEUE_MAXSIZE`：进程内队列长度（防止内存爆）；
* `PLAN_TASK_MAX_RUNNING_PER_USER`：单用户并发任务上限（成本控制）；
* `PLAN_TASK_RETENTION_DAYS`：任务结果保留天数（清理策略可后续实现）。

4) 地理中心点与 POI 数据质量（建议开启）

* `GEOCODE_PROVIDER`：建议 `amap`（可回退 `mock/disabled`），用于目的地中心点解析，提升 POI 候选质量；
* `AMAP_API_KEY`（或项目中等价的高德 Key 配置）：用于 geocode/reverse geocode；
* POI 数据建议补齐 `ext.city/ext.province/ext.district` 等字段（可用 `scripts/enrich_reverse_geocode.py` 对 CSV 做离线补全，再导入数据库）。

约定：**不**在 `PLAN_*` 中混入 `LLM_*` 或 `AI_*` 的同义配置，避免 Stage-4/5 的聊天配置与规划配置相互污染。

### 3.3 Graph 状态与节点约定（Planner 相关）

Stage-8 延续 Stage-7 的 `PlannerState` 与“规划图”思路，并扩展 deep 节点：

* `PlannerState`（建议）：`user_id`、`destination`、`start_date`、`end_date`、`preferences`、`mode`、`save`、`async`、`request_id`、`seed_mode`、`trace_id`、`tool_traces`、`metrics`、`result`、`errors`；
* `PlannerNode`：按 `mode` 分流：
  * `fast`：规则规划（不触发 LLM）；
  * `deep`：LLM 深度规划（按天多轮；可含 fast 草案种子作为全局骨架）。
* `PlannerValidatorNode`：对输出做统一校验（结构 + 业务约束），建议分为“单日校验 + 全局校验”，并提供可控的修复/回退。

约定：deep 链路必须输出 `metrics`（至少包含：LLM 耗时、tokens、是否回退、重试次数）与 `tool_traces`（节点级耗时与状态），便于 Admin 对比与论文复现。

### 3.4 Deep 规划策略与一致性约定（LLM，按天多轮生成）

DeepPlanner 的目标不是“更聪明就行”，而是 **在可控结构输出的前提下提升质量，并显著降低输出不规范风险**：

1) 输出一致性（必须满足）

* deep 的最终输出必须能解析为 `PlanTripSchema`（或同结构 TripSchema）；
* deep 的 LLM 每轮输出必须能解析为“**单日结构**”（建议复用 `PlanDayCardSchema` 或等价 schema，仅包含当天 `date/day_index/sub_trips[]`）；
* 必须满足：天数/日期连续、`day_cards.day_index` 唯一且连续、`sub_trips.order_index` 唯一且从 0/1 起连续（以项目约定为准）；
* 不得引入不可复现的动态字段（如 `generated_at`），仅允许在 `meta/ext` 中写入 `prompt_version/seed_mode/llm_provider_response_id` 等可控字段。

2) 推荐的生成策略（建议最小可行集）

* **全局骨架（outline）**：
  * 默认复用 fast 草案作为骨架（`seed_mode=fast`）：保证天数/日期/半天节奏等硬约束稳定；
  * 允许对 fast 草案抽取“骨架摘要”（例如：每天主题/活动类型配比/已使用 POI 列表），用于后续每一天的生成约束。
* **按天多轮生成（核心）**：对 `day_index=0..day_count-1` 循环：
  * 输入 Prompt 必须包含：
    * Trip 基本信息（destination/date_range/preferences）；
    * 全局骨架（outline）；
    * **上下文摘要**：仅包含“已确认的前 N 天游记摘要”（活动标题 + 关键 POI 标识），禁止传入前几天完整 JSON；
    * 当天候选 POI（裁剪后）与“已用 POI 集合”（用于去重）。
  * LLM 只输出：**当前一天的 itinerary JSON**（day_card/sub_trips），不得输出其他文字。
  * 每轮输出先通过“单日校验器”（结构 + 基本约束 + 去重），失败时只重试当天（成本可控）。
* **聚合 + 全局校验（必须）**：
  * 外部程序负责把每天的 day_card 聚合为最终 Trip；
  * 聚合后使用统一 `PlanValidator` 做全局校验（日期连续、计数一致、跨天去重等），失败时：
    * 优先定位到某一天进行局部重试/修复；
    * 仍失败时按配置回退到 fast 草案（并在 metrics 标记 `fallback=true`）。

3) 提示词约束（必须明确）

* 强制要求 LLM **只输出 JSON**（无 Markdown、无解释性文字）；
* 明确约束字段名、类型与时间窗规则（避免自由发挥）；
* 对候选 POI 的引用必须可追踪（例如写入 `sub_trips.ext.poi.provider/provider_id`）。

4) 上下文摘要策略（必须简单可实现）

* 上下文摘要应是“短 JSON 或短文本列表”，建议包含：
  * `day_index/date`；
  * `highlights[]`（每条包含 activity 标题 + poi 标识）；
  * `used_pois[]`（provider/provider_id 列表，用于跨天去重）。
* 摘要长度必须受 `PLAN_DEEP_CONTEXT_MAX_DAYS/CHARS` 控制；当 day_count 很大时，仅保留最近 N 天摘要即可。

### 3.5 异步任务（ai_tasks）约定与边界（必须遵守）

1) 状态机与语义

* 任务状态建议：`queued → running → succeeded|failed|canceled`（与现有 `PlanTaskSchema` 对齐）。
  * 允许与设计文档中的 `pending/done` 做同义映射，但对外 API 口径应统一。

2) 幂等与重复提交

* `request_id` 用于 deep 规划的幂等：
  * 同一 `user_id + request_id` 的 deep 请求重复提交，应返回同一个 `task_id`（或同一个最终结果）；
  * 若同 `request_id` 但 payload 不一致，应返回明确错误（避免“幂等键污染”）。

3) 事务边界

* 创建任务：短事务写入 `ai_tasks`（status=queued）；
* 执行任务：worker 更新 `running` → 写回 `result/metrics/tool_traces` 并更新 `finished_at`；
* 规划结果落库（`save=true`）必须使用短事务，避免占用长锁；任务执行期间不应持有 DB 事务跨越 LLM 调用。

4) 成本与安全

* deep 必须有并发上限（至少单用户限流）；当触发限流时返回明确错误码；
* 任务结果中不应存储敏感信息（API Key、完整 prompt、用户隐私原文），必要时仅存摘要/哈希。

---

## 4. 详细功能与实现要求

### 4.1 任务 T8-1：`ai_tasks` 表与任务模型（ORM/Migration）

**目标**：落地异步任务的持久化底座，供 deep 规划异步执行与 Admin 观测。

1) 表结构（对齐数据库设计文档，可按工程需要补充）

* 表：`ai_tasks`
* 建议字段：
  * `id`：主键（可 BIGSERIAL）；
  * `user_id`：任务归属用户；
  * `kind`：`plan:deep`（预留未来扩展）；
  * `payload`：请求参数（PlanRequest 的安全子集）；
  * `status`：`queued/running/succeeded/failed/canceled`；
  * `result`：结构化结果（建议存 `PlanResponseData` 的 data 部分或其子集）；
  * `created_at/updated_at/finished_at`：时间戳（便于统计/清理）；
  * （可选）`error`：失败原因结构化字段（亦可放入 `result`）。
* 索引建议：`(user_id)`、`(status)`、`(created_at)`；若使用 `request_id` 幂等，可加 `(user_id, request_id)` 唯一或普通索引。

2) ORM 与迁移

* 增加 SQLAlchemy ORM 模型（与现有 `backend/app/models/orm.py` 风格一致）；
* 增加 Alembic migration（命名建议包含 stage8/ai_tasks 语义）；
* 迁移需支持 sqlite（测试）与 postgresql（生产）两种方言的最小兼容。

### 4.2 任务 T8-2：DeepPlanner（LLM 深度规划核心）

**目标**：实现可控的 deep 规划器：按天多轮生成、降低输出不规范风险，且保持本科毕设可实现的复杂度。

1) 输入

* `PlanRequest`：
  * 必须支持 `mode=deep`；
  * `seed_mode=fast` 时先生成 fast 草案（作为全局骨架/seed）；
  * `preferences` 合并 mem0 的用户偏好（见 T8-7）。

2) 规划流程（按天多轮，建议最小可行集）

* Step A：构建全局骨架（outline）
  * 直接复用 fast 草案，或抽取 fast 草案的“骨架摘要”（天数/日期/节奏/已用 POI 列表）。
  * 本阶段不强制做“LLM 生成全局 outline”，以降低实现复杂度；如需，建议作为可选开关（`PLAN_DEEP_OUTLINE_SOURCE=llm_outline`）。
* Step B：按天循环生成（核心）
  * 对 `day_index=0..day_count-1`：
    * 由程序构造 Prompt：Trip 基本信息 + outline + 上下文摘要（最近 N 天）+ 当天候选 POI；
    * 通过 `AiClient` 调用 LLM；
    * LLM **只输出当前一天 JSON**（建议复用 `PlanDayCardSchema`）；
    * 每天输出立刻做：
      * schema 解析（Pydantic）；
      * 单日业务校验（时间窗、order_index 连续、POI 去重等）。
* Step C：聚合与全局校验（必须）
  * 程序将每天输出聚合为最终 `PlanTripSchema`（补齐 `day_count/sub_trip_count` 等派生字段）；
  * 使用统一 `PlanValidator` 做全局校验（日期连续、跨天去重、计数一致等）。
* Step D：失败处理（必须可控）
  * 单日失败：仅重试当天（`PLAN_DEEP_RETRIES`，建议 0～2）；
  * 全局校验失败：优先定位到某一天做局部重试/修复；
  * 超时/异常：记录错误并按 `PLAN_DEEP_FALLBACK_TO_FAST` 决定回退或失败。

3) 质量最小增益（建议）

* 在 fast 草案基础上提升：
  * 活动类型更贴近兴趣（interests）；
  * 同类活动去重与更好的多样性；
  * 将候选 POI 的地址/评分等信息写入 `sub_trips.ext`（可用于前端展示）；
* 不以“更长更复杂”为目标：优先保证结构正确与可执行性。

4) POI 候选与目的地匹配（建议）

* deep 使用 POI 候选时应优先基于“目的地城市”过滤/排序（例如 `pois.ext.city` 或 `ext.amap.city`），避免目的地中心点不准导致的跨城候选；
* 若当前 POI 数据缺少可用的 city 字段，建议先跑离线补全脚本并回填数据，再评估 deep 质量提升幅度。

5) 指标与 trace

* `metrics` 至少包含：
  * `planner`（如 `deep_llm_v1`）、`prompt_version`；
  * `llm_latency_ms`、`llm_tokens_prompt/llm_tokens_completion/llm_tokens_total`；
  * `llm_calls`（按天调用次数）、`llm_retries`、`fallback_to_fast`；
  * `latency_ms`（端到端总耗时）。
* `tool_traces` 至少包含：
  * `planner_seed_fast`（若启用）；
  * `planner_deep_day`（建议记录 day_index）；
  * `plan_validate`；
  * `plan_validate_global`；
  * `plan_output`。

### 4.3 任务 T8-3：`POST /api/ai/plan`（Deep 同步/异步接口）

**目标**：在不破坏 Stage-7 fast 行为的前提下，扩展 deep 的同步与异步路径。

1) 行为矩阵（建议）

* `mode=fast`：保持 Stage-7 行为不变
  * `async` 字段忽略（或显式返回 `async=false`）。
* `mode=deep`：
  * `async=false`：同步执行 deep 并返回 `plan`；
  * `async=true`：创建任务并立即返回 `task_id`，`plan` 为空。

2) 返回结构（对齐 `PlanResponseData`）

* 同步返回：`data.plan` 非空，`data.task_id` 为空；
* 异步返回：`data.task_id` 非空，`data.plan` 为空；`data.trace_id` 必须存在（用于排障与 Admin 关联）。

3) 错误码建议（可按项目现有约定调整）

* `mode` 不支持/参数错误：`14080`～`14089`；
* 幂等冲突（同 request_id 不同 payload）：`14086`；
* 并发/配额限制：`14087`；
* deep 规划失败（且不回退）：`14089`。

### 4.4 任务 T8-4：任务查询接口（轮询）与状态流转

**目标**：提供从 `task_id` 获取状态/结果的最小闭环，为前端与 Admin 使用。

1) 任务查询接口（建议）

* `GET /api/ai/plan/tasks/{task_id}`
  * 返回 `PlanTaskSchema`（或同等结构）：`status/result/error/created_at/updated_at`；
  * 必须做用户隔离：仅允许任务所属用户读取（或在 Admin 下可读）。

2) 状态流转（必须一致）

* `queued`：任务已创建等待执行；
* `running`：worker 已开始执行（LLM 调用前后都可能处于该状态）；
* `succeeded`：`result` 非空（若 `save=true`，结果应包含落库后的 IDs）；
* `failed`：`error`/失败信息可排障（但不泄露敏感数据）；
* `canceled`：可选（若本阶段不做取消，先预留但不暴露接口）。

### 4.5 任务 T8-5：后台任务执行器（Worker）最小落地

**目标**：实现一个最小可用的 deep 异步执行器，可在单进程部署下稳定工作。

1) 执行模型（建议最小方案）

* 进程内队列（`asyncio.Queue`）+ 后台 worker 协程；
* worker 并发由 `PLAN_TASK_WORKER_CONCURRENCY` 控制；
* 入队前做限流（`PLAN_TASK_MAX_RUNNING_PER_USER`），避免成本失控。
* 执行逻辑上应与 DeepPlanner 一致：**按天多轮调用 LLM → 聚合 → 全局校验**；LLM 调用期间不得持有 DB 事务。

2) 崩溃恢复（建议）

* 服务重启后可扫描 `ai_tasks` 中 `queued/running` 的任务：
  * `queued`：可重新入队；
  * `running`：标记为 `failed`（error=worker_restart）或重新入队（二选一，需明确口径）。

3) 结果写回

* deep 规划成功：写 `result`（含 plan/metrics/tool_traces/trace_id）并置 `succeeded`；
* deep 规划失败：写 `error` 并置 `failed`；
* （可选，建议）按天生成过程中可增量写入 `result.progress`（如 `current_day_index/day_count`），便于轮询接口与 Admin 观察进度；
* 任何写回必须短事务完成。

### 4.6 任务 T8-6：Admin 任务与规划监控（Tasks + Deep 指标）

**目标**：让 deep 能被观测、可对比、可排障。

1) 任务监控（建议最小集）

* `GET /admin/ai/tasks`（或 `GET /admin/ai/tasks/summary`）：
  * `queued/running/succeeded/failed` 数量；
  * 平均耗时、p95；
  * 常见失败原因 topN；
  * 最近 N 条任务（含 trace_id/task_id/request_id）。

2) 规划对比指标（扩展现有 `/admin/plan/summary`）

* 增加 deep 指标（与 fast 同口径）：
  * `plan_deep_calls/failures/failure_rate`；
  * `plan_deep_latency_ms_mean/p95`；
  * `plan_deep_llm_tokens_total`（可按时间窗口聚合）；
  * `plan_deep_fallback_rate`（回退 fast 的比例）。

### 4.7 任务 T8-7：个性化（mem0）与“fast vs deep”实验闭环

**目标**：让 deep 能体现偏好，并形成可复现实验数据。

1) 读取偏好（建议）

* deep 执行前从 mem0 读取用户偏好（user level），合并到 `PlanRequest.preferences`：
  * `interests[]`、`pace`、`budget_level` 等；
  * 合并策略：显式请求 > mem0 > 默认值。

2) 写入摘要（建议）

* deep 成功后，将“本次规划摘要（目的地/天数/偏好/关键点）”写入 mem0（便于下一次规划个性化与论文记录）。

3) 实验样例（必须交付）

* 固定一组输入（destination + 日期 + interests/pace），输出：
  * fast 结果；
  * deep 结果；
  * 两者的 metrics/tool_traces/trace_id；
* 形成可复现对比（用于论文实验章节）。

---

## 5. 阶段 8 整体验收标准

当满足以下条件时，Stage-8 视为完成：

1. **Deep 规划可用且结构合规**
   * `POST /api/ai/plan` 在 `mode=deep, async=false` 下返回结构化 Trip，且通过统一校验；
   * deep 采用按天多轮生成：每轮只生成当天 JSON，由后端聚合，并具备“全局骨架 + 上下文摘要 + 全局校验”的最小闭环；
   * deep 失败时：要么返回明确错误，要么按配置回退 fast，并在 `metrics` 明确标记（不出现 500/不出现模糊成功）。
2. **异步任务闭环可用**
   * `POST /api/ai/plan` 在 `mode=deep, async=true` 下返回 `task_id`；
   * `GET /api/ai/plan/tasks/{task_id}` 可查询状态并在成功时获取结果；
   * 支持 `request_id` 幂等（重复提交不生成多份任务）。
3. **Schema 与接口向后兼容**
   * fast 行为与 Stage-7 保持一致；
   * deep 仅在 `meta/ext/metrics/tool_traces` 扩展，不破坏 TripSchema 主结构。
4. **可观测与对比**
   * Admin 能看到任务状态分布与失败原因聚合；
   * `/admin/plan/summary`（或同等）包含 fast vs deep 的对比指标（至少调用次数、失败率、p95、tokens 口径）。
5. **质量**
   * pytest 覆盖：deep（mock LLM）同步路径、异步 task 状态流转、幂等冲突与限流边界、ai_tasks migration/ORM；
   * `ruff`/`black`/`pytest` 在项目约定下通过（如项目已启用）。
