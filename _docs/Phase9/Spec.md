## 1. 概述

### 1.1 阶段编号与名称

* 阶段编号：**Stage-9**
* 阶段名称：**行程助手多轮对话（REST + WebSocket）+ 会话持久化 + 在线监控**

### 1.2 背景

前置阶段已完成：

* Stage-4：LLM Provider（`AiClient`）与 mem0 记忆层（`MemoryService`）接入；
* Stage-5：LangGraph 智能助手 v1（`POST /api/ai/chat`），支持会话持久化（`chat_sessions/messages`）与 SSE 流式输出；
* Stage-6：POI & 地理服务（`/api/poi/around`）+ 缓存 + `PoiNode` 工具接入；
* Stage-7/8：统一规划入口 `POST /api/ai/plan`（fast/deep）与 deep 异步任务（`ai_tasks`）闭环。

目前助手链路虽然具备“多轮”语义（`session_id` + `messages` 持久化），但仍主要以 **REST 请求**为主，且流式输出采用 SSE。按总体设计与阶段开发规划，Stage-9 需要把助手升级为真正的“持续对话形态”：

* 引入 **WebSocket**：支持更自然的流式回复、低开销的多轮交互；
* 完善 **会话与消息持久化**：WebSocket 对话同样落库可追踪；
* 提供 **Admin 在线监控**：实时观察在线连接数、活跃会话列表、常见错误；
* 同时对现有“行程助手智能体”进行工程化优化：去除冗余、理清模块边界、提升性能与可维护性，避免 Stage-10/11 前端联调阶段出现混乱。

### 1.3 阶段目标（Stage-9 完成时应达到）

1. **WebSocket 多轮对话可用**
   * 提供 `WS /ws/assistant?user_id&session_id`，支持客户端持续连接；
   * 支持流式输出（token/分片），并在连接断开时安全收敛（取消执行、释放资源）。
2. **会话持久化闭环**
   * WebSocket 对话写入 `chat_sessions/messages`；
   * 语义记忆（mem0）写入策略明确（例如每轮结束写入摘要/关键偏好）。
3. **与现有 REST 行为兼容**
   * `POST /api/ai/chat`（含 SSE 流式）保持可用且语义不变；
   * WebSocket 与 REST 使用同一套核心 `AssistantService`/LangGraph 节点能力（避免双实现漂移）。
4. **Admin 实时可观测**
   * 提供 `/admin/chat/live`（页面）与对应数据接口：在线连接数、活跃会话列表、最近消息/错误摘要；
   * 指标口径稳定，可用于演示与排障。
5. **智能体全方位优化（去冗余/结构/性能）**
   * 消除重复的 streaming/序列化/会话读写逻辑；
   * 优化关键路径（历史加载、DB 写入、工具调用开销）；
   * 将“关键业务推理”从 LLM 中剥离为 deterministic（例如相对日期、地点抽取、工具参数校验），并将生成式能力收敛到单一节点（Answer Composer），提升稳定性；
   * 引入必要的限流、背压与资源上限，避免 WS 场景下“慢客户端/高并发”拖垮服务。

---

## 2. 范围说明

### 2.1 本阶段实现范围

* 新增 WebSocket 助手入口：`/ws/assistant`；
* 设计并实现 WebSocket 消息协议（收发事件类型、序列号、错误模型、DONE 语义）；
* 将 WebSocket 与现有 LangGraph 助手能力打通，实现端到端流式输出；
* WebSocket 对话的 `chat_sessions/messages` 落库闭环；
* 在线连接管理（内存/Redis 任选其一作为最小可行实现）；
* Admin 在线监控页面 `/admin/chat/live` 与统计接口；
* 对智能体与相关模块进行结构重构与性能优化（详见 4.6）。

### 2.2 非本阶段范围（但需兼容/预留）

