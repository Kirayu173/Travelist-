# 阶段 5 测试文档（Tests）
## 1. 测试环境
- 操作系统：Windows 11（本机）
- Python 解释器：`D:\Development\Python\Envs\travelist+\python.exe`（Python 3.12.12）
- 依赖版本：fastapi 0.121.3、langgraph 0.4.5、ruff 0.14.5、black 25.11.0、pytest 8.3.3（覆盖 fixture 中强制 `ai_provider=mock`，`mem0_mode=disabled`）
- 数据库：PostgreSQL（pytest 使用临时测试库，Alembic 自动升级至 `20251121_02`，包含 ai_prompts / chat_sessions / messages 表）
- 运行方式：本地 CLI 执行质量检查与 pytest；Admin/AI 手工验证通过 uvicorn `127.0.0.1:8081`
- 代码分支：`main`（本地工作副本，Stage5 变更）

## 2. 测试范围
1. **功能完整性**：LangGraph 智能助手 `/api/ai/chat`（多轮/流式）、Prompt 管理接口/UI、Admin Chat Summary、既有行程 CRUD/健康检查回归。
2. **性能稳定性**：AI 调用链路端到端响应、Admin 流式调试台逐字输出可用性。
3. **兼容性**：pytest mock provider 模式、实际 Ollama provider（本地服务）双通道验证；Admin HTML 页面。
4. **安全性**：Admin Token 鉴权、SSE 解析健壮性、记忆/行程访问越权保护（session/user 校验）。
5. **代码质量**：ruff/black/pytest 全量通过。

## 3. 测试用例与结果
| 用例ID | 分类 | 测试步骤 | 预期结果 | 实际结果 | 结论 |
| --- | --- | --- | --- | --- | --- |
| QA-RUFF | 代码质量 | `ruff check backend/app backend/tests --fix` | 无新 lint 告警 | 全部通过 | 通过 |
| QA-BLACK | 代码质量 | `python -m black backend --check` | 所有文件格式化 | 通过 | 通过 |
| UNIT-PYTEST | 单元/集成 | `pytest` | 34 用例全绿 | 34 passed（3~4s），pydantic/asyncio 仅提示弃用警告 | 通过 |
| MIG-ALEMBIC | 迁移 | `alembic upgrade head`（pytest 前自动执行） | 新表 ai_prompts/chat_sessions/messages 创建成功 | 长度/索引均创建，测试库升级/回滚正常 | 通过 |
| FUNC-AI-CHAT-REST | 功能 | `POST /api/ai/chat`（无 session_id） | 返回 session_id、answer、tool_traces、ai_meta | 200，自动创建 session，answer 来自 mock 规则，tool_traces 标记 memory_read/assistant/response_formatter | 通过 |
| FUNC-AI-CHAT-SESSION | 功能 | 连续两次 `POST /api/ai/chat` 带同一 session_id | 历史加载、messages 返回 ≥2，intent 延续 | 200，messages 返回 4 条（含本轮），intent=general_qa | 通过 |
| FUNC-AI-STREAM | 功能/稳定 | SSE 调用 `/api/ai/chat`（stream=true）| 前端逐字显示，result 事件携带 meta | Verified：浏览器 Network 显示 chunk/result 事件，气泡正常打字 | 通过 |
| FUNC-PROMPT-API | 功能/安全 | `GET/PUT/POST(reset) /admin/api/prompts/{key}`（带 Admin Token） | 可读写/恢复默认，未带 token 拒绝 | 200 时可更新/恢复；未带 token 返回 401 | 通过 |
| FUNC-ADMIN-PROMPTS-UI | 功能 | 访问 `/admin/ai/prompts` | 列表加载，编辑后保存成功 | 页面加载正常，保存/重置均成功 | 通过 |
| FUNC-ADMIN-CONSOLE | 功能 | `/admin/ai/console` 流式对话 | 可选/新建 session，展示记忆/工具轨迹/AI Meta | 交互正常，SSE 渲染稳定 | 通过 |
| FUNC-CHAT-SUMMARY | 功能 | `/admin/chat/summary` | 返回会话/消息统计、意图分布 | sessions_total/messages_total 正常递增，top_intents 返回 general_qa | 通过 |
| FUNC-SAFETY-SESSION | 安全 | `/api/ai/chat` 传入不存在/他人 session | 返回 400，阻止越权 | 验证 ValueError 提示“会话不存在或不属于该用户” | 通过 |
| PERF-AI-LATENCY | 性能 | 本机 Ollama provider 调用 `/api/ai/chat` | 响应时间 < 3s，SSE 无阻塞 | 日志示例 latency_ms≈1980ms，流式分块正常 | 通过 |
| COMP-OLLAMA | 兼容 | 启动本地 Ollama，真实 provider 流式 | 返回真实模型内容 | 通过（见日志 trace_id=ai-20251121124618-93d4f7ab） | 通过 |
| SEC-ADMIN-AUTH | 安全 | `/admin/chat/summary` / `/admin/api/prompts` 不带 token | 401 拒绝 | 实测 401，code=2001 | 通过 |

## 4. 测试结论
- 阶段 5 的核心能力（LangGraph 助手、多轮对话、记忆/行程工具、Prompt 管理、Admin 观测）均按 Spec 跑通；pytest 全绿，质量检查无阻塞。
- 流式链路在本机 Ollama 及 mock 模式下均验证可用，Admin 测试台逐字输出稳定；迁移脚本升级/降级通过。
- 未发现阻断性缺陷，可进入后续阶段；保留少量低优先级警告供后续跟踪。

## 5. 问题记录
1. **第三方包弃用警告**：pydantic/asyncio 在 pytest 时提示默认 loop scope 将变更，当前不影响功能，后续可在 pytest.ini 显式设置 `asyncio_default_fixture_loop_scope=function` 消除。
2. **Ollama 依赖时延**：首次调用会触发模型拉取，延迟在 2s 左右，建议生产环境预拉取模型或使用更轻量模型以降低冷启动时延。
3. **Admin SSE 调试日志**：前端已加入 `console.debug` 输出，若未来需要更简洁 UI 可增加日志开关避免过多前端控制台输出。*** End Patch USPARSER_AI_EXPECTED_JSON_INPUT территория ***!
