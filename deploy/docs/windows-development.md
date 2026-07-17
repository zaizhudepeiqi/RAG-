# Windows 开发运行指南

本文档适用于 Windows + PowerShell 7 开发环境。除了标明需要新终端的命令，全部命令都从仓库根目录执行。需求和部署边界以 [部署与运行阶段性真源](../../docs/requirements/12-deployment-source.md) 为准；常见失败见 [故障排查](troubleshooting.md)。

## 1. 前置条件和版本

安装 Git、Docker Desktop、Python 3.13.9、uv 0.11.28、Node.js 24.16.0、npm 11.13.0，以及 PowerShell 7.4.17 LTS 或更新的兼容 7.x 版本。先验证本机工具：

```powershell
git --version
python --version
uv --version
node --version
npm --version
pwsh --version
docker --version
docker compose version
```

版本不符时修正本机工具，不要通过改动 `backend/uv.lock` 或 `frontend/package-lock.json` 绕过版本约束。

## 2. 启动 Docker Desktop Linux containers

```powershell
docker desktop start
docker desktop engine use linux
$dockerOs = docker info --format '{{.OSType}}'
if ($LASTEXITCODE -ne 0 -or $dockerOs -ne 'linux') {
  throw 'Docker Desktop is not ready with Linux containers.'
}
```

如果当前 Docker Desktop 版本不支持 `docker desktop` 子命令，从开始菜单打开 Docker Desktop，在托盘菜单中切换到 Linux containers，然后重新执行 `docker info --format '{{.OSType}}'`。

## 3. 创建并导入本机环境

`deploy/env/.env.development` 被 Git 忽略。首次创建时从示例复制；文件已存在时不覆盖本机设置：

```powershell
if (-not (Test-Path -LiteralPath deploy/env/.env.development)) {
  Copy-Item deploy/env/.env.development.example deploy/env/.env.development
}
. ./deploy/scripts/import-env.ps1 -Path deploy/env/.env.development
```

只在这个本机忽略文件中保存开发凭据。不要提交真实 Token、Provider Key、生产签名密钥、加密主密钥或管理员密码，也不要在终端中输出这些值。

## 4. 启动锁定的依赖容器

```powershell
docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml up -d --wait
pwsh -NoProfile -File deploy/scripts/wait-for-dependencies.ps1 -EnvFile deploy/env/.env.development
```

Compose 使用带 digest 的 PostgreSQL、Redis 和 Chroma 镜像，并仅将开发端口绑定到 `127.0.0.1`。

## 5. 非破坏性创建集成测试库

以导入的 PostgreSQL 用户检查 `rag_kb_test`；只在它不存在时创建，不删除或重置任何数据库：

```powershell
$testDatabaseExists = docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml exec -T postgres psql --set ON_ERROR_STOP=1 --tuples-only --no-align --username $env:POSTGRES_USER --dbname postgres --command "SELECT 1 FROM pg_database WHERE datname = 'rag_kb_test'"
if ($LASTEXITCODE -ne 0) {
  throw 'Failed to inspect the integration test database.'
}
if (($testDatabaseExists | Out-String).Trim() -ne '1') {
  docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml exec -T postgres psql --set ON_ERROR_STOP=1 --username $env:POSTGRES_USER --dbname postgres --command 'CREATE DATABASE rag_kb_test'
  if ($LASTEXITCODE -ne 0) {
    throw 'Failed to create the integration test database.'
  }
}
$env:RAG_TEST_DATABASE_URL = $env:DATABASE_URL -replace '/rag_kb$', '/rag_kb_test'
if ($env:RAG_TEST_DATABASE_URL -eq $env:DATABASE_URL) {
  throw 'DATABASE_URL must end in /rag_kb before deriving RAG_TEST_DATABASE_URL.'
}
```

`RAG_TEST_DATABASE_URL` 使用项目已锁定的 psycopg SQLAlchemy URL，并且必须指向以 `_test` 结尾的独立数据库。