* Android/前端完整 UI 联调与体验优化（Stage-10/11 处理）；
* WebSocket 上的 deep 规划任务事件推送（可预留事件类型，但不强制在本阶段闭环）；
* 分布式部署下的跨进程 WS 会话一致性（本阶段可用单进程/单实例方案，需预留扩展点）；
* 长期归档/分区（messages/ai_tasks）的大规模运维方案（可在文档中提出建议与开关）。

---

## 3. 总体技术与通用约定

### 3.1 技术栈与依赖

延续现有技术栈：

* FastAPI（ASGI）+ WebSocket：WS 连接与消息收发；
* LangGraph：助手编排与工具调用链路；
* PostgreSQL + SQLAlchemy：`chat_sessions/messages` 持久化；
* Redis（可选）：在线会话与短期消息缓存、连接元数据（`session:ws:{session_id}`）；
* pytest + httpx：自动化测试（含 WebSocket 客户端）。

### 3.2 配置与环境变量约定

建议新增（命名遵循集中前缀，避免与规划/LLM 混用）：

* `ASSISTANT_WS_ENABLED`：是否启用 WS 路由；
* `ASSISTANT_WS_MAX_CONNECTIONS_PER_USER`：单用户 WS 连接上限；
* `ASSISTANT_WS_IDLE_TIMEOUT_S`：连接空闲超时（心跳缺失/长期无消息）；
* `ASSISTANT_WS_SEND_QUEUE_MAXSIZE`：发送队列上限（背压，防止慢客户端耗尽内存）；
* `ASSISTANT_WS_MAX_MESSAGE_CHARS`：单条输入最大长度；
* `ASSISTANT_WS_RATE_LIMIT_PER_MIN`：WS 消息速率限制（可先内存实现）；
* `ASSISTANT_HISTORY_MAX_ROUNDS`：WS 侧默认历史轮数（与 `ai_assistant_max_history_rounds` 对齐或复用）。

约定：WS 配置使用 `ASSISTANT_WS_*` 前缀；助手通用配置使用 `AI_ASSISTANT_*`；避免与 `PLAN_*`（规划）混用。

### 3.3 Graph 状态与节点约定（Assistant 相关）

Stage-9 不新增新的“业务能力节点”，重点在“对话通道/会话管理/性能”：

* `AssistantState` 继续作为 LangGraph 状态载体；
* WebSocket 入口仅负责：
  * 解析/校验客户端消息；
  * 调用 `AssistantService.run_chat(...)`（或等价方法）；
  * 将 `AiStreamChunk` 等流式分片推送给客户端；
  * 在轮次结束后统一落库（用户消息 + 助手最终答案 + meta）。

约定：WS 链路的 trace 必须与 REST/SSE 一致输出（`trace_id`、`tool_traces`、`ai_meta`），便于统一排障与论文复现实验。

### 3.4 WebSocket 对话协议与一致性约定

为保证后续 Android/前端接入不混乱，Stage-9 必须冻结一个最小可行协议（可扩展但向后兼容）：

1) 连接参数

* 路径：`/ws/assistant`
* Query：
  * `user_id`：必填；
  * `session_id`：可选；缺失时由服务端创建并在 `ready` 事件回传；
  * `trip_id`：可选（用于会话绑定行程上下文，若存在）。

2) 客户端 → 服务端消息（JSON）

* `{"type":"user_message","id":"<client_msg_id>","payload":{...}}`
  * `payload.query`：必填；
  * 其余字段尽量复用 `ChatPayload`（`use_memory/top_k_memory/location/poi_type/poi_radius/return_tool_traces` 等）。
* `{"type":"ping","ts":...}`：心跳；
* `{"type":"cancel","id":"<client_msg_id>"}`：取消当前生成（若正在进行）。

3) 服务端 → 客户端事件（JSON）

* `ready`：连接建立/会话确定
  * `{"type":"ready","session_id":123,"server_time":"...","caps":{...}}`
