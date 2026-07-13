# 第一阶段工程骨架与基础设施 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从当前只有文档和低保真展示的仓库建立第一条可运行闭环：固定依赖、启动 PostgreSQL/Redis/Chroma、迁移数据库、运行 FastAPI/Celery/Vue、完成管理员认证、健康检查、Operation/Outbox 幂等证明、OpenAPI 客户端生成和 CI。

**Architecture:** 后端保持模块化单体，FastAPI 路由和 Celery task 只调用 application service；PostgreSQL 是认证和任务状态真源，Redis 只作 broker/限流，Chroma 在本阶段只建立连接与契约，文件通过 LocalStorageAdapter。前端从 v3-admin-vite 固定 commit 导入可复用基座，删除 demo 业务，所有 API 类型由后端 OpenAPI 生成。

**Tech Stack:** Python 3.13.9、uv 0.11.28、FastAPI 0.139.0、SQLAlchemy 2.0.51、Alembic 1.18.5、Celery 5.6.3、PostgreSQL 17.10、Redis 7.4.9、Chroma 1.5.9、Node 24.16.0、pnpm 11.12.0、Vue 3.5.39、Vite 7.3.6、TypeScript 5.9.3、Element Plus 2.14.2。

---

## 0. 执行边界和成功标准

本计划只实现 `docs/requirements/99-development-readiness.md` 第 4 节的第一阶段边界。MinerU、模型 Provider、数据上传/解析、知识库、检索算法、机器人和外部渠道业务不在本阶段创建空接口、空表或假实现。

成功标准：

1. 从空环境按根 README 启动依赖、迁移、API、Worker 和前端。
2. 初始管理员只初始化一次，登录/首次改密/logout/CSRF/authVersion/限流行为有测试。
3. `/api/v1/health/live`、`ready`、`dependencies` 返回稳定 DTO 和 traceId，并正确区分依赖状态。
4. 一个测试业务命令能在同一事务创建 Operation 和 Outbox；重复投递只有一次副作用。
5. 前端通过 generated client 完成登录、读取管理员、读取健康和查看最小任务列表。
6. 后端 lint/typecheck/unit/integration、前端 lint/typecheck/unit/build、OpenAPI 漂移检查和 Playwright smoke 在 CI 通过。
7. 工作区没有真实 secret、浮动依赖、未归类生成物或生产占位实现。

## 1. 文件结构锁定

第一阶段创建或修改以下责任边界；未列出的业务模块不创建。

```text
README.md                              根启动、检查和目录说明
.python-version                       Python 3.13.9
.node-version                         Node 24.16.0
package.json                          根命令和 pnpm 版本

backend/
  pyproject.toml                      后端直接依赖和工具配置
  uv.lock                             uv 生成的传递依赖锁
  alembic.ini                         Alembic 入口
  app/
    main.py                           ASGI 导出，不含业务逻辑
    bootstrap/
      application.py                  FastAPI 装配
      celery_app.py                   Celery 装配和队列配置
      dependencies.py                 基础依赖装配
    core/
      config.py                       强类型启动配置
      errors.py                       AppError/ApiError 和映射
      ids.py                          UUID/trace context
      logging.py                      structlog 脱敏和配置
      middleware.py                   traceId/安全头/CSRF 门禁
      schemas.py                      camelCase ApiModel
      security.py                     Argon2/JWT/CSRF/AES-GCM 基元
    modules/
      auth/                            管理员领域、服务、端口、DTO、路由
      capabilities/                    显式能力注册、DTO、路由
      observability/                   健康检查编排、DTO、路由
      tasks/                           Operation/Outbox 领域、服务、端口、DTO、路由、薄 task
    infrastructure/
      database/                        engine/session、ORM、repository 实现
      redis/                           client、登录限流、健康实现
      storage/                         LocalStorageAdapter
      vector/                          Chroma 健康 client
  migrations/
    env.py
    script.py.mako
    versions/0001_foundation.py
  scripts/
    export_openapi.py
  tests/
    unit/
    integration/
    api/

frontend/
  TEMPLATE_UPSTREAM.md                模板版本、commit、许可证和改动边界
  package.json / pnpm-lock.yaml        精确前端依赖
  openapi-ts.config.ts                generated client 配置
  src/api/generated/                  生成代码，禁止手改
  src/api/client/                     Cookie/CSRF/traceId/错误适配
  src/features/auth/                  登录和管理员状态
  src/features/health/                基础运行状态
  src/features/tasks/                 最小任务列表/详情
  src/layouts/                         沿用并收敛模板布局
  src/router/                          第一阶段真实可达路由
  tests/                               Vitest
  e2e/                                Playwright smoke

deploy/
  compose/compose.deps.yml             Windows 开发依赖
  env/.env.development.example         无真实 secret 的示例
  scripts/wait-for-dependencies.ps1    开发健康等待
  tests/test-compose.ps1               Compose 静态门禁

scripts/
  check.ps1                            根一键检查
  dev-status.ps1                       本地状态摘要

.github/workflows/ci.yml               完整基础阶段 CI
```

## 2. 全阶段命令约定

所有命令从仓库根 `D:\RAG知识库` 执行：

```powershell
uv sync --project backend --frozen --all-groups
uv run --project backend pytest backend/tests -m "not integration"
uv run --project backend ruff check backend/app backend/tests
uv run --project backend mypy backend/app

pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend run lint
pnpm --dir frontend run typecheck
pnpm --dir frontend run test:unit
pnpm --dir frontend run build

docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml up -d --wait
. ./deploy/scripts/import-env.ps1 -Path deploy/env/.env.development
uv run --project backend alembic -c backend/alembic.ini upgrade head
uv run --project backend uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8001
```

`deploy/env/.env.development` 是从 example 创建的本机文件并被 Git 忽略；CI 使用 GitHub Actions job environment，不提交运行 secret。

### Task 1: 建立开发分支和仓库级版本锁

**Files:**
- Create: `README.md`
- Create: `.python-version`
- Create: `.node-version`
- Create: `package.json`
- Create: `scripts/check-repository.ps1`
- Modify: `.gitignore`
- Modify: `.gitattributes`

- [ ] **Step 1: 使用隔离 worktree 创建阶段分支**

先调用 `superpowers:using-git-worktrees`，从最新 `main` 创建 `codex/phase-01-foundation`。验证：

```powershell
git branch --show-current
git status --short --branch
```

Expected: 当前分支为 `codex/phase-01-foundation`，工作区无未提交变更。

- [ ] **Step 2: 先写仓库结构失败检查**

`scripts/check-repository.ps1` 使用明确路径，不递归执行未知脚本：

```powershell
$ErrorActionPreference = "Stop"
$required = @(
  ".python-version",
  ".node-version",
  "package.json",
  "backend/pyproject.toml",
  "frontend/package.json",
  "deploy/compose/compose.deps.yml"
)

$missing = $required | Where-Object { -not (Test-Path -LiteralPath $_) }
if ($missing.Count -gt 0) {
  throw "Missing required repository paths: $($missing -join ', ')"
}

if ((Get-Content -Raw -LiteralPath ".python-version").Trim() -ne "3.13.9") {
  throw ".python-version must be 3.13.9"
}
if ((Get-Content -Raw -LiteralPath ".node-version").Trim() -ne "24.16.0") {
  throw ".node-version must be 24.16.0"
}
```

Run:

```powershell
pwsh -NoProfile -File scripts/check-repository.ps1
```

Expected: FAIL，至少报告 `backend/pyproject.toml` 等路径缺失。

- [ ] **Step 3: 创建运行时和根代理命令文件**

`.python-version`：

```text
3.13.9
```

`.node-version`：

```text
24.16.0
```

根 `package.json` 只代理唯一的 Node 包，不建立 pnpm workspace，避免锁文件位置产生双重真源：

```json
{
  "name": "enterprise-rag-knowledge-base",
  "private": true,
  "packageManager": "pnpm@11.12.0",
  "engines": {
    "node": "24.16.0",
    "pnpm": "11.12.0"
  },
  "scripts": {
    "frontend:dev": "pnpm --dir frontend dev",
    "frontend:check": "pnpm --dir frontend check",
    "frontend:generate-api": "pnpm --dir frontend generate:api"
  }
}
```

扩充 `.gitignore`，保留 generated client 和锁文件，但忽略本机配置与运行数据：

```gitignore
/deploy/env/.env.development
/backend/.venv/
/backend/.mypy_cache/
/backend/.pytest_cache/
/backend/.ruff_cache/
/frontend/playwright-report/
/frontend/test-results/
/storage/
!deploy/env/.env.development.example
!frontend/.env.example
```

- [ ] **Step 4: 写根 README 的可执行入口**

`README.md` 必须包含：项目边界、`docs/requirements` 真源声明、目录树、Windows 前置条件、复制 example env、启动依赖、迁移、API/Worker/前端命令、检查命令和“不把 MinerU/模型密钥写入 env”的说明。所有命令使用本计划第 2 节的根目录形式。

- [ ] **Step 5: 暂时验证预期仍失败并提交原子变更**

Run:

```powershell
pwsh -NoProfile -File scripts/check-repository.ps1
git diff --check
```

Expected: 结构检查仍因后续目录缺失而失败；`git diff --check` 无本任务新增格式错误。

Commit:

```powershell
git add README.md .python-version .node-version package.json scripts/check-repository.ps1 .gitignore .gitattributes
git commit -m "chore: lock repository runtimes"
```

### Task 2: 创建 PostgreSQL、Redis 和 Chroma 开发基础设施

**Files:**
- Create: `deploy/compose/compose.deps.yml`
- Create: `deploy/env/.env.development.example`
- Create: `deploy/scripts/import-env.ps1`
- Create: `deploy/scripts/wait-for-dependencies.ps1`
- Create: `deploy/tests/test-compose.ps1`

- [ ] **Step 1: 先写镜像和端口静态失败测试**

`deploy/tests/test-compose.ps1`：

```powershell
$ErrorActionPreference = "Stop"
$compose = Get-Content -Raw -LiteralPath "deploy/compose/compose.deps.yml"
$expectations = @(
  'postgres:17.10-bookworm@sha256:5530681ea5d3e2ed4ce396f9b5cb443efbac6baf2a8a19c0c0635e40ae7eadce',
  'redis:7.4.9-bookworm@sha256:b2b95679e3b46fb51864949ed25ea976fc3a6bcc00a40a1bc00d568cb2822e50',
  'chromadb/chroma:1.5.9@sha256:1e0b73a187a28757c572acba508c46f48c9e8b0acaf5c20e6d95cdedce1acdf6',
  '127.0.0.1:${POSTGRES_PORT:-5432}:5432',
  '127.0.0.1:${REDIS_PORT:-6379}:6379',
  '127.0.0.1:${CHROMA_PORT:-8000}:8000'
)

foreach ($expected in $expectations) {
  if (-not $compose.Contains($expected)) {
    throw "Compose contract missing: $expected"
  }
}

if ($compose -match "(?m)^\s*image:\s*[^\r\n]*:latest") {
  throw "Floating latest image is forbidden"
}
```

