# 部署与运行阶段性真源

> 文档职责：定义开发/生产拓扑、Docker、Celery/Redis、环境变量、健康检查、迁移、备份恢复和第一版容量基线。

## 1. 部署形态

第一版提供两套明确方式：

- Windows 开发：Docker Desktop 运行基础依赖，FastAPI/Celery/前端在 Windows 本机运行。
- 单节点生产：Linux + Docker Compose 运行完整应用栈。

Windows + Docker Desktop 是开发环境，不作为企业生产部署承诺。第一版不做 Kubernetes、HA、多区域和自动弹性扩缩。

## 2. Windows 开发拓扑

Docker Desktop：

- PostgreSQL。
- Redis。
- Chroma。

Windows 本机：

- FastAPI/uvicorn。
- Parsing Worker，`--pool=solo`。
- Indexing Worker，`--pool=solo`。
- Chat/Maintenance Worker，`--pool=solo`，开发可合并队列。
- Ant Design Pro/Umi Max dev server。

必须提供 PowerShell 友好的分步骤命令、`.env.example`、健康脚本和常见错误排查。所有命令从 Monorepo 根目录执行并说明当前工作目录。

## 3. 生产 Docker Compose

服务：

```text
frontend-proxy        Nginx/Caddy，静态前端、TLS、反向代理
api                   FastAPI ASGI
worker-parsing        Celery parsing 队列
worker-indexing       Celery indexing 队列
worker-chat           Celery chat 队列
worker-maintenance    outbox、callback、清理、统计
scheduler             Celery Beat 或独立调度器
postgres              业务真源
redis                 broker/cache/rate limit
chroma                向量索引服务
```

所有镜像和依赖固定版本或 digest，禁止 `latest`。PostgreSQL、Redis、Chroma 不发布宿主公网端口；只在 Compose 内网通信。

持久卷：

- PostgreSQL data。
- Chroma data。
- `STORAGE_ROOT` 原始文件/解析产物。
- 备份目录。

Redis 不是业务真源，但生产开启 AOF everysec，减少队列波动；Redis 丢失后由 PostgreSQL outbox/reconciler 重发未完成任务。

## 4. 队列隔离

队列：

- `parsing`：MinerU 提交、轮询、下载、标准化。
- `indexing`：分块、Embedding、索引和 generation 校验。
- `chat`：异步问答和临时附件问答。
- `maintenance`：outbox、callback、清理、指标和评测。

解析/索引任务不能阻塞聊天队列。默认生产并发：

- parsing 2。
- indexing 2。
- chat 4。
- maintenance 1。

均通过环境变量调整并受 Provider 限流约束。Celery 设置：

- `task_acks_late=true`。
- `task_reject_on_worker_lost=true`。
- `worker_prefetch_multiplier=1` 用于长任务队列。
- 每类任务有明确 soft/hard time limit；业务轮询超时仍以需求状态机为准。
- task serializer 只允许 JSON，禁止 pickle。

## 5. Outbox 和恢复

- API 事务写 `task_outbox`，maintenance worker 发布 Celery。
- outbox 未发布记录每 5 秒扫描一次。
- operation queued 但超过 1 分钟无已发布事件时 reconciler 自动补发并告警。
- Worker 启动先尝试幂等 claim；同一 operation 重复投递只有一个执行者。
- Redis 清空后重新发布 pending/retryable operation，不重提已经有 providerTaskId 的 MinerU 任务。

## 6. 环境变量

至少包括：

```env
APP_ENV=development|production
APP_VERSION=
API_BASE_URL=
FRONTEND_ORIGIN=

DATABASE_URL=
REDIS_URL=
CHROMA_HOST=
CHROMA_PORT=
STORAGE_ROOT=

JWT_SIGNING_KEY=
CREDENTIAL_ENCRYPTION_KEY=
INITIAL_ADMIN_USERNAME=
INITIAL_ADMIN_PASSWORD=
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

MinerU Token和模型 Provider Key 通过后台加密保存，不要求长期写 `.env`。生产 secret 不提交仓库、不进入 Compose 示例明文。

## 7. 启动和迁移

部署顺序：

1. 校验环境变量和目录权限。
2. 启动 PostgreSQL/Redis/Chroma，等待健康。
3. 执行 Alembic migration；失败则停止发布。
4. 启动 API 和 Worker。
5. 启动 frontend-proxy。
6. 执行 readiness 和最小 smoke test。

迁移规则：

- Schema 只通过 Alembic 变更，不在应用启动时 `create_all` 代替迁移。
- 生产禁止自动执行不可逆/大表 destructive migration。
- 数据回填使用可恢复脚本并记录进度。
- API、Worker 和 schema 有兼容窗口；滚动升级期间旧 Worker 不得消费不兼容任务 schema。
- 每个 outbox/task payload 保存 `schemaVersion`。

## 8. 健康检查

端点：

- `/health/live`：进程事件循环可响应，不查询外部依赖。
- `/health/ready`：数据库迁移版本正确、PostgreSQL 可写、必要配置存在。
- `/health/dependencies`：PostgreSQL、Redis、Chroma、Storage、Worker heartbeat、MinerU/模型配置摘要。

外部 MinerU/模型临时不可用不让 API liveness 失败，但依赖状态标记 degraded。Redis/Chroma 失败时相关写/检索接口返回 503，读取不相关管理数据仍可用。

健康脚本输出 JSON 和人类可读摘要，退出码：0 healthy、1 degraded、2 unhealthy。

## 9. 存储布局

物理路径只使用内部 ID：

```text
storage/
  blobs/{sha256-prefix}/{sha256}
  parsing/{dataSourceId}/{parsedSourceVersionId}/
    raw/
    extracted/
    normalized/
  temp/attachments/{attachmentId}/
  temp/operations/{operationId}/
  exports/