* `chunk`：流式分片（与 SSE chunk 语义对齐）
  * `{"type":"chunk","trace_id":"...","index":0,"delta":"...","done":false}`
* `result`：一轮完成
  * `{"type":"result","payload":{ChatResult...}}`
* `error`：错误事件（不应直接断开，除非致命）
  * `{"type":"error","error_type":"bad_request|rate_limited|internal","message":"...","trace_id":"..."}`
* `done`：本轮流式结束标记（如需与前端兼容 `[DONE]` 语义）

4) 一致性原则（必须满足）

* 同一轮对话必须只产生一个最终 `result`；
* `chunk` 的 `index` 必须递增（前端可按序拼接）；
* `cancel` 后必须停止继续发送 chunk，并返回一个明确 `error`/`result`（二选一，建议返回 `error_type=cancelled`）；
* 服务端不得因单条消息异常导致整个 WS 服务崩溃（必须隔离异常，返回 error）。

### 3.5 会话持久化与安全边界（必须遵守）

1) DB 表对齐

* `chat_sessions`、`messages` 表结构必须与数据库设计文档一致；
* `messages` 必须具备 `(session_id, created_at)` 的查询索引（现有 `ix_messages_session_created` 可复用）。

2) 用户隔离

* WS 接入必须校验 `session_id` 属于 `user_id`（不允许越权读取/写入他人会话）；
* Admin 才可跨用户查看在线会话列表与消息摘要（沿用 Admin Token/IP 策略）。

3) 写入策略

* 建议按“轮次”写入：收到用户消息先写 `role=user`；生成完成后写 `role=assistant`；
* 禁止把每个 chunk 都落库（会造成 DB 写放大）。

4) 资源上限

* 每个 session 的历史加载有上限（rounds/message 条数），避免大历史导致延迟飙升；
* WS 连接数、发送队列长度、单条消息大小需有上限与错误码。

---

## 4. 详细功能与实现要求

### 4.1 任务 T9-1：WebSocket 路由与连接生命周期（/ws/assistant）

**目标**：在 FastAPI 应用中新增 WS 路由，并实现稳定的 connect/receive/send/close 生命周期管理。

* 在应用工厂中注册 WS 路由（建议集中在 `core/app.py` 或专用模块）；
* 支持：
  * `accept` 后发送 `ready`；
  * 心跳（ping/pong）与空闲超时；
  * 断线清理（释放连接、移除在线列表、取消未完成任务）。

### 4.2 任务 T9-2：WS 流式对话执行（对齐 SSE 语义）

**目标**：复用现有 `AssistantService` + LangGraph，形成 WS 流式输出链路。

* 收到 `user_message` 后：
  * 组装等价于 `ChatPayload` 的输入；
  * 调用 `AssistantService.run_chat(payload, stream_handler=...)`；
  * `stream_handler` 以 `chunk` 事件向 WS 推送；
* 在对话结束后推送 `result`；
* 错误处理：
  * 参数错误：`error_type=bad_request`；
  * 限流/背压：`error_type=rate_limited`；
  * 运行时异常：`error_type=internal`（不得泄露敏感信息）。

### 4.3 任务 T9-3：WS 会话创建/绑定与消息落库

**目标**：WS 场景下会话语义清晰、持久化一致。

* `session_id` 缺失：
  * 创建新的 `chat_sessions` 记录；
  * 在 `ready` 中返回新 `session_id`；
* `session_id` 存在：
  * 校验属于 `user_id`；
  * 加载最近 N 轮历史（与配置一致）；
* 落库：
  * 用户消息与最终助手答案必须写入 `messages`；
  * 将 `intent/tool_traces/ai_meta` 写入 `messages.meta`（建议仅存可用子集，避免过大）。

### 4.4 任务 T9-4：在线会话管理与 Admin 实时监控（/admin/chat/live）

**目标**：实现在线连接统计与可视化，便于演示与排障。