## 6. 安装锁定依赖并迁移开发库

```powershell
uv sync --project backend --frozen --all-groups
npm --prefix frontend ci
uv run --project backend alembic -c backend/alembic.ini upgrade head
uv run --project backend alembic -c backend/alembic.ini current
uv run --project backend alembic -c backend/alembic.ini heads
uv run --project backend alembic -c backend/alembic.ini check
```

`current` 应与 `heads` 的唯一 head 一致，`check` 应报告没有新的 upgrade operations。

## 7. 启动 API

在新的 PowerShell 7 终端中，从仓库根目录执行：

```powershell
. ./deploy/scripts/import-env.ps1 -Path deploy/env/.env.development
uv run --project backend uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8001
```

## 8. 启动四个队列的 Worker 副本

Windows 开发按运行真源使用 `solo` pool。`solo` Worker 每个进程一次只执行一个任务，因此所有进程都固定使用 `--concurrency=1`；需要通过多个独立 Worker 进程获得队列并行能力，不要把 `--concurrency` 设置为 2 或 4。有效副本矩阵如下：

| 队列 | Worker 进程数 | 实例编号 |
|---|---:|---|
| `parsing` | 2 | 1、2 |
| `indexing` | 2 | 1、2 |
| `chat` | 4 | 1、2、3、4 |
| `maintenance` | 1 | 1 |

总共打开 9 个独立 PowerShell 7 Worker 终端。每个终端从仓库根目录执行对应模板，并把 `$instance` 设置为该队列尚未使用的实例编号。`--hostname=<queue>-<instance>@%h` 必须在所有同时运行的 Worker 中保持唯一。

Parsing Worker 模板（分别以 `$instance = 1` 和 `$instance = 2` 启动）：

```powershell
. ./deploy/scripts/import-env.ps1 -Path deploy/env/.env.development
$instance = 1
uv run --project backend celery --workdir backend -A app.bootstrap.celery_app:celery_app worker --pool=solo --queues=parsing --concurrency=1 --hostname="parsing-$instance@%h" --loglevel=INFO
```

Indexing Worker 模板（分别以 `$instance = 1` 和 `$instance = 2` 启动）：

```powershell
. ./deploy/scripts/import-env.ps1 -Path deploy/env/.env.development
$instance = 1
uv run --project backend celery --workdir backend -A app.bootstrap.celery_app:celery_app worker --pool=solo --queues=indexing --concurrency=1 --hostname="indexing-$instance@%h" --loglevel=INFO
```

Chat Worker 模板（分别以 `$instance = 1`、2、3 和 4 启动）：

```powershell
. ./deploy/scripts/import-env.ps1 -Path deploy/env/.env.development
$instance = 1
uv run --project backend celery --workdir backend -A app.bootstrap.celery_app:celery_app worker --pool=solo --queues=chat --concurrency=1 --hostname="chat-$instance@%h" --loglevel=INFO
```

Maintenance Worker（唯一实例）：

```powershell
. ./deploy/scripts/import-env.ps1 -Path deploy/env/.env.development
uv run --project backend celery --workdir backend -A app.bootstrap.celery_app:celery_app worker --pool=solo --queues=maintenance --concurrency=1 --hostname=maintenance-1@%h --loglevel=INFO
```

环境中的 parsing 2、indexing 2 和 chat 4 表示目标 Worker 副本数；maintenance 的目标副本数为 1。它们不改变 Windows `solo` Worker 的单进程有效并发数。

## 9. 启动 Celery Beat

在另一个 PowerShell 7 终端从仓库根目录启动唯一的 Beat 进程：

```powershell
. ./deploy/scripts/import-env.ps1 -Path deploy/env/.env.development
uv run --project backend celery --workdir backend -A app.bootstrap.celery_app:celery_app beat --loglevel=INFO
```

定时 outbox 分发、outbox reconciliation 和 Worker heartbeat 任务依赖 Beat 调度。开发运行时只启动一个 Beat；缺少 Beat 时这些周期任务不会被投递。

