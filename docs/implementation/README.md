# 企业级 RAG 知识库 V1 分阶段实施路线图

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement each approved phase task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变已确认需求语义的前提下，把当前文档基线分阶段交付为可部署、可追溯、可验收的企业级 RAG 知识库 V1。

**Architecture:** 采用 Monorepo、模块化单体 FastAPI、独立 Celery Worker、PostgreSQL 业务真源、Redis 队列、Chroma 向量索引、本地 StorageAdapter 和 Ant Design Pro/React 管理后台。每个阶段都形成可运行的纵向增量，并以测试、OpenAPI、迁移和验收证据作为进入下一阶段的门禁。

**Tech Stack:** Python 3.13、FastAPI、SQLAlchemy、Alembic、Celery、PostgreSQL 17、Redis 7、Chroma 1.5、Ant Design Pro v6.0.2 Simple Mode、React 19、Umi Max 4、Ant Design 6、TypeScript、npm、Docker Compose、GitHub Actions。

---

## 1. 文档职责

本目录是实施计划，不是需求真源。

- 需求语义以 `docs/requirements/` 为唯一真源。
- 路径、DTO 和错误码以 `docs/api/v1-api-contract.md` 为开发契约。
- 表、列、约束和迁移顺序以 `docs/database/schema.md` 为数据库契约。
- 状态转换以 `docs/state-machines/state-machines.md` 为状态机契约。
- 页面动作以 `docs/frontend-api-map/page-api-map.md` 为前后端映射契约。
- 发布结论以 `docs/acceptance/v1-acceptance.md` 的证据为准。
- 实施中发现契约歧义时停止对应任务，先修改唯一需求真源及所有受影响的派生文档，再修改计划和代码。

本路线图只决定交付顺序、工程文件、依赖版本、验证方式和阶段门禁，不得自行改变产品规则。

## 2. 当前门禁

当前代码状态：生产代码尚未创建。

当前文档状态：`IMPLEMENTATION PLAN IN REVIEW`。需求和开发契约基线已进入实施计划审阅；只有用户明确确认本路线图和第一阶段详细计划后，才建立第一阶段开发分支并写生产代码。

第一阶段详细计划：`docs/implementation/01-foundation-implementation-plan.md`。

后续阶段在上一阶段通过退出门禁后，依据本路线图分别形成独立详细计划。这样可以使用已经验证的 OpenAPI、迁移和适配器契约，不让早期猜测扩散到后续五十余张表和全部页面。

## 3. 锁定版本基线

版本快照日期：2026-07-13。所有直接依赖使用精确版本，传递依赖以锁文件为准；禁止浮动 `latest`、`^` 和 `~`。

### 3.1 运行时和包管理

| 组件 | 锁定版本 | 约束 |
|---|---:|---|
| Python | 3.13.9 | `.python-version`、`pyproject.toml` 和生产镜像一致 |
| uv | 0.11.28 | 生成并校验 `backend/uv.lock` |
| Node.js | 24.16.0 LTS | `.node-version` 和 CI 一致 |
| npm | 11.13.0 | 根 `packageManager`、`frontend/package-lock.json` 和 CI 一致 |
| Ant Design Pro | v6.0.2 | 固定 commit `2b453c67b535b76f5f95d6542397a4b987b61de2`，保留 MIT License，不跟随 `master` |

### 3.2 后端直接依赖

| 包 | 版本 | 用途 |
|---|---:|---|
| fastapi | 0.139.0 | HTTP API/OpenAPI |
| uvicorn | 0.51.0 | ASGI server |
| pydantic | 2.13.4 | DTO 和配置校验 |
| pydantic-settings | 2.14.2 | 强类型环境配置 |
| sqlalchemy | 2.0.51 | ORM/事务 |
| alembic | 1.18.5 | 唯一 schema 迁移工具 |
| psycopg | 3.3.4 | PostgreSQL 驱动 |
| psycopg-pool | 3.3.1 | 连接池 |
| celery | 5.6.3 | 异步任务 |
| redis Python client | 6.4.0 | 满足 Kombu `redis < 6.5` 约束 |
| chromadb | 1.5.9 | Chroma HTTP client/契约测试 |
| httpx | 0.28.1 | 上游 API 和测试客户端 |
| structlog | 26.1.0 | 结构化日志 |
| PyJWT | 2.13.0 | 管理员 JWT |
| argon2-cffi | 25.1.0 | Argon2id 密码哈希 |
| cryptography | 49.0.0 | AES-256-GCM 凭据加密 |
| python-multipart | 0.0.32 | 后续流式上传协议支持 |