Run:

```powershell
pwsh -NoProfile -File deploy/tests/test-compose.ps1
```

Expected: FAIL，因为 Compose 文件尚不存在。

- [ ] **Step 2: 创建固定 digest 的 Compose**

`deploy/compose/compose.deps.yml`：

```yaml
name: enterprise-rag-dev

services:
  postgres:
    image: postgres:17.10-bookworm@sha256:5530681ea5d3e2ed4ce396f9b5cb443efbac6baf2a8a19c0c0635e40ae7eadce
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-rag_kb}
      POSTGRES_USER: ${POSTGRES_USER:-rag_app}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}
    ports:
      - "127.0.0.1:${POSTGRES_PORT:-5432}:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 20
      start_period: 10s
    restart: unless-stopped

  redis:
    image: redis:7.4.9-bookworm@sha256:b2b95679e3b46fb51864949ed25ea976fc3a6bcc00a40a1bc00d568cb2822e50
    command: ["redis-server", "--appendonly", "yes", "--appendfsync", "everysec"]
    ports:
      - "127.0.0.1:${REDIS_PORT:-6379}:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 20
    restart: unless-stopped

  chroma:
    image: chromadb/chroma:1.5.9@sha256:1e0b73a187a28757c572acba508c46f48c9e8b0acaf5c20e6d95cdedce1acdf6
    ports:
      - "127.0.0.1:${CHROMA_PORT:-8000}:8000"
    volumes:
      - chroma_data:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v2/heartbeat"]
      interval: 5s
      timeout: 5s
      retries: 20
      start_period: 10s
    restart: unless-stopped

volumes:
  postgres_data:
  redis_data:
  chroma_data:
```

`deploy/env/.env.development.example` 只放开发值：

```env
APP_ENV=development
APP_VERSION=0.1.0
API_BASE_URL=http://127.0.0.1:8001
FRONTEND_ORIGIN=http://127.0.0.1:5173

POSTGRES_DB=rag_kb
POSTGRES_USER=rag_app
POSTGRES_PASSWORD=local-dev-only-change-before-sharing
POSTGRES_PORT=5432
DATABASE_URL=postgresql+psycopg://rag_app:local-dev-only-change-before-sharing@127.0.0.1:5432/rag_kb

REDIS_PORT=6379
REDIS_URL=redis://127.0.0.1:6379/0

CHROMA_PORT=8000
CHROMA_HOST=127.0.0.1
STORAGE_ROOT=./storage

JWT_SIGNING_KEY=local-development-jwt-key-32-bytes-minimum
CREDENTIAL_ENCRYPTION_KEY=bG9jYWwtZGV2LWNyZWRlbnRpYWwta2V5LTAwMDAwMDE=
INITIAL_ADMIN_USERNAME=admin
INITIAL_ADMIN_PASSWORD=Local-Development-Admin-Password-01!
ACCESS_TOKEN_EXPIRE_MINUTES=10080

PARSING_WORKER_CONCURRENCY=2
INDEXING_WORKER_CONCURRENCY=2
CHAT_WORKER_CONCURRENCY=4
MINERU_POLL_TIMEOUT_SECONDS=1800

CHAT_TRACE_RETENTION_DAYS=30
CONVERSATION_RETENTION_DAYS=30
OPERATION_RETENTION_DAYS=90
AUDIT_RETENTION_DAYS=180
TEMP_ATTACHMENT_RETENTION_HOURS=24

ALLOW_PRIVATE_CALLBACKS=false
ENABLE_PRODUCTION_OPENAPI=false
```

这些值只允许 `APP_ENV=development` 本机使用；生产环境必须由部署 secret 注入独立高熵值。MinerU Token 和模型 Provider Key 不放入该文件。

- [ ] **Step 3: 创建 PowerShell env 导入脚本**

`deploy/scripts/import-env.ps1` 接受固定参数 `-Path`，逐行跳过空行和 `#`，按第一个 `=` 分割并设置当前进程环境变量；拒绝无 `=`、空 key 和重复 key。值保持原文，不执行变量展开、命令替换或 PowerShell 表达式。

使用方式：

```powershell
. ./deploy/scripts/import-env.ps1 -Path deploy/env/.env.development
```

导入后检查 `APP_ENV` 必须为 development；脚本不得打印任何变量值。

- [ ] **Step 4: 创建健康等待脚本**

`deploy/scripts/wait-for-dependencies.ps1` 读取 Compose JSON 状态，最多等待 120 秒；任何容器 exited/unhealthy 立即输出 `docker compose ps` 和最近 100 行日志后退出 2，全部 healthy 退出 0。脚本只操作固定文件 `deploy/compose/compose.deps.yml`。

- [ ] **Step 5: 运行静态和 Compose 解析验证**

```powershell
Copy-Item deploy/env/.env.development.example deploy/env/.env.development
pwsh -NoProfile -File deploy/tests/test-compose.ps1
docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml config --quiet
```

Expected: 两个命令 exit 0；解析后的三个 image 都含 digest。

- [ ] **Step 6: 启动 Docker Desktop 后运行真实健康检查**

```powershell
docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml up -d --wait
docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml ps
```

Expected: `postgres`、`redis`、`chroma` 均为 running/healthy。若 Docker Desktop 未启动，本步骤是环境阻塞，不修改 Compose 绕过。

- [ ] **Step 7: 提交基础设施**

```powershell
git add deploy/compose/compose.deps.yml deploy/env/.env.development.example deploy/scripts/import-env.ps1 deploy/scripts/wait-for-dependencies.ps1 deploy/tests/test-compose.ps1
git commit -m "chore: add pinned development services"
```

### Task 3: 固定后端依赖和工具门禁

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/uv.lock` (generated)
- Create: `backend/app/__init__.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/unit/test_dependency_baseline.py`

- [ ] **Step 1: 写失败的依赖版本测试**

`backend/tests/unit/test_dependency_baseline.py`：

```python
from importlib.metadata import version


def test_direct_runtime_dependencies_are_locked() -> None:
    expected = {
        "fastapi": "0.139.0",
        "sqlalchemy": "2.0.51",
        "alembic": "1.18.5",
        "celery": "5.6.3",
        "redis": "6.4.0",
        "chromadb": "1.5.9",
        "pydantic": "2.13.4",
    }
    assert {name: version(name) for name in expected} == expected
```

Run:

```powershell
python -m pytest backend/tests/unit/test_dependency_baseline.py -v
```

Expected: FAIL，因为后端项目环境尚未建立。

- [ ] **Step 2: 创建完整 `backend/pyproject.toml`**

```toml
[project]
name = "enterprise-rag-backend"
version = "0.1.0"
description = "Enterprise RAG knowledge base backend"
requires-python = "==3.13.*"
dependencies = [
  "alembic==1.18.5",
  "argon2-cffi==25.1.0",
  "celery[redis]==5.6.3",
  "chromadb==1.5.9",
  "cryptography==49.0.0",
  "fastapi==0.139.0",
  "httpx==0.28.1",
  "psycopg[binary,pool]==3.3.4",
  "psycopg-pool==3.3.1",
  "pydantic==2.13.4",
  "pydantic-settings==2.14.2",
  "PyJWT==2.13.0",
  "python-multipart==0.0.32",
  "redis==6.4.0",
  "sqlalchemy==2.0.51",
  "structlog==26.1.0",
  "uvicorn[standard]==0.51.0",
]

[dependency-groups]
dev = [
  "asgi-lifespan==2.1.0",
  "freezegun==1.5.5",
  "mypy==2.2.0",
  "pytest==9.1.1",
  "pytest-asyncio==1.4.0",
  "pytest-cov==7.1.0",
  "respx==0.23.1",
  "ruff==0.15.21",
  "testcontainers==4.14.2",
]

[tool.pytest.ini_options]
addopts = "-ra --strict-config --strict-markers"
pythonpath = ["."]
testpaths = ["tests"]
markers = [
  "integration: requires Docker development services",
]

[tool.ruff]
target-version = "py313"
line-length = 100
src = ["app", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "ASYNC", "S", "RUF"]
ignore = ["S101"]

[tool.mypy]
python_version = "3.13"
strict = true
plugins = ["pydantic.mypy"]
files = ["app"]
warn_unreachable = true

[tool.coverage.run]
branch = true
source = ["app"]

[tool.coverage.report]
show_missing = true
fail_under = 80
```

- [ ] **Step 3: 生成并冻结 uv 锁文件**

```powershell
uv lock --project backend --python 3.13.9
uv sync --project backend --frozen --all-groups
```

Expected: `backend/uv.lock` 创建；解析出的 Redis Python client 为 6.4.0，且没有依赖冲突。

- [ ] **Step 4: 运行依赖、Ruff 和 mypy 基线**

```powershell
uv run --project backend pytest backend/tests/unit/test_dependency_baseline.py -v
uv run --project backend ruff check backend/app backend/tests
uv run --project backend mypy backend/app
```

Expected: 全部 exit 0。

- [ ] **Step 5: 提交后端依赖锁**

```powershell
git add backend/pyproject.toml backend/uv.lock backend/app/__init__.py backend/tests/__init__.py backend/tests/unit/test_dependency_baseline.py
git commit -m "chore: lock backend dependencies"
```

### Task 4: 实现配置、camelCase DTO、统一错误和 traceId

**Files:**
- Create: `backend/app/core/config.py`
- Create: `backend/app/core/schemas.py`
- Create: `backend/app/core/ids.py`
- Create: `backend/app/core/errors.py`
- Create: `backend/app/core/logging.py`
- Create: `backend/app/core/middleware.py`
- Create: `backend/app/bootstrap/application.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/unit/core/test_config.py`
- Create: `backend/tests/unit/core/test_schemas.py`
- Create: `backend/tests/api/test_error_and_trace_contract.py`

- [ ] **Step 1: 写配置和 DTO 失败测试**

关键断言：

```python
def test_api_model_serializes_camel_case() -> None:
    class Example(ApiModel):
        trace_id: str

    assert Example(trace_id="abc").model_dump(by_alias=True) == {"traceId": "abc"}


