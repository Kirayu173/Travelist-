
## 1. 概述

### 1.1 阶段编号与名称

* 阶段编号：**Stage-4**
* 阶段名称：**LLM Provider 层 & mem0 记忆接入 + AI 基础监控（智能体底座）**

### 1.2 背景

前 3 个阶段已经完成：

* Stage-1：搭建了基础后端管理界面 `/admin/dashboard`，可查看 API 调用统计和基础健康检查。
* Stage-2：落地 PostgreSQL + PostGIS 核心表结构（users / trips / day_cards / sub_trips / pois / favorites 等），并在 Admin 中接入真实的 DB 健康检查和统计。
* Stage-3：实现了完整的行程 CRUD API、子行程排序与跨天移动、Admin 行程统计、API 注册表 & 在线测试、数据库结构可视化等，形成可视化 + 可测试的后端监控中心。

Stage-3 Review 已确认业务与架构整体达标，同时指出后续阶段需要注意：

* 统一 lint/format，避免 ruff/black 报错堆积；
* 为 `/admin/api/*` 这类敏感接口增加鉴权；
* 未来引入 AI/Agent 后，要在 Admin 中补充更细致的监控与日志指标。

根据更新后的阶段开发计划，本阶段（Stage-4）不再立刻推进 LangGraph 或完整智能助手，而是先搭建一个“智能层 SDK”：统一 LLM Provider 抽象、接入 mem0 作为记忆层，并在 Admin 中加入基础的 AI 调用监控能力，为后续 LangGraph 智能助手、行程规划 Fast/Deep 模式等提供可靠底座。

本阶段目标同时需要与整体产品设计、技术选型、后端/数据库设计以及毕业设计任务书保持一致。

### 1.3 阶段目标（Stage-4 完成时应达到）

1. **统一 LLM 调用层**
   * 设计并实现 `AiClient` 抽象，封装具体 Provider（先支持 1 个主模型），统一错误处理与监控数据采集。
2. **引入 mem0 作为记忆层（MemoryService）**
   * 基于 mem0 Python SDK 实现 `MemoryService`，支持多层级记忆（user/trip/session），提供 `write_memory` / `search_memory` 等标准接口。
3. **实现最小可用 AI 问答链路**
   * 新增 `POST /api/ai/chat_demo`，完成 “用户问题 → LLM 回答 → 写入 mem0 → 再问时可检索记忆” 的闭环。
4. **Admin 中接入 AI 调用监控与测试入口**
   * 新增 `/admin/ai/summary` 与 `/admin/ai/console`：展示 AI 调用次数、平均耗时、错误率、mem0 调用情况，并提供简单的在线对话测试界面。
5. **解决与本阶段强相关的 Stage-3 遗留问题**
   * 至少覆盖：统一后端 lint/format；为新老 `/admin/*` 中敏感接口增加基础鉴权约定；在文档/配置中明确 FAST_DB/SQLite 的使用范围。

---

## 2. 范围说明

### 2.1 本阶段实现范围

1. **AiClient 抽象与默认 Provider 实现**
   * 统一封装 LLM 聊天/补全能力，支持：
     * 文本回答模式；
     * （为后续做准备）JSON 结构化回答模式。
   * 负责：
     * 封装底层 HTTP/SDK 调用；
     * 记录调用耗时、Token 使用量（如果 Provider 提供）；
     * 统一异常映射为内部 `AiClientError`。
2. **MemoryService & mem0 集成**
   * 基于 mem0 Python SDK（参考官方 quickstart）封装：
     * `write_memory(user_id, level, data, metadata)`
     * `search_memory(user_id, level, query, k)`
   * 设计 user/trip/session 多级记忆的编码方式（如命名空间/collection/标签规范）。
3. **AI Demo 接口 `/api/ai/chat_demo`**
   * 提供一个简单问答接口，用于验证：
     * 能调用 LLM 返回回答；
     * 能将用户问题与回答写入 mem0；
     * 再次发问时可以从 mem0 中检索到相关记忆并显示/利用。
