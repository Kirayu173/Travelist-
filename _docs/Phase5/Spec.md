
---

## 1. 概述

### 1.1 阶段编号与名称

* 阶段编号：**Stage-5**
* 阶段名称：**LangGraph 智能助手 v1 + Prompt 中心管理（多轮对话版）**

### 1.2 背景

前 4 个阶段已经完成：

* Stage-1：后端管理界面 `/admin/dashboard` 基础版，提供 API 调用统计与基础健康检查。
* Stage-2：落地 PostgreSQL + PostGIS 核心表结构，并在 Admin 中接入真实 DB 健康检查与统计。
* Stage-3：实现行程 CRUD、子行程排序与跨天移动、Admin 行程统计、API 注册表与在线测试、数据库结构可视化等。
* Stage-4：完成 LLM Provider 层（AiClient）、mem0 记忆接入（MemoryService）、AI Demo 接口 `/api/ai/chat_demo` 以及 Admin AI 监控和在线测试控制台。

Stage-4 Review 已确认：

* LLM 抽象（AiClient）、mem0 集成、AI 基础监控已经落地；
* `/api/ai/chat_demo` 支持流式输出，Admin 有 AI Console 可在线测试；
* 同时给出明确改进建议：
  1. **prompt 管理需要从代码中抽离，做成可配置/统一管理** ；
  2. 后续智能体阶段需要在 Admin 中补充更细颗粒度的 AI 指标与可调参数。

根据阶段开发文档，Stage-5 原本是「LangGraph 智能助手 v1（单轮问答 + 多级记忆）」；

结合最新需求，本阶段在此基础上 **提前引入多轮对话能力** ，并完成一版「能日常使用」的行程助手。

### 1.3 阶段目标（Stage-5 完成时应达到）

1. **统一 Prompt 管理**
   * 将当前零散在代码中的 system prompt / tool prompt 收敛到统一的 Prompt Registry（可持久化到 DB）。
   * 对接 Admin 后台，提供一个  **可视化 Prompt 管理页** ，支持查看、编辑、恢复默认等操作（为后续实验/论文留操作空间）。
2. **LangGraph 智能助手 v1**
   * 使用 LangGraph 设计并实现第一版行程助手图谱，至少包含：
     * `AssistantNode`（入口 & 意图解析）
     * `MemoryReadNode`（调用 mem0）
     * `TripQueryNode`（访问 trips/day_cards/sub_trips）
     * `ResponseFormatter`（结构化结果 → 文本回答）
   * 所有 LLM 调用必须走现有 `AiClient` 抽象与 Prompt Registry。
3. **多轮对话（REST + session）**
   * 提供一个面向前端的正式接口 `POST /api/ai/chat`：
     * 支持通过 `session_id` 实现 **多轮对话** ；
     * 每轮对话写入 `chat_sessions` / `messages` 表，并在 mem0 中写入会话级记忆。
   * 通过重复调用 `/api/ai/chat`（带同一个 session_id）实现上下文连续的对话体验。
4. **Admin 聊天监控与 Prompt 管理 UI**
   * 新增 `/admin/chat/summary`：统计会话数量、消息数量、简单意图分布等；
   * 新增 `/admin/ai/prompts` 页：可视化展示与编辑 prompt；
   * 对现有 `/admin/ai/console` 进行升级，支持基于 `/api/ai/chat` 的多轮对话调试。
5. **质量与文档**
   * 完成与 Stage-5 强相关的 migration、测试与文档；
   * 为后续 WebSocket 多轮助手（规划在后续阶段）预留接口与设计空间。

---

## 2. 范围说明

### 2.1 本阶段实现范围

1. **Prompt 中心管理（Prompt Registry + DB + Admin UI）**
   * 设计并实现 `PromptRegistry` / `PromptService`：
     * 支持根据 key（如 `assistant.system.main`）获取 prompt；
     * 支持从数据库加载、内存缓存、代码内置默认值。
   * 新增 `ai_prompts` 表（或同等结构），存储：
     * `key`、`title`、`role`（system/user/assistant/tool）、`content`、`version`、`tags`、`is_active`、`updated_at`、`updated_by` 等；
   * 所有 AI 模块（含 `/api/ai/chat_demo`）必须改为通过 PromptRegistry 获取 prompt，不允许再在业务代码里直接写死 system prompt。
