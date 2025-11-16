# 阶段 1 测试文档（Tests-1）
## 1. 测试环境
- 操作系统：Windows 11 + PowerShell 7.4
- Python 解释器：D:\Development\Python\Envs\travelist+\python.exe（3.12.7）
- 关键依赖：FastAPI 0.121.2、Starlette 0.49.3、SQLAlchemy 2.0.44、httpx 0.28.1、Jinja2 3.1.6、pytest 8.3.3、ruff 0.14.5、black 25.11.0
- 容器环境：Docker Desktop 27.x（Compose v2.35.1），镜像 postgis/postgis:16-3.4、redis:7-alpine，服务端口 5432/6380
- 代码分支：main（工作副本），测试命令均在仓库根目录执行

## 2. 测试范围
1. 功能完整性：Admin Dashboard、API 在线测试、数据检查、健康状态聚合、DB/Redis 状态接口。
2. 性能稳定性：MetricsRegistry 窗口统计、健康检查 5s 缓存、API 测试耗时数据。
3. 兼容性：Windows 本地 CLI + Docker Compose 依赖服务；FastAPI/ASGI 内部调用与真实 HTTP 请求均验证。
4. 安全性：配置隔离（.env 忽略）、健康检查探针异常提示、Docker 警告记录。

## 3. 测试用例与结果
| 用例ID | 分类 | 测试步骤 | 预期结果 | 实际结果 | 结论 |
| --- | --- | --- | --- | --- | --- |
| QA-RUFF | 代码质量 | `python -m ruff check backend` | 无 lint 告警 | 输出 `All checks passed!` | 通过 |
| QA-BLACK | 代码质量 | `python -m black backend --check` | 代码均已格式化 | CLI 提示 27 files unchanged | 通过 |
| UNIT-PYTEST | 单元/集成 | `$env:PYTHONPATH='backend'; pytest` | 8 个用例通过 | `backend/tests/test_admin.py`、`test_health.py` 全部成功 | 通过 |
| FUNC-DASHBOARD | 功能 | `Invoke-WebRequest http://127.0.0.1:8081/admin/dashboard` | 返回 200，HTML 正文加载仪表盘 | HTTP 200，HTML 长度 14118，UI 渲染成功 | 通过 |
| FUNC-CHECKS | 功能 | `Invoke-RestMethod /admin/checks` | 返回 DB/Redis/Alembic 三条检查 | `db_connectivity`、`redis_connectivity` 状态 pass，`alembic_initialized`=unknown | 通过 |
| FUNC-API-TEST | 功能 | `POST /admin/api/test`（GET /healthz） | 返回 status_code=200、响应摘录 | duration 2.112ms，摘录 `{"code":0,"msg":"ok"...}` | 通过 |
| PERF-HEALTH | 性能 | `Invoke-RestMethod /admin/health`；短时间再次调用 | 第一次查询真实探针，随后命中缓存 | DB 延迟 52.497ms、Redis 6.217ms，Dashboard 多次刷新未重复建连 | 通过 |
| PERF-SUMMARY | 性能 | `GET /admin/api/summary?window=120` | 返回窗口统计和 p95 | total_requests=3，`/admin/checks` p95=136.168ms，满足 Spec | 通过 |
| COMP-DOCKER | 兼容 | `docker compose up -d postgres redis` | Postgres/Redis 成功启动 | 两服务 Running，仅输出 `version` 警告 | 通过 |
| COMP-HTTPX | 兼容 | Dashboard 中运行预设接口 & 手动请求 | httpx ASGI/HTTP 双模式可用 | UI 可执行预设和自定义测试，历史记录更新 | 通过 |
| SEC-CONFIG | 安全 | 检查 `.gitignore`、`.env`、接口响应 | 配置不入库，接口错误安全可控 | `.env` 忽略正常；健康接口在依赖异常时返回错误详情字段 | 通过 |

## 4. 真实环境测试记录
- `docker compose up -d postgres redis` 启动依赖，使用 `uvicorn backend.app.main:app --port 8081` 本机运行后，关键接口返回如下：
  * `/admin/dashboard`：HTTP 200，HTML 长度 14118。
  * `/admin/checks`：`db_connectivity` pass（延迟 ~52.5ms）、`redis_connectivity` pass（~6.2ms），`alembic_initialized` 维持 unknown（按预期提示未初始化迁移）。
  * `/admin/health`：`app=db=redis=ok`，返回 DB/Redis 延迟字段。
  * `/admin/api/summary?window=120`：统计窗口 120s，总请求 3 条，均提供 `avg_ms`/`p95_ms`。
  * `/admin/api/test`（GET `/healthz`）：status_code=200，duration≈2.1ms。
- 健康检查缓存生效：同一窗口多次刷新 `/admin/health`，无额外 DB/Redis 连接日志。

## 5. 测试结论
阶段 1 功能集（仪表盘、统计、在线测试、健康聚合、数据检查）在 Windows + Docker 组合环境下均按 Spec 工作。所有自动化测试通过；真实 Postgres/Redis 连接稳定，UI 交互满足需求。整体满足交付标准，可进入下一阶段。

## 6. 问题记录与建议
1. **Docker Compose version 警告**：v2 会提示 `version` 字段废弃，建议后续删除该字段以消除噪音。
2. **Alembic 状态为 unknown**：当前阶段尚未初始化迁移，接口提示正常；进入建表阶段需补齐 `migrations` 目录并更新检查结果。
3. **pytest-asyncio 警告**：提示 `asyncio_default_fixture_loop_scope` 未设置，不影响结果，建议未来在配置中显式指定以避免噪音。
