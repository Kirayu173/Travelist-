# 阶段 1 开发工作报告

## 1. 开发概述
- 依据《Spec-1》完成 Admin Dashboard、API 在线测试、DB/Redis 连通性探测与数据检查框架。
- 调整核心模块划分：新增 `app/admin`（服务、模板、Schema）、`app/core/db.py`、`app/core/redis.py`、`app/utils/metrics.py`、`app/utils/http_client.py`，统一承载监控、探测逻辑。
- 通过 Jinja2 模板渲染 `/admin/dashboard`，并在页面中嵌入 API 测试、指标刷新、数据检查等交互。

## 2. 目录与关键文件
- `backend/app/admin/service.py`：`AdminService` 聚合基础信息、API 统计、DB/Redis 状态、数据检查、在线 API 测试。
- `backend/app/admin/schemas.py`：定义 `ApiTestRequest/Result/Case` 及 `DataCheckResult` 模型，约束输入输出。
- `backend/app/admin/templates/dashboard.html`：Stage-1 规范要求的仪表盘页面（基础信息、统计、健康、测试、Data Check）。
- `backend/app/utils/metrics.py`：`MetricsRegistry` + `APIMetricsMiddleware`，支持累积统计与窗口查询，并提供测试重置函数。
- `backend/app/utils/http_client.py`：封装 httpx AsyncClient，供在线测试执行内部 API 调用。
- `backend/app/core/db.py` / `backend/app/core/redis.py`：提供连接工厂与 `check_*_health()`，真实发起 `SELECT 1`、`PING`。
- `backend/app/api/admin.py`：路由扩展，覆盖 Spec-1 所列的 JSON/HTML 接口。
- `backend/tests/test_admin.py`：新增 8 个用例覆盖 Dashboard、Summary window、API Test、Data Checks、DB/Redis 状态等核心路径。
- `_docs/Phase1/Code.md`：记录本阶段实现、问题、测试结果。

## 3. 技术实现要点
1. **MetricsRegistry**
   - 使用 `RouteStats`（count/avg/last_ms/p95）+ `RequestEvent`（用于窗口统计），以 `Lock` 保证线程安全。
   - 中间件在 `dispatch` 中记录 method/path/duration/status，可提供 `snapshot()` 与 `snapshot_window(window_seconds)`。
2. **AdminService**
   - 维护应用启动时间、预设 API 测试用例以及项目根目录引用。
   - `get_dashboard_context()` 同步基础信息 + `asyncio.gather` 聚合健康和数据检查，避免阻塞渲染。
   - `run_api_test()` 调用 `perform_internal_request(app=request.app, base_url=request.base_url, ...)`，并裁剪响应头/体，满足 Spec 要求的字段。
3. **DB/Redis 健康**
   - SQLAlchemy Engine 统一创建连接（`connect_timeout=1s`，`pool_pre_ping=True`），`anyio.to_thread` 执行 `SELECT 1`，返回 `status/latency/error`。
   - Redis 使用 `redis.asyncio` 客户端，设置 1s socket 超时，捕获异常后标记 `fail`。
4. **Data Check**
   - 针对 DB/Redis 连通性给出 `pass/fail` 与对应 level/suggestion；Alembic 检查通过是否存在 `alembic.ini` + `migrations/env.py/versions` 组合判断 `pass/fail/unknown`。
   - `/admin/checks` 与 Dashboard 都返回统一结构，便于扩展后续检查项。
5. **Dashboard UI**
   - 页面基础信息区域+网格卡片布局；表格呈现 API 路由统计与 Data Check。
   - JS 在加载后定时刷新 `/admin/api/summary?window=300` 与 `/admin/checks`，并提供预设用例一键填充 + JSON Body 输入校验。
6. **依赖与配置**
   - Requirements / pyproject 增加 `sqlalchemy>=2.0`，并清理 `requirements.txt` 中的非 ASCII 注释以兼容 pip。
   - `TestClient` fixture 调用 `reset_metrics_registry()`，保证跨测试指标隔离。

## 4. 遇到的问题与解决方案
1. **pip 解析 requirements.txt 报 UnicodeDecodeError**
   - 原文件包含中文注释，Windows 下默认 `cp936` 解码失败；改用英文注释（ASCII）彻底解决。
2. **pytest 无法导入 `app` 包**
   - 直接在根目录运行 `pytest` 时缺少 `PYTHONPATH`，通过在命令前设置 `$env:PYTHONPATH='backend'` 保持 Stage-0 的包导入策略即可，同时记录用法。
3. **DB/Redis 不可用导致接口慢**
   - 采用 `asyncio.gather` 并统一 1s 超时，同时在响应中返回 `error` 详情，既满足 Spec 的“真实探测”又避免长时间阻塞。

## 5. 测试与验证
- 依赖安装：`python -m pip install -r requirements.txt`（新增 SQLAlchemy）。
- 单元/集成测试：`$env:PYTHONPATH='backend'; pytest`，共 8 个测试全部通过，覆盖 Dashboard、Summary Window、API Test、Checks、Health 等路径。
- 手动验证：启动 `uvicorn backend.app.main:app`，浏览器访问 `/admin/dashboard` 可查看基础信息、API 统计与 Data Check 区域；使用页面预设用例运行 `/healthz`，能够展示状态码、耗时与响应体摘录；关闭/未启动 DB 或 Redis 时，`/admin/health` 与 `/admin/checks` 会将状态变更为 `fail/unknown` 并展示错误信息。

## 6. 后续建议
1. 在 `MetricsRegistry` 中引入更精细的时间窗口（环形缓冲或滑动桶），以降低事件列表增长。
2. Dashboard 可加入表格分页、错误率/柱状图展示，并对 API 测试增加历史记录。
3. 数据检查框架可抽象为可扩展注册表，Stage-2 之后可逐步增加数据质量校验项（孤儿记录、同步延迟等）。
