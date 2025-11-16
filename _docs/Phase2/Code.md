# 阶段 2 开发工作报告

## 1. 开发概述
- 依据《Spec-2》落地 PostgreSQL/PostGIS 的核心业务表，建立 Alembic 迁移体系并可无损回滚。
- 完成 SQLAlchemy ORM 与 Pydantic Schema，覆盖用户、行程、每日卡片、子行程、POI 与收藏六大实体。
- Admin 服务新增数据库健康与统计接口，Data Check 增加 PostGIS/表存在性/迁移版本/基础数据检测，并在 Dashboard 替换为真实数据。
- 扩充测试矩阵：迁移执行、ORM 写读链路、`/admin/db/*` 新接口及数据检查全覆盖，确保 Stage-2 功能具备回归防护。

## 2. 目录与关键文件
- `alembic.ini`、`backend/migrations/`：Alembic 配置、环境脚本与 `20241114_01_stage2_core_tables.py` 迁移。
- `backend/app/core/db.py`：提供 Engine/Session 工厂、`session_scope()` 事务封装，供 ORM 与 Admin 使用。
- `backend/app/models/orm.py`、`schemas.py`：核心 ORM & Pydantic 模型，封装 `TransportMode`、可移植的 `PointGeography` 类型。
- `backend/app/admin/service.py`、`api/admin.py`、`admin/templates/dashboard.html`：Admin 侧新增 `GET /admin/db/health|stats`、真实 DB 卡片及数据检查扩展。
- `backend/tests/models/`：迁移执行与 ORM CRUD 测试；`backend/tests/test_admin.py` 更新 Admin 接口/检查断言。
- `_docs/Phase2/Code.md`：本阶段开发报告。

## 3. 技术实现要点
1. **Alembic 与迁移脚本**
   - `env.py` 动态注入工程根路径并使用 `settings.database_url`，支持在线/离线执行。
   - Stage-2 迁移启用 PostGIS（PostgreSQL 方言下），创建 `transport` ENUM，并为六张核心表设置唯一约束与索引；GiST 索引用条件编译，仅在 PostgreSQL 生效。
   - 通过 `BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")` 与 `autoincrement=True` 兼容 SQLite 测试环境。
2. **ORM / Schema 设计**
   - 统一 `TimestampMixin` 管理 `created_at/updated_at`，`PointGeography` TypeDecorator 自动在 PostgreSQL/SQLite 之间切换。
   - `TransportMode` 使用 `StrEnum`，SQLAlchemy 侧 `TRANSPORT_ENUM` 配置 `native_enum=False` 以兼容通用数据库。
   - Pydantic Schema 支持嵌套（用户→行程→卡片→子行程）并预留 `lat/lng`、`ext` 等扩展字段。
3. **Admin 能力扩展**
   - `AdminService` 通过 `to_thread.run_sync` 运行 SQL 任务，提供 `get_db_health()`（脱敏 DSN、缓存延迟）、`get_db_stats()`（表行数与错误信息）。
   - Data Check 新增 PostGIS、核心表、迁移版本、基础数据四项，均基于真实数据库信息。
   - Dashboard 新增 “数据库表统计” 卡片，显示真实行数/提示；`GET /admin/db/stats` 数据用于模板直出。
4. **测试策略**
   - `backend/tests/conftest.py` 自动将测试数据库切换为临时 SQLite，运行 Alembic 迁移后再执行所有用例。
   - `test_migrations.py` 在独立数据库验证 `upgrade`/`downgrade` 全链路；`test_models.py` 构造用户-行程-POI-收藏链路验证 ORM 写读。
   - `test_admin.py` 校验新接口、数据检查名称集合以及统计回包结构。

## 4. 遇到的问题与解决方案
- **SQLite 自增主键异常**：`BigInteger` 在 SQLite 不会自动映射到 ROWID，导致 ORM 插入失败。通过在迁移与 ORM 中统一使用 `BigInteger().with_variant(Integer, "sqlite")` 并显式 `autoincrement=True` 解决。
- **测试环境缺少 geoalchemy2**：执行 Alembic 时提示模块缺失，改为在开发环境中安装 `geoalchemy2` 并在 `pyproject/requirements` 中声明依赖，保证 CI 可复现。
- **Pytest 导入 app 失败**：因包根目录未加入 `sys.path`，在 `conftest` 中在导入前手动插入 `PROJECT_ROOT` 与 `backend` 路径，恢复 `from app...` 的导入体验。
- **多数据库兼容的 PostGIS 检查**：SQLite 无 `pg_extension` 表，查询报错。Data Check 在捕获 `SQLAlchemyError` 后返回 `status="unknown"` 并提示迁移 Postgres 才能启用扩展，避免阻塞其他检查。

## 5. 测试与验证
- 依赖安装：`python3 -m pip install --break-system-packages geoalchemy2`。
- 运行 `pytest`（根目录）：
  ```
  =========================== test session starts ===========================
  platform linux -- Python 3.12.3
  collected 12 items

  backend/tests/models/test_migrations.py .                               
  backend/tests/models/test_models.py .                                    
  backend/tests/test_admin.py .........                                    
  backend/tests/test_health.py .                                           

  ======================= 12 passed, 19 warnings in 1.53s ====================
  ```
- 测试覆盖：Alembic 升降级、ORM CRUD、Admin 新路由/检查、现有 `/healthz`、Dashboard 渲染均通过。

## 6. 后续建议
1. 在 Stage-3 引入真实 PostgreSQL 与 PostGIS 容器，避免 SQLite 下 PostGIS 检查长期 `unknown`。
2. 为 `/admin/db/stats` 增加缓存或 `pg_stat_user_tables` 快速路径，减轻大表 `COUNT(*)` 压力。
3. 在 ORM 层补充 `updated_at` 自动更新事件（SQLAlchemy `onupdate` 已配置，但后续可结合触发器确保数据库级一致性）。