2. **LangGraph 智能助手图谱（单图）**
   * 在 `backend/app/ai/graph/` 下定义第一版 LangGraph 图：
     * 状态模型（Graph State）：包含 `user_id`, `trip_id`, `session_id`, `query`, `intent`, `memories`, `trip_data`, `answer_text`, `tool_traces` 等字段；
     * 核心节点：
       * `AssistantNode`：构造 prompt（通过 PromptRegistry）、调用 LLM 判定意图与是否需要工具；
       * `MemoryReadNode`：调用 `MemoryService.search_memory`，并将结果写入 state；
       * `TripQueryNode`：根据 user_id / trip_id 查询 PostgreSQL 中当前行程、次日行程等；
       * `ResponseFormatter`：基于 state 中的结构化数据拼接最终回答；
       * `FallbackNode`（可选）：当工具/记忆不可用时直接调用 LLM 做通用回答。
   * LangGraph 使用的所有 LLM 调用统一走 `AiClient.chat`，所有记忆读写走 `MemoryService`。
3. **多轮对话 REST 接口 `/api/ai/chat`**
   * 设计并实现：
     * `POST /api/ai/chat`
   * 功能：
     * 支持请求中携带 `session_id`：
       * 无 session_id 或为 null → 创建新的 `chat_session` 记录并返回新的 session_id；
       * 有 session_id → 关联到已有会话；
     * 每条 request/response 作为两条 `messages` 记录写入 DB；
     * 调用 LangGraph 图执行完整流程：
       * 读 mem0 记忆 → 读 trip 信息 → LLM 生成回答 → 写 DB 消息 → 写 mem0 新记忆；
     * 支持返回本轮使用到的记忆与工具调用痕迹（用于调试与论文截图）。
   * 多轮对话通过反复调用 `/api/ai/chat`（带同一 session_id）实现上下文联结。
4. **会话表与消息表落地**
   * 依据数据库设计文档新增并迁移：`chat_sessions` 与 `messages` 表；
   * 基本字段要求：
     * `chat_sessions`：
       * `id`（主键）、`user_id`、`trip_id`（可空）、`opened_at`、`closed_at`（可空）、`meta` JSONB；
     * `messages`：
       * `id`、`session_id`、`role`（user/assistant/system）、`content`、`tokens`（可空）、`created_at`；
   * 对热门查询字段（`session_id`, `created_at`）建立索引，便于按会话拉取历史。
5. **Admin 侧扩展**
   * 新增 JSON 接口：
     * `GET /admin/chat/summary`：
       * 会话总数、今日新增会话数；
       * 消息总数、平均每会话轮数；
       * 按意图统计的简单分布（从 `messages.meta` 或额外聚合表中读取）；
     * `GET /admin/api/prompts` / `PUT /admin/api/prompts/{key}`：
       * 用于前端 Admin UI 调用。
   * 新增/扩展 HTML 页面：
     * `/admin/ai/prompts`：基于上述接口，提供 prompt 列表与编辑表单；
     * `/admin/ai/console` 升级：
       * 支持选择/创建 `session_id`；
       * 可以查看当前会话最近 N 条消息与使用到的记忆；
       * 能直连 `/api/ai/chat` 实现多轮对话调试。
6. **测试与文档**
   * 为 PromptRegistry、LangGraph 图、`/api/ai/chat`、Admin 新接口编写单元/集成测试；
   * 更新 `_docs/Phase5/Spec.md`、`Code.md`、`Tests.md`、`Review.md` 四套文档骨架，与前几阶段保持一致。

### 2.2 非本阶段范围（但需兼容）

* WebSocket 多轮对话与流式回复（`/ws/assistant`）——保留在后续阶段；
* 行程规划 Fast/Deep 模式的 LangGraph Planner 节点（属于后续规划阶段）；
* POI 工具节点（`PoiNode`）与天气工具节点（`WeatherNode`）的接入；
* Prompt A/B 实验、复杂版本控制与权限体系；
* 与 Android 客户端的前端联调（本阶段可以通过 Admin Console 与 Postman 进行验证）。

---

## 3. 总体技术与通用约定

### 3.1 技术栈与依赖