4. **Admin AI 监控与在线测试**
   * Admin 后台增加：
     * `GET /admin/ai/summary`：返回 AI & mem0 调用统计；
     * `GET /admin/ai/console`：HTML 界面，可在浏览器中输入问题，对接 `/api/ai/chat_demo` 进行测试，并展示最近若干次 AI 调用记录。
5. **测试与基础质量保障**
   * 为 AiClient、MemoryService、`/api/ai/chat_demo` 和 Admin AI 接口编写单元/集成测试；
   * 在本阶段结束时，确保：
     * 后端 lint/format 通过；
     * 新增代码纳入 CI；
     * 与 AI/记忆相关的错误有可观测性。

### 2.2 非本阶段范围（但需兼容）

* 不在本阶段实现：
  * LangGraph 智能图谱、意图解析、多工具调用；
  * 行程 Fast/Deep 模式智能规划；
  * WebSocket 多轮智能助手；
  * Android 前端接入 AI 能力。
* 不引入新的数据库表（除非经论证确有必要记录 AI 调用日志），但要与现有 `trips / chat_sessions / messages / ai_tasks 等设计保持兼容。
* `/api/ai/chat_demo` 仅用于内部调试，后续对外正式 AI 接口将另行设计（例如 `/api/ai/chat`、`/ws/assistant` 等）。

---

## 3. 总体技术与通用约定

### 3.1 技术栈与依赖

* 后端框架： **FastAPI** （沿用既有结构）。
* 数据库： **PostgreSQL + PostGIS** （本阶段不新增表结构变更，除非为 AI 日志单独建表）。
* ORM： **SQLAlchemy** ，通过现有 Session 工具复用。
* 缓存：Redis（本阶段可用于存储 AI 调用计数等轻量指标）。
* 新增外部依赖：
  * `mem0ai`（mem0 Python SDK）；
  * 一个 LLM Provider SDK 或基于 `httpx` 的自封装客户端（例如兼容 OpenAI 风格的接口）。

### 3.2 配置与环境变量约定

新增或强调的配置项（具体命名可在 Code 阶段微调，但在 Spec 中统一思路）：

* LLM Provider：
  * `AI_PROVIDER`（如：`openai`、`xxx`）；
  * `AI_API_KEY`；
  * `AI_API_BASE`（如自建代理网关）；
  * `AI_MODEL_CHAT`（主聊天模型名称）。
* mem0：
  * `MEM0_API_KEY`；
  * `MEM0_BASE_URL`（如适用）；
  * `MEM0_DEFAULT_K`（默认召回记忆条数）。
* Admin 鉴权：
  * `ADMIN_API_TOKEN` 或 `ADMIN_ALLOWED_IPS`（二选一或组合，用于保护 `/admin/api/*` / `/admin/ai/*` 等敏感接口）。

配置规则：

* 所有上述 Key 必须通过环境变量注入，不写入代码仓库；
* 在 `_docs/Phase4/Code.md` 中需附带示例 `.env.example` 片段，标明各变量用途和必填/可选。

### 3.3 AiClient 抽象约定

定义一个统一的 AiClient 接口（可为 `Protocol` 或基类），示意：

```python
class AiMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str

class AiChatRequest(BaseModel):
    messages: list[AiMessage]
    response_format: Literal["text", "json"] = "text"
    timeout_s: float = 30.0

class AiChatResult(BaseModel):
    content: str          # 主回答文本
    raw: dict | None      # Provider 原始回包（截断敏感字段）
    usage_tokens: int | None
    latency_ms: float

class AiClientError(Exception):
    type: str   # e.g. "timeout", "rate_limit", "provider_error", "invalid_output"
    message: str
```

接口要求：

* 至少提供一个方法：
  * `async def chat(self, req: AiChatRequest) -> AiChatResult`
* 要求：
  * 将 Provider 特定异常转换为 `AiClientError`；
  * 记录调用开始/结束时间，计算 `latency_ms`；
  * 尽量解析出 Token 使用量，否则置空；
  * 对 JSON 模式下 Provider 返回的结构做最基础的 JSON 校验（本阶段 `chat_demo` 可只用 text 模式）。

### 3.4 MemoryService 与多级记忆约定

MemoryService 接口示意：

```python
class MemoryLevel(str, Enum):
    user = "user"
    trip = "trip"
    session = "session"

class MemoryItem(BaseModel):
    id: str
    text: str
    score: float | None = None
    metadata: dict | None = None

class MemoryService:
    async def write_memory(
        self,
        user_id: int,
        level: MemoryLevel,
        text: str,
        metadata: dict | None = None,
    ) -> str: ...
  
    async def search_memory(
        self,
        user_id: int,
        level: MemoryLevel,
        query: str,
        k: int = 5,
    ) -> list[MemoryItem]: ...
```

多级记忆编码约定（逻辑）：

* **user 级** ：与用户长期偏好、常见问题等相关；
* **trip 级** ：绑定特定 `trip_id`，用于记录该行程相关的偏好/变更上下文；
* **session 级** ：绑定对话 `session_id`（后续 WebSocket 阶段会大量使用）。

在 mem0 侧，要求统一命名规则，例如：

* `namespace`/`collection`：`"user:{user_id}"` / `"trip:{trip_id}"` / `"session:{session_id}"`；
* `metadata` 中必须包含：
  * `level`（user/trip/session）；
  * 相关实体 ID（如 `trip_id`、`session_id`）；
  * 来源（如 `"source": "chat_demo"`）。

要求：

* 当 mem0 配置缺失或调用失败时，MemoryService 需 **优雅降级** ：返回空结果并打日志，不得影响主流程返回 LLM 回答。

### 3.5 API 设计与通用响应格式

* 继续沿用统一响应格式：

```json
{
  "code": 0,
  "msg": "ok",
  "data": { ... }
}
```

* 错误码：
  * `1xxx`：业务错误（如参数缺失）；
  * `2xxx`：鉴权错误（如 Admin Token 无效）；
  * `3xxx`：外部依赖错误（LLM/mem0 调用失败等）。

---

## 4. 详细功能与实现要求

本阶段拆分为 5 个主要任务：

* **T4-1：AiClient 抽象层与默认 Provider 实现**
* **T4-2：MemoryService 与 mem0 接入**
* **T4-3：AI Demo 接口 `/api/ai/chat_demo`**
* **T4-4：Admin AI 监控与在线测试**
* **T4-5：质量与安全相关改进（lint/鉴权/文档）**

---

### 4.1 任务 T4-1：AiClient 抽象层与默认 Provider 实现

#### 4.1.1 功能目标

实现一个独立的 `AiClient` 模块，作为后续 LangGraph、Planner、助手等所有 AI 调用的统一入口，屏蔽底层多 Provider 差异。

#### 4.1.2 目录与模块建议

```text
backend/app/
  ai/
    client.py        # AiClient 抽象 & 默认实现
    models.py        # AiMessage/AiChatRequest/AiChatResult 等
    exceptions.py    # AiClientError 定义
```

#### 4.1.3 行为与约束

* `AiClient` 默认实现需支持：
  * 指定模型（`AI_MODEL_CHAT`）；
  * 指定 Base URL & API Key；
  * request 超时（默认 30s，可配置）。
* 错误处理：
  * HTTP 非 2xx → 统一封装为 `AiClientError(type="provider_error", ...)`；
  * 超时 → `AiClientError(type="timeout", ...)`；
  * Provider 返回结构无法解析 → `AiClientError(type="invalid_output", ...)`。
* 监控数据采集：
  * 每次调用记录：
    * Provider 名称、模型名；
    * latency_ms；
    * usage_tokens（如可用）；
    * 是否成功 / 错误类型。
  * 这些数据通过一个轻量级 `AiMetrics` 单例或模块级对象暴露给 Admin（详见 T4-4）。

#### 4.1.4 测试要求

* 使用 Fake/Mock Provider 编写单元测试：
  * 正常返回；
  * 超时；
  * 非法 JSON；
* 验证：
  * 异常被统一映射为 `AiClientError`；
  * 监控数据计数正确更新。

---

### 4.2 任务 T4-2：MemoryService 与 mem0 接入

#### 4.2.1 功能目标

建立与 mem0 的基础集成，支持简洁的写入和检索接口，为后续 LangGraph + 多轮对话记忆提供能力。

#### 4.2.2 目录结构建议

```text
backend/app/
  services/
    memory_service.py   # MemoryService 实现
  ai/
    memory_models.py    # MemoryLevel / MemoryItem 定义（也可放在 services 中）
```

#### 4.2.3 实现要求

* 将 mem0 官方 Python SDK 封装为 `MemoryService`，提供：
  * `write_memory(user_id, level, text, metadata)`：
    * 将 text 写入 mem0；
    * 附带 metadata（必须包含 level 与相关 ID）；
    * 返回 mem0 记录 id。
  * `search_memory(user_id, level, query, k)`：
    * 在对应 level 范围内检索语义相关记忆；
    * 返回 `MemoryItem` 列表。
* 命名规范：
  * 结合 mem0 的 namespace/collection/tag 机制，保证后续可以按 user/trip/session 精确筛选；
  * 具体字段映射细节在 `_docs/Phase4/Code.md` 中说明，便于论文记录。
* 失败与降级：
  * 当 mem0 未配置或调用失败时：
    * `write_memory` 打 warning 级日志，返回一个占位 id（如 `"mem0_disabled"`）；
    * `search_memory` 返回空列表；
    * 不抛出到上层业务（避免 chat_demo 硬挂）。

#### 4.2.4 测试要求

* 为 `MemoryService` 写单元测试（可使用 Fake mem0 client）：
  * 写入后检索能返回；
  * 在“mem0 不可用”时，函数不抛异常且行为符合降级预期。
* 如条件允许，可在本地或单独 CI job 中增加真实 mem0 集成测试（非必须）。

---

### 4.3 任务 T4-3：AI Demo 接口 `/api/ai/chat_demo`

#### 4.3.1 功能目标

实现一个最小可用的 AI 问答接口，串起：**用户输入 →（可选）记忆检索 → LLM 回答 → 写入新记忆** 的完整流程。

#### 4.3.2 接口定义（草案）

* 路由：`POST /api/ai/chat_demo`
* 鉴权：沿用当前 `/api/*` 的策略（如尚未引入统一鉴权，可暂时通过 `user_id` 作为必填字段，后续可无痛迁移）。
* 请求体示例：

```json
{
  "user_id": 1,
  "trip_id": 123,
  "session_id": null,
  "level": "trip",
  "query": "帮我记一下：第一天要早点起床去广州塔。",
  "use_memory": true,
  "top_k": 5,
  "return_memory": true
}
```

* 响应体示例：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "answer": "好的，已经为本次行程记录下：第一天早点起床去广州塔。",
    "used_memory": [
      {
        "id": "mem0-xxx",
        "text": "你之前说这次广州行比较赶，希望第一天早一点出发。",
        "score": 0.82,
        "metadata": {
          "level": "trip",
          "trip_id": 123,
          "source": "chat_demo"
        }
      }
    ],
    "ai_meta": {
      "provider": "openai",
      "model": "gpt-4.x",
      "latency_ms": 123.4,
      "usage_tokens": 256,
      "trace_id": "ai-20251117-xxxx"
    }
  }
}
```

#### 4.3.3 行为逻辑

1. 参数校验：
   * `user_id` 必填；
   * `level` 与 `trip_id` / `session_id` 的组合需合法：
     * `level=user` → 只需 user_id；
     * `level=trip` → 必须提供 `trip_id`；
     * `level=session` → 必须提供 `session_id`（后续多轮对话将使用）。
2. 构造上下文：
   * 若 `use_memory=true`：
     * 调用 `MemoryService.search_memory` 获取若干条历史记忆；
     * 将这些记忆以简短形式拼入 system prompt 或 context 中（具体策略在 Code 文档中说明）。
3. 调用 AiClient：
   * 构造 `AiChatRequest`（system + user 消息）；
   * 调 `AiClient.chat` 获取回答。
4. 写入新记忆：
   * 根据 level，构造一条记忆文本，如：`"Q: ...\nA: ..."`；
   * 调用 `MemoryService.write_memory` 写入 mem0；
   * metadata 中写入 `source="chat_demo"`。
5. 组装响应：
   * 返回回答文本、（可选）使用到的记忆、AiClient 返回的元数据（latency/tokens 等）。

#### 4.3.4 错误处理

* AiClient 抛出 `AiClientError`：
  * 记录 error_type、message、trace_id；
  * 返回 `code=3001`，`msg` 提示为“AI 调用失败”，`data` 中附带 `error_type` 和 `trace_id`（不暴露 Provider 细节）。
* MemoryService 降级：
  * 不影响主流程；
  * 在 Admin 指标中反映 mem0 错误数量即可。

#### 4.3.5 测试要求

* 测试场景：
  * 不使用记忆（`use_memory=false`）时，接口可正常返回回答；
  * 使用记忆时，第二次请求中能检索到第一次写入的记忆（在 mem0 集成可用的前提下）；
  * mem0 不可用时，仍能返回 LLM 回答；
  * AiClient 抛出错误时，接口返回约定错误码与 trace_id。

---

### 4.4 任务 T4-4：Admin AI 监控与在线测试

#### 4.4.1 功能目标

在现有 Admin 后台的基础上，增加 AI 调用的监控视图和一个内嵌的 QA 测试入口，便于开发调试与后续论文截图展示。

#### 4.4.2 接口与页面

1. `GET /admin/ai/summary`（JSON）
   * 输出示例：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "ai_calls_total": 42,
    "ai_calls_success": 40,
    "ai_calls_failed": 2,
    "avg_latency_ms": 230.5,
    "last_10_calls": [
      {
        "trace_id": "ai-20251117-xxxx",
        "provider": "openai",
        "model": "gpt-4.x",
        "latency_ms": 210.3,
        "success": true,
        "error_type": null,
        "timestamp": "2025-11-17T10:23:45Z"
      }
    ],
    "mem0_calls_total": 30,
    "mem0_errors": 1
  }
}
```

* 数据来源：
  * `AiMetrics`（内存结构，进程级统计）；
  * 如有必要，可将 last_10_calls 同步写入一个轻量级表以便重启后仍可展示。

2. `GET /admin/ai/console`（HTML/Jinja2）
   * 页面包含：
     * 简单表单：
       * user_id、trip_id、level、query；
     * 一个“发送”按钮，调用 `/admin/api/test` 或直接调用 `/api/ai/chat_demo`；
     * 下方展示最近一次回答、耗时以及使用到的记忆片段；
     * 右侧/下方展示 `ai_calls_total`、`avg_latency_ms` 等指标。
   * 要求：
     * 仅在开发/测试环境使用，生产环境可通过配置屏蔽或限制 IP。
3. Admin Dashboard 增强
   * 在 `/admin/dashboard` 中增加一个“AI 概览”卡片，展示：
     * 今日 AI 调用次数；
     * 最近一次调用耗时；
     * 当前错误率（近 N 分钟内）。

#### 4.4.3 鉴权与安全要求

* `/admin/ai/summary`、`/admin/ai/console`、以及既有 `/admin/api/routes`、`/admin/api/test` 等接口都视为 **敏感接口** ：
  * 需统一增加一种轻量鉴权方式（建议）：
    * 要求请求头携带 `X-Admin-Token: <ADMIN_API_TOKEN>`；
    * 或者基于 IP 白名单检查（可二选一或组合）。
* 在 `_docs/Phase4/Tests.md` 和 README 中说明这些接口仅面向开发者/运维，不对外公开。

#### 4.4.4 测试要求

* 调用 `/api/ai/chat_demo` 多次后，`/admin/ai/summary` 中的计数与 last_10_calls 变化符合预期；
* 未携带正确 Admin Token 时访问 `/admin/ai/*` 返回 `code=2001`（鉴权错误）；
* `dashboard` 上 AI 卡片与 summary JSON 中的关键指标一致。

---

### 4.5 任务 T4-5：质量与安全相关改进（lint/鉴权/文档）

本任务主要用于收尾 Stage-3 Review 中与 Stage-4 强相关的改进项，使后续智能体开发处于相对干净的基础之上。

#### 4.5.1 lint/format 统一

* 在本阶段完成前，执行：
  * `ruff --select I,E,F --fix backend`；
  * `black backend`；
* 将 lint/format 步骤加入 CI，保证后续 MR/提交不会再次引入大面积样式差异。

#### 4.5.2 Admin 鉴权规范化

* 如 4.4.3 所述，为以下路径统一引入鉴权中间件：
  * `/admin/api/routes`
  * `/admin/api/schemas`
  * `/admin/api/test`
  * `/admin/ai/*`
  * 以及其他适合保护的 Admin 接口。
* 在 Spec/Code/Tests 文档中记录规则，避免之后忘记。

#### 4.5.3 FAST_DB/SQLite 使用说明

* 在测试/文档中补充：
  * FAST_DB 仅限本地开发提速；
  * CI 与生产部署必须使用真实 PostgreSQL，与 Stage-2/3 一致。

---

## 5. 阶段 4 整体验收标准

当满足以下条件时，Stage-4 可视为完成：

1. **AiClient 与 MemoryService**
   * 可在本地通过一个简单脚本调用 `AiClient.chat`，获得正常回答；
   * 在 mem0 正常配置时，`MemoryService.write_memory` + `search_memory` 可以实现“写入一条记忆 → 立即检索到”；
   * mem0 未配置时，MemoryService 不影响主流程、仅在 Admin 指标中体现错误次数。
2. **`/api/ai/chat_demo` 功能链路**
   * 一次请求能获得 LLM 回答，返回格式符合 Spec；
   * 连续两次请求（同 user/level）时，第二次响应的 `used_memory` 中能看见第一次写入的记忆（在 mem0 可用场景下）；
   * 当 LLM 调用失败时，接口返回约定错误码和 trace_id，Admin 中的错误计数随之增加。
3. **Admin AI 监控与测试**
   * `/admin/ai/summary` 能正确反映调用次数、平均耗时、错误率等指标；
   * `/admin/ai/console` 页面可通过浏览器直接发起请求并查看结果；
   * `/admin/dashboard` 中新增的 AI 概览卡片数据与 summary 一致。
4. **安全与质量**
   * 新增/既有 Admin 敏感接口均启用基础鉴权（Admin Token 或 IP 白名单）；
   * 后端 `ruff` 与 `black --check` 全部通过；
   * 新增功能具备基本单元/集成测试，CI 中测试全部通过。
5. **文档与可追溯性**
   * `_docs/Phase4/Spec.md`、`Code.md`、`Tests.md`、`Review.md` 四个文档齐备，且对本阶段 AiClient/Mem0/Admin AI 的设计和结果有完整记录；
   * 设计与实现与产品设计说明书、技术选型方案、后端/数据库设计文档及毕业任务书中的总体目标一致。
