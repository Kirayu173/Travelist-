# 阶段 2 测试文档（Tests）

## 1. 测试环境
- 操作系统：Windows 11 + WSL2（`Linux DESKTOP-3RNRFTT 6.6.87.1-microsoft-standard-WSL2`）
- Python：`python3 --version` → **3.12.3**（WSL 系统 Python）
- 依赖版本：pytest 9.0.1、alembic 1.13.x、psycopg 3.2.x、geoalchemy2 0.18.0
- 容器/数据库：
  - Docker Engine 27.x / Docker Compose v2.35.1-desktop.1
  - PostgreSQL：`postgis/postgis:16-3.4`（容器名 `travelist_postgres`，暴露 5432）
  - Redis：`redis:7-alpine`（容器名 `travelist_redis`，暴露 6380）
- 代码分支：`main`（Stage-2 最新提交）
- 数据库状态：执行 `alembic upgrade head` + `python3 -m scripts.seed_stage2_data` 后，核心表分别包含 1 条示例记录

## 2. 测试范围
1. **数据库基础设施**：Alembic 迁移、PostGIS 扩展、种子数据脚本。
2. **ORM 与 Schema**：pytest 下的 ORM CRUD、迁移执行测试。
3. **Admin 接口**：`get_db_health`、`get_db_stats`、数据检查逻辑。
4. **性能与可靠性**：实时健康延迟、表统计准确性。
5. **兼容性**：WSL 环境 + Docker Compose（postgres/redis/app）。
6. **安全性**：连接串脱敏、依赖探针异常处理。

## 3. 测试用例与结果
| 用例ID | 分类 | 测试步骤 | 预期结果 | 实际结果 | 结论 |
| --- | --- | --- | --- | --- | --- |
| MIG-001 | 数据库迁移 | `alembic upgrade head` | 成功创建 core 表、transport ENUM、PostGIS | CLI 日志显示 `Context impl PostgresqlImpl`，升级至 `20241114_01`，无错误 | 通过 |
| DATA-002 | 种子数据 | `python3 -m scripts.seed_stage2_data` | 若无示例数据则插入 1 条完整链路 | 命令输出 `Stage-2 示例数据已就绪`，重复执行自动跳过已存在记录 | 通过 |
| TEST-003 | 单元/集成 | `pytest`（WSL） | 所有 Stage-2 用例通过 | 12 个用例全部通过；运行耗时 2.73s | 通过 |
| ADMIN-004 | Admin 健康 & 统计 | `PYTHONPATH=backend python3 - <<'PY' ...` 调用 `AdminService.get_db_health/stats` | 返回 DB latency、脱敏 DSN 以及 6 张表的 row_count | 输出 `latency_ms≈59.0ms`，`engine_url=postgresql+psycopg://travelist:***@localhost:5432/travelist`，6 张表 row_count 均为 1 | 通过 |
| DEP-005 | Docker 依赖 | `docker compose up -d postgres redis` | 容器健康检查通过 | compose 输出 Healthy，Postgres/Redis 均可被 Admin 健康探针访问 | 通过 |
| APP-006 | Backend 容器 | `docker compose up -d app` → 访问 `http://localhost:8000/admin/db/health` | 应能直接返回健康数据 | 实际容器日志出现 `ModuleNotFoundError: No module named 'app'`（uvicorn 子进程无法定位包）；`curl` 请求失败 | 未通过（需修复命令/环境变量） |
| PERF-007 | 性能观测 | 读取 `get_db_health` 输出 & `get_db_stats` 生成时间 | 延迟 < 100ms；统计生成时间附带 ISO8601 | `latency_ms 59.014`，`generated_at 2025-11-16T12:24:20Z` | 通过 |
| SEC-008 | 敏感信息保护 | 检查 `get_db_health()` 返回的 `engine_url` | 应脱敏密码信息 | 返回 `postgresql+psycopg://travelist:***@localhost:5432/...`，满足要求 | 通过 |
| ORM-009 | ORM CRUD | pytest 用例 `test_orm_can_persist_full_trip_graph` | 可创建用户→行程→卡片→子行程→收藏关系并查询 | 用例通过，验证 ENUM、外键、JSON 字段写读正常 | 通过 |
| CHECK-010 | 数据检查 | `pytest backend/tests/test_admin.py::test_admin_checks_endpoint...` | `/admin/checks` 包含新检查项（postgis/core_tables/migration_version/seed_data） | 用例断言 7 个检查项全部存在 | 通过 |

## 4. 测试结论
- **数据库层**：Alembic 迁移与种子脚本在真实 PostGIS 实例上通过，核心表/索引/ENUM 的建表逻辑得到验证。
- **ORM/Schema**：pytest 覆盖了迁移与多实体 CRUD，确保 Stage-2 数据模型可直接用于后续业务。
- **Admin 能力**：实时健康/统计接口运行正常，能够反映真实延迟及行数；连接串已脱敏，避免泄露凭据。
- **容器兼容性**：数据库与 Redis 容器工作正常，但 Backend 容器仍需解决 `ModuleNotFoundError` 才能提供 HTTP 服务。
- **安全/性能**：延迟 <100ms，且健康接口在异常（容器未起）时能够给出可读错误；当前无敏感信息泄漏。

## 5. 问题记录
1. **APP-006：Backend 容器无法导入 `app` 包**  
   - 现象：`docker compose up -d app` 后，`docker logs travelist_app` 显示 `ModuleNotFoundError: No module named 'app'`。  
   - 影响：无法通过容器对外提供 Stage-2 新增的 Admin API；所有 HTTP 检查只能在本地 Python 环境执行。  
   - 建议：在 compose 中为 `app` 服务设置 `PYTHONPATH=/app/backend` 或在镜像构建阶段执行 `pip install -e .` 并以项目根为工作目录；完成后重新验证 `/admin/db/health`。

2. **性能监控指标尚为最小集**  
   - 虽然 Stage-2 已返回真实延迟，但仍缺乏更细粒度指标（例如 Redis 延迟、统计缓存）。建议在 Stage-3 引入更丰富的指标或接入外部监控。

3. **测试环境单一**  
   - 当前仅验证 WSL + Docker 组合，尚未覆盖 Windows 纯环境或 Linux 服务器环境；若后续需上线，应在 CI 或预发环境补充测试矩阵。
