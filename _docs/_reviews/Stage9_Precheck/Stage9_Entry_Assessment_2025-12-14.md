# Stage-9 准入评估报告（进入阶段9开发前审查）

评估日期：2025-12-14  
评估对象：Travelist+ 后端（截至 `main` 分支最新提交）  
目标：评估是否满足进入 **Stage-9（行程助手多轮对话：REST + WebSocket + 会话持久化 + 在线监控）** 的必要条件，并给出明确结论与依据。

---

## 1. 结论（是否批准进入 Stage-9）

结论：**有条件批准进入 Stage-9**。

**批准依据（满足项）**
1. Stage-8（Deep 规划 + 异步任务 ai_tasks）已形成闭环，并具备测试与审查材料（见 `_docs/Phase8/*`）。
2. Stage-5 级别的“多轮语义”基础已具备：`session_id` + `chat_sessions/messages` 持久化、SSE 流式输出、工具调用链路已存在（见 `backend/app/services/assistant_service.py`、`backend/app/api/ai.py`）。
3. 自动化测试可运行并通过（本地 `pytest -q`：`83 passed, 2 skipped`）。

**准入阻断项（必须先修复，否则 Stage-9 会被 CI/质量门禁拖垮）**
1. **CI 质量门禁当前不可通过**：`ruff` 与 `black --check` 在当前代码上失败，意味着 GitHub Actions 预计会红灯，Stage-9 迭代无法稳定回归。
   - 证据：`_docs/_reviews/Stage9_Precheck/evidence/ruff_fail.txt`、`_docs/_reviews/Stage9_Precheck/evidence/black_fail.txt`

> 建议：在 Stage-9 开工前先用 0.5~1 天把 lint/format 清零并确保 CI 全绿；否则 Stage-9 引入 WebSocket 并发与协议层复杂度后，回归成本会指数上升。

---

## 2. 计划对照与项目进度

### 2.1 阶段计划对照（来自阶段开发文档）
Stage-9 目标与任务定义见：
- `_docs/_design/阶段开发文档（4-11）.md`（阶段9段落）
- `_docs/Phase9/Spec.md`

### 2.2 当前进度评估
- **Stage-8：已完成**（从 `_docs/Phase8/Review.md`、`_docs/Phase8/Tests.md` 的闭环叙述与测试结果可佐证）。
- **Stage-9：尚未开始实现**（代码层面未发现 `/ws/assistant` WebSocket 路由与 `/admin/chat/live` 相关页面/接口；Phase9 目录当前仅有 `Spec.md`，缺少 Code/Tests/Review）。

---

## 3. 已完成功能模块质量与完整性评估

### 3.1 智能助手（Stage-5 基础能力）
已具备：
- REST 接口：`POST /api/ai/chat`（含 SSE 流式输出）
- 会话持久化：`chat_sessions/messages`（service 内持久化逻辑见 `backend/app/services/assistant_service.py`）
- 记忆：mem0 写入策略已存在（按回合写入）
- 工具：工具目录与调用链路已存在（ToolRegistry/ToolSelector/ToolAgent）

不足（与 Stage-9 目标的“原生工具编排”存在差距）：
- 当前助手仍以“自定义工具选择/自定义 tool_calls 解析 + tool agent 执行”为主（而 Stage-9 目标倾向 LangGraph `MessagesState + ToolNode + checkpointer` 的原生编排形态）。

### 3.2 规划体系（Stage-7/8）
已具备：
- 统一规划入口：`POST /api/ai/plan`（fast/deep）
- deep 异步任务：`ai_tasks` + worker + 轮询接口
- Admin 可观测：任务页、summary、规划 overview

风险提示（Stage-9 会放大）
- `ai_tasks`、`messages` 等表的增长与清理策略需提前规划（否则 Stage-9 WebSocket 多轮会显著增加写入量）。

---

## 4. 核心技术指标与工程化门禁

### 4.1 测试
- `pytest -q`：通过（`83 passed, 2 skipped`）。

### 4.2 静态质量（阻断项）
当前失败：
- `ruff check backend/app backend/tests backend/prod_tests`
- `black --check backend/app backend/tests backend/prod_tests`