开发门禁固定使用 pytest 9.1.1、pytest-asyncio 1.4.0、pytest-cov 7.1.0、testcontainers 4.14.2、ruff 0.15.21、mypy 2.2.0、respx 0.23.1、freezegun 1.5.5 和 pip-audit 2.10.1。

### 3.3 前端关键直接依赖

第一阶段以 Ant Design Pro v6.0.2 的 `package-lock.json` 为解析真源。以下是必须单独审计的关键版本；其他保留的直接依赖也在导入审计后写为锁文件中的精确版本，不保留 `^`/`~` 浮动范围：

| 包 | 版本 |
|---|---:|
| react | 19.2.5 |
| react-dom | 19.2.5 |
| antd | 6.4.3 |
| @ant-design/icons | 6.2.3 |
| @ant-design/pro-components | 3.1.12-0 |
| @ant-design/x | 2.7.0 |
| @ant-design/x-markdown | 2.7.0 |
| @ant-design/x-sdk | 2.7.0 |
| @tanstack/react-query | 5.100.9 |
| @umijs/max | 4.6.51 |
| @umijs/max-plugin-openapi | 2.0.3 |
| typescript | 6.0.3 |
| @biomejs/biome | 2.4.14 |
| @testing-library/react | 16.3.2 |
| jest | 30.4.1 |
| jest-environment-jsdom | 30.4.1 |
| tailwindcss | 4.3.0 |
| antd-style | 4.1.0 |
| @playwright/test | 1.61.1 |

模板在独立阶段 worktree 中分三次形成可审查历史：先导入固定 commit 的完整可运行应用并提交，再执行官方 `npm run simple`、审查删除范围并提交，最后删除 Simple Mode 仍保留的 Welcome/Admin/查询表格、Mock、上游品牌和无关插件并建立产品壳。沿用 ProLayout、ProComponents、Ant Design、Umi Router/request/initialState/model/React Query/OpenAPI 和登录布局；第一版不把 Umi access 扩展成虚假 RBAC。

官方 Simple Mode 会移除 `@ant-design/plots`、D3 和 TopoJSON。第一阶段接受该删除，阶段 7 根据实际指标图表重新引入所需精确依赖，不提前保留未使用图表栈。

### 3.4 基础设施镜像

开发和 CI 使用多架构 manifest digest；生产发布重新构建应用镜像并记录 digest，但不能更换下列服务版本而不运行 Adapter 契约测试。

| 服务 | 镜像 |
|---|---|
| PostgreSQL | `postgres:17.10-bookworm@sha256:5530681ea5d3e2ed4ce396f9b5cb443efbac6baf2a8a19c0c0635e40ae7eadce` |
| Redis | `redis:7.4.9-bookworm@sha256:b2b95679e3b46fb51864949ed25ea976fc3a6bcc00a40a1bc00d568cb2822e50` |
| Chroma | `chromadb/chroma:1.5.9@sha256:1e0b73a187a28757c572acba508c46f48c9e8b0acaf5c20e6d95cdedce1acdf6` |
| Python build/runtime | `python:3.13.9-slim-bookworm@sha256:b685a4fa58bb19d1814d78a1ec0f0208f351452724f78b20212c984d6e124a34` |

开发端口固定为：前端 `5173`、FastAPI `8001`、Chroma `8000`、PostgreSQL `5432`、Redis `6379`。生产只公开反向代理的 `80/443`。

## 4. 分支、提交和变更规则

1. 计划确认后从 `main` 创建 `codex/phase-01-foundation`，不直接在 `main` 开发生产代码。
2. 每个任务按“失败测试 -> 最小实现 -> 通过测试 -> 小提交”执行。
3. 一个提交只承担一个可解释目的；迁移、ORM、API、OpenAPI 和对应测试必须在同一功能提交中保持一致。
4. 不使用 `git add -A` 混入无关文件；生成物只提交明确允许的 OpenAPI、generated service 和锁文件。
5. 每阶段通过代码审查、CI 和阶段验收后再合并；失败证据不得通过关闭测试或降低阈值处理。
6. 后续增加能力时先更新 capability 注册和契约，不在页面或 service 增加供应商字符串分支。

