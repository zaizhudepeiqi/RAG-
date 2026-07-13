# 企业级 RAG 知识库系统

本仓库用于交付单企业、单工作区、单管理员的私有化 RAG 知识库后台。第一版业务闭环为：数据解析、知识库构建与检索、机器人、多知识库融合、Webhook/API 渠道、引用和全链路排障。

## 文档真源

- `docs/requirements/` 是唯一需求真源。
- `docs/api/`、`docs/database/`、`docs/state-machines/`、`docs/frontend-api-map/` 和 `docs/acceptance/` 是派生开发契约。
- 发现实现与契约冲突时，先修改需求真源及派生文档，再修改代码。

## 目录

```text
backend/       FastAPI 模块化单体和 Celery Worker
frontend/      Ant Design Pro v6.0.2 Simple Mode 管理后台
deploy/        Docker Compose、环境示例和运维脚本
docs/          需求真源、开发契约和实施计划
scripts/       仓库级检查与开发辅助脚本
```

## Windows 前置条件

- Git。
- Docker Desktop，使用 Linux containers。
- Python 3.13.9。
- uv 0.11.28。
- Node.js 24.16.0。
- npm 11.13.0。
- PowerShell 7.4.17 LTS 或更新的兼容 7.x 版本。

从仓库根目录验证：

```powershell
python --version
uv --version
node --version
npm --version
pwsh --version
docker version
```

版本不一致时先修正本机工具，不修改项目锁文件规避失败。

## 开发启动

创建本机开发配置，该文件被 Git 忽略：

```powershell
Copy-Item deploy/env/.env.development.example deploy/env/.env.development
. ./deploy/scripts/import-env.ps1 -Path deploy/env/.env.development
```

启动依赖并迁移数据库：

```powershell
docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml up -d --wait
uv sync --project backend --frozen --all-groups
uv run --project backend alembic -c backend/alembic.ini upgrade head
```

分别启动 API、Worker 和前端：

```powershell
uv run --project backend uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8001
uv run --project backend celery -A app.bootstrap.celery_app:celery_app worker --loglevel=INFO
npm --prefix frontend run dev
```

## 检查

```powershell
pwsh -NoProfile -File scripts/check.ps1
```

第一阶段尚未完成前，可按 `docs/implementation/01-foundation-implementation-plan.md` 运行对应任务的局部检查。

## 密钥边界

开发示例只允许无生产价值的本机值。MinerU Token、模型 Provider Key、生产 JWT 密钥、凭据加密主密钥和渠道密钥不得提交仓库，也不得写入前端环境变量。MinerU 和模型凭据最终通过后台保存并由后端加密。
