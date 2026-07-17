# Windows 开发故障排查

本文档的命令默认从仓库根目录在 PowerShell 7 执行，并假设已按 [Windows 开发运行指南](windows-development.md) 创建本机忽略环境。每个症状都先检查、再非破坏性修复。不要在工单、截图或终端输出中暴露本机环境值。

## Docker Desktop Linux pipe 不存在

典型报错包含 `dockerDesktopLinuxEngine` pipe 不存在或 Docker daemon 无法连接。

检查：

```powershell
docker desktop status
docker context show
docker context ls
Test-Path -LiteralPath '\\.\pipe\dockerDesktopLinuxEngine'
docker info --format '{{.OSType}}'
```

修复：

```powershell
docker desktop start
docker desktop engine use linux
docker context use desktop-linux
docker info --format '{{.OSType}}'
```

如果 `docker desktop` 子命令不可用，从开始菜单启动 Docker Desktop，通过托盘菜单切换到 Linux containers，等待引擎就绪后重试。不要通过删除 Docker Desktop 数据或项目卷来修复 pipe 问题。

## 端口 5432、6379、8000、8001 或 5173 被占用

检查监听进程，再根据 PID 确认所属程序：

```powershell
$ports = 5432, 6379, 8000, 8001, 5173
$listeners = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
  Where-Object LocalPort -In $ports |
  Sort-Object LocalPort
$listeners | Select-Object LocalAddress, LocalPort, OwningProcess
$listeners | ForEach-Object {
  Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue |
    Select-Object Id, ProcessName, Path
}
docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml ps
```

修复：先通过对应应用的正常退出方式停止已确认的占用者，再重新启动本项目。不要对未识别 PID 盲目执行 `Stop-Process -Force`。

PostgreSQL、Redis 和 Chroma 的本地宿主端口可在 `deploy/env/.env.development` 中调整；同时修正该本机文件中对应的 `DATABASE_URL`、`REDIS_URL` 或 `CHROMA_PORT`，然后重新导入并启动依赖：

```powershell
. ./deploy/scripts/import-env.ps1 -Path deploy/env/.env.development
docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml up -d --wait
```

API `8001` 和前端 `5173` 是开发代理契约端口。优先停止占用者，不要只改启动参数造成前后端地址漂移。

## Alembic 不在 head 或检出 schema 漂移

检查当前 revision、仓库 head 和自动生成漂移：

```powershell
. ./deploy/scripts/import-env.ps1 -Path deploy/env/.env.development
uv run --project backend alembic -c backend/alembic.ini current
uv run --project backend alembic -c backend/alembic.ini heads
uv run --project backend alembic -c backend/alembic.ini check
```

数据库落后时执行唯一常规修复：

```powershell
uv run --project backend alembic -c backend/alembic.ini upgrade head
uv run --project backend alembic -c backend/alembic.ini current
uv run --project backend alembic -c backend/alembic.ini check
```

如果存在多个 head 或 `check` 仍报告 operations，先审查本分支的 model/migration 差异；不要对开发库执行 `downgrade base`、drop schema 或删卷。

## Cookie 或 CSRF 请求返回 403

本项目使用 HttpOnly 会话 Cookie 和可读的 `rag_csrf` Cookie。`POST`、`PUT`、`PATCH` 和 `DELETE` 请求必须发送匹配的 `X-CSRF-Token` header，并携带 credentials。

检查服务、本机时钟和访问地址：

```powershell
Get-Date
(Invoke-WebRequest -Uri http://127.0.0.1:5173 -UseBasicParsing -SkipHttpErrorCheck).StatusCode
(Invoke-WebRequest -Uri http://127.0.0.1:8001/api/v1/health/live -UseBasicParsing -SkipHttpErrorCheck).StatusCode
```

在浏览器 DevTools 中检查：

- 页面始终从 `http://127.0.0.1:5173` 访问，不混用 `localhost`、IP 和直连 API 地址。
- Application/Storage 中存在当前 origin 的会话 Cookie 和 `rag_csrf`，且未过期。
- 失败的非安全方法请求包含 `X-CSRF-Token`，值来自 `rag_csrf`，请求携带 Cookie。
- 系统时钟、时区、Cookie domain/path/SameSite 未导致 Cookie 被拒绝。