1) 在线会话管理（最小可行）

* 维护活跃连接表：
  * 内存实现：进程内 dict + TTL（单实例可用）；
  * Redis 实现（可选）：`session:ws:{session_id}`（TTL 600s），支持多实例汇总；
* 记录信息：
  * `session_id/user_id/connected_at/last_seen_at/client_ip/user_agent`（可选）。

2) Admin 页面与接口

* 页面：`/admin/chat/live`
* JSON 接口（建议）：`GET /admin/chat/live/summary`
  * `active_connections`：当前连接数；
  * `active_sessions`：当前活跃 session 数；
  * `recent_sessions`：最近 N 个 session（含 last_seen/消息数摘要）。

### 4.5 任务 T9-5：性能与稳定性（WS 场景）

**目标**：确保 WS 场景下系统不会因慢客户端/高并发退化到不可用。

* 背压：
  * WS 发送使用队列并限制 maxsize（队列满时丢弃/断开/返回 error，需明确策略）；
* 限流：
  * 每用户消息速率限制（避免刷接口）；
* DB 优化：
  * 历史查询只取必要字段与有限条数；
  * 写入按轮次写，不写 chunk；
* 取消与超时：
  * 客户端 `cancel` 或连接断开时取消正在运行的生成任务；
  * 对单轮生成设置最大耗时上限（复用 `ai_request_timeout_s` 或新增 WS 专用）。

### 4.6 任务 T9-6：行程助手智能体全方位优化（去冗余/结构/性能）

**目标**：在不改变外部接口语义的前提下，系统性降低复杂度并提升可维护性与性能。

1) 去冗余与结构化

* 将 SSE/WS 共有的 streaming 事件结构抽到统一模块（避免两套格式漂移）；
* 将会话读写（`chat_sessions/messages`）抽到 `ChatRepository`（建议放在 `backend/app/repositories`）；
* 明确 `AssistantService` 的职责边界：
  * “组装状态/调用图/聚合结果”在 service 层；
  * “DB 读写”在 repository 层；
  * “协议与连接管理”在 ws handler 层。

2) 智能体链路重构（高效、稳定、简洁）

**目标**：将“可确定”的逻辑从 LLM 推理中剥离，减少不必要的模型回合与 token 消耗；把生成式能力集中在单点，提升多轮一致性与可测试性。

**必须 deterministic 的节点（不依赖 LLM）**

* `load_context`：会话校验、历史加载与裁剪、反注入清洗（超长/可疑 system 内容）；
* `memory_retrieve`：mem0 检索 + 去重/截断 + “槽位化”摘要（地点/日期/偏好/已确认约束）；
* `rule_router`：强规则路由（天气/POI/导航/行程/搜索/闲聊），对高确定性问题优先直达工具；
* `tool_args_normalize_and_validate`：工具参数补全、schema 校验、范围约束（例如天气预报 ≤4 天）；
* `task_runner`：工具执行器（超时/重试/降级/并发限制）+ 结构化 tool trace；
* `result_canonicalize`：将工具输出规范化为统一结构（weather/poi/trip/search），供后续生成使用；
* `fallback_rules`：缺失槽位（地点/日期等）时输出最小追问，不进入“盲目工具调用”。

**适合 agent 化的节点（仅在开放式/组合推理时启用）**

* `answer_compose`：基于规范化结果 + 槽位记忆 + 历史，生成最终自然语言回复（尽量只调用一次 LLM）；
* `trip_planner_optional`（可选）：当用户提出“做行程/比较方案/多工具探索”时，LLM 仅负责拆解计划与字段提取；实际工具调用仍由 `task_runner` 执行（强 schema + 调用次数上限）。

**推荐的新链路（Stage-9 落地形态）**