* 继续沿用：
  * 后端框架： **FastAPI** ；
  * 数据库： **PostgreSQL + PostGIS** ；
  * ORM： **SQLAlchemy** ；
  * 缓存：Redis；
  * LLM 抽象：Stage-4 的 `AiClient`；
  * 记忆层：Stage-4 的 `MemoryService`（mem0）。
* 新增/强调依赖：
  * `langgraph`（或相应 Python 包）用于定义智能体图；
  * 提示词管理可选使用的 Markdown/JSON 模板库（非强制）。

### 3.2 配置与环境变量约定

新增/强调配置项（名称可在 Code 阶段微调，但思路统一）：

* LangGraph：
  * `AI_ASSISTANT_GRAPH_ENABLED`（是否启用 LangGraph 流程，便于切换回简单模式 debug）；
  * `AI_ASSISTANT_MAX_HISTORY_ROUNDS`（从 DB 中回溯的历史轮数，默认 6–10）。
* Prompt：
  * `AI_PROMPT_EDIT_IN_PROD`（是否允许在生产环境编辑 prompt，默认 false）；
  * `AI_PROMPT_CACHE_TTL`（PromptRegistry 内存缓存 TTL，默认 60s）。
* 其他：
  * 沿用 Stage-4 中的 `AI_PROVIDER`、`AI_MODEL_CHAT`、`MEM0_*` 等。

配置规则：

* 所有环境变量依然通过 `.env` 注入，在配置文档和 `.env.example` 中补充说明；
* Prompt 编辑在开发/测试环境默认开启，在生产环境需显式配置才允许。

### 3.3 Graph 状态与节点约定

 **Graph State（示意）** ：

```python
class AssistantState(BaseModel):
    user_id: int
    trip_id: int | None = None
    session_id: int | None = None

    query: str
    intent: str | None = None

    history: list[dict] = []      # 最近 N 轮对话（从 messages 表加载）
    memories: list[MemoryItem] = []
    trip_data: dict | None = None

    answer_text: str | None = None
    tool_traces: list[dict] = []  # 调用过哪些工具 / 节点的记录
    ai_meta: dict | None = None   # latency, tokens 等
```

 **主要节点行为约定** ：

* `AssistantNode`
  * 从 PromptRegistry 读取主 system prompt（如 `assistant.system.main`）；
  * 构造 messages：包括系统 prompt、历史摘要、用户当前 query，以及必要的工具描述；
  * 调用 `AiClient.chat` 得到初步回答与意图字段（例如通过 JSON 输出/函数调用格式解析 intent）；
  * 将 `intent`（如 `trip_query`, `general_qa`）写入 state。
* `MemoryReadNode`
  * 根据 `user_id` + `trip_id` 调用 `MemoryService.search_memory`，返回 user/trip 级记忆；
  * 将结果写入 `state.memories`，并为后续 prompt 拼接简短摘要。
* `TripQueryNode`
  * 根据 `intent` 决定是否实际访问数据库；
  * 如果意图为「问某天行程」「我明天去哪」之类，从 trips/day_cards/sub_trips 中查出结构化数据；
  * 将结果放入 `state.trip_data`。
* `ResponseFormatter`
  * 基于 `memories` + `trip_data` + `query`，构造一个结构化 context，再次调用 `AiClient.chat` 或在应用层拼装自然语言回答；
  * 将最终文本写入 `state.answer_text`，同时记录 `ai_meta`（latency, usage_tokens）。
* `FallbackNode`（可选）
  * 在 mem0 或 DB 出错时，直接调用通用 QA prompt，从而保证「可用优先」。

### 3.4 多轮对话与记忆策略

* **短期对话记忆** ：通过 `chat_sessions` / `messages` 表维护完整对话历史；
* **长期语义记忆** ：通过 `MemoryService` + mem0 进行 user/trip/session 级记忆；
* 本阶段的折中策略：
  * 每轮对话：
    * 从 DB 中拉取最近 N 条 messages（仅 user/assistant 角色），形成 `history`；
    * 使用 mem0 进行一次 search，得到若干条语义记忆；
    * 将上述信息简要拼入 prompt；
    * 回答完成后：
      * 向 `messages` 写入两条记录（user & assistant）；
      * 把这一轮「Q/A」作为一条合并文本写入 mem0，对应 level=session 或 trip，metadata 包含会话 id、来源 `source="assistant_v1"`。