```

知识库 chunks 的业务真源在 PostgreSQL；可选 JSON 调试导出放 generation 路径但不是数据库替代。

- 临时写入后 fsync/校验再原子 rename。
- 每个产物保存 SHA-256 和大小。
- `STORAGE_ROOT` 一旦有数据不能通过后台随意修改。
- 启动检查目录可写和剩余空间。

## 10. 备份和恢复

第一版单节点目标：默认 RPO 24 小时、RTO 4 小时；部署方可提高频率。

备份至少包括：

- PostgreSQL 一致性备份。
- `STORAGE_ROOT` 快照。
- Chroma 持久卷快照，或明确使用 PostgreSQL chunks + 模型配置重建。
- 版本匹配的环境配置摘要。
- `JWT_SIGNING_KEY` 和 `CREDENTIAL_ENCRYPTION_KEY` 的安全离线备份。

Redis 不需要业务数据备份。

每日备份：

1. 记录应用版本、schema revision 和备份时间。
2. 执行 PostgreSQL 备份。
3. 对 Storage/Chroma 做快照或暂停写入的短一致性窗口。
4. 生成 manifest 和校验和。
5. 在独立位置保存，不能只放同一磁盘。

恢复顺序：PostgreSQL -> Storage -> Chroma（或重建）-> 密钥 -> migration compatibility check -> health -> 抽样引用/检索测试。

发布前必须至少实际演练一次恢复，不能只写备份脚本不验证。

## 11. 日志和时钟

- 容器日志输出 stdout JSON，由宿主采集和轮转。
- 默认每文件/日志流轮转 100 MB，保留 14 天；业务 Trace 保留由数据库策略决定。
- 所有主机和容器使用 NTP，同步 UTC。
- 日志中时间带时区，traceId 可跨服务查询。
- 生产不启用 debug SQL、HTTP body 或供应商密钥日志。

## 12. 容量基线

第一版是单节点中小规模企业基线，不宣称无限扩展。参考验收环境：

- 8 vCPU。
- 32 GB RAM。
- NVMe SSD，数据盘至少 200 GB并按文档增长扩容。
- MinerU 和业务模型使用外部 API。

验收负载目标：

- 50 个知识库。
- 5000 个活动数据源/解析版本。
- 50 万个活动检索 chunks。
- 10 个并发问答请求。
- 2 个并发解析任务和 2 个并发构建任务。

这些是发布前压测基线，不是硬编码产品上限。达到 70% 资源或索引容量时告警；规模继续增长时优先增加 Worker、替换向量库/对象存储，再考虑拆服务。

## 13. 反向代理和网络

- frontend 和 API 同域部署，减少 Cookie/CORS 风险。
- TLS 终止于受控反向代理。
- 上传 body size、连接/读取超时与应用限制一致。
- `/chat:sync` 代理超时略高于应用 60 秒，例如 70 秒。
- 内部服务网络与公共入口分离。
- 管理后台可通过 VPN/内网或额外网关限制访问。

## 14. 发布和回滚

- 发布前运行 migration dry-run、单元/集成/E2E、OpenAPI diff、compose config 检查和备份。
- 应用镜像带版本，禁止覆盖同 tag。
- 回滚应用前确认数据库 migration 向后兼容；不兼容时使用前向修复，不强行降 schema。
- 知识库 index generation 与应用发布分离，应用回滚不能删除活动 collection。

## 15. 部署验收

- Windows 开发可按文档分别启动依赖、API、各 Worker 和前端。
- Linux Compose 从空机器完成启动、迁移、管理员初始化和 smoke test。
- 停止 Redis、Chroma、Worker、MinerU 网络后系统分别返回可定位 degraded/error，不误报无命中。
- Redis 数据清空后 outbox 能恢复未发布任务且不重复提交上游任务。
- 备份可在干净环境恢复并通过解析来源、知识库检索和机器人问答抽测。
- 数据库/Redis/Chroma 无公共端口，生产 OpenAPI 按配置关闭。
