
---

# 阶段 0 规格说明书（Spec-0）

## 1. 概述

### 1.1 阶段编号与名称

* 阶段编号：**Stage-0**
* 阶段名称：**后端基础骨架与监控雏形**

### 1.2 背景

本阶段为智能旅游 APP 项目的第一个开发阶段，目标是在现有设计文档基础上，建立一个**可运行、可观测、可测试、可容器化部署**的后端基础工程，为后续业务功能与智能体能力提供稳定底座。

### 1.3 阶段目标

阶段 0 完成后，应满足：

1. 后端项目具备清晰的目录结构与基础依赖配置。
2. FastAPI 应用可启动，对外提供 `/healthz` 与基础 `/admin` 管理接口。
3. 管理接口具备 **最小可用的 API 调用统计与健康状态聚合能力** 。
4. 后端可通过 Docker Compose 与数据库、Redis 一起启动。
5. 项目具备基础 CI 流水线，能在提交后自动执行格式检查与测试。
6. 环境变量与配置管理机制可用，开发环境启动不依赖硬编码配置。

---

## 2. 范围说明

### 2.1 本阶段实现范围

* 后端服务基础骨架（FastAPI 应用）。
* Admin 管理接口的 **监控雏形** （调用统计 + 健康聚合占位）。
* 容器化部署（`docker-compose`）。
* CI 配置（以 GitHub Actions 为例）。
* 环境配置文件与 Settings 模块。

### 2.2 不在本阶段范围

* 业务功能接口（用户、行程、POI 等）。
* 真正访问数据库、Redis 的业务逻辑。
* 智能体（LLM / LangGraph）逻辑。
* Android 客户端实现。
* 完整运维监控体系（Prometheus / Grafana 等）。

---

## 3. 总体技术与通用约定

### 3.1 技术栈约定

* 编程语言：**Python 3.12**
* Web 框架：**FastAPI**
* ASGI Server：**Uvicorn**
* 数据库： **PostgreSQL（PostGIS 镜像）** （本阶段仅作为容器依赖）
* 缓存 / 消息：**Redis**
* 测试：**pytest + pytest-cov**
* 代码风格与检查：
  * 格式化：**black**
  * 静态检查：**ruff**
* 容器编排：**docker-compose**
* CI：**GitHub Actions**

### 3.2 目录结构约定

项目根目录应符合下列结构（允许合理扩展，但不得违反主干约定）：

```text
/backend/
  app/
    __init__.py
    main.py
    api/
      __init__.py
      admin.py
      health.py
    core/
      __init__.py
      app.py
      settings.py
    services/
      __init__.py
      admin_service.py
    db/
      __init__.py
    models/
      __init__.py
    agents/
      __init__.py
    utils/
      __init__.py
  tests/
    __init__.py
    test_health.py
    test_admin.py
/infra/
  docker-compose.yml
/.github/
  workflows/
    ci.yml
/.env.example
/pyproject.toml（或等价配置文件）
/README.md
/.gitignore
```

### 3.3 代码规范

* 所有 Python 代码应通过：
  * `black` 格式化检查（`black --check`）。
  * `ruff` 静态检查。
* 测试应使用 `pytest` 组织，测试文件放置于 `backend/tests/` 目录。

### 3.4 接口返回格式约定

所有 HTTP 成功响应应采用统一结构：

```json
{
  "code": 0,
  "msg": "ok",
  "data": { ... }
}
```

错误响应本阶段可采用占位结构，例如：

```json
{
  "code": 10001,
  "msg": "error message",
  "data": null
}
```

### 3.5 测试覆盖率

本阶段要求：

* 使用 `pytest-cov` 统计覆盖率；
* 后端模块整体覆盖率应达到  **≥ 80%** 。

---

## 4. 详细功能与实现要求

本阶段拆分为 5 个任务：

T0-1：项目结构 & 版本控制

T0-2：FastAPI 后端骨架与 Admin 监控

T0-3：容器化部署（docker-compose）

T0-4：CI 流水线

T0-5：环境配置与 Settings

---

### 4.1 任务 T0-1：项目结构与基础配置

#### 4.1.1 目录与文件

 **需求 T0-1-R1** ：根目录应存在并初始化以下关键路径和文件：

* `backend/app/main.py`
* `backend/app/core/app.py`
* `backend/app/core/settings.py`
* `backend/app/api/health.py`
* `backend/app/api/admin.py`
* `backend/app/services/admin_service.py`
* `backend/tests/test_health.py`
* `backend/tests/test_admin.py`
* `infra/docker-compose.yml`
* `.github/workflows/ci.yml`
* `.env.example`
* `pyproject.toml`（或 `requirements.txt + setup.cfg` 组合）
* `README.md`
* `.gitignore`

其他 `__init__.py` 文件需按目录结构补全，以保证模块可导入。