---

## 4. 详细功能与实现要求

本阶段拆分为 5 个主要任务：

* **T5-1：Prompt 中心管理（PromptRegistry + ai_prompts + Admin UI）**
* **T5-2：LangGraph 智能助手图谱搭建**
* **T5-3：多轮对话 REST 接口与会话持久化**
* **T5-4：Admin 聊天监控与 AI Console 升级**
* **T5-5：质量保障（测试 / 安全 / 文档）**

---

### 4.1 任务 T5-1：Prompt 中心管理

#### 4.1.1 功能目标

建立统一可管理的 Prompt 中心，让所有智能体相关 prompt 可配置、可调试、可追踪。

#### 4.1.2 目录结构建议

```text
backend/app/
  ai/
    prompts.py          # PromptRegistry / PromptService
  models/
    prompt_models.py     # AiPrompt ORM / Pydantic 模型（如有）
  admin/
    routes_prompts.py    # Admin prompt JSON 接口
    templates/
      ai_prompts.html    # Prompt 管理页面
```

#### 4.1.3 行为与约束

* `PromptRegistry` 职责：
  * `get_prompt(key: str, role: str | None = None) -> Prompt`：
    * 优先从内存缓存读取；
    * 缓存 miss 时从 DB 读取；
    * DB 无记录时回退到内置默认 prompt（代码中维护一个 DEFAULT_PROMPTS dict）；
  * 支持简单的更新接口供 Admin 使用。
* `ai_prompts` 表字段建议：
  * `id`、`key`（唯一）、`title`、`role`、`content`、`version`、`tags`（JSONB）、`is_active`、`updated_at`、`updated_by`；
* 要求：
  * Stage-4 的 `AiChatDemoService` 中的 system prompt 必须迁移到 PromptRegistry；
  * 新增 LangGraph 助手所需的所有 prompt（意图解析、回答格式等）均通过 key 管理。

#### 4.1.4 Admin 提示词管理 UI

* `GET /admin/api/prompts`：
  * 返回所有 prompts 的基本信息；
* `GET /admin/api/prompts/{key}`：
  * 返回指定 prompt 的详细内容；
* `PUT /admin/api/prompts/{key}`：
  * 更新内容与标签（仅开发/测试环境默认允许）；
* `/admin/ai/prompts` 页面：
  * 列表显示所有 key、标题、更新时间；
  * 点击可进入详情编辑页面，支持保存以及「恢复默认」按钮（调用服务端重置为内置版本）。

#### 4.1.5 测试要求

* 单元测试：
  * PromptRegistry 在 DB 有值/无值/缓存存在时行为正确；
  * Admin 接口鉴权后可更新 prompt，并能在下一次 LLM 调用中生效。
* 集成测试：
  * 修改某个 prompt 后，调用 `/api/ai/chat_demo` 或 `/api/ai/chat`，确认回答中风格变化或特定短语变化。

---

### 4.2 任务 T5-2：LangGraph 智能助手图谱搭建

#### 4.2.1 功能目标

构建一个最小可用的 LangGraph 助手图，实现「意图解析 → 工具调用 → 回答格式化」的闭环。

#### 4.2.2 目录建议

```text
backend/app/ai/
  graph/
    state.py           # AssistantState 定义
    nodes.py           # 各节点实现
    graph_builder.py   # 组装完整 Graph 的工厂函数
```

#### 4.2.3 实现要求

* State 模型按 3.3 小节定义；
* 节点实现：
  * `assistant_node(state)`：
    * 利用 PromptRegistry 构造 prompt；
    * 调用 AiClient，获取意图（intent）与初步回答草稿；
  * `memory_read_node(state)`：
    * 调 MemoryService，按 user/trip/session 拉取记忆；
  * `trip_query_node(state)`：
    * 查询 trips/day_cards/sub_trips（通过已有 ORM/Service），构造结构化行程信息；
  * `response_formatter_node(state)`：
    * 综合 history + memories + trip_data，得到最终 answer_text；
  * 错误处理：
    * 节点内部不得直接向外抛出原始 Provider 异常，统一映射为 `AiClientError` 或自定义 `AssistantError`，最终由 API 层统一转换为标准错误码。

#### 4.2.4 流程示例（逻辑）