## 10. 启动前端

在另一个 PowerShell 7 终端从仓库根目录执行：

```powershell
npm --prefix frontend run dev
```

前端仅监听 `http://127.0.0.1:5173`，开发代理将 `/api/v1` 请求转发到 `http://127.0.0.1:8001`。

## 11. 健康和状态检查

```powershell
(Invoke-WebRequest -Uri http://127.0.0.1:8001/api/v1/health/live -UseBasicParsing).StatusCode
(Invoke-WebRequest -Uri http://127.0.0.1:8001/api/v1/health/ready -UseBasicParsing).StatusCode
(Invoke-WebRequest -Uri http://127.0.0.1:8001/api/v1/health/dependencies -UseBasicParsing).StatusCode
(Invoke-WebRequest -Uri http://127.0.0.1:5173 -UseBasicParsing).StatusCode
pwsh -NoProfile -File scripts/dev-status.ps1
```

`dev-status.ps1` 只读检查 Compose 依赖、三个 API 健康端点和 Celery ping，不启动、停止或修改服务。

## 12. 单元、集成和 E2E 测试

单元/API 测试和前端单元测试：

```powershell
. ./deploy/scripts/import-env.ps1 -Path deploy/env/.env.development
uv run --project backend pytest backend/tests -m "not integration"
npm --prefix frontend run test:unit
```

集成测试使用前面创建的 `rag_kb_test`：

```powershell
. ./deploy/scripts/import-env.ps1 -Path deploy/env/.env.development
$env:RAG_TEST_DATABASE_URL = $env:DATABASE_URL -replace '/rag_kb$', '/rag_kb_test'
if ($env:RAG_TEST_DATABASE_URL -eq $env:DATABASE_URL) {
  throw 'DATABASE_URL must end in /rag_kb before deriving RAG_TEST_DATABASE_URL.'
}
$developmentDatabaseUrl = $env:DATABASE_URL
$developmentAppEnv = $env:APP_ENV
try {
  $env:APP_ENV = 'test'
  $env:DATABASE_URL = $env:RAG_TEST_DATABASE_URL
  uv run --project backend pytest backend/tests -v -m integration
}
finally {
  $env:DATABASE_URL = $developmentDatabaseUrl
  $env:APP_ENV = $developmentAppEnv
}
```

E2E 需要 API 和前端正在运行，并且以下三个变量仅在当前测试终端中设置。请从本机忽略环境取得用户名和当前密码，并交互式输入不同的新密码：

```powershell
. ./deploy/scripts/import-env.ps1 -Path deploy/env/.env.development
$env:RAG_E2E_USERNAME = $env:INITIAL_ADMIN_USERNAME
$env:RAG_E2E_PASSWORD = $env:INITIAL_ADMIN_PASSWORD
$env:RAG_E2E_NEW_PASSWORD = Read-Host -MaskInput 'Enter a new local-only E2E password'
npm --prefix frontend exec -- playwright install chromium
npm --prefix frontend run test:e2e
```

认证 smoke 会修改管理员密码。只对专用本地测试状态运行，不要指向共享或生产数据库；再次运行前应使用该状态当前密码。

仓库根检查与 CI 的静态/单元命令一致：

```powershell
pwsh -NoProfile -File scripts/check.ps1
```

## 13. 停止并保留数据卷

在 API、9 个 Worker 副本、Celery Beat 和前端终端分别按 `Ctrl+C`。然后从仓库根目录停止依赖：

```powershell
docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml down
```

该命令保留 PostgreSQL、Redis 和 Chroma 命名卷，下次 `up -d --wait` 会复用数据。

`docker compose ... down -v` 会删除这些命名卷，包括本地数据库和向量数据。它是显式的破坏性清理操作，绝不是日常启动或故障排查的第一步；仅在已确认不需要任何卷数据并接受无法恢复时手工执行。