#### 4.1.2 `.gitignore` 要求

 **需求 T0-1-R2** ：`.gitignore` 至少应包含：

* Python 相关：
  ```text
  __pycache__/
  .venv/
  .pytest_cache/
  .ruff_cache/
  .coverage
  coverage.xml
  dist/
  build/
  .env
  .env.*
  ```
* 通用系统文件：
  ```text
  .DS_Store
  ```

---

### 4.2 任务 T0-2：FastAPI 后端骨架与 Admin 监控雏形

#### 4.2.1 应用创建（`core/app.py`）

 **需求 T0-2-R1** ：应实现应用工厂函数，例如 `create_app()`，职责包括：

* 创建 `FastAPI` 实例（配置项目名称与版本号）。
* 注册 Admin 统计中间件。
* 注册以下路由模块：
  * `health` 路由（不带前缀）。
  * `admin` 路由（前缀 `/admin`，推荐 tag 为 `"admin"`）。

#### 4.2.2 应用入口（`main.py`）

 **需求 T0-2-R2** ：`app.main` 模块需暴露 `app` 变量：

```python
from app.core.app import create_app

app = create_app()
```

以保证可以通过：

```bash
uvicorn app.main:app
```

启动服务。

#### 4.2.3 Admin 统计中间件与服务（`services/admin_service.py`）

 **需求 T0-2-R3** ：应实现一个中间件，用于统计请求信息，建议特性如下：

* 记录每次请求的：
  * 请求路径
  * HTTP 方法
  * 状态码
  * 耗时（毫秒，浮点数即可）
* 使用进程内数据结构（如 `dict + Counter`）维护：
  * 每个路由（如 `"GET /healthz"`）的调用次数。
  * 每个路由最近一次请求耗时。
  * 总请求次数。

 **需求 T0-2-R4** ：应提供一个函数（如 `get_api_summary()`），返回 API 调用统计摘要，结构类似：

```python
{
  "routes": {
    "GET /healthz": {
      "count": 10,
      "last_ms": 12.3
    },
    "GET /admin/ping": {
      "count": 5,
      "last_ms": 5.6
    }
  },
  "total_requests": 15
}
```

 **需求 T0-2-R5** ：应提供健康状态聚合函数（如 `get_health_status()`）：

* 当前阶段允许返回占位值，例如：
  ```python
  {
    "app": "ok",
    "db": "unknown",
    "redis": "unknown"
  }
  ```
* 后续阶段可逐步替换为真实探测逻辑。

#### 4.2.4 路由定义（`api/health.py` 与 `api/admin.py`）

 **需求 T0-2-R6** ：`/healthz` 路由：

* method：`GET`
* path：`/healthz`
* 响应结构：
  ```json
  {
    "code": 0,
    "msg": "ok",
    "data": { "status": "ok" }
  }
  ```

 **需求 T0-2-R7** ：`/admin/ping` 路由：

* method：`GET`
* path：`/admin/ping`
* 返回字段应至少包含：
  * `version`：当前服务版本号（如 `"0.0.1"`）。
  * `time`：当前服务器时间（ISO8601 字符串）。
* 按统一返回包裹：
  ```json
  {
    "code": 0,
    "msg": "ok",
    "data": {
      "version": "0.0.1",
      "time": "2025-11-14T10:00:00Z"
    }
  }
  ```

 **需求 T0-2-R8** ：`/admin/api/summary` 路由：

* method：`GET`
* path：`/admin/api/summary`
* 应返回 `get_api_summary()` 的结果，并按统一结构包装到 `data` 中。

 **需求 T0-2-R9** ：`/admin/health` 路由：

* method：`GET`
* path：`/admin/health`
* 应返回 `get_health_status()` 的结果，并按统一结构包装到 `data` 中。

#### 4.2.5 测试用例（`tests/test_health.py`, `tests/test_admin.py`）

 **需求 T0-2-R10** ：健康检查测试应至少包含：

* `/healthz` 返回状态码 200。
* 响应 `code == 0`。
* `data.status == "ok"`。

 **需求 T0-2-R11** ：Admin 测试应至少包含：

* `/admin/ping`：
  * 状态码 200。
  * 响应中 `data.version` 存在且为字符串。
  * 响应中 `data.time` 存在且为字符串。
* `/admin/api/summary`：
  * 在调用若干次 `/healthz` 与 `/admin/ping` 之后，再调用该接口；
  * `total_requests` 值应不小于前述调用次数；
  * `routes` 字段中应包含 `"GET /healthz"` 与 `"GET /admin/ping"`。
* `/admin/health`：
  * `data` 至少包含 `"app"`, `"db"`, `"redis"` 三个键。

---

### 4.3 任务 T0-3：容器化部署（docker-compose）

#### 4.3.1 `infra/docker-compose.yml` 要求

 **需求 T0-3-R1** ：`docker-compose.yml` 中应定义至少三个服务：