```text
用户请求 → 构造初始 state
      → (可选) 从 DB 加载 history
      → memory_read_node
      → assistant_node (解析 intent)
      → [若 intent 需要行程信息] → trip_query_node
      → response_formatter_node
      → 返回 answer_text + tool_traces
```

#### 4.2.5 测试要求

* 为各节点编写单元测试（使用 mock AiClient / MemoryService / TripService）；
* 为整张图编写集成测试：
  * 输入一个「问明天行程」的意图，验证 TripQueryNode 被调用且回答中包含正确行程数据；
  * 输入一个纯闲聊问题，验证不会访问 DB/TripQueryNode。

---

### 4.3 任务 T5-3：多轮对话 REST 接口与会话持久化

#### 4.3.1 功能目标

提供正式的 `/api/ai/chat` 接口，支持基于 session 的多轮对话，并将会话/消息持久化到数据库，同时与 mem0 接通。

#### 4.3.2 接口定义（草案）

* 路由：`POST /api/ai/chat`
* 请求体示例：

```json
{
  "user_id": 1,
  "trip_id": 123,
  "session_id": null,
  "query": "我明天的行程是什么？",
  "use_memory": true,
  "top_k_memory": 5,
  "return_memory": true,
  "return_tool_traces": false
}
```

* 响应体示例：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "session_id": 42,
    "answer": "明天你上午会去广州塔，下午在珠江边散步。",
    "used_memory": [
      {
        "id": "mem0-xxx",
        "text": "你之前说这次行程希望节奏轻松一点。",
        "score": 0.82,
        "metadata": {
          "level": "trip",
          "trip_id": 123
        }
      }
    ],
    "tool_traces": [
      {
        "node": "trip_query",
        "status": "ok",
        "extra": { "queried_day": "2025-12-02" }
      }
    ],
    "ai_meta": {
      "provider": "openai",
      "model": "gpt-4.x",
      "latency_ms": 210.3,
      "usage_tokens": 512,
      "trace_id": "ai-20251119-xxxx"
    },
    "messages": [
      {
        "role": "user",
        "content": "我明天的行程是什么？",
        "created_at": "2025-11-19T10:00:00Z"
      },
      {
        "role": "assistant",
        "content": "明天你上午会去广州塔，下午在珠江边散步。",
        "created_at": "2025-11-19T10:00:02Z"
      }
    ]
  }
}
```

#### 4.3.3 行为逻辑

1. **会话管理**
   * 若 `session_id` 为空：
     * 创建新的 `chat_sessions` 记录（user_id, trip_id, opened_at）；
     * 使用生成的 session_id；
   * 若 `session_id` 不为空：
     * 校验 session 是否存在且属于该 user（防止越权）；
2. **历史加载**
   * 从 `messages` 表中加载最近 `AI_ASSISTANT_MAX_HISTORY_ROUNDS * 2` 条 user/assistant 消息，按时间排序；
3. **调用 LangGraph**
   * 构造初始 state（包含 user_id / trip_id / session_id / query / history）；
   * 执行 LangGraph 图；
   * 获取 `answer_text`、`used_memory`、`tool_traces`、`ai_meta` 等信息；
4. **持久化**
   * 在同一事务中：
     * 向 `messages` 表插入一条 user 消息和一条 assistant 消息；
     * 若是新会话，确保 session 已写入；
   * 调用 `MemoryService.write_memory` 写入一条会话记忆（包含 Q/A 文本与 metadata）；
5. **响应**
   * 返回 answer、session_id、部分历史消息（可选）、使用到的记忆及工具信息、ai_meta。

#### 4.3.4 错误处理

* 当 LangGraph/LLM 调用失败：
  * 将错误映射为 `code=3001`，`msg="AI 调用失败"`，`data` 中带 `error_type` 和 `trace_id`；
  * 若是 LLM 超时/限流，可考虑尝试一次降级（简单 template 的规则回答）。
* 当 mem0 调用失败：
  * 不影响主流程返回，应写 warning 日志并在 `tool_traces` 中标记失败。

#### 4.3.5 测试要求

* 场景测试：
  * 第一次调用 `/api/ai/chat` 无 session_id，返回新的 session_id 且能写入 DB；
  * 第二次带同一 session_id 调用时，回答中能引用上一轮内容（通过历史加载与 mem0）；
  * 在 mem0 未配置/故障的情况下，接口仍可正常回答。

---

### 4.4 任务 T5-4：Admin 聊天监控与 AI Console 升级

#### 4.4.1 功能目标

让 Admin 成为调试与观测智能助手的「中控台」：看得到会话量、意图分布，也能直接在后台玩多轮对话和调整 prompt。

#### 4.4.2 新增/扩展接口

1. `GET /admin/chat/summary`（JSON）
   * 输出示例：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "sessions_total": 12,
    "sessions_today": 3,
    "messages_total": 120,
    "avg_turns_per_session": 10,
    "top_intents": [
      {"intent": "trip_query", "count": 30},
      {"intent": "general_qa", "count": 50}
    ]
  }
}
```

