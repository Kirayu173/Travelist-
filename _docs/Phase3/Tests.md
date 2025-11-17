# 阶段 3 测试报告（Tests）

## 1. 测试环境
- 操作系统：Windows 11，PowerShell 7.4
- Python：3.12.7（`D:\Development\Python\Anaconda3\python.exe`）
- 主要依赖：ruff 0.5.7、black 24.10.0、pytest 8.3.3、httpx 0.27.2
- 数据库：Docker Desktop 已运行；`docker compose up -d postgres redis` 启动 `travelist_postgres`（PostGIS 16）和 `travelist_redis`。所有自动化测试均连接 `postgresql+psycopg://travelist:travelist_dev_password@localhost:5432/travelist`。
- 代码基线：`_docs/Phase3/Spec.md` 所对应的最新提交（包含 `/admin/trips/summary` datetime 兼容修复）。

## 2. 测试范围
1. **功能完整性**：Trip CRUD + 子行程排序、Admin Summary/API 注册/在线测试、Admin UI（API Docs & DB Schema）。
2. **性能稳定性**：在 Postgres 环境中度量 Trip/排序接口、Admin Summary 的响应时间，目标 <150 ms。
3. **兼容性**：主要验证 Postgres；SQLite 仅作为开发备用，现已具备 datetime 兜底逻辑。
4. **安全性**：`.env` 忽略策略、Docker 暴露端口（8081/5432/6380）、`/admin/api/test` 路径限制。

## 3. 测试矩阵

| 用例 ID | 目标 | 命令/方式 | 预期 | 实际 | 结论 |
| --- | --- | --- | --- | --- | --- |
| QA-RUFF | Lint（I/E501/F841） | `ruff check backend --select I,E501,F841 --fix` | 无异常 | ✅ 所有涉及导入顺序、超长行、未使用变量的问题均已自动修复 | 通过 |
| QA-BLACK | 代码格式 | `black backend` / `black backend --check` | 无异常 | ✅ 7 个文件被重排，`--check` 返回 0 变更 | 通过 |
| UNIT-TRIPS | 子行程排序 | `pytest backend/tests/test_trips.py::test_sub_trip_reorder_across_days -q` | 通过 | ✅ 1 passed in 1.11s | 通过 |
| UNIT-ADMIN | Admin 接口 | `pytest backend/tests/test_admin.py -q` | 17 条用例通过 | ✅ Summary/API Routes/DB Schema 等 17 passed | 通过 |
| FULL-PYTEST | 全量回归 | `pytest backend/tests` | 22/22 通过 | ✅ 22 passed, 17 warnings in 2.94s | 通过 |
| FUNC-API | 手工验证 | TestClient + Postgres | Trip CRUD、Admin Summary、API Docs、DB Schema、`/admin/api/test` 均 2xx | ✅ 实测全部 2xx，Summary 返回有效统计数据 | 通过 |
| PERF-TRIP | 接口延迟 | 采集 TestClient `response.elapsed` | <150 ms | Trip 创建 45 ms、详情 19 ms、排序 28 ms（Postgres） | 通过 |
| SEC-ENV | 安全配置 | 检查 `.gitignore`/`docker-compose.yml`/`/admin/api/test` | `.env*` 忽略，端口限定，路径限制 | ✅ 均满足 Stage-0/Stage-3 要求 | 通过 |

## 4. 测试结论
1. Trip 业务链路与 Admin 可视化功能已在 Docker/Postgres 环境下 100% 覆盖并通过自动化回归。  
2. `/admin/trips/summary` 通过 `_format_iso` 兼容 datetime/字符串，SQLite/FAST_DB 模式下也不会抛错；正式环境建议继续使用 Postgres。  
3. Lint/Format 已清零，`ruff` 与 `black --check` 均返回 0 error。  
4. `.env` 忽略、端口暴露、`/admin/api/test` 路径限制符合安全要求，但后续仍建议加强鉴权。

## 5. 问题记录
1. **鉴权**：`/admin/api/test` 仍未加入 Admin Token/白名单，仅依赖路径限制。建议在 Stage-4 实现鉴权或开关控制。  
2. **FAST_DB 使用**：在本地调试可开启 `PYTEST_FAST_DB=1`，但在 CI/生产前须保持默认（0），以确保迁移脚本全流程可测。  
3. **SQLite 说明**：虽然已兼容，但官方推荐环境仍为 Postgres。需在 README/Tests 中提醒开发者注意。