证据：
- `_docs/_reviews/Stage9_Precheck/evidence/ruff_fail.txt`
- `_docs/_reviews/Stage9_Precheck/evidence/black_fail.txt`

结论：
- 质量门禁不通过会直接导致 CI 红灯（见 `.github/workflows/ci.yml`），因此应视为 Stage-9 开工前必须解决的“工程化前置”。

---

## 5. Stage-9 关键缺口清单（按优先级）

### P0（必须具备，才算 Stage-9 启动条件）
1. **CI 全绿**：修复 ruff/black 失败，确保 `.github/workflows/ci.yml` 可持续运行。
2. **WebSocket 最小可行方案落地设计确认**：
   - 路由：`/ws/assistant?user_id&session_id`
   - 消息协议：event types、chunk/result/error/DONE、cancel/heartbeat
   - 资源上限：连接数、队列 maxsize、消息大小、速率限制

### P1（Stage-9 主体交付必需）
1. WS handler 实现与生命周期管理（accept/receive/send/close、断线取消、背压）。
2. WS 对话落库闭环（按回合写入 messages；禁止逐 chunk 写入）。
3. Admin 在线监控 `/admin/chat/live`（在线连接数、活跃会话、最近错误摘要）。

### P2（强烈建议，避免 Stage-10/11 联调风险）
1. 抽象会话读写：引入 `ChatRepository`（service 与协议层解耦）。
2. 逐步迁移到原生 tool-calls 编排：ToolNode/Structured tools 导出，减少手写解析与漂移风险。
3. 压测与稳定性基线：少量并发 WS 压测脚本与指标口径（连接数/平均延迟/失败率）。

---

## 6. 风险与问题清单

1. **工程化风险（高）**：ruff/black 当前失败导致 CI 不可靠，Stage-9 引入并发与协议后会显著放大回归成本。
2. **并发与背压风险（高）**：WS 下慢客户端、发送队列膨胀、任务取消与超时控制不当会拖垮进程。
3. **数据增长风险（中）**：messages/ai_tasks 随多轮交互增长，需要保留期与清理任务（或归档策略）。
4. **安全与隔离风险（中）**：WS 必须严格校验 `session_id` 属于 `user_id`；Admin 才可跨用户观测。
5. **架构漂移风险（中）**：若 WS 与 REST 各自实现一套对话逻辑，后续会出现行为不一致与难以排障。

---

## 7. 资源配置与团队能力匹配（就代码现状可推断部分）

已具备：
- FastAPI/LangGraph/SQLAlchemy/PostGIS/Redis 的整体工程能力与测试体系；
- 对“异步任务闭环（ai_tasks + worker + admin）”已有实现经验，可复用到 WS 的连接管理/事件推送设计。

仍需重点关注：
- ASGI WebSocket 并发、背压、取消、超时等工程细节；
- 以“协议优先”的方式推进（先定消息协议与验收用例，再做实现），避免反复返工。

---

## 8. 文档完整性与规范性

现状：
- Stage-9：仅存在 `Spec.md`（`_docs/Phase9/Spec.md`），缺少 Code/Tests/Review 的交付闭环文件。

建议（不作为阻断，但建议开工当天完成骨架）：
- 新增：
  - `_docs/Phase9/Code.md`
  - `_docs/Phase9/Tests.md`
  - `_docs/Phase9/Review.md`
并在其中明确：WS 协议、验收标准、压测基线、落库口径与安全边界。

---

## 9. 建议的准入动作与时限（可执行）

### 9.1 进入 Stage-9 前（T+1 天内）
1. 修复 ruff/black（以 CI 目标范围为准：`backend/app backend/tests backend/prod_tests`）。
2. 补齐 Phase9 文档骨架（Code/Tests/Review），固化 WS 协议与验收标准。

### 9.2 Stage-9 第 1 周（建议节奏）
1. WS 路由 + 协议最小闭环（ready → user_message → chunk → result → DONE）。
2. 落库闭环与安全校验（session 归属、按回合写入、禁止 chunk 写库）。
3. Admin 在线监控最小可用（active_connections / recent_sessions）。
4. 引入背压/限流与取消机制（慢客户端保护）。