* 数据来源：
  * 聚合 `chat_sessions` / `messages` 表；
  * 意图统计可通过在 messages 或单独表中存 `intent` 字段。

2. `GET /admin/ai/console`（HTML）
   * 升级点：
     * 会话列表：可选择已有 session 或创建新 session；
     * 对话窗口：显示最近 N 条消息，底部输入框直接调用 `/api/ai/chat`；
     * 右侧信息栏：显示本轮使用的 prompt key、mem0 命中条目数、trip_query 是否被调用。
3. `GET /admin/ai/prompts`（HTML）
   * Prompt 列表与编辑页面，如 T5-1 所述。

#### 4.4.3 鉴权与安全

* 所有 `/admin/chat/*` 与 `/admin/ai/*` 接口继续沿用 Stage-4 中的 Admin Token / IP 白名单机制；
* 特别是 Prompt 编辑接口，在生产环境默认不开放，需要通过配置显式启用。

#### 4.4.4 测试要求

* 调用 `/api/ai/chat` 多次后，`/admin/chat/summary` 的会话/消息统计应正确变化；
* 在 Admin Console 中可以完整跑一段对话，查看历史与工具痕迹；
* 不带 Admin Token 访问上述接口应返回鉴权错误码（2xxx）。

---

### 4.5 任务 T5-5：质量保障与文档

#### 4.5.1 lint/format 与测试

* 保持 Stage-4 的规范：`ruff` + `black` 全项目通过；
* 新增测试覆盖：
  * PromptRegistry；
  * LangGraph 助手图；
  * `/api/ai/chat`；
  * Admin 新接口。

#### 4.5.2 文档与可追溯性

* 在 `_docs/Phase5/Spec.md`、`Code.md`、`Tests.md`、`Review.md` 中补齐：
  * Prompt 管理设计与实现；
  * LangGraph 助手节点设计与流程图；
  * 多轮对话与记忆策略；
  * Admin 监控指标的定义与示例截图（后续在 Review 阶段补充）。

---

## 5. 阶段 5 整体验收标准

当满足以下条件时，Stage-5 视为完成：

1. **Prompt 中心管理**
   * 所有智能助手相关的 system prompt 不再散落在业务代码中，而是通过 PromptRegistry 按 key 统一管理；
   * 在 `/admin/ai/prompts` 中可以查看和编辑 prompt，并在下次调用 `/api/ai/chat` / `/api/ai/chat_demo` 时生效。
2. **LangGraph 智能助手 v1**
   * LangGraph 图能完整跑通意图解析 → 记忆读取 → 行程查询 → 回答格式化的链路；
   * 至少能回答与当前行程相关的问题（如「我明天的行程是？」）和通用问答。
3. **多轮对话能力**
   * 通过 `/api/ai/chat`，使用同一 `session_id` 连续发起多轮对话，助手能在回答中体现上下文记忆；
   * 会话与消息可以在 `chat_sessions` / `messages` 表中查询到，记录完整、无明显重复/缺失。
4. **Admin 监控与调试**
   * `/admin/chat/summary` 能正确展示会话/消息统计信息；
   * `/admin/ai/console` 支持基于 `/api/ai/chat` 的多轮对话调试，并展示简单工具调用信息；
   * `/admin/ai/prompts` 页面可正常使用，并受鉴权保护。
5. **质量与文档**
   * 后端通过 lint/format 检查，测试全部通过；
   * 本阶段相关设计与实现已在 Phase5 文档集中记录，可直接用于毕业论文中「智能体与提示词管理」等章节的写作。
