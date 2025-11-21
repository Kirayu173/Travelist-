# 阶段 5 开发工作报告
## 1. 开发概要
- LangGraph 助手 v1：在 `backend/app/ai/graph` 构建 `AssistantState`、节点集与图装配，串起意图识别、记忆读取、行程查询与回答格式化，默认走 AiClient（mock 时使用规则兜底）。
- Prompt 中心：新增 `ai_prompts` 表与 `PromptRegistry`，所有提示词统一通过 key 获取/更新/恢复默认，Admin 提供可视化编辑页。
- 多轮 REST 对话：实现 `POST /api/ai/chat`，支持 session_id 自动创建/复用、mem0 写入、工具轨迹返回，流式 SSE 输出。
- 会话持久化与统计：落地 `chat_sessions`、`messages` 表，提供 `/admin/chat/summary` 会话/意图分布统计。
- Admin UI 升级：AI 调试台改造为“智能体测试台”（多轮流式调试、会话选择、记忆/工具展示），新增“提示词管理”页。

## 2. 目录与关键文件
- LangGraph 助手：`backend/app/ai/graph/state.py`、`nodes.py`、`graph_builder.py`（含 `AssistantState`、节点行为、图装配）。
- Prompt Center：`backend/app/ai/prompts.py`（默认模板、缓存、DB 覆盖、更新/重置接口）。
- 对话与服务：`backend/app/services/assistant_service.py`（多轮对话编排、会话管理、记忆写入）；`backend/app/api/ai.py` 新 `/api/ai/chat` 路由。
- Admin 与统计：`backend/app/admin/service.py`（chat summary、prompt 操作、AI Console context）、`backend/app/api/admin.py`（prompt/summary API & 页）、`backend/app/admin/templates/ai_console.html`、`ai_prompts.html`、`base.html`。
- 数据层：`backend/app/models/orm.py` 新增 `AiPrompt`、`ChatSession`、`Message`；迁移 `backend/migrations/versions/20251121_02_stage5_prompts_and_chat.py`。
- 配置：`backend/app/core/settings.py` 新增 AI 助手/Prompt 相关开关；`requirements.txt`/`pyproject.toml` 增加 `langgraph`。

## 3. 技术实现要点
1. **LangGraph 编排**
   - `AssistantNodes`：`memory_read_node`（按 session/trip/user 读取记忆），`assistant_node`（调用 AiClient 判定意图 + 本地启发式兜底），`trip_query_node`（按 intent 读取行程），`response_formatter_node`（结合记忆/行程生成回答，mock 模型走规则文案）。
   - `build_assistant_graph` 用 `StateGraph` 串联节点，intent=trip_query 时走 DB 查询分支，其余直接格式化。
   - 图输出统一转为 `AssistantState`，保留 tool_traces/ai_meta 便于观测。
2. **Prompt Registry**
   - 默认模板 `DEFAULT_PROMPTS`（intent classify/formatter/fallback/demo 等），DB 覆盖优先，缓存 TTL 可配置，支持更新/重置。
   - Admin API：`GET/PUT/POST(reset) /admin/api/prompts/{key}`，列表接口 `/admin/api/prompts`，编辑页 `/admin/ai/prompts`。
3. **多轮 REST & 流式**
   - `/api/ai/chat` 接收 `session_id`（为空则创建）、`top_k_memory`、`return_memory/tool_traces/messages` 等；SSE 事件 `chunk` + `result`，客户端 Typewriter 渲染。
   - `AssistantService`：会话验证/创建、历史加载、graph 执行、消息持久化、mem0 `write_memory`（session 优先级 > trip > user）。
4. **Admin 升级**
   - Chat Summary：`/admin/chat/summary` 返回会话总数/今日新增/消息总数/平均轮次/意图分布。
   - 智能体测试台：支持会话选择/新建、流式回复、显示记忆与工具轨迹、AI meta；默认 payload 注入。
   - 导航更新：侧边栏显示“智能体测试台”“提示词管理”。

## 4. 遇到的问题与解决方案
- **LangGraph 版本签名差异**：`add_conditional_edges` 不支持 `default`，改为显式路由函数仅返回已注册分支。
- **State 返回类型**：LangGraph 返回 `dict`/`AddableValuesDict`，新增装载为 `AssistantState` 的转换，避免属性访问报错。
- **空历史导致校验失败**：`AiMessage` 校验非空，history block 为空时不再注入 system message。
- **Admin B008 噪音**：对 admin 路由文件添加 `ruff` 局部忽略，保持 FastAPI 依赖写法。  
- **静态文件乱码**：重写 `base.html`/AI Console 模板，移除原有乱码段并同步导航文案。

## 5. 测试与验证
- 执行 `pytest`（PostgreSQL 测试库 + mock AI/mem0）：`34 passed`。关键用例：
  - `/api/ai/chat_demo` 记忆复用、mock 流式。
  - `/api/ai/chat` 会话创建/复用、消息返回、tool_traces/memory 输出。
  - Admin：AI/Chat summary 鉴权与数据、Prompt 更新/重置 API、页面 HTML 校验。
  - 迁移/模型/行程 CRUD 回归。
- 代码格式：`black backend`，`ruff check backend/app backend/tests --fix`（保留 mem0 上游文件原样）。

## 6. 后续建议
1. 为 `/api/ai/chat` 增加历史拉取接口，便于 Admin/前端切换 session 时加载旧对话。
2. Prompt 管理后续可加版本比对与只读模式（生产禁写），并将修改日志化。
3. LangGraph 节点可扩展 tools（POI/天气/规划），同时考虑 intent 分类走严格 JSON 解析与错误回退。 
4. 将 mem0/ollama 初始化日志降噪或延迟到首次需要时，加快冷启动。 
