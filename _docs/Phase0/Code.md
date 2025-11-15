# 阶段 0 开发工作报告

## 1. 开发概述
- 依据《Spec-0》完成后端骨架、监控接口、配置管理、容器化与 CI。
- 所有核心模块位于 `backend/app`，测试存放于 `backend/tests`，并通过根目录 `pyproject.toml` 统一管理依赖与工具链。

## 2. 目录与关键文件
- `backend/app/core/settings.py`：基于 `pydantic-settings` 的配置中心，提供 `settings` 单例。
- `backend/app/core/app.py`：FastAPI 应用工厂，注册中间件及路由。
- `backend/app/services/admin_service.py`：请求统计中间件、API 摘要与健康聚合占位。
- `backend/app/api/*.py`：`/healthz` 与 `/admin` 系列接口。
- `backend/tests/`：pytest + TestClient 单元与集成测试。
- `docker-compose.yml`：PostgreSQL、Redis、Backend 三服务编排（统一放在根目录）。
- `scripts/test_connections.py`：用于验证 `.env` 中的数据库与 Redis 连接串。
- `.github/workflows/ci.yml`：CI 触发配置、ruff/black/pytest 流程。
- `.env.example`：环境变量示例。

## 3. 技术实现要点
1. **配置管理**：使用 `SettingsConfigDict` 指定 `.env` 为默认配置源，支持版本、端口、数据库、Redis、LLM/JWT 等变量。
2. **应用工厂**：`create_app()` 负责构建 FastAPI 实例并装配 `APIMetricsMiddleware`、健康与管理路由，统一响应格式由 `app/utils/responses.py` 提供。
3. **监控雏形**：
   - 中间件使用 `perf_counter` 统计请求耗时，并以线程安全字典记录 `count/last_ms/last_status`。
   - `get_api_summary()` 返回 `routes` + `total_requests` 结构；`get_health_status()` 暂返回占位状态。
4. **健康探针**：引入 `psycopg` 与 `redis` 客户端，真实发起 `SELECT 1` 与 `PING`，超时后降级为 `"error"`，并保持 API 响应包格式不变。
5. **API 设计**：
   - `GET /healthz`、`GET /admin/ping`、`GET /admin/api/summary`、`GET /admin/health` 全部遵循 `{code,msg,data}` 包装。
   - `/admin/ping` 返回版本号与 ISO8601 时间。
6. **测试策略**：利用 `conftest.py` 统一构造 `TestClient` 并在每次测试前调用 `reset_metrics()`，覆盖健康检查、管理接口与统计指标。

## 4. 遇到的问题与解决方案
- **PEP 668 限制 pip 安装**：系统为 externally managed，`python3 -m venv` 因缺少 `python3.12-venv` 失败。改用 `python3 -m pip install --break-system-packages -e .[dev]` 在用户目录安装依赖，完成测试环境搭建。
- **ruff 配置升级提示**：根据 0.4+ 新规范把 `select` 移到 `[tool.ruff.lint]`，同时结合 `ruff --fix` 与手动编辑解决导入排序、长行等告警。
- **指定 Windows 虚拟环境联调**：使用 `D:\Development\Python\Envs\travelist+\python.exe` 安装依赖并运行 `ruff`、`black --workers 1 --check`、`pytest --cov`，满足用户“固定解释器”要求。
- **Docker 端口冲突**：宿主机已有 PostgreSQL/Redis 占用 `5432/6379`，最终调整为“根目录 docker-compose + PostgreSQL 暴露 5432、Redis 暴露 6380”的方式，并在 `.env` 中直接指向 `localhost`；借助 `scripts/test_connections.py` 进行连通性验证后，`/admin/health` 能稳定返回 `{"db":"ok","redis":"ok"}`。
- **uvicorn --reload 在 WSL 调用 Windows 解释器时重新加载失败**：由于 reloader 进程在 `D:\Development\Python\Envs\travelist+\python.exe` 启动时无法再被 WSL 的 `timeout` 包裹，改为从仓库根目录执行 `python -m uvicorn backend.app.main:app`，并保留 `curl` 证据。

## 5. 测试与验证
- 代码质量：在指定 Windows 解释器中运行 `python.exe -m ruff check backend`、`python.exe -m black backend --check --workers 1`，全部通过。
- 单元/集成测试：`cd backend && python.exe -m pytest --cov=app --cov-report=xml`，4 个用例通过并生成 `coverage.xml`，覆盖率 ≥ 80%。
- Docker Compose：`docker compose up -d postgres redis` 启动依赖（Redis 暴露 6380），待依赖就绪后运行 `python -m uvicorn backend.app.main:app --port 8081`，`curl http://127.0.0.1:8081/healthz` 与 `curl http://127.0.0.1:8081/admin/health` 分别返回 `{"status":"ok"}` 与 `{"app":"ok","db":"ok","redis":"ok"}`；最后 `docker compose down --volumes` 清理现场。

## 6. 后续建议
1. 在后续阶段扩展 `get_health_status()`，增加数据库与 Redis 的真实探测。
2. 根据业务需求丰富 `/admin` 指标，如平均耗时、错误率等。
3. 建议在 Stage-1 引入自定义后端镜像与多环境配置，提升容器启动与部署效率。