## 5. 阶段总览

| 阶段 | 目标 | 主要输出 | 退出门禁 |
|---|---|---|---|
| 1. 工程骨架与基础设施 | 建立可运行、可迁移、可测试的工程闭环 | Monorepo、依赖锁、Compose、FastAPI 核心、认证、健康、Operation/Outbox/Celery、前端壳、OpenAPI 生成、CI | 全新环境可启动；迁移、登录、健康、幂等任务和前端构建通过 |
| 2. 模型配置与数据解析 | 交付模型注册和独立解析闭环 | Provider/Model、凭据加密、真实类型测试、MinerU 设置、上传、ParsedSourceVersion、对比和解析 UI API | 模型选择规则和 MinerU/builtin_text 解析验收通过 |
| 3. 知识库构建与检索 | 交付多知识库、分块、索引和单库检索 | 配置修订、五种分块、两种结构、Chroma HNSW、pg_trgm、三种检索、重写、重排、generation 原子激活 | 首次/重建/partial/失败重试和检索固定样例通过 |
| 4. 机器人运行时 | 交付多机器人、多库融合、记忆、兜底和引用 | BotConfigRevision、并行单库检索、跨库加权 RRF、上下文预算、ChatRun、Citation | 命中、无命中、部分失败、全失败和引用来源验收通过 |
| 5. Webhook/API 渠道 | 交付第一版外部接入面 | ChannelInstance、一次性 API Key、同步/异步、幂等、限流、附件、callback | 渠道鉴权、60 秒边界、异步查询、HMAC 和附件生命周期通过 |
| 6. React 管理后台与联调 | 完成所有后台业务页面并与 generated service 对齐 | 固定导航、解析/模型/知识库/机器人/渠道/任务/日志/设置页面、错误和 operation 交互 | 页面/API 对照表、响应式和关键 Playwright 流程通过 |
| 7. 可观测性与 RAG 质量 | 形成可排障、可评测的运行闭环 | Trace、审计、仪表盘、指标聚合、评测集、Hit@K/Recall@K/MRR/No-hit accuracy、保留清理 | 指标口径、敏感 Trace、评测固定样例和任务排障通过 |
| 8. 生产部署与发布验收 | 完成 Linux 单节点交付和恢复证据 | 完整 Compose、反向代理、镜像、备份恢复、容量测试、安全扫描、发布清单 | `docs/acceptance/v1-acceptance.md` 全部适用项有证据 |

## 6. 阶段 1：工程骨架与基础设施

### 输入

- 已确认的需求和开发契约。
- 空的生产代码目录。
- Windows Docker Desktop 开发环境；执行时必须先启动 Docker Desktop。

### 工作包

1. 固定 Monorepo 结构、运行时、直接依赖、锁文件和根命令。
2. 提供 PostgreSQL、Redis、Chroma 开发 Compose、持久卷和健康检查。
3. 建立 FastAPI app factory、强类型配置、camelCase DTO、统一错误、traceId 和结构化日志。
4. 建立 SQLAlchemy session、Alembic 初始迁移、`pg_trgm`、管理员/审计/Operation/Outbox 基础表。
5. 完成单管理员初始化、Argon2id、JWT Cookie、CSRF、authVersion 和登录限流。
6. 建立 Storage/Redis/Chroma/PostgreSQL 健康 Adapter 和三个健康端点。
7. 建立 Operation 状态机、Transactional Outbox、Celery 四队列、重复投递 claim 和最小 noop 任务证明。
8. 导入并记录 Ant Design Pro 固定基线，分提交执行 Simple Mode 和 demo 清理，建立中文登录、运行健康/任务管理壳；完整固定导航随阶段 6 的真实页面落地。
9. 使用 `@umijs/max-plugin-openapi` 从 FastAPI OpenAPI 生成唯一前端 service，并统一经过 Umi request；CI 检查生成结果无漂移。
10. 建立 backend/frontend/integration 最小 CI 闭环和 Windows 启动文档。

### 退出门禁