* `db`：PostgreSQL + PostGIS 镜像，例如 `postgis/postgis:14-3.3`
* `redis`：Redis 镜像，例如 `redis:7`
* `backend`：运行 FastAPI 应用的服务

配置示例结构（允许等价实现）：

```yaml
version: "3.9"

services:
  db:
    image: postgis/postgis:14-3.3
    environment:
      POSTGRES_DB: appdb
      POSTGRES_USER: appuser
      POSTGRES_PASSWORD: apppass
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7
    ports:
      - "6379:6379"

  backend:
    image: python:3.12-slim   # 或使用自定义 Dockerfile
    working_dir: /app/backend
    volumes:
      - ../backend:/app/backend
    command: >
      bash -c "pip install -r requirements.txt &&
               uvicorn app.main:app --host 0.0.0.0 --port 8000"
    env_file:
      - ../.env
    ports:
      - "8000:8000"
    depends_on:
      - db
      - redis

volumes:
  pgdata:
```

---

### 4.4 任务 T0-4：CI 流水线（GitHub Actions）

#### 4.4.1 CI 工作流 `.github/workflows/ci.yml`

 **需求 T0-4-R1** ：CI 触发条件应包括：

```yaml
on:
  push:
    branches: ["main", "feat/*", "fix/*"]
  pull_request:
    branches: ["main"]
```

 **需求 T0-4-R2** ：CI Job 应包含以下步骤（可细化为多个 step）：

1. 检出代码（`actions/checkout`）。
2. 设置 Python 3.12 环境。
3. 安装后端依赖（如：`cd backend && pip install -r requirements.txt`）。
4. 执行 `ruff` 检查。
5. 执行 `black --check`。
6. 执行测试并生成覆盖率报告：
   ```bash
   cd backend
   pytest --cov=app --cov-report=xml
   ```

---

### 4.5 任务 T0-5：环境配置与 Settings 模块

#### 4.5.1 `.env.example`

 **需求 T0-5-R1** ：根目录 `.env.example` 文件应至少包含下列配置项（可包含注释）：

```env
# 应用环境
APP_ENV=development
DEBUG=true
UVICORN_HOST=0.0.0.0
UVICORN_PORT=8000

# 数据库配置（开发环境示例）
DATABASE_URL=postgresql+psycopg://appuser:apppass@localhost:5432/appdb

# Redis 配置
REDIS_URL=redis://localhost:6379/0

# 第三方 Key（占位）
GAODE_KEY=your_gaode_api_key
LLM_PROVIDER=openai
LLM_API_KEY=your_llm_key

# JWT 配置（占位）
JWT_SECRET=change_me
JWT_ALG=HS256
JWT_EXPIRE_MIN=60
```

同时 `.gitignore` 中应忽略 `.env` 与 `.env.*`。

#### 4.5.2 Settings 模块（`core/settings.py`）

 **需求 T0-5-R2** ：应实现基于 `pydantic.BaseSettings` 的配置类，例如：

* 支持读取上述环境变量；
* 指定 `.env` 文件为默认配置源；
* 提供可复用的单例 `settings` 或 `get_settings()`。

示例结构（可等价实现）：

```python
from functools import lru_cache
from pydantic import BaseSettings

class Settings(BaseSettings):
    app_env: str = "development"
    debug: bool = True
    uvicorn_host: str = "0.0.0.0"
    uvicorn_port: int = 8000

    database_url: str = "postgresql+psycopg://appuser:apppass@localhost:5432/appdb"
    redis_url: str = "redis://localhost:6379/0"

    gaode_key: str | None = None
    llm_provider: str | None = None
    llm_api_key: str | None = None

    jwt_secret: str = "change_me"
    jwt_alg: str = "HS256"
    jwt_expire_min: int = 60

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
```

---

## 5. 阶段 0 整体验收标准

阶段 0 视为完成时，应满足以下条件：

1. **基础运行**
   * 在 `backend` 目录执行：
     ```bash
     uvicorn app.main:app --reload
     ```
   * 访问以下接口均返回 HTTP 200，且响应结构符合统一格式：
     * `GET /healthz`
     * `GET /admin/ping`
     * `GET /admin/api/summary`
     * `GET /admin/health`
2. **测试与覆盖率**
   * 在 `backend` 目录执行：
     ```bash
     pytest --cov=app --cov-report=xml
     ```
   * 所有测试用例通过，覆盖率 ≥ 80%。
3. **容器运行**
   * 在 `infra` 目录执行：
     ```bash
     docker compose up -d
     ```
   * 访问 `http://localhost:8000/healthz` 返回 200 且响应结构正确。
   * 可通过 `docker compose down` 正常停止服务。
4. **CI 状态**
   * 推送代码到远程仓库后，对应提交的 CI Job（`ci`）应全部为成功状态：
     * 依赖安装成功。
     * `ruff`、`black --check` 无报错。
     * `pytest` 与覆盖率统计执行成功。