def test_production_rejects_weak_initial_password(base_env: dict[str, str]) -> None:
    base_env.update(APP_ENV="production", INITIAL_ADMIN_PASSWORD="admin123")
    with pytest.raises(ValidationError):
        Settings(**base_env)
```

API 契约测试使用 `TestClient(create_app(settings))`，断言：

```python
assert response.headers["X-Trace-Id"] == response.json()["traceId"]
assert UUID(response.json()["traceId"])
assert response.json() == {
    "code": "RESOURCE_REVISION_CONFLICT",
    "message": "测试冲突",
    "traceId": response.json()["traceId"],
    "details": {"current": "old"},
}
```

Run:

```powershell
uv run --project backend pytest backend/tests/unit/core backend/tests/api/test_error_and_trace_contract.py -v
```

Expected: FAIL，导入的 core 和 app factory 尚不存在。

- [ ] **Step 2: 实现共享 DTO 和 trace context**

`backend/app/core/schemas.py` 核心接口：

```python
from pydantic import BaseModel, ConfigDict


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
    )
```

`backend/app/core/ids.py` 提供 `new_uuid() -> UUID`、`parse_or_create_trace_id(value: str | None) -> UUID`、`trace_id_context: ContextVar[UUID | None]`。只接受合法 UUID 请求头，非法值生成新 UUID，不能让客户端注入任意日志文本。

- [ ] **Step 3: 实现强类型 Settings**

`Settings` 固定字段与 `12-deployment-source.md` 第 6 节一致，使用 `SettingsConfigDict(env_file=None, case_sensitive=False, extra="forbid")`。关键校验：

```python
class Settings(BaseSettings):
    app_env: Literal["development", "test", "production"]
    app_version: str = "0.1.0"
    api_base_url: str = "http://127.0.0.1:8001"
    frontend_origin: str = "http://127.0.0.1:5173"
    database_url: str
    redis_url: str
    chroma_host: str = "127.0.0.1"
    chroma_port: int = 8000
    storage_root: Path
    jwt_signing_key: SecretStr
    credential_encryption_key: SecretStr
    initial_admin_username: str = "admin"
    initial_admin_password: SecretStr
    access_token_expire_minutes: int = 10080
    enable_production_openapi: bool = False
```

生产环境要求 JWT signing key 至少 32 bytes；credential encryption key 必须是 Base64 编码的恰好 32 bytes，解码失败或长度错误立即停止启动；两把 key 不得相同。初始密码满足安全真源；`storage_root` 解析为绝对路径但不在 Settings 构造时创建目录。

Settings 只通过只读属性 `jwt_signing_key_bytes` 和 `credential_encryption_key_bytes` 暴露解码后的 bytes；日志/`repr`/validation error 对两个 SecretStr 保持遮罩，调用模块不再自行 Base64 解码。

- [ ] **Step 4: 实现稳定错误映射**

`AppError` 构造参数固定为 `code/message/status_code/details`。`ApiError` 字段固定为 `code/message/trace_id/details`。注册以下 handler：

- `AppError`：使用指定 HTTP 状态。
- `RequestValidationError`：HTTP 422、`VALIDATION_ERROR`、`details.fieldErrors`。
- 未捕获异常：HTTP 500、`INTERNAL_ERROR`，仅日志保留异常，不在响应返回堆栈。

错误 handler 从 context 读取 traceId；response header 同时写 `X-Trace-Id`。

- [ ] **Step 5: 实现 middleware 和 app factory**

`TraceIdMiddleware` 在最外层设置/清理 context，并为成功和失败响应写 header。安全头至少写：

```text
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
X-Frame-Options: DENY
Content-Security-Policy: frame-ancestors 'none'
```

app factory 使用 `CORSMiddleware` 且 `allow_origins=[settings.frontend_origin]`、`allow_credentials=true`，不允许 `*`；允许方法和 header 使用本阶段 API 的明确集合，并暴露 `X-Trace-Id`。API 测试覆盖允许 origin 和恶意 origin 的 preflight。

`create_app(settings: Settings) -> FastAPI` 只负责装配；生产环境且 `enable_production_openapi=false` 时 `docs_url/openapi_url/redoc_url=None`。`backend/app/main.py` 只包含：

```python
from app.bootstrap.application import create_app
from app.core.config import get_settings

app = create_app(get_settings())
```

- [ ] **Step 6: 运行核心契约测试和静态检查**

```powershell
uv run --project backend pytest backend/tests/unit/core backend/tests/api/test_error_and_trace_contract.py -v
uv run --project backend ruff check backend/app backend/tests
uv run --project backend mypy backend/app
```

Expected: 全部通过；错误响应没有 traceback 和本地路径。

- [ ] **Step 7: 提交 API 核心**

```powershell
git add backend/app/core backend/app/bootstrap/application.py backend/app/main.py backend/tests/unit/core backend/tests/api/test_error_and_trace_contract.py
git commit -m "feat: add typed api foundation"
```

### Task 5: 建立 SQLAlchemy、Alembic 和第一批基础表

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/migrations/env.py`
- Create: `backend/migrations/script.py.mako`
- Create: `backend/migrations/versions/0001_foundation.py`
- Create: `backend/app/infrastructure/database/base.py`
- Create: `backend/app/infrastructure/database/session.py`
- Create: `backend/app/infrastructure/database/models/auth.py`
- Create: `backend/app/infrastructure/database/models/settings.py`
- Create: `backend/app/infrastructure/database/models/tasks.py`
- Create: `backend/app/infrastructure/database/models/__init__.py`
- Create: `backend/tests/integration/database/test_migrations.py`
- Create: `backend/tests/integration/database/test_foundation_constraints.py`
- Create: `backend/tests/conftest.py`

- [ ] **Step 1: 写空库迁移失败测试**

测试只连接 `RAG_TEST_DATABASE_URL` 指向的独立测试数据库，拒绝数据库名不是 `_test` 后缀，防止误清开发库：

```python
@pytest.mark.integration
def test_upgrade_from_empty_database_reaches_head(database_url: str) -> None:
    assert database_url.rsplit("/", 1)[-1].endswith("_test")
    run_alembic("downgrade", "base", database_url=database_url)
    run_alembic("upgrade", "head", database_url=database_url)
    assert current_revision(database_url) == head_revision()
```

约束测试至少包含：用户名大小写唯一、Operation 业务幂等键唯一、Outbox `(operation_id,event_type)` 唯一、非法 Operation 状态被数据库拒绝、`pg_trgm` 已安装。

Run:

```powershell
uv run --project backend pytest backend/tests/integration/database -v -m integration
```

Expected: FAIL，因为 Alembic 和表尚不存在。

- [ ] **Step 2: 创建同步 SQLAlchemy session 边界**

第一版 application service 和 Celery 都使用同步 session，避免在 Celery 中嵌套事件循环；FastAPI 的数据库路由使用同步 `def`，由线程池执行。

`backend/app/infrastructure/database/session.py` 公开：

```python
def create_engine_from_settings(settings: Settings) -> Engine: ...
def create_session_factory(engine: Engine) -> sessionmaker[Session]: ...


@contextmanager
def transaction(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        with session.begin():
            yield session
    finally:
        session.close()
```

禁止在该 helper 中自动重试非幂等事务；重试由明确用例处理。

- [ ] **Step 3: 定义第一阶段 ORM model**

使用 SQLAlchemy 2 `Mapped[...]`。第一阶段只建立以下模型：

```text
AdministratorModel
  id UUID PK
  username text not null
  password_hash text not null
  first_login_required boolean default true
  auth_version integer default 1
  revision integer default 1
  last_login_at timestamptz null
  created_at/updated_at timestamptz not null

RetentionSettingsModel
  id UUID PK
  chat_trace_days/conversation_days/operation_days/audit_days/
  temp_attachment_hours/metric_days + revision + timestamps

AuditLogModel
  schema.md 第 67-80 行全部列，不提供普通删除 repository

OperationModel
  schema.md 第 614-635 行全部列

OperationItemModel
  schema.md 第 637-643 行全部列

TaskOutboxModel
  schema.md 第 645-655 行全部列

AdminApiIdempotencyRecordModel
  id UUID PK
  administrator_id UUID FK administrators RESTRICT
  endpoint_code text not null
  idempotency_key_hash char(64) not null
  request_hash char(64) not null
  operation_id UUID null
  response_status integer null
  response_body jsonb null
  expires_at/created_at timestamptz not null
```

`AdminApiIdempotencyRecordModel` 是最终 `api_idempotency_records` 的 expand 阶段：当前只支持管理员 actor 并建立 `(administrator_id, endpoint_code, idempotency_key_hash)` 唯一约束。阶段 5 创建 `channel_instances` 后，用新迁移增加 `channel_instance_id` FK 和“恰好一个 actor”最终 CHECK，不提前创建空渠道表。

所有时间由应用传入 UTC-aware `datetime`；数据库再提供 `server_default=func.now()` 防线。状态使用 `CheckConstraint`，不使用 PostgreSQL enum。

- [ ] **Step 4: 编写确定性的初始迁移**

`0001_foundation.py` 的 upgrade 顺序固定：

```python
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    create_administrators()
    create_retention_settings()
    create_audit_logs()
    create_operations()
    create_operation_items()
    create_task_outbox()
    create_admin_api_idempotency_records()
```

迁移必须显式创建：

- `administrators_lower_username_uq`：`UNIQUE (lower(username))`。
- `operations_business_idempotency_key_uq`。
- `task_outbox_operation_event_uq`。
- `task_outbox_status_next_attempt_idx`。
- `api_idempotency_admin_scope_uq` 管理员作用域部分唯一索引。
- `audit_logs` 三组契约索引。
- 所有状态、保留天数和进度非负 CHECK。

`downgrade()` 仅用于开发/CI，严格按反向依赖顺序删除本迁移创建对象，不删除 `pg_trgm` 扩展，避免影响共享数据库中的其他对象。

- [ ] **Step 5: 配置 Alembic 只读取应用 metadata**

`migrations/env.py` 从 `DATABASE_URL` 或 `-x database_url=` 获取连接，导入 `Base.metadata` 和所有 model；禁止调用 `create_all`。若 URL 缺失，直接失败并给出缺少变量的错误。

- [ ] **Step 6: 创建独立测试数据库并运行迁移/约束测试**

```powershell
$exists = docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml exec -T postgres psql -U rag_app -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='rag_kb_test'"
if ($exists.Trim() -ne "1") {
  docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml exec -T postgres createdb -U rag_app rag_kb_test
}
$env:RAG_TEST_DATABASE_URL="postgresql+psycopg://rag_app:local-dev-only-change-before-sharing@127.0.0.1:5432/rag_kb_test"
uv run --project backend pytest backend/tests/integration/database -v -m integration
uv run --project backend alembic -c backend/alembic.ini upgrade head
uv run --project backend alembic -c backend/alembic.ini check
```

