# 阶段 4 测试文档（Tests）
## 1. 测试环境
- 操作系统：Windows 11（本地桌面环境）  
- Python：3.12.7（`python -m pytest` / `python -m ruff` / `python -m black`）  
- 依赖与工具：httpx 0.27.2（为兼容 Starlette TestClient，手动降级自 0.28.x）、psycopg/psycopg-binary、pytest 8.3.3、pytest-asyncio、pytest-cov、ruff、black  
- 后端服务：本地 PostgreSQL 17 + PostGIS 3.4（用户 `travelist`，库 `travelist`，已启用 `postgis` 扩展）、Redis Windows 服务（端口 6380）  
- 代码基线：`main` 分支本地工作副本（包含 mem0 缺失模块补齐、Admin 路由/模板修复）  

## 2. 测试范围
1. **功能完整性**：`/api/ai/chat_demo` 闭环（mock provider + mem0 fallback）、Admin AI 监控与控制台、Admin 数据检查/健康探针/DB Schema、行程 CRUD 回归。  
2. **性能稳定性**：pytest 全套在本地 Postgres/Redis 环境下运行，关注连接复用、迁移执行与接口稳定性。  
3. **兼容性**：Windows 本地环境 + 本地 PostGIS/Redis，httpx 版本与 Starlette 兼容性验证。  
4. **安全性**：Admin Token 鉴权（`/admin/api/*`、`/admin/ai/*`）与公开探针（`/admin/checks`、`/admin/db/*`）的行为校验。  
5. **代码质量**：ruff/black 静态检查（不自动修复），覆盖率统计。  

## 3. 测试用例与结果
| 用例ID | 分类 | 测试步骤 | 预期结果 | 实际结果 | 结论 |
| --- | --- | --- | --- | --- | --- |
| QA-RUFF | 代码质量 | `python -m ruff check backend` | 零告警 | **失败**：351 条告警（大多来自 vendored `backend/mem0/*` 的长行/B904/B905，以及 FastAPI 路由上的 B008 依赖注入告警、导入未排序等） | 未通过 |
| QA-BLACK | 代码质量 | `python -m black backend --check` | 所有文件已格式化 | **失败**：`backend/app/api/admin.py`、`backend/mem0/utils/factory.py` 将被重排 | 未通过 |
| UNIT-PYTEST | 单元/集成 | `python -m pytest --cov=app --cov-report=term` | 全部用例通过，输出覆盖率 | **通过**：29 通过/0 失败/25 警告（pytest-asyncio 默认 loop scope 提示），总覆盖率 77% | 通过 |
| FUNC-AI-CHAT | 功能 | 调用 `/api/ai/chat_demo`（mock provider，`use_memory=true` 连续两次） | 返回 `mock:` 前缀答案，第二次响应携带 `used_memory` 与 `memory_record_id` | 实测响应满足预期，trace_id 命名为 `ai-*`，记忆复用成功 | 通过 |
| FUNC-ADMIN-AI | 功能&安全 | 携带 `X-Admin-Token` 访问 `/admin/ai/summary`、`/admin/ai/console` | 200，返回 AI/ mem0 指标；控制台 HTML 可加载 | 指标字段齐全（calls/latency/mem0 错误），HTML 渲染中文正常 | 通过 |
| FUNC-ADMIN-DATA | 功能 | 访问 `/admin/checks`、`/admin/db/status`、`/admin/redis/status`、`/admin/trips/summary` | 200，返回检查项名称集合/DB&Redis 状态/行程统计 | 返回集合覆盖 db_connectivity/postgis_extension/seed_data 等；DB/Redis 均 `status=ok`；行程统计包含 recent_trips | 通过 |
| FUNC-ADMIN-DOCS | 功能 | `/admin/api-docs`、`/admin/db/schema?view=1` | HTML 含中文标题；Schema 页面渲染表结构 | 页面标题分别含 “API 文档与在线测试”“数据库结构视图”；表格可见 trips/day_cards/sub_trips 等 | 通过 |
| FUNC-ADMIN-API | 功能&安全 | `/admin/api/routes|schemas|testcases|test`（带 Token 未带 Token） | 携 Token 200 返回 JSON；缺 Token 401 code=2001 | 行为符合预期，涵盖 `/api/*` 路由/组件列举与示例调用 | 通过 |

## 4. 测试结论
- 核心功能（AI Demo + Admin AI 监控、数据检查、行程 CRUD）在本地 Postgres/Redis 环境下通过，29 条自动化用例全部绿。  
- 代码质量未达标：ruff/black 均未通过，主要受 Vendor `mem0` 长行/抽象类告警及 `app/api/admin.py` 导入/行宽影响。  
- 覆盖率 77%，低于早期阶段（Stage0 94%）。AI Client、MemoryService 及 mem0 相关模块覆盖显著不足。  
- pytest 仍有 `pytest_asyncio` 默认 loop scope 警告，建议后续在 `pyproject.toml` 配置 `asyncio_default_fixture_loop_scope=function`。  

## 5. 问题记录
1. **ruff 未通过**：351 条告警集中在 vendored `backend/mem0`（长行、抽象类、zip 严格模式等）及 FastAPI 路由 B008 依赖注入模式；需决定忽略规则或清理 Vendor 代码。  
2. **black 未通过**：`backend/app/api/admin.py`、`backend/mem0/utils/factory.py` 需要重新格式化。  
3. **依赖兼容性**：httpx 0.28.x 与 Starlette TestClient 不兼容（`Client.__init__` 签名变化）；已临时降级为 0.27.2，需在依赖中固定版本。  
4. **覆盖率缺口**：AiClient/MemoryService/mem0 引擎大量分支未被覆盖（见覆盖率报表），后续需补充针对超时、错误分支与 mem0 降级路径的测试。  
5. **警告残留**：pytest-asyncio 默认 loop scope 警告尚未处理；Admin 部分公开探针（`/admin/checks`、`/admin/db/*`）未加 Token 保护，生产环境需结合 IP 白名单或 Token。  