- `uv sync --project backend --frozen --all-groups` 和 `npm --prefix frontend ci` 成功。
- Compose 配置无浮动镜像，三个依赖达到 healthy。
- 空 PostgreSQL 执行 Alembic upgrade 到 head，重复检查不产生 schema 漂移。
- 初始管理员只创建一次；登录、首次强制改密、logout/authVersion 和 CSRF 测试通过。
- `/api/v1/health/live` 不访问依赖；ready/dependencies 能区分 healthy/degraded/unhealthy/not_configured。
- 业务记录、Operation 和 Outbox 在同一事务；重复 Celery delivery 不重复执行业务副作用。
- OpenAPI 生成的 TypeScript service 无手写 DTO，重新生成后 `git diff --exit-code`。
- Ruff、mypy、pytest、Biome、TypeScript、Jest/React Testing Library、Playwright smoke 和前端 build 全通过。

详细步骤见 `docs/implementation/01-foundation-implementation-plan.md`。

## 7. 阶段 2：模型配置与数据解析

### 入口门禁

阶段 1 已合并；认证、Operation、Outbox、加密服务、StorageAdapter 和 generated service 可复用。

### 工作包

1. 按 `model_providers/model_configs/model_verifications` 迁移实现 Provider 和 Model 聚合。
2. 实现 OpenAI、OpenAI-Compatible、DeepSeek、通义千问 Adapter；LLM、Embedding、Rerank、Vision 分类型验证。
3. 实现 AES-256-GCM 凭据保存、遮罩响应、引用锁定、stale/failed/passed 状态和模型选择查询。
4. 实现 MinerU 设置保存与独立完整连接测试 Operation；外发确认单独持久化。
5. 实现流式上传、MIME/签名检查、SHA-256 SourceBlob 去重和安全 ZIP 展开。
6. 实现 `builtin_text` 和 MinerU Precision API Adapter，按 `batchId + dataId` 映射任务。
7. 实现不可变 ParsedSourceVersion、轮询/下载/标准化 checkpoint、失败继续查询和重试边界。
8. 实现 parsed blocks/assets/artifacts、处理前后对比和可选解析版本查询 API。

### 退出门禁

- 未测试、失败、stale、disabled 和类型错误模型无法被业务选择。
- Provider 凭据和 MinerU Token 不出现在数据库明文、响应、日志、Trace 或 OpenAPI 示例。
- 上传不自动解析；开始解析才同事务创建 ParsedSourceVersion、Operation 和 Outbox。
- MinerU 超时继续查询不重复提交；下载/标准化重试不重复收费。
- 新解析版本不自动影响知识库；`succeeded/degraded` 才可选择。
- 对应验收清单第 3、4、5 节通过。

## 8. 阶段 3：知识库构建与检索

### 入口门禁

阶段 2 已合并；至少有一个验证通过的 Embedding、LLM、Rerank 配置和多种特征解析版本 fixture。

### 工作包

1. 实现 KnowledgeBase、构建/检索配置修订、具体解析版本绑定和创建事务。
2. 实现 Token、段落、标题、按页、语义五种 Strategy 及参数 JSON Schema/capability。
3. 实现 Chunk 和 Parent-Child 两种索引结构、来源 block/asset 映射和确定性 ID。
4. 实现 Chroma collection 隔离、HNSW cosine score contract 和 PostgreSQL pg_trgm GIN。
5. 实现 vector/keyword/hybrid、RRF/Weighted Score、HyDE/Multi-Query/Step-Back、模型/LLM 重排。
6. 实现 staging generation、逐项 checkpoint、校验、首次 partial 激活和已有活动索引原子切换。
7. 实现失败项重试、活动 partial 继任 repair generation、迟到 Worker 防覆盖和延迟清理。
8. 实现检索测试 API、完整 JSON、来源追溯和离线参数覆盖而不写 ChatRun。

### 退出门禁

- 每个知识库独立 chunks、关键词命名空间和 Chroma collection，同一 Embedding 配置不共享索引状态。
- 五种分块、两种结构、三种检索、四种重写状态和三种重排状态均有固定输入输出回归。
- 重建期间旧索引服务；失败不切活动指针；成功同事务切 generation/retrieval revision。
- pg_trgm 查询计划使用 GIN，Chroma distance 到 relevanceScore 可复算。
- 对应验收清单第 6、7、8 节通过。

## 9. 阶段 4：机器人运行时