Expected: 测试通过；开发库和测试库都在 head；`alembic check` 输出无新 upgrade operations。

- [ ] **Step 7: 提交数据库基础**

```powershell
git add backend/alembic.ini backend/migrations backend/app/infrastructure/database backend/tests/conftest.py backend/tests/integration/database
git commit -m "feat: add foundation database migration"
```

### Task 6: 实现密码、JWT、CSRF 和凭据加密基元

**Files:**
- Create: `backend/app/core/security.py`
- Create: `backend/tests/unit/core/test_security.py`

- [ ] **Step 1: 写安全基元失败测试**

测试命名必须直接表达真源规则：

```python
def test_password_hash_uses_argon2id_and_never_contains_plaintext() -> None: ...
def test_password_policy_requires_12_to_128_chars_and_three_categories() -> None: ...
def test_admin_token_rejects_wrong_algorithm_token_type_and_auth_version() -> None: ...
def test_csrf_comparison_is_constant_time_contract() -> None: ...
def test_aes_gcm_rejects_wrong_associated_data() -> None: ...
def test_encryption_never_reuses_nonce() -> None: ...
```

AES 测试固定明文只使用 `b"test-secret"`，不能把真实 key 写入 fixture。

Run:

```powershell
uv run --project backend pytest backend/tests/unit/core/test_security.py -v
```

Expected: FAIL，`app.core.security` 尚不存在。

- [ ] **Step 2: 实现密码策略和 Argon2id**

公开接口：

```python
class PasswordPolicyError(ValueError): ...


def validate_admin_password(*, username: str, password: str) -> None: ...
def hash_password(password: str) -> str: ...
def verify_password(password_hash: str, candidate: str) -> bool: ...
```

规则：12-128 字符、至少大写/小写/数字/符号或非 ASCII 四类中的三类、不能与用户名大小写折叠后相同、拒绝项目内固定弱密码集合。Argon2 使用 `argon2.PasswordHasher(type=Type.ID)`；验证异常统一返回 False，不泄漏 hash 解析差异。

- [ ] **Step 3: 实现固定算法的管理员 JWT**

公开接口：

```python
@dataclass(frozen=True)
class AdminTokenClaims:
    administrator_id: UUID
    auth_version: int
    jti: UUID
    issued_at: datetime
    expires_at: datetime


def issue_admin_token(claims: AdminTokenClaims, signing_key: bytes) -> str: ...
def decode_admin_token(token: str, signing_key: bytes, now: datetime) -> AdminTokenClaims: ...
```

只允许 `HS256`，payload 固定 `sub/jti/iat/exp/tokenType=admin/ver`；decode 不能读取 token header 后动态选择算法。

- [ ] **Step 4: 实现 CSRF 和 AES-256-GCM**

```python
def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_matches(cookie_value: str | None, header_value: str | None) -> bool:
    if not cookie_value or not header_value:
        return False
    return secrets.compare_digest(cookie_value, header_value)


@dataclass(frozen=True)
class EncryptedSecret:
    ciphertext: bytes
    nonce: bytes
    key_version: str


def encrypt_secret(plaintext: bytes, key: bytes, *, associated_data: bytes, key_version: str) -> EncryptedSecret: ...
def decrypt_secret(value: EncryptedSecret, key: bytes, *, associated_data: bytes) -> bytes: ...
```

key 必须恰好 32 bytes；nonce 每次由 `os.urandom(12)` 生成；任何失败只抛稳定的 `CredentialDecryptionError`，不回显密文或 key。

- [ ] **Step 5: 运行安全测试和 secret 文本扫描**

```powershell
uv run --project backend pytest backend/tests/unit/core/test_security.py -v
uv run --project backend ruff check backend/app/core/security.py backend/tests/unit/core/test_security.py
uv run --project backend mypy backend/app/core/security.py
```

Expected: 全部通过；同一明文两次加密 nonce/ciphertext 不同，正确 associated data 可还原。

- [ ] **Step 6: 提交安全基元**

```powershell
git add backend/app/core/security.py backend/tests/unit/core/test_security.py
git commit -m "feat: add authentication security primitives"
```

### Task 7: 完成管理员初始化和认证 API

**Files:**
- Create: `backend/app/modules/auth/domain.py`
- Create: `backend/app/modules/auth/schemas.py`
- Create: `backend/app/modules/auth/repository.py`
- Create: `backend/app/modules/auth/ports.py`
- Create: `backend/app/modules/auth/service.py`
- Create: `backend/app/modules/auth/api.py`
- Create: `backend/app/modules/auth/dependencies.py`
- Create: `backend/app/infrastructure/database/repositories/auth.py`
- Create: `backend/app/infrastructure/database/repositories/audit.py`
- Create: `backend/app/infrastructure/redis/login_rate_limit.py`
- Create: `backend/tests/unit/auth/test_password_and_session_rules.py`
- Create: `backend/tests/integration/auth/test_admin_bootstrap.py`
- Create: `backend/tests/api/test_auth_api.py`
- Modify: `backend/app/bootstrap/application.py`
- Modify: `backend/app/bootstrap/dependencies.py`

- [ ] **Step 1: 写管理员生命周期失败测试**

覆盖：

```python
def test_bootstrap_creates_one_admin_only_when_table_is_empty() -> None: ...
def test_second_bootstrap_never_overwrites_existing_password() -> None: ...
def test_login_error_does_not_reveal_unknown_username() -> None: ...
def test_first_login_can_only_change_password_logout_or_read_health() -> None: ...
def test_logout_increments_auth_version_and_invalidates_current_token() -> None: ...
def test_password_change_invalidates_old_tokens_and_issues_current_token() -> None: ...
def test_ten_failures_in_fifteen_minutes_return_429_and_retry_after() -> None: ...
def test_redis_failure_uses_process_local_conservative_limiter() -> None: ...
def test_write_without_matching_csrf_is_403() -> None: ...
```

Run:

```powershell
uv run --project backend pytest backend/tests/unit/auth backend/tests/integration/auth backend/tests/api/test_auth_api.py -v
```

Expected: FAIL，认证模块尚不存在。

- [ ] **Step 2: 定义不依赖 SQLAlchemy 的认证端口**

`AdministratorRepository` 只暴露用例需要的方法：

```python
class AdministratorRepository(Protocol):
    def count(self, session: Session) -> int: ...
    def find_by_username(self, session: Session, username: str) -> Administrator | None: ...
    def get_by_id(self, session: Session, administrator_id: UUID) -> Administrator | None: ...
    def add(self, session: Session, administrator: Administrator) -> None: ...
    def save(self, session: Session, administrator: Administrator) -> None: ...
```

领域 `Administrator` 包含 id、username、password_hash、first_login_required、auth_version、revision 和时间，不导入 FastAPI/SQLAlchemy。

- [ ] **Step 3: 实现管理员 bootstrap**

在 PostgreSQL 事务中锁定 `administrators` 初始化路径；count 为 0 时才创建。并发启动依靠 `lower(username)` 唯一索引，唯一冲突后重新读取并视为“已存在”，绝不覆盖。初始化日志只记录 `event=admin_bootstrap_created|admin_bootstrap_exists`。

应用 lifespan 在 migration 已达 head 后执行 bootstrap；migration 不正确时 readiness 失败，应用不调用 `create_all`。

- [ ] **Step 4: 实现 Redis 滑动窗口和本地保守降级**

key 为 `sha256(casefold(username)) + normalized source IP`，不把用户名写进 Redis key。Redis 使用 Lua 原子执行清理 15 分钟前记录、计数、添加失败和设置 TTL。前 9 次失败返回统一凭据错误；第 10 次失败触发 `AUTH_RATE_LIMITED`、HTTP 429 和 `Retry-After`，之后在窗口过期前不再执行密码验证。成功登录清理该 key 的失败窗口。

Redis 异常时切到有界进程内 limiter；最多保存 10,000 个 key，过期清理，行为同样不允许无限尝试；日志标记 dependency degraded。

- [ ] **Step 5: 实现四个认证端点**

端点和响应必须精确匹配 API 契约：

```text
POST /api/v1/auth/login
POST /api/v1/auth/logout
GET  /api/v1/auth/me
POST /api/v1/auth/change-password
```

Cookie：

```python
ACCESS_COOKIE = "rag_admin_access"
CSRF_COOKIE = "rag_csrf"
```

- Access：HttpOnly、SameSite=Lax、production Secure、path `/`、max-age 与 JWT 一致。
- CSRF：可读、SameSite=Lax、production Secure、path `/`。
- login 成功返回 `LoginResponse`，但密码修改前的依赖只允许 change-password/logout/health。
- logout 和改密都递增数据库 `auth_version`；改密后签发新 JWT/CSRF。
- 所有成功、失败、限流、logout、改密写 `audit_logs`，不记录密码/token/完整 usernameHash。

- [ ] **Step 6: 注册全局鉴权和 CSRF 门禁**

管理员业务路由默认依赖 `require_admin`；公开白名单仅 login、三个 health、未来外部 channel API。对 Cookie 鉴权的 POST/PATCH/PUT/DELETE 校验双提交 CSRF；OpenAPI 中声明 cookie/header 安全说明。

- [ ] **Step 7: 运行认证全套测试**

```powershell
uv run --project backend pytest backend/tests/unit/auth backend/tests/integration/auth backend/tests/api/test_auth_api.py -v
uv run --project backend mypy backend/app/modules/auth backend/app/infrastructure/database/repositories/auth.py
```

Expected: 全部通过；数据库中只有 Argon2 hash，响应/日志没有 password/JWT。

- [ ] **Step 8: 提交认证闭环**

```powershell
git add backend/app/modules/auth backend/app/infrastructure/database/repositories/auth.py backend/app/infrastructure/database/repositories/audit.py backend/app/infrastructure/redis/login_rate_limit.py backend/app/bootstrap backend/tests/unit/auth backend/tests/integration/auth backend/tests/api/test_auth_api.py
git commit -m "feat: add administrator authentication"
```

### Task 8: 实现基础设施 Adapter 和健康端点

