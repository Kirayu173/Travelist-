# 阶段 0 测试文档（Tests）

## 1. 测试环境
- 操作系统：Windows 11 + WSL2（`Linux DESKTOP-3RNRFTT 6.6.87.1-microsoft-standard-WSL2`）
- Python 解释器：`D:\Development\Python\Envs\travelist+\python.exe`（Python 3.12.12）
- 依赖版本：ruff 0.14.5、black 25.11.0、pytest 9.0.1、coverage 7.0.0
- 容器：Docker Engine 27.x（Compose v2.35.1-desktop.1），镜像 postgis/postgis:14-3.3、redis:7、python:3.12-slim（Redis 暴露到宿主机 6380 以避免端口冲突）
- 代码分支：`main`（本地工作副本）

## 2. 测试范围
1. **功能完整性**：`/healthz`、`/admin/*` 接口、请求统计及健康探针；pytest 单元/集成测试。
2. **性能稳定性**：基于 `/admin/api/summary` 的实时统计，关注单次请求耗时与接口可用性。
3. **兼容性**：同时验证 Windows Python 环境与 Docker Compose（Linux 容器）运行效果。
4. **安全性**：基础配置隔离（`.env` 忽略、端口暴露范围）、服务依赖探针、容器日志告警。
5. **代码质量**：静态检查、格式化与覆盖率要求（≥80%）。

## 3. 测试用例与结果
| 用例ID | 分类 | 测试步骤 | 预期结果 | 实际结果 | 结论 |
| --- | --- | --- | --- | --- | --- |
| QA-RUFF | 代码质量 | `python.exe -m ruff check backend` | 无 lint 告警 | CLI 返回 `All checks passed!` | 通过 |
| QA-BLACK | 代码质量 | `python.exe -m black backend --check --workers 1` | 所有文件保持格式化 | 输出 “20 files would be left unchanged.” | 通过 |
| UNIT-PYTEST | 单元/集成 | `cd backend && python.exe -m pytest --cov=app --cov-report=xml` | 所有用例通过，覆盖率≥80% | 4 个用例通过，`coverage report` 总覆盖率 94%，关键模块 100% 覆盖 | 通过 |
| FUNC-HEALTHZ | 功能 | `docker compose up -d postgres redis` 后 `curl http://127.0.0.1:8081/healthz` | 返回 `{code:0,data.status:"ok"}` | `{"code":0,"msg":"ok","data":{"status":"ok"}}` | 通过 |
| FUNC-ADMIN-PING | 功能 | `curl http://127.0.0.1:8081/admin/ping` | 返回版本号与 ISO8601 时间 | `{"version":"0.0.1","time":"2025-11-15T03:56:55.320965+00:00"}` | 通过 |
| FUNC-ADMIN-SUMMARY | 功能 | `curl /admin/api/summary`（先访问 `/healthz`、`/admin/ping`） | routes 中包含被调接口、统计值 ≥ 调用次数 | 返回 `"GET /healthz"` 与 `"GET /admin/ping"`，`total_requests=2`，耗时 0.9~1.4ms | 通过 |
| FUNC-ADMIN-HEALTH | 功能&安全 | `curl /admin/health` | 展示 `app/db/redis` 状态且真实探针成功 | `{"app":"ok","db":"ok","redis":"ok"}` | 通过 |
| PERF-LATENCY | 性能 | 读取 API Summary 中 `last_ms` | 单次请求耗时 < 100ms | `GET /healthz`=1.429ms，`GET /admin/ping`=0.925ms | 通过 |
| COMP-DOCKER | 兼容性 | `docker compose up -d postgres redis` 并查看日志 | 容器可一次性启动，依赖正常 | PostgreSQL 暴露 5432、Redis 暴露 6380；日志显示服务成功就绪 | 通过 |
| COMP-WINDOWS | 兼容性 | 本地 Windows Python 环境执行 ruff/black/pytest | 命令可直接执行且无错 | 全部命令成功运行 | 通过 |
| SEC-ENV | 安全 | `grep -n ".env" .gitignore` + 审查 `docker-compose.yml` 端口 | `.env`、`.env.*` 被忽略；仅暴露 8081/5432/6380 | `.gitignore` 第 2-4 行包含 `.env`；compose 仅映射必要端口，服务内部通过容器名互联 | 通过 |
| SEC-DEPENDENCY | 安全 | 利用 `/admin/health` 输出确认 DB/Redis 探针 | 可检测依赖可用性 | `db/redis` 均返回 `ok`，支持进一步监控 | 通过 |

## 4. 测试结论
- 阶段 0 的主要功能、监控指标、容器化部署在指定环境下全部通过；覆盖率 94% 满足 Spec-0 要求。
- 性能方面，实时统计的单次请求耗时均在 2ms 内；Docker Compose 与本地 Python 环境均可稳定启动，满足兼容性指标。
- 安全性关注点（`.env` 隔离、端口暴露、依赖可观测性）满足当前阶段标准。

## 5. 问题记录
1. **Docker compose 警告**：CLI 多次提示 `version` 字段已废弃（Compose v2 自动忽略）。短期不影响运行，建议后续移除该字段。
2. **容器内 pip 告警**：Backend 容器安装依赖时提示 “Running pip as the 'root' user...” 。属常规提醒，若需消除可改用非 root 用户或预构建镜像。
3. **覆盖率盲区**：`app.main` 与 `app.utils.responses.error_response` 为简单包装函数，当前测试未直接触发，导致覆盖率报告显示 0% / 80%。整体覆盖率已达 94%，后续可补充针对入口与错误响应的测试。
