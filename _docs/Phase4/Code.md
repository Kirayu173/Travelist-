# 阶段 4 开发工作报告

## 1. 开发概述
- 按 Spec 统一 AI 抽象：落地 `AiClient/AiMessage/AiChatRequest`，默认兼容本地 Ollama 流式输出，可通过 `mock` provider 注入测试，所有调用均打点到新的 `AiMetrics`。
- 引入 mem0 SDK 包装的 `MemoryService`，抽象 user/trip/session 三层命名空间，封装写入/检索与本地回退存储，异常仅计入监控不阻断主流程。
- 新增 `POST /api/ai/chat_demo`，串联记忆召回 → 流式 LLM → 记忆写入，支持 SSE 式逐字返回；同时补充 `ChatDemoPayload/Result` schema 与 `AiChatDemoService`。
- Admin 管理台扩展：新增 `/admin/ai/summary` JSON 指标和 `/admin/ai/console` 在线对话页面，Dashboard 上增加 AI 卡片；对 `/admin/api/*` 与 `/admin/ai/*` 引入 `X-Admin-Token` 鉴权（或 IP 白名单）。
- 质量体系补强：新增 AI 单测/接口测、Admin 鉴权测，统一执行 `ruff check --select I,E,F --fix` 与 `black backend`，pytest 全量通过；.env&文档补齐 AI/mem0/Admin 配置说明。

## 2. 目录与关键文件
- `backend/app/ai/`: 新的智能客户端模块（`client.py`, `models.py`, `metrics.py`, `memory_models.py`, `exceptions.py`），提供统一调用、流式回调与指标采集。
- `backend/app/services/memory_service.py`: mem0 集成及本地 fallback；`ai_chat_service.py` 串联记忆/LLM/写入逻辑。
- `backend/app/api/ai.py`: `POST /api/ai/chat_demo` 路由，内建 SSE streaming。
- `backend/app/admin/auth.py`, `backend/app/api/admin.py`, `backend/app/admin/templates/ai_console.html`, `dashboard.html`: Admin 鉴权、中台指标页面、AI Console 模板与 Dashboard AI 卡片。
- `backend/app/core/settings.py`, `.env`: 新增 AI / mem0 / Admin 配置项与解析（列表型 ENV 支持）。
- `backend/tests/test_ai.py`, `test_ai_api.py`, `test_admin.py`: AI 客户端/记忆单测、API 集成测、Admin 鉴权/指标测；`backend/tests/conftest.py` 配置 mock provider 与 Admin token。
- `_docs/Phase4/Code.md`: 本报告（阶段 4）；Stage3 遗留变更说明亦同步更新相关设计记录。

## 3. 技术实现要点
1. **AiClient 与流式输出**
   - `AiClient.chat` 接收 `AiChatRequest`，根据 `settings.ai_provider` 选择实现：`ollama` 走 HTTP 流式分块（`httpx.AsyncClient.stream`），`mock` 供测试/CI 使用。
   - 每个 chunk 触发 `StreamCallback`（可直接推送 SSE），同时累计文本、统计 latency/token，最终返回 `AiChatResult`（含 trace_id/raw payload）。
   - `AiMetrics` 记录成功/失败数、平均耗时、usage tokens、最近调用明细，以及 mem0 调用次数/错误。
2. **MemoryService & mem0**
   - 内置 `LocalMemoryEngine`（`backend/app/ai/local_memory_engine.py`）基于 `backend/mem0` OSS 内核构建，默认 `MEM0_VECTOR_PROVIDER=pgvector` 指向 PostgreSQL + pgvector；若数据库尚未安装 `vector` 扩展则自动降级至自定义 `pgarray` 存储（同样驻留在 PostgreSQL，通过 double precision[] + 余弦相似度实现），Embedder/LLM 统一走本机 Ollama；
   - `MemoryService` 同步改造：通过 `anyio.to_thread` 调用本地引擎，写入/检索成功会体现在 AiMetrics 的 `mem0_calls_*` 指标中，异常则回落 `_InMemoryStore` 并在 Admin 中提示；命名空间规范依旧为 `user:{id}` / `user:{id}:trip:{trip_id}` / `user:{id}:session:{session_id}`；
   - 查找支持 `k`（默认 `settings.mem0_default_k`），当 pgvector 不可用时自动回落到 fallback 匹配，保证 Demo 体验稳定。