**Files:**
- Create: `backend/app/modules/observability/ports.py`
- Create: `backend/app/modules/observability/schemas.py`
- Create: `backend/app/modules/observability/service.py`
- Create: `backend/app/modules/observability/api.py`
- Create: `backend/app/infrastructure/redis/client.py`
- Create: `backend/app/infrastructure/vector/chroma.py`
- Create: `backend/app/infrastructure/storage/local.py`
- Create: `backend/app/infrastructure/health/postgresql.py`
- Create: `backend/app/infrastructure/health/redis.py`
- Create: `backend/app/infrastructure/health/chroma.py`
- Create: `backend/app/infrastructure/health/storage.py`
- Create: `backend/app/infrastructure/health/celery.py`
- Create: `backend/tests/unit/observability/test_health_service.py`
- Create: `backend/tests/integration/observability/test_dependency_health.py`
- Create: `backend/tests/api/test_health_api.py`
- Modify: `backend/app/bootstrap/application.py`
- Modify: `backend/app/bootstrap/dependencies.py`

- [ ] **Step 1: 写健康状态聚合失败测试**

```python
def test_liveness_never_calls_dependency_checks() -> None: ...
def test_ready_is_unhealthy_when_database_or_storage_is_unhealthy() -> None: ...
def test_dependencies_preserve_not_configured_for_mineru_and_models() -> None: ...
def test_optional_provider_degraded_does_not_fail_liveness() -> None: ...
def test_dependency_failure_returns_503_with_trace_id() -> None: ...
```

Run:

```powershell
uv run --project backend pytest backend/tests/unit/observability backend/tests/api/test_health_api.py -v
```

Expected: FAIL，健康模块尚不存在。

- [ ] **Step 2: 定义健康 Port 和 DTO**

```python
class DependencyProbe(Protocol):
    code: DependencyCode
    required_for_readiness: bool

    def check(self) -> DependencyStatus: ...


class HealthResponse(ApiModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    timestamp: datetime
    trace_id: UUID


class DependencyHealthResponse(HealthResponse):
    dependencies: list[DependencyHealthItem]
```

`DependencyHealthItem.code` 只允许 `postgresql/redis/chroma/storage/celery/mineru/models`；status 只允许 `healthy/degraded/unhealthy/not_configured`。

- [ ] **Step 3: 实现四个真实基础 Adapter**

- PostgreSQL：`SELECT 1`、读取 Alembic current/head、ready 时验证当前等于 head。
- Redis：`PING`，超时 1 秒。
- Chroma：HTTP `/api/v2/heartbeat`，超时 2 秒；禁止自动创建 collection。
- LocalStorage：确保 root 位于配置绝对路径，创建 `.health` 临时文件、flush、fsync、rename、删除；响应不返回绝对路径。
- Celery：本阶段读取 Redis heartbeat key；无 Worker 时 dependencies 为 degraded，不让 liveness 失败。

每个 probe 捕获自己的已知连接异常并返回脱敏 message；未知编程异常继续抛出，由统一 500 记录。

- [ ] **Step 4: 实现三个公开健康端点**

```text
GET /api/v1/health/live          始终只检查进程
GET /api/v1/health/ready         检查 PostgreSQL migration、可写性、Storage 和必要配置
GET /api/v1/health/dependencies  返回全部七项摘要
```

`ready/dependencies` 为 unhealthy 时 HTTP 503；degraded 但仍可服务时 HTTP 200。MinerU/models 在阶段 2 前固定 `not_configured`，不是假连接测试。

- [ ] **Step 5: 运行 fake 和真实依赖测试**

```powershell
uv run --project backend pytest backend/tests/unit/observability backend/tests/api/test_health_api.py -v
uv run --project backend pytest backend/tests/integration/observability -v -m integration
```

然后依次停止 Redis/Chroma 并验证分类，测试脚本必须 finally 恢复容器：

```powershell
docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml stop redis
Invoke-RestMethod http://127.0.0.1:8001/api/v1/health/dependencies
docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml start redis
```

Expected: liveness 仍 200；dependencies 中 Redis 为 unhealthy/degraded 且不泄露 URL/密码。

- [ ] **Step 6: 提交健康闭环**

```powershell
git add backend/app/modules/observability backend/app/infrastructure/redis backend/app/infrastructure/vector backend/app/infrastructure/storage backend/app/infrastructure/health backend/app/bootstrap backend/tests/unit/observability backend/tests/integration/observability backend/tests/api/test_health_api.py
git commit -m "feat: add dependency health checks"
```

### Task 9: 实现 Operation 状态机、Repository 和查询 API

**Files:**
- Create: `backend/app/modules/tasks/domain.py`
- Create: `backend/app/modules/tasks/schemas.py`
- Create: `backend/app/modules/tasks/repository.py`
- Create: `backend/app/modules/tasks/service.py`
- Create: `backend/app/modules/tasks/api.py`
- Create: `backend/app/modules/tasks/errors.py`
- Create: `backend/app/modules/tasks/idempotency.py`
- Create: `backend/app/infrastructure/database/repositories/tasks.py`
- Create: `backend/tests/unit/tasks/test_operation_state_machine.py`
- Create: `backend/tests/integration/tasks/test_operation_repository.py`
- Create: `backend/tests/integration/tasks/test_admin_idempotency.py`
- Create: `backend/tests/api/test_operations_api.py`
- Modify: `backend/app/bootstrap/application.py`
- Modify: `backend/app/bootstrap/dependencies.py`

- [ ] **Step 1: 写 Operation 状态机失败测试**

固定状态转换：

```python
@pytest.mark.parametrize(
    ("current", "event", "expected"),
    [
        (OperationStatus.QUEUED, OperationEvent.WORKER_CLAIM, OperationStatus.RUNNING),
        (OperationStatus.QUEUED, OperationEvent.CANCEL, OperationStatus.CANCELLED),
        (OperationStatus.RUNNING, OperationEvent.COMPLETE, OperationStatus.SUCCEEDED),
        (
            OperationStatus.RUNNING,
            OperationEvent.COMPLETE_PARTIAL,
            OperationStatus.PARTIAL_SUCCEEDED,
        ),
        (OperationStatus.RUNNING, OperationEvent.FAIL, OperationStatus.FAILED),
    ],
)
def test_allowed_operation_transition(current, event, expected) -> None: ...


def test_terminal_duplicate_delivery_is_noop() -> None: ...
def test_running_operation_cannot_be_cancelled() -> None: ...
def test_retry_creates_new_operation_and_never_requeues_old_one() -> None: ...
```

非法转换必须产生 `INVALID_STATE_TRANSITION`，details 包含 `current/event/allowedEvents`。

Run:

```powershell
uv run --project backend pytest backend/tests/unit/tasks/test_operation_state_machine.py -v
```

Expected: FAIL，tasks domain 尚不存在。

- [ ] **Step 2: 实现纯领域状态机**

`domain.py` 不导入 SQLAlchemy/FastAPI/Celery：

```python
class OperationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_SUCCEEDED = "partial_succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_OPERATION_STATUSES = frozenset(
    {
        OperationStatus.SUCCEEDED,
        OperationStatus.PARTIAL_SUCCEEDED,
        OperationStatus.FAILED,
        OperationStatus.CANCELLED,
    }
)


def transition_operation(operation: Operation, event: OperationEvent, now: datetime) -> Operation: ...
```

每个事件只修改状态机契约允许的字段；heartbeat 过期通过 `is_stalled(now, threshold)` 派生，不修改顶层 status。

- [ ] **Step 3: 定义 Repository port 和事务用例**

```python
class OperationRepository(Protocol):
    def add(self, session: Session, operation: Operation) -> None: ...
    def get(self, session: Session, operation_id: UUID, *, for_update: bool = False) -> Operation | None: ...
    def find_by_business_key(self, session: Session, key: str) -> Operation | None: ...
    def list(self, session: Session, query: OperationListQuery) -> Page[Operation]: ...
    def save(self, session: Session, operation: Operation) -> None: ...


class OutboxRepository(Protocol):
    def add(self, session: Session, event: OutboxEvent) -> None: ...
```

`create_operation(...)` 接受调用方已有 session，在同一事务写 Operation 和 Outbox；业务幂等键规范化为 64 字符 SHA-256。相同业务键返回已有 Operation，不创建第二条 Outbox。

管理员 POST 命令通过 `AdminIdempotencyService` 使用 `administratorId + endpointCode + sha256(Idempotency-Key)` 查记录。相同 key/requestHash 返回原 Operation/响应；相同 key 不同 requestHash 返回 409 `IDEMPOTENCY_KEY_REUSED`。明文 key 不入库，记录默认保留 24 小时。

- [ ] **Step 4: 实现带行锁的 SQLAlchemy Repository**

- worker claim/cancel/terminal transition 使用 `SELECT ... FOR UPDATE`。
- 更新语句同时比较当前 status，数据库行锁和状态守卫共同防线。
- 列表只允许契约白名单 sort，默认 `-queued_at`，pageSize 20/50/100。
- `error_message` 入库前脱敏并限制长度，不保存 traceback。
- ORM 到 domain 映射集中在 repository 文件，不把 ORM model 返回 service 外。

- [ ] **Step 5: 实现 Operation 管理 API**

```text
GET  /api/v1/operations
GET  /api/v1/operations/{operationId}
POST /api/v1/operations/{operationId}:cancel
POST /api/v1/operations/{operationId}:retry
```

第一阶段 retry 强制 8-128 字符 `Idempotency-Key`，并通过显式 `RetryHandlerRegistry` 查找 task type；尚未注册的类型返回 409 `OPERATION_NOT_RETRYABLE`，不能复制旧 payload 猜测重试。cancel 只允许 queued。所有写接口校验管理员 Cookie/CSRF 和 expected state。

- [ ] **Step 6: 运行状态、Repository 和 API 测试**

```powershell
uv run --project backend pytest backend/tests/unit/tasks backend/tests/integration/tasks backend/tests/api/test_operations_api.py -v
```

Expected: 全部通过；并发两个相同业务键只存在一条 Operation 和一条 Outbox。

- [ ] **Step 7: 提交 Operation 真源**

```powershell
git add backend/app/modules/tasks backend/app/infrastructure/database/repositories/tasks.py backend/app/bootstrap backend/tests/unit/tasks backend/tests/integration/tasks backend/tests/api/test_operations_api.py
git commit -m "feat: add operation state management"
```

### Task 10: 实现 Transactional Outbox、Celery 队列和幂等 Worker

**Files:**
- Create: `backend/app/modules/tasks/ports.py`
- Create: `backend/app/modules/tasks/dispatcher.py`
- Create: `backend/app/modules/tasks/worker.py`
- Create: `backend/app/modules/tasks/tasks.py`
- Create: `backend/app/bootstrap/celery_app.py`
- Create: `backend/tests/unit/tasks/test_outbox_dispatcher.py`
- Create: `backend/tests/unit/tasks/test_worker_idempotency.py`
- Create: `backend/tests/integration/tasks/test_celery_redis_smoke.py`
- Create: `backend/tests/integration/tasks/test_outbox_recovery.py`
- Create: `backend/tests/support/task_handlers.py`
- Modify: `backend/app/modules/tasks/service.py`
- Modify: `backend/app/bootstrap/dependencies.py`