1. `load_context`（deterministic）
2. `memory_retrieve`（deterministic）
3. `rule_router`（deterministic）
4. `task_runner`（deterministic，执行 0~N 个工具）
5. `answer_compose`（LLM，可选；仅在需要自然语言组织/建议/解释时调用）
6. `persist`（deterministic：messages/mem0/tool_traces）

> 约束：自主型 agent 不直接持有“任意工具调用权”；其输出为“计划/草稿”，工具执行由 deterministic 执行器负责（校验、限额、可观测）。

3) 性能优化点（建议优先级）

* 降低历史加载成本：只取最近 N 轮 + 必要字段；
* 降低 tool_traces 体积：对外返回可配置；落库只存摘要；
* Prompt/ToolRegistry 缓存：复用既有缓存策略，避免每轮重复构建；
* 减少不必要的对象拷贝与 JSON dump（热点路径）。

4) 可维护性与可测试性

* 引入清晰的“对话轮次”抽象（message_id / client_msg_id）；
* 为 WS handler 增加可注入依赖（便于 pytest 模拟）；
* 统一错误码与错误结构（REST/SSE/WS 一致）。

5) 优化交付清单（必须交付，避免“只重构不落地”）

* **目录与职责清单**：写清楚 Stage-9 后各模块职责（ws / service / repository / agents），并在代码结构上体现；
* **统一 streaming**：WS 与 SSE 共享同一套 chunk/result/error 结构定义与序列化（允许传输层不同）；
* **性能基线**：提供至少一组本地基线数据（例如单轮/多轮平均耗时、history 查询次数、消息落库次数），用于后续阶段回归；
* **冗余清理**：删除/合并重复的会话查询与消息序列化逻辑，避免出现两套“看起来一样但行为不一致”的实现。
* **deterministic 核心链路落地**：将天气相对日期/地点抽取、工具参数校验、缺槽追问等关键路径实现为可单测的 deterministic 模块，并在 WS/REST 入口复用；
* **LLM 调用收敛**：在常见请求（天气/POI/导航/事实搜索）中，尽量将模型调用收敛为单次 `answer_compose`（或在工具已返回可用自然语言时直接跳过）。

### 4.7 任务 T9-7：测试与回归（含 WS）

**目标**：补齐 Stage-9 核心能力的自动化测试，保证回归稳定。

测试建议覆盖：

* WS 基本链路：connect → ready → user_message → chunk* → result；
* `session_id` 绑定与越权防护：错误 session_id 不能读/写；
* 取消/断线：cancel 生效、断线后资源释放；
* Admin chat live：鉴权、在线数与会话列表口径；
* 回归：`POST /api/ai/chat` 与 `stream=true` 行为不受影响。

---

## 5. 阶段 9 整体验收标准

当满足以下条件时，Stage-9 视为完成：

1. **WS 多轮对话可用**
   * `WS /ws/assistant` 可建立连接并流式返回助手回复；
   * 支持 `session_id` 复用与多轮连续对话。
2. **持久化与隔离正确**
   * WS 对话的用户/助手消息写入 `messages`；
   * `session_id` 与 `user_id` 隔离正确，越权请求返回明确错误。
3. **与 REST 兼容**
   * `POST /api/ai/chat`（含 SSE 流式）保持可用且回归通过。
4. **Admin 可观测**
   * `/admin/chat/live` 能展示在线连接数与活跃会话列表（至少最小可行口径）。
5. **优化交付**
   * 完成智能体相关冗余清理与模块边界整理（至少包含 streaming 复用与会话 repository 化）；
   * 在同等输入下，WS 对话关键路径性能不劣于现有 SSE（可用简单基线对比）。
   * 多轮稳定性提升：对“追问补槽”（如“薄外套冷不冷？”）能稳定利用 session 记忆/历史避免重复追问；对“相对日期天气”（今天/明天/后天）结果日期不漂移。
6. **质量**
   * pytest 覆盖 WS 主链路与安全边界；
   * `ruff`/`black`/`pytest` 在项目约定下通过（如项目已启用）。