3. **AI Demo 接口与 Admin Console**
   - `ChatDemoPayload` 校验 level 与 trip/session 约束，`AiChatDemoService` 负责记忆召回、拼装 system/context prompt、调用 `AiClient`、写入新记忆，并返回 `ChatDemoResult`。
   - `/api/ai/chat_demo` 支持 `stream=true`：服务端组装 SSE（`StreamingResponse`），前端可读取逐字输出；普通模式直接返回标准 JSON。
   - Admin Dashboard 新增 AI 卡片显示调用总数/成功率/mem0 状态/最近调用；`/admin/ai/console` 提供表单 + 流式输出 + 指标刷新，支持 `?token=` 注入后写入 cookie，再对 `/admin/ai/summary` 发起鉴权请求。
4. **Admin 鉴权与配置管理**
   - 新增 `verify_admin_access`，允许 `X-Admin-Token` 请求头、`?token=` query 或 `admin_token` cookie（token/IP 任一满足即放行）；所有 `/admin/api/routes|schemas|test|testcases` 与 `/admin/ai/*` 需鉴权。
   - `core/settings.py` 扩展 AI/mem0/Admin 配置；`admin_allowed_ips` 支持逗号字符串解析；`.env` 样例说明各变量用途与 fallback 策略。
5. **FAST_DB / SQLite 使用边界**
   - `backend/tests/conftest.py` 中保留 `PYTEST_FAST_DB=1` 快速模式，仅允许在本地复用已存在测试库；CI/默认模式依旧 drop/create 真正的 PostgreSQL 库，文档与 `.env` 均明确 SQLite 仅供单机/快速验证。

## 4. 遇到的问题与解决方案
- **APIRouter 无 `exception_handler`**：原计划在路由层注册 AdminAuthError 处理器，FastAPI 版本暂不支持。改为在 `create_app()` 中调用 `application.add_exception_handler(AdminAuthError, handler)`，统一 JSON `code=2001`。
- **ENV 列表解析报错**：`ADMIN_ALLOWED_IPS=` 空值导致 `pydantic` 无法解析 `list[str]`。字段类型兼容 `list[str] | str | None` 并在 `field_validator(mode="before")` 中统一转换，解决 DotEnv 解析问题。
- **全局 AiClient 缓存**：为便于测试自定义 provider，新增 `reset_ai_client()` 并在 `pytest` fixture 中 autouse，通过 `settings.ai_provider = "mock"` + reset 保证每次用例独立。
- **Dashboard 中文本编码残留**：旧模板存在乱码 `�?`，重写 `backend/app/api/admin.py` 文案并使用一致的 UTF-8 文本，避免 lint/syntax 问题。

## 5. 测试与验证
- 代码质量：执行 `ruff check --select I,E,F --fix backend`、`black backend`，消除 import/格式告警。
- 单/集成测试：`pytest`（PostgreSQL 临时库 + mock AI/mem0）全部通过，覆盖 29 个用例，包括：
  - `test_ai_client_mock_provider_streams_chunks` / `test_memory_service_fallback_roundtrip`
  - `test_chat_demo_returns_answer` / `test_chat_demo_reuses_memory_on_second_call`
  - 新增 `/admin/ai/summary` 鉴权、`/admin/api/routes` 未携 token 401、AI 卡片统计等
  - 既有行程 CRUD、Admin DB 统计/健康检查、健康探针等回归

示例输出：
```
======================= 29 passed, 17 warnings in 3.70s =======================
```

## 6. 后续建议
1. 结合 LangGraph/Agent 计划扩展 `AiClient` 输出模板（JSON schema 等），并在 `AiMetrics` 中记录 tokens/费用以构建计费模型。
2. 若后续部署 mem0 服务，建议在 `MemoryService` 增加健康检查/断路器，并定期将本地 fallback 内容批量写回远端，避免记忆割裂。
3. Admin AI Console 可进一步加入“多轮历史回放”和“trace 检索”，并考虑简易的 token/IP 登录页，减少 query token 暴露风险。