- [ ] **Step 1: 写发布失败和重复投递失败测试**

```python
def test_publish_failure_returns_outbox_to_pending_with_backoff() -> None: ...
def test_crash_after_publish_before_mark_allows_duplicate_delivery() -> None: ...
def test_duplicate_delivery_of_running_or_terminal_operation_has_no_side_effect() -> None: ...
def test_worker_claim_is_atomic_for_same_operation() -> None: ...
def test_payload_contains_ids_and_revisions_but_no_secret_or_document_body() -> None: ...
def test_queued_operation_without_published_event_is_reconciled_after_one_minute() -> None: ...
```

测试专用 handler 只放 `backend/tests/support/task_handlers.py`，生产 registry 不注册 noop/demo task。

Run:

```powershell
uv run --project backend pytest backend/tests/unit/tasks/test_outbox_dispatcher.py backend/tests/unit/tasks/test_worker_idempotency.py -v
```

Expected: FAIL，dispatcher/worker 尚不存在。

- [ ] **Step 2: 创建显式 task dispatch registry**

```python
@dataclass(frozen=True)
class TaskDispatchDefinition:
    event_type: str
    schema_version: str
    celery_task_name: str
    queue: Literal["parsing", "indexing", "chat", "maintenance"]


class TaskDispatchRegistry:
    def register(self, definition: TaskDispatchDefinition) -> None: ...
    def resolve(self, event_type: str, schema_version: str) -> TaskDispatchDefinition: ...
```

未知 event/schema 返回稳定 `TASK_SCHEMA_UNSUPPORTED`，把 Outbox 标为不可自动重试的 failed，并使对应 Operation failed；不能把数据库 event_type 直接当 Celery task name 执行。

- [ ] **Step 3: 实现 outbox claim/publish/ack**

一次最多 claim 50 条：

```sql
SELECT id
FROM task_outbox
WHERE status IN ('pending', 'failed')
  AND next_attempt_at <= now()
ORDER BY created_at
FOR UPDATE SKIP LOCKED
LIMIT 50
```

事务内将 claim 行设为 publishing 并递增 attempt，提交后调用 publisher；成功单独事务标 published，失败单独事务回 pending/failed 并按 `min(300, 2 ** attempt)` 秒退避。进程在 publish 后、mark 前崩溃允许重复消息，因此 Worker 必须幂等。

- [ ] **Step 4: 配置 Celery 四队列**

`backend/app/bootstrap/celery_app.py` 固定：

```python
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "app.tasks.parsing.*": {"queue": "parsing"},
        "app.tasks.indexing.*": {"queue": "indexing"},
        "app.tasks.chat.*": {"queue": "chat"},
        "app.tasks.maintenance.*": {"queue": "maintenance"},
    },
)
```

Beat schedule：每 5 秒 dispatch outbox，每 60 秒 reconcile queued/no-published event；任务参数只包含 `operationId/eventType/schemaVersion`。

- [ ] **Step 5: 实现通用幂等执行壳**

```python
def execute_operation(
    operation_id: UUID,
    expected_task_type: str,
    handler: OperationHandler,
    dependencies: WorkerDependencies,
) -> None:
    claim = dependencies.operations.claim(operation_id, expected_task_type)
    if claim.kind in {ClaimKind.ALREADY_RUNNING, ClaimKind.TERMINAL}:
        return
    try:
        result = handler.run(claim.operation)
    except RetryableTaskError as exc:
        dependencies.operations.fail(operation_id, exc.code, retryable=True)
        raise
    except NonRetryableTaskError as exc:
        dependencies.operations.fail(operation_id, exc.code, retryable=False)
        return
    dependencies.operations.complete(operation_id, result)
```

业务 handler 对每个外部副作用仍需使用确定性 ID/upsert；通用壳不能宣称自动让任意代码幂等。

- [ ] **Step 6: 运行真实 Redis 发布和恢复测试**

```powershell
uv run --project backend pytest backend/tests/unit/tasks/test_outbox_dispatcher.py backend/tests/unit/tasks/test_worker_idempotency.py -v
uv run --project backend pytest backend/tests/integration/tasks/test_celery_redis_smoke.py backend/tests/integration/tasks/test_outbox_recovery.py -v -m integration
```

Expected: Redis 可收 JSON 消息；同一 operation 的测试 handler 副作用计数为 1；Redis 停止时 Outbox 留在可恢复状态，恢复后发布。

- [ ] **Step 7: 启动 Windows solo Worker 做进程 smoke**

```powershell
. ./deploy/scripts/import-env.ps1 -Path deploy/env/.env.development
uv run --project backend celery --workdir backend -A app.bootstrap.celery_app:celery_app worker --pool=solo --queues=maintenance --loglevel=INFO
```

在另一个终端运行 integration smoke。Expected: Worker heartbeat 可被 health endpoint 识别；日志不含 broker 密码和 payload 正文。

- [ ] **Step 8: 提交异步骨架**

```powershell
git add backend/app/modules/tasks backend/app/bootstrap/celery_app.py backend/app/bootstrap/dependencies.py backend/tests/unit/tasks backend/tests/integration/tasks backend/tests/support/task_handlers.py
git commit -m "feat: add transactional outbox workers"
```

### Task 11: 实现显式 Capability Registry

**Files:**
- Create: `backend/app/modules/capabilities/domain.py`
- Create: `backend/app/modules/capabilities/registry.py`
- Create: `backend/app/modules/capabilities/schemas.py`
- Create: `backend/app/modules/capabilities/service.py`
- Create: `backend/app/modules/capabilities/api.py`
- Create: `backend/app/modules/capabilities/errors.py`
- Create: `backend/tests/unit/capabilities/test_registry.py`
- Create: `backend/tests/api/test_capabilities_api.py`
- Modify: `backend/app/bootstrap/application.py`
- Modify: `backend/app/bootstrap/dependencies.py`

- [ ] **Step 1: 写 registry 失败测试**

```python
def test_duplicate_code_and_version_is_rejected_at_bootstrap() -> None: ...
def test_list_filters_category_visibility_and_disabled_state() -> None: ...
def test_unknown_version_returns_capability_not_found() -> None: ...
def test_registry_does_not_load_arbitrary_python_plugins() -> None: ...
def test_api_serializes_config_and_ui_schema_without_unknown_fields() -> None: ...
```

Run:

```powershell
uv run --project backend pytest backend/tests/unit/capabilities backend/tests/api/test_capabilities_api.py -v
```

Expected: FAIL，capabilities 模块尚不存在。

- [ ] **Step 2: 实现不可变 CapabilityOption**

字段与 API 契约完全一致：code、name、description、enabled、visible、version、category、unavailableReason、configSchema、uiSchema、requiredSourceFeatures、preferredSourceFeatures。`configSchema/uiSchema` 在注册时深拷贝并冻结对外视图，调用方不能修改 registry 内状态。

Registry 只接受 bootstrap 中显式 `register()`；不扫描 entry points、目录或任意 Python 模块。

- [ ] **Step 3: 实现两个读取端点**

```text
GET /api/v1/capabilities?category=&includeDisabled=
GET /api/v1/capabilities/{code}/versions/{version}
```

第一阶段不注册尚未完成的 parser/model/chunk/retrieval/channel 能力，也不伪造 enabled 选项。Storage/Chroma/pg_trgm 的健康可用不等于知识库能力已实现，因此对应业务 capability 在阶段 3 随真实实现注册。

- [ ] **Step 4: 运行测试并提交**

```powershell
uv run --project backend pytest backend/tests/unit/capabilities backend/tests/api/test_capabilities_api.py -v
git add backend/app/modules/capabilities backend/app/bootstrap backend/tests/unit/capabilities backend/tests/api/test_capabilities_api.py
git commit -m "feat: add explicit capability registry"
```

### Task 12: 导入并记录 v3-admin-vite 基座

**Files:**
- Create: `frontend/` from upstream v5.2.0
- Create: `frontend/TEMPLATE_UPSTREAM.md`
- Create: `frontend/LICENSE.v3-admin-vite`
- Modify: `frontend/package.json`
- Modify: `frontend/.npmrc`

- [ ] **Step 1: 在工作区外获取并验证模板 commit**

```powershell
$templateRoot = Join-Path ([IO.Path]::GetTempPath()) "v3-admin-vite-v5.2.0"
if (Test-Path -LiteralPath $templateRoot) {
  throw "Temporary template directory already exists: $templateRoot"
}
git clone --depth 1 --branch v5.2.0 https://github.com/un-pany/v3-admin-vite.git $templateRoot
$actualCommit = git -C $templateRoot rev-parse HEAD
if ($actualCommit -ne "a079b069f9fa6b92b0946d36cf28b50d8655c457") {
  throw "Unexpected v3-admin-vite commit: $actualCommit"
}
```

Expected: commit 精确匹配；不接受 main 或另一个同名本地目录。

- [ ] **Step 2: 复制明确的模板工程文件**

只复制这些入口，不复制上游 `.git/.github/.vscode/docs/skills`：

```powershell
$items = @(
  "src", "public", "tests", "types", ".editorconfig", ".npmrc", "eslint.config.js", "index.html", "package.json",
  "pnpm-lock.yaml", "tsconfig.json", "uno.config.ts", "vite.config.ts"
)
New-Item -ItemType Directory -Path frontend -ErrorAction Stop | Out-Null
foreach ($item in $items) {
  Copy-Item -LiteralPath (Join-Path $templateRoot $item) -Destination frontend -Recurse
}
Copy-Item -LiteralPath (Join-Path $templateRoot "LICENSE") -Destination "frontend/LICENSE.v3-admin-vite"
```

删除临时目录前先验证其 resolved path 以系统 temp 开头且目录名完全匹配，再使用 PowerShell `Remove-Item -LiteralPath $templateRoot -Recurse`。不能在工作区内执行计算路径的递归删除。

- [ ] **Step 3: 记录模板来源和沿用/替换边界**

`frontend/TEMPLATE_UPSTREAM.md` 固定：

```markdown
# v3-admin-vite 上游记录

- Repository: https://github.com/un-pany/v3-admin-vite
- Release: v5.2.0
- Commit: a079b069f9fa6b92b0946d36cf28b50d8655c457
- License: MIT，见 `LICENSE.v3-admin-vite`

沿用：Vue/Vite/TypeScript/Element Plus、布局骨架、主题基础、Router、Pinia、构建配置。
替换：mock API、localStorage Token、验证码、demo/权限演示/外链菜单、上游产品品牌和业务页面。
约束：后端 OpenAPI 生成 client，Cookie + CSRF 认证，中文产品导航，业务功能按本项目真源实现。
```

