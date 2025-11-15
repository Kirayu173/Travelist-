# Travelist+ Backend

阶段 0 目标：搭建 FastAPI 后端骨架、基础监控接口、容器化与 CI 管线。

## 快速开始

```bash
cp .env.example .env          # 首次运行需要拷贝并按需修改
python -m pip install -e .[dev]
python -m uvicorn backend.app.main:app --port 8081
```

> 如需热重载，可在 `backend` 目录运行 `uvicorn app.main:app --reload --port 8081`，只是要注意 `.env` 也需要复制到该目录。推荐直接在仓库根目录启动，以便统一读取根目录 `.env`。

## 项目结构（摘录）

- `backend/app`：FastAPI 应用、路由与核心配置
- `backend/tests`：pytest 测试套件
- `docker-compose.yml`：PostgreSQL / Redis / Backend 编排
- `scripts/`：辅助脚本（如 `test_connections.py`）
- `.github/workflows`：CI 流程
- `_docs`：规格文档

## 关键命令

```bash
# 运行测试
cd backend
python -m pytest --cov=app --cov-report=xml

# 代码质量
cd backend
python -m ruff check backend
python -m black backend --check
```

## Docker Compose（可选）

```bash
# 启动数据库与 Redis（无密码，Redis 暴露到 6380 以避免端口冲突）
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

脚本会对配置的 PostgreSQL 与 Redis 发起简单的 `SELECT 1` / `PING`，并在终端输出结果。