### 入口门禁

阶段 3 已合并；多个 ready/partial_ready 知识库可稳定检索并返回完整 provenance。

### 工作包

1. 实现 Bot、不可变 BotConfigRevision、多知识库绑定、优先级和活动指针。
2. 实现 standalone query rewrite；会话历史只参与指代消解。
3. 并行冻结每库 generation/retrieval revision，分别执行并分类正常命中、正常无命中、失败和 skipped。
4. 实现跨知识库按本库 rank 的加权 RRF、exact provenance duplicate 合并和稳定排序。
5. 实现模型窗口、Prompt、query、output reserve 和上下文的确定性 token 预算。
6. 实现知识库命中回答、`message_only`、`message_then_llm` 和检索故障禁止伪装无命中。
7. 实现 S 编号上下文、citation 校验/一次修复、none/simple/standard/full 裁剪和历史快照。
8. 实现 ChatRun/Conversation/ModelCallLog 最小持久化和管理员机器人测试 API。

### 退出门禁

- 多机器人、多知识库多对多复用，跨库不比较异构原始分数。
- 有上下文且部分库失败可带警告回答；零上下文且任一库失败整体失败。
- 全部正常无命中才提示知识库未找到并按配置调用通用 LLM。
- 引用只来自最终进入 Prompt 的上下文，并可追溯到 KB/generation/chunk/解析版本/页/block/asset。
- 对应验收清单第 9、10 节通过。

## 10. 阶段 5：Webhook/API 渠道

### 入口门禁

阶段 4 已合并；统一机器人回答服务不依赖 HTTP 渠道细节。

### 工作包

1. 实现 ChannelAdapter 和 `webhook_api`，一个渠道实例绑定一个机器人。
2. 实现 256-bit API Key 一次展示、SHA-256 hash、前缀、轮换和独立鉴权依赖。
3. 实现外部 `Idempotency-Key` request hash/响应复用和同 key 不同 body 冲突。
4. 实现同步 60 秒边界、异步 Operation 查询和同渠道实例授权隔离。
5. 实现文本/即时附件/需解析附件分流、24 小时临时清理和持久导入只进入解析模块。
6. 实现限流、并发限制、HMAC callback、退避、永久 4xx 和人工重发新 delivery。

### 退出门禁

- API Key 无法跨渠道实例访问，轮换后旧 Key 立即失效。
- 同步超时不返回半截答案；异步结果只能由原实例查询。
- 临时附件不进入知识库，持久导入不自动绑定知识库。
- callback 失败不改成功 ChatRun；总投递次数和签名 fixture 可复算。
- 对应验收清单第 11 节通过。

## 11. 阶段 6：React 管理后台与完整联调

### 入口门禁

阶段 2 至 5 的业务 API 和 OpenAPI 已稳定；阶段 1 的布局、认证和 generated service 可用。

### 工作包

1. 固定侧栏顺序、解析顶部、知识库/机器人独立 `+` 与下拉箭头、系统设置底部。
2. 完成解析长页面、处理前后对比、数据源详情和版本选择。
3. 完成模型/Provider/MinerU 保存与检测分离交互。
4. 完成知识库六区创建页、详情 Tabs、动态策略 schema、构建历史、检索测试和评测入口。
5. 完成机器人列表/创建/详情、多库绑定、Prompt、记忆、兜底、引用和测试抽屉。
6. 完成渠道、任务中心、问答日志、系统设置和运行健康页面。
7. 完成 URL 筛选恢复、409/422/429/503/504 专用交互、operation polling 和敏感操作确认。

### 退出门禁

- 所有关键按钮唯一映射 `page-api-map.md` 中的 API；不存在 mock 业务数据和手写重复 DTO。
- disabled capability 显示原因但无法提交；关键数值可编辑且前后端约束一致。
- 1280x720、1440x900、1920x1080 无重叠、溢出和不可达内容。
- 页面只有一个主滚动容器，sticky 操作栏不遮挡尾部字段。
- 对应验收清单第 14 节通过。

## 12. 阶段 7：可观测性与 RAG 质量

### 入口门禁

完整业务链路已有真实 ChatRun、Operation、Provider 调用和 generation 数据。

### 工作包