- [ ] **Step 4: 固定 pnpm 和官方 registry**

在 `frontend/package.json` 增加：

```json
"packageManager": "pnpm@11.12.0",
"engines": {
  "node": "24.16.0",
  "pnpm": "11.12.0"
}
```

删除上游 `prepare` script、`lint-staged` 配置以及 `husky/lint-staged` devDependencies，避免子目录模板擅自改写 Monorepo 根 Git hooks；项目级 hooks 只有在根工程明确设计后才加入。

`frontend/.npmrc`：

```ini
registry=https://registry.npmjs.org/
save-exact=true
```

保留其余上游 package 精确版本，不在导入提交中升级依赖。运行 `pnpm --dir frontend install --lockfile-only` 使删除 hooks 后的 importer 与 lockfile 一致。

- [ ] **Step 5: 验证未修改模板可复现**

```powershell
pnpm --dir frontend install --lockfile-only
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend run test
pnpm --dir frontend run build
```

Expected: 上游单元测试和 build 通过。若上游固定版本在当前 Node 24.16.0 失败，记录真实错误并先评估 Node 兼容补丁；禁止直接升级 Vite/TypeScript 逃避。

- [ ] **Step 6: 提交模板来源基线**

```powershell
git add frontend
git commit -m "chore: import pinned admin template"
```

### Task 13: 导出 OpenAPI 并生成唯一前端 client

**Files:**
- Create: `backend/scripts/export_openapi.py`
- Create: `backend/tests/api/test_openapi_contract.py`
- Create: `docs/api/openapi.json` (generated)
- Create: `frontend/openapi-ts.config.ts`
- Create: `frontend/src/api/runtime-config.ts`
- Create: `frontend/src/api/generated/` (generated)
- Modify: `frontend/package.json`
- Modify: `frontend/pnpm-lock.yaml` (generated)

- [ ] **Step 1: 写 OpenAPI 稳定性失败测试**

`test_openapi_contract.py` 断言第一阶段路由和 operationId 精确集合：

```python
EXPECTED_OPERATIONS = {
    ("post", "/api/v1/auth/login", "authLogin"),
    ("post", "/api/v1/auth/logout", "authLogout"),
    ("get", "/api/v1/auth/me", "authMe"),
    ("post", "/api/v1/auth/change-password", "authChangePassword"),
    ("get", "/api/v1/health/live", "healthLive"),
    ("get", "/api/v1/health/ready", "healthReady"),
    ("get", "/api/v1/health/dependencies", "healthDependencies"),
    ("get", "/api/v1/capabilities", "capabilitiesList"),
    ("get", "/api/v1/capabilities/{code}/versions/{version}", "capabilitiesGetVersion"),
    ("get", "/api/v1/operations", "operationsList"),
    ("get", "/api/v1/operations/{operationId}", "operationsGet"),
    ("post", "/api/v1/operations/{operationId}:cancel", "operationsCancel"),
    ("post", "/api/v1/operations/{operationId}:retry", "operationsRetry"),
}
```

另断言 schema/example 中不出现 `INITIAL_ADMIN_PASSWORD`、JWT、数据库 URL、绝对 Storage path 或 secret 值。

Run:

```powershell
uv run --project backend pytest backend/tests/api/test_openapi_contract.py -v
```

Expected: 首次 FAIL，直到 Task 7-11 的每个路由显式设置稳定 `operation_id`。

- [ ] **Step 2: 修正路由 operationId 并实现确定性导出**

`backend/scripts/export_openapi.py`：

```python
import json
from pathlib import Path

from app.bootstrap.application import create_app
from app.core.config import Settings
from pydantic import SecretStr


def main() -> None:
    settings = Settings(
        app_env="test",
        app_version="0.1.0",
        database_url="postgresql+psycopg://openapi:openapi@127.0.0.1:5432/openapi",
        redis_url="redis://127.0.0.1:6379/15",
        storage_root=Path("storage/openapi-export").resolve(),
        jwt_signing_key=SecretStr("openapi-export-only-jwt-key-0001"),
        credential_encryption_key=SecretStr("b3BlbmFwaS1leHBvcnQtY3JlZGVudGlhbC1rZXktMDE="),
        initial_admin_password=SecretStr("OpenAPI-Export-Only-Password-03!"),
    )
    schema = create_app(settings).openapi()
    output = Path("docs/api/openapi.json")
    output.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
```

导出脚本只构造无真实 secret 的内存配置；app factory 在 schema 导出时不得连接数据库/Redis/Chroma 或创建管理员。这些固定字符串只用于 schema 构造，不能被部署代码读取。

- [ ] **Step 3: 安装固定生成器并配置 Runtime API**

```powershell
pnpm --dir frontend add --save-dev @hey-api/openapi-ts@0.99.0
pnpm --dir frontend add @hey-api/client-axios@0.9.1
```

`frontend/openapi-ts.config.ts`：

```typescript
import { defineConfig, type UserConfig } from "@hey-api/openapi-ts"

const config: Promise<UserConfig> = defineConfig({
  input: "../docs/api/openapi.json",
  output: {
    path: "./src/api/generated"
  },
  plugins: [
    {
      name: "@hey-api/client-axios",
      runtimeConfigPath: "./src/api/runtime-config.ts"
    },
    "@hey-api/sdk",
    {
      enums: "javascript",
      name: "@hey-api/typescript"
    }
  ]
})

export default config
```

`runtime-config.ts`：

```typescript
import type { CreateClientConfig } from "./generated/client.gen"

export const createClientConfig: CreateClientConfig = config => ({
  ...config,
  baseURL: "/api/v1",
  withCredentials: true
})
```

- [ ] **Step 4: 增加生成和漂移检查命令**

`frontend/package.json` scripts：

```json
"generate:api": "openapi-ts",
"check:generated": "pnpm generate:api && git diff --exit-code -- ../docs/api/openapi.json src/api/generated"
```

导出和生成：

```powershell
uv run --project backend python backend/scripts/export_openapi.py
pnpm --dir frontend run generate:api
```

- [ ] **Step 5: 验证后端 schema 和前端生成物无漂移**

```powershell
uv run --project backend pytest backend/tests/api/test_openapi_contract.py -v
uv run --project backend python backend/scripts/export_openapi.py
pnpm --dir frontend run generate:api
git diff --exit-code -- docs/api/openapi.json frontend/src/api/generated
```

Expected: 测试通过，重复生成无 diff。`frontend/src/api/generated` 中不存在手写文件。

- [ ] **Step 6: 提交契约生成链**

```powershell
git add backend/scripts/export_openapi.py backend/tests/api/test_openapi_contract.py docs/api/openapi.json frontend/openapi-ts.config.ts frontend/src/api/runtime-config.ts frontend/src/api/generated frontend/package.json frontend/pnpm-lock.yaml
git commit -m "chore: generate frontend api client"
```

### Task 14: 把模板认证改为 Cookie/CSRF 并建立真实管理壳

**Files:**
- Delete: `frontend/src/pages/demo/`
- Delete: `frontend/src/common/apis/tables/`
- Delete: `frontend/src/common/apis/users/`
- Delete: `frontend/src/pages/login/apis/`
- Delete: `frontend/src/http/axios.ts`
- Delete: `frontend/src/common/composables/usePany.ts`
- Delete: template demo tests and demo-only assets
- Create: `frontend/src/api/client/cookies.ts`
- Create: `frontend/src/api/client/errors.ts`
- Create: `frontend/src/api/client/setup.ts`
- Create: `frontend/src/features/auth/store.ts`
- Create: `frontend/src/features/auth/LoginPage.vue`
- Create: `frontend/src/features/auth/ChangePasswordPage.vue`
- Create: `frontend/src/features/health/HealthSummary.vue`
- Create: `frontend/src/features/tasks/TaskListPage.vue`
- Create: `frontend/tests/api/client.test.ts`
- Create: `frontend/tests/features/auth-store.test.ts`
- Create: `frontend/tests/router/guard.test.ts`
- Create: `frontend/e2e/auth-smoke.spec.ts`
- Create: `frontend/playwright.config.ts`
- Create: `frontend/.env.example`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/router/guard.ts`
- Modify: `frontend/src/pinia/stores/user.ts` or replace all imports with `features/auth/store.ts`
- Modify: `frontend/src/pages/dashboard/index.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/main.ts`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/package.json`
- Modify: `frontend/pnpm-lock.yaml` (generated)

- [ ] **Step 1: 先写 Cookie 认证和路由失败测试**

关键断言：

```typescript
it("never reads or writes an access token in localStorage", async () => { /* spy + assert */ })
it("adds X-CSRF-Token only to unsafe methods when csrf cookie exists", async () => { /* assert */ })
it("maps ApiError traceId without replacing backend message", async () => { /* assert */ })
it("loads authMe once when auth state is unknown", async () => { /* assert */ })
it("redirects password-change-required users to /change-password", async () => { /* assert */ })
it("redirects unauthenticated users to /login with encoded redirect", async () => { /* assert */ })
```

Run:

```powershell
pnpm --dir frontend run test -- tests/api/client.test.ts tests/features/auth-store.test.ts tests/router/guard.test.ts
```

Expected: FAIL，新模块尚不存在。

- [ ] **Step 2: 配置 generated Axios client**

`cookies.ts` 只读取精确 cookie 名 `rag_csrf`，使用分号分割和 `decodeURIComponent`，不提供 access token helper。

`setup.ts`：

```typescript
import { client } from "@/api/generated/client.gen"
import { readCookie } from "./cookies"
import { toApiClientError } from "./errors"

const unsafeMethods = new Set(["post", "put", "patch", "delete"])

client.setConfig({ baseURL: "/api/v1", withCredentials: true })

client.instance.interceptors.request.use(config => {
  if (unsafeMethods.has(config.method?.toLowerCase() ?? "")) {
    const csrf = readCookie("rag_csrf")
    if (csrf) config.headers.set("X-CSRF-Token", csrf)
  }
  return config
})

client.instance.interceptors.response.use(
  response => response,
  error => Promise.reject(toApiClientError(error))
)
```

`ApiClientError` 保存 HTTP status、后端 code/message/traceId/details；401 由 auth store 清状态，409/422/429/503/504 保留给页面专用 UI，不能全部弹同一个 toast。

- [ ] **Step 3: 替换 localStorage Token auth store 和 guard**

