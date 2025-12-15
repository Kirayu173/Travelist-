# Travelist+ Backend

当前阶段：**Stage-7（行程规划 Fast 模式 + PlannerGraph + Admin 可观测）**

## 快速开始
```bash
cp .env.example .env          # 首次运行需复制并按需修改
python -m pip install -e .[dev]
python -m uvicorn backend.app.main:app --port 8081
```
> 如需热重载，可在 `backend` 目录运行 `uvicorn app.main:app --reload --port 8081`，注意 `.env` 也需在仓库根或当前目录可见。

## 项目结构（节选）
- `backend/app`：FastAPI 应用、路由、核心配置与服务
- `backend/tests`：pytest 测试套件
- `docker-compose.yml`：PostgreSQL / Redis / Backend 编排
- `scripts/`：辅助脚本（如 `test_connections.py`）
- `_docs`：分阶段规格与设计文档

## 常用命令
```bash
# 运行测试
cd backend
python -m pytest --cov=app --cov-report=xml

# 代码质量
python -m ruff check backend/app backend/tests
python -m black backend/app backend/tests --check

# Stage-7 冒烟（需服务已启动，并配置 ADMIN_API_TOKEN）
ADMIN_API_TOKEN=please-change-admin-token python scripts/smoke_stage7.py --base-url http://127.0.0.1:8000
```

## Docker Compose（可选）
```bash
# 启动数据库与 Redis（Redis 默认暴露 6380 端口以避免冲突）
docker compose up -d postgres redis

# 关闭并清理
docker compose down --volumes
```

## 环境连通性测试
如需确认 `.env` 中的 `DATABASE_URL` / `REDIS_URL` 是否可达，可执行：
```bash
cd backend
python ..\scripts\test_connections.py
```
脚本会对配置的 PostgreSQL / Redis 分别执行 `SELECT 1` / `PING` 并输出结果。

## 配置补充
- `CACHE_PROVIDER`（对应 settings.cache_provider）：`memory` / `redis`，默认为内存缓存；选择 `redis` 可在多实例间共享缓存。
- `AI_MEMORY_CACHE_TTL_SECONDS`：智能助手记忆召回缓存 TTL（秒），用于降低重复 embeddings / mem0 搜索开销。
- `AI_MEMORY_DUAL_WRITE_ENABLED`：是否开启记忆双写（session + user/trip），提升跨会话可用性。
- `AI_TOOL_SELECT_CACHE_TTL_SECONDS`：工具选择结果缓存 TTL（秒），减少短时间重复请求的 LLM 路由开销。
- 其他配置见 `.env.example` 与 `backend/app/core/settings.py`。