修复时关闭混用 origin 的标签页，清除仅 `127.0.0.1:5173` 的过期开发 Cookie，重新登录并通过前端代理重试。不要将 access token 改存到 `localStorage`，也不要关闭 CSRF 校验。

## PostgreSQL、Redis 或 Chroma 不健康

先检查 Compose 状态和单个依赖，不输出本机环境文件：

```powershell
. ./deploy/scripts/import-env.ps1 -Path deploy/env/.env.development
docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml ps
docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml exec -T postgres pg_isready --username $env:POSTGRES_USER --dbname $env:POSTGRES_DB
docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml exec -T redis redis-cli ping
(Invoke-WebRequest -Uri http://127.0.0.1:$env:CHROMA_PORT/api/v2/heartbeat -UseBasicParsing -SkipHttpErrorCheck).StatusCode
docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml logs --tail 100 postgres
docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml logs --tail 100 redis
docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml logs --tail 100 chroma
```

重启只有问题的服务，然后使用现有等待脚本复查：

```powershell
docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml restart postgres
pwsh -NoProfile -File deploy/scripts/wait-for-dependencies.ps1 -EnvFile deploy/env/.env.development
```

将 `postgres` 替换为已确认故障的 `redis` 或 `chroma`。如果重启后仍不健康，保留上述状态和日志进一步定位；不要先删除卷。

## Worker heartbeat 缺失或队列未监听

检查 broker、Worker ping、活动队列和 heartbeat key 是否存在，不读取 heartbeat 值：

```powershell
. ./deploy/scripts/import-env.ps1 -Path deploy/env/.env.development
docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml exec -T redis redis-cli ping
uv run --project backend celery --workdir backend -A app.bootstrap.celery_app:celery_app inspect ping --timeout 5
uv run --project backend celery --workdir backend -A app.bootstrap.celery_app:celery_app inspect active_queues --timeout 5
docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml exec -T redis redis-cli exists celery:heartbeat
pwsh -NoProfile -File scripts/dev-status.ps1
```

`active_queues` 应分别显示 `parsing`、`indexing`、`chat` 和 `maintenance`。修复时从仓库根目录的四个独立终端重新导入环境，再使用 [四个 Worker 启动命令](windows-development.md#8-启动四个独立-worker)。确认 maintenance 队列的 worker 存活；不要通过清空 Redis 来修复队列路由或 heartbeat 问题。

## npm/package-lock 漂移

检查锁文件与声明的 npm 版本：

```powershell
npm --version
npm --prefix frontend ci
git status --short -- frontend/package.json frontend/package-lock.json
git diff -- frontend/package.json frontend/package-lock.json
```

`npm ci` 失败时先确认 npm 是 11.13.0。如果依赖变更是有意的，用精确版本执行 `npm --prefix frontend install <package>@<version> --save-exact`，审查 `package.json` 和 `package-lock.json` 后再提交两者。如果变更不是有意的，不要重新生成锁文件；先保留工作区并确认应恢复的已审核版本。

## uv.lock 漂移

使用锁定检查定位是工具版本、`pyproject.toml` 还是 lock 不一致：

```powershell
uv --version
uv lock --project backend --check
uv sync --project backend --frozen --all-groups
git status --short -- backend/pyproject.toml backend/uv.lock
git diff -- backend/pyproject.toml backend/uv.lock
```

先确认 uv 是 0.11.28。如果依赖变更是有意的，使用项目命令更新并审查 lock：

```powershell
uv lock --project backend
uv sync --project backend --frozen --all-groups
git diff -- backend/pyproject.toml backend/uv.lock
```

如果变更不是有意的，不要用非 frozen sync 掩盖漂移，也不要为了让安装通过而改宽版本范围。

## 破坏性操作警告

`docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml down -v`、删除 Docker Desktop 数据、drop database/schema 和 Alembic `downgrade base` 都可能不可逆地清除本地开发状态。这些不是任何上述症状的常规第一步。只有在已备份所需数据、确认目标范围并明确接受数据丢失后，才可手工执行。