store 状态固定：`unknown/authenticated/unauthenticated/password_change_required`。刷新页面时调用 generated `authMe()`；HttpOnly Cookie 不可见，不通过猜 cookie 判断。login 成功保存返回 AdminProfile/CSRF（CSRF 的真源仍是 cookie），logout 无论响应成功与否都清内存状态并跳登录。

guard 公开白名单仅 `/login`；`/change-password` 需要有效管理员但允许 first login。首次改密限制由后端硬校验，前端 guard 只改善体验。

- [ ] **Step 4: 创建第一阶段真实页面并收敛路由**

保留真实可用页面：

```text
/login             中文登录表单
/change-password   强制改密表单
/dashboard         调用 healthDependencies 的运行摘要
/tasks             调用 operationsList 的最小任务列表，详情抽屉调用 operationsGet
```

删除 demo、权限演示和外链路由。第一阶段不为尚未实现的数据解析/模型/知识库/机器人/渠道创建“即将上线”假页面；完整固定导航在阶段 6 与真实页面一起落地。

登录表单只包含用户名、密码、提交；不保留模板验证码、Owl 动画、admin/editor 提示或 mock 账号。所有界面文案中文，API 专业 code 保持英文。

- [ ] **Step 5: 收敛 Vite 和 package scripts**

Vite dev server：host `127.0.0.1`、port `5173`、strictPort true、open false；`/api/v1` proxy 到 `http://127.0.0.1:8001`，不使用 Apifox mock。

`frontend/.env.example` 只包含会公开到浏览器的 `VITE_APP_TITLE=企业 RAG 知识库` 和 `VITE_PUBLIC_PATH=/`；任何 Provider/MinerU/API secret 禁止使用 `VITE_` 前缀。

同时从 `vite.config.ts` 和 package 中删除 `vite-plugin-mcp`，从 `App.vue` 删除模板作者通知逻辑；Open Design/Stitch 等设计工具连接不应被打包进业务前端 dev server。

安装 Playwright：

```powershell
pnpm --dir frontend add --save-dev @playwright/test@1.61.1
```

scripts 固定：

```json
"lint": "eslint .",
"lint:fix": "eslint . --fix",
"typecheck": "vue-tsc --noEmit",
"test:unit": "vitest run",
"test:e2e": "playwright test",
"check": "pnpm lint && pnpm typecheck && pnpm test:unit && pnpm build"
```

- [ ] **Step 6: 运行前端静态、单元和 build**

```powershell
pnpm --dir frontend run lint
pnpm --dir frontend run typecheck
pnpm --dir frontend run test:unit
pnpm --dir frontend run build
```

Expected: 全部通过；全仓前端搜索不存在 `localStorage` access token、mock API URL、`/demo` 路由和上游账号提示。

- [ ] **Step 7: 运行真实认证 E2E**

启动 API 和前端后：

```powershell
pnpm --dir frontend exec playwright install chromium
pnpm --dir frontend run test:e2e
```

`auth-smoke.spec.ts` 覆盖：未登录跳转、初始账号登录、强制改密、dashboard health 可见、刷新仍通过 Cookie 登录、logout 后旧 Cookie 不可访问 dashboard。测试使用专用 test admin，不复用开发密码。

- [ ] **Step 8: 提交前端产品壳**

```powershell
git add -A -- frontend
git commit -m "feat: add authenticated admin shell"
```

### Task 15: 建立根检查、CI 和第一阶段运行文档

**Files:**
- Create: `scripts/check.ps1`
- Create: `scripts/check-docs.ps1`
- Create: `scripts/dev-status.ps1`
- Create: `.github/workflows/ci.yml`
- Create: `deploy/docs/windows-development.md`
- Create: `deploy/docs/troubleshooting.md`
- Modify: `README.md`
- Modify: `docs/requirements/99-development-readiness.md` (仅在计划获批并开始执行时更新状态)

- [ ] **Step 1: 写根检查脚本并先观察失败**

`scripts/check.ps1` 顺序执行且遇错停止：

```powershell
$ErrorActionPreference = "Stop"
pwsh -NoProfile -File scripts/check-repository.ps1
pwsh -NoProfile -File scripts/check-docs.ps1
pwsh -NoProfile -File deploy/tests/test-compose.ps1
uv sync --project backend --frozen --all-groups
uv run --project backend ruff format --check backend/app backend/tests
uv run --project backend ruff check backend/app backend/tests
uv run --project backend mypy backend/app
uv run --project backend pytest backend/tests -m "not integration"
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend run check
uv run --project backend python backend/scripts/export_openapi.py
pnpm --dir frontend run generate:api
git diff --exit-code -- docs/api/openapi.json frontend/src/api/generated
```

Run before CI exists. Expected: 若前面任务还有任何遗漏，本脚本在第一个失败门禁停止并返回非零。

- [ ] **Step 2: 实现文档和 secret 基线扫描**

`scripts/check-docs.ps1` 检查：Markdown 单 H1、相对链接存在、代码围栏成对、核心文档无未决占位标记、仓库文本无 GitHub/OpenAI/Google API 凭据前缀、private key header 或带真实值的 password-secret 模式。允许 `<strong-secret>`、明确的本地 development example 和 DTO 字段名，不把这些契约文字误报为真实 secret。

脚本输出文件和行号，任何命中 exit 1；二进制和 `.git/node_modules/.venv` 排除。

- [ ] **Step 3: 创建最小权限 CI**

`.github/workflows/ci.yml`：

```yaml
name: ci

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  quality:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065
        with:
          python-version: 3.13.9
      - uses: astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78
        with:
          version: 0.11.28
      - uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020
        with:
          node-version: 24.16.0
      - uses: pnpm/action-setup@b906affcce14559ad1aafd4ab0e942779e9f58b1
        with:
          version: 11.12.0
      - name: Static and unit checks
        shell: pwsh
        run: ./scripts/check.ps1
```

增加独立 `integration` job：同样固定 actions，复制 development env，`docker compose up -d --wait`，创建 `_test` 数据库，执行 Alembic、integration pytest、启动 API/前端、Playwright Chromium smoke；`if: always()` 执行 compose logs 和 down。Job env 使用测试专用高熵 JWT/加密 key/初始密码，日志不得打印值。

- [ ] **Step 4: 加入依赖和 secret 检查**

CI 在 lock 安装后执行：

```powershell
uvx --from pip-audit==2.10.1 pip-audit --locked backend
pnpm --dir frontend audit --audit-level high
pwsh -NoProfile -File scripts/check-docs.ps1
docker compose --env-file deploy/env/.env.development.example -f deploy/compose/compose.deps.yml config --quiet
```

若 `pip-audit 2.10.1` 因供应链原因无法取得，必须先在工程基线变更中记录替代精确版本，不能改为浮动安装。漏洞只允许带到期日、CVE、不可利用理由和负责人记录的临时例外。

- [ ] **Step 5: 写 Windows 开发和故障排查文档**

`windows-development.md` 包含：Docker Desktop 启动、env 创建、依赖启动、测试库、migration、API、四队列 Worker 命令、前端、健康、停止但保留卷、显式清卷风险说明。

`troubleshooting.md` 按症状列：Docker pipe 不存在、端口占用、migration 非 head、Cookie/CSRF 403、Redis/Chroma unhealthy、Worker heartbeat 缺失、pnpm/uv 锁漂移。每项给检查命令和非破坏修复；不建议 reset/delete volumes 作为第一步。

- [ ] **Step 6: 在计划获批执行时更新开发门禁状态**

只在用户明确批准本计划并开始第一阶段时修改 `99-development-readiness.md`：

```text
当前结论：IMPLEMENTATION IN PROGRESS（PHASE 1）。
用户基线审阅：完成。
分阶段实施计划：完成并确认。
生产代码：第一阶段进行中。
Git 状态说明：仓库已初始化，阶段开发使用 codex/phase-01-foundation。
```

该状态更新与第一阶段首个生产代码提交一起提交；计划审阅阶段不提前宣称获批。

- [ ] **Step 7: 运行第一阶段完整本地验证**

```powershell
pwsh -NoProfile -File scripts/check.ps1
docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml up -d --wait
$env:RAG_TEST_DATABASE_URL="postgresql+psycopg://rag_app:local-dev-only-change-before-sharing@127.0.0.1:5432/rag_kb_test"
uv run --project backend pytest backend/tests/integration -v -m integration
pnpm --dir frontend run test:e2e
git status --short
```

Expected: 所有命令 exit 0；`git status --short` 只显示本任务预期文档/CI改动。

- [ ] **Step 8: 提交 CI 和运行文档**

```powershell
git add scripts .github/workflows/ci.yml deploy/docs README.md docs/requirements/99-development-readiness.md
git commit -m "ci: enforce foundation quality gates"
```

## 3. 第一阶段最终审阅清单

- [ ] `git diff main...HEAD --check` 无新增空白错误。
- [ ] `git diff main...HEAD --name-only` 中没有 MinerU、模型、知识库、机器人或渠道假实现。
- [ ] `backend/uv.lock` 和 `frontend/pnpm-lock.yaml` 均已提交，重复 frozen install 成功。
- [ ] Compose 三个镜像都有版本和 digest，不含 `latest`。
- [ ] Alembic 从空库到 head、重复 check、数据库约束反例全部通过。
- [ ] 管理员 bootstrap、Argon2id、Cookie、CSRF、authVersion、限流和审计全部通过。
- [ ] liveness 不查询依赖；ready/dependencies 的状态和 HTTP code 可复现。
- [ ] Operation/Outbox 同事务、Redis 故障恢复和重复 delivery 单副作用通过。
- [ ] OpenAPI operationId/错误/DTO 稳定，generated client 重生成无 diff。
- [ ] 前端不存在 localStorage access token、mock API、demo 菜单或手写重复 DTO。
- [ ] 根检查、integration、E2E 和 GitHub Actions 全部通过。
- [ ] 文档明确 Docker Desktop 当前必须由用户启动；没有谎称未运行的服务已验证。

## 4. 第一阶段提交序列

预期提交按以下顺序出现，每个提交通过自己的局部测试：

```text
chore: lock repository runtimes
chore: add pinned development services
chore: lock backend dependencies
feat: add typed api foundation
feat: add foundation database migration
feat: add authentication security primitives
feat: add administrator authentication
feat: add dependency health checks
feat: add operation state management
feat: add transactional outbox workers
feat: add explicit capability registry
chore: import pinned admin template
chore: generate frontend api client
feat: add authenticated admin shell
ci: enforce foundation quality gates
```

不把以上提交压成一个无法审查的巨型提交。阶段完成后使用 `superpowers:requesting-code-review` 做需求和代码两轮审查，再根据用户选择创建 PR 或合并。