1. 补齐 HTTP/Operation/Provider/ChatRun traceId 关联和敏感 Trace AES-GCM 存储。
2. 完成任务详情、阶段、item、attempt、heartbeat/stalled、错误和 retryable 视图。
3. 完成仪表盘系统、任务、RAG、模型指标聚合，明确 `generatedAt/dataThrough`。
4. 实现评测集不可变 revision、固定 generation/retrieval revision 的运行和结果快照。
5. 实现 Hit@K、Recall@K、MRR、No-hit accuracy 确定性算法和人工可算 fixture。
6. 实现按类型保留清理、审计和低命中/检索失败问题查询。

### 退出门禁

- 普通日志不含正文、Prompt、密钥和签名 URL；敏感 Trace 查看二次确认并审计。
- 在线命中率排除 retrieval failed，不冒充答案准确率。
- `admin_test` 和 KB retrieval test 不污染外部业务量。
- 评测指标与手算 fixture 一致，运行固定全部配置快照。
- 对应验收清单第 12、13 节通过。

## 13. 阶段 8：生产部署与发布验收

### 入口门禁

阶段 1 至 7 的 CI、迁移、OpenAPI、E2E 和业务验收全部通过。

### 工作包

1. 构建固定 digest 的 API、Worker、前端镜像和 Linux 单节点 Compose。
2. 配置反向代理、TLS、同源 Cookie、CSP、CORS 和内部依赖网络隔离。
3. 实现 migration/preflight/health/smoke/backup/restore PowerShell 与 shell 脚本。
4. 完成 PostgreSQL、Storage、Chroma 快照或重建方案和恢复演练。
5. 执行 50 KB、5000 sources、50 万 chunks 或等价可重复数据准备，记录 10 并发问答与队列隔离结果。
6. 执行依赖、secret、容器配置、安全头、文件/ZIP/SSRF/Prompt 注入检查。
7. 逐项填写发布验收证据，记录 commit、OpenAPI hash、migration revision、镜像 digest 和测试数据 SHA-256。

### 退出门禁

- Linux 空机可按文档启动完整栈，PostgreSQL/Redis/Chroma 不暴露公网端口。
- 依赖中断返回可定位 degraded/error，不被统计为知识库无命中。
- 实际恢复满足或明确记录 RPO 24h/RTO 4h 结果。
- `docs/acceptance/v1-acceptance.md` 所有适用项有命令、报告、截图或数据证据。
- 不存在阻塞发布的 P0/P1 缺陷、明文 secret、浮动依赖或未归类生成物。

## 14. 跨阶段需求映射

| 真源 | 主要实现阶段 | 回归阶段 |
|---|---|---|
| `01-architecture-source.md` | 1 | 2-8 |
| `02-domain-model-source.md` | 1-5 | 6-8 |
| `03-data-parsing-source.md` | 2 | 6-8 |
| `04-model-registry-source.md` | 2 | 3、4、6-8 |
| `05-knowledge-base-source.md` | 3 | 4、6-8 |
| `06-retrieval-source.md` | 3 | 4、6-8 |
| `07-bot-runtime-source.md` | 4 | 5-8 |
| `08-channel-integration-source.md` | 5 | 6-8 |
| `09-frontend-source.md` | 1、6 | 7、8 |
| `10-observability-quality-source.md` | 1、4、7 | 8 |
| `11-security-source.md` | 1-5 | 6-8 |
| `12-deployment-source.md` | 1、8 | 8 |
| `13-engineering-quality-source.md` | 1 | 每阶段 |

## 15. 每阶段统一完成定义

阶段只有同时满足以下条件才允许关闭：

1. 对应需求、API、数据库、状态机和页面映射没有未处理冲突。
2. 所有新增行为先有失败测试，再有最小实现和通过证据。
3. 迁移可从该阶段入口 schema 升级到 head，失败可恢复。
4. OpenAPI 与前端 generated service 同步，重新生成无 diff。
5. 成功、空结果、失败、重试、并发、删除和依赖中断按风险覆盖。
6. 日志和 Trace 能定位对象、修订、阶段和 traceId，且不泄露敏感数据。
7. Windows 开发命令和 CI 使用同一锁文件及检查命令。
8. 对应验收项有可重复证据，不用口头或截图替代自动化断言能够覆盖的行为。
9. 工作区干净，提交范围可解释，阶段分支已推送并完成审查。
