# P2-3：Admin SQL 调试台安全加固

## 整改目标
- 降低线上误用风险：默认禁用 SQL 调试台；启用后仅允许单条 SELECT，具备超时与最大行数限制，并记录审计日志。

## 实施步骤
1. 新增配置项（默认关闭）：`backend/app/core/settings.py`、`.env.example`
   - `ADMIN_SQL_CONSOLE_ENABLED=false`
   - `ADMIN_SQL_CONSOLE_TIMEOUT_MS=1500`
   - `ADMIN_SQL_CONSOLE_MAX_ROWS=100`
2. 后端限制：`backend/app/api/admin.py`
   - 禁止空 query、多语句（`;`）、注释（`--`/`/* */`）
   - 禁止危险关键字（`pg_sleep/copy/create/alter/drop/insert/update/delete`）
   - 自动补齐 `LIMIT`（未显式提供时）
   - 设置 `SET LOCAL statement_timeout`
   - 记录 `admin.sql_test` 审计日志（client、timeout、max_rows、query_len）
3. 前端体验：`backend/app/admin/templates/db_schema.html`
   - 当 SQL 调试台禁用时禁用 Tab，并给出提示
4. 测试环境对齐：`backend/tests/conftest.py` 在测试中显式启用 console，确保原有单测通过。

## 完成时限
- 2025-12-13（已完成）

## 效果验证
- 默认情况下 `/admin/api/sql_test` 返回 404（禁用）。
- 启用后：
  - `select 1 as a` 返回 200
  - `select 1; select 2` 返回 400
  - `update ...` 返回 400
  - 运行超过超时时间的查询应被中止（依赖 Postgres statement_timeout）

## 证据材料
- 变更文件：
  - `backend/app/api/admin.py`
  - `backend/app/admin/templates/db_schema.html`
  - `backend/app/core/settings.py`
  - `.env.example`
  - `backend/tests/conftest.py`

