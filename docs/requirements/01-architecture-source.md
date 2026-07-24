# 架构阶段性真源

> 文档职责：定义系统边界、模块依赖、工程目录、基础设施归属和跨模块可靠性规则。
> 领域对象及关系以 [02-domain-model-source.md](./02-domain-model-source.md) 为准；具体业务行为由对应模块真源定义。

## 1. 架构结论

第一版采用 **Monorepo + 模块化单体 + 独立 Worker 进程**，不拆微服务。

这样选择不是为了省事，而是因为第一版的解析、知识库构建、检索和问答存在大量一致性约束。过早拆微服务只会引入分布式事务、接口漂移和部署复杂度，不能提高业务质量。

运行单元：

```text
Browser
  -> Frontend (Ant Design Pro / React 19)
  -> FastAPI /api/v1
       -> PostgreSQL      业务真源、任务真源、关键词索引、日志元数据
       -> Redis           Celery broker、短期缓存、限流；不是业务真源
       -> Chroma          向量索引；可以由 PostgreSQL + 文件产物重建
       -> Local Storage   原始文件、解析产物、标准化产物
       -> Provider APIs   MinerU、LLM、Embedding、Rerank

Celery Workers
  parsing queue      解析和 MinerU 轮询/下载/标准化
  indexing queue     分块、Embedding、关键词索引、向量索引
  chat queue         异步问答和异步附件问答
  maintenance queue  callback、清理、统计聚合、健康任务
```

第一版是单节点私有化部署基线，但进程和适配器边界必须允许以后横向增加 Worker、替换存储或增加渠道。

## 2. Monorepo 目录

```text
docs/
  requirements/          唯一需求真源
  api/                   由需求派生的 API 契约
  database/              由需求派生的数据库设计
  state-machines/        由需求派生的状态机
  frontend-api-map/      页面、控件、DTO、API 对照表
  acceptance/            验收清单和标准测试集说明

backend/
  app/
    main.py
    bootstrap/           应用装配、生命周期和依赖注入
    core/                配置、错误、鉴权、日志、时间、ID
    modules/             业务模块
    infrastructure/      外部系统和基础设施实现
  migrations/            Alembic 迁移
  tests/

frontend/
  config/
    config.ts              Umi Max 插件、OpenAPI、代理和构建配置
    routes.ts              唯一前端路由与菜单定义
  src/
    app.tsx                initialState、ProLayout 和 request 运行时配置
    access.ts              登录守卫；第一版不承载 RBAC 业务规则
    services/ragApi/       由 Umi OpenAPI 插件生成，禁止手改
    features/              按业务模块组织用例状态、hooks 和组件
    pages/                 Umi 路由页面入口，保持薄层
    components/            真正跨模块复用的 UI 组件
    models/                少量跨页面客户端状态，不保存业务真源
  tests/                   Jest + React Testing Library
  e2e/                     Playwright

deploy/
  compose/
  env/
  scripts/
  docs/
```

根目录不允许随意堆放临时脚本、原型、日志、下载文件或测试产物。临时原型统一放在明确目录，生产代码开始后由 `.gitignore` 和目录约束管理生成物。

## 3. 后端模块

```text
backend/app/modules/
  auth/                  管理员登录和密码
  capabilities/          可用能力、枚举和配置 schema
  model_registry/        供应商、模型和连接测试
  parsing/               原始数据源、解析版本、MinerU 编排
  knowledge_bases/       知识库、配置修订、数据源绑定、构建代次
  retrieval/             分块、索引、单库检索和检索测试
  bots/                  多库融合、记忆、Prompt、回答和引用
  channels/              Webhook/API 与 Channel Adapter
  tasks/                 业务任务、outbox、重试和任务查询
  observability/         Trace、审计和运行指标
  analytics/             仪表盘聚合和离线质量评测
```

每个业务模块按需包含：

```text
module/
  api.py                 路由，仅做协议转换、鉴权、校验
  schemas.py             Request/Response DTO
  domain.py              实体、值对象、领域规则
  service.py             用例编排和事务边界
  repository.py          本模块持久化端口
  ports.py               本模块需要的外部能力接口
  tasks.py               很薄的 Celery 入口
  errors.py              稳定业务错误码
```

不是每个模块都必须机械创建全部文件。只有存在对应职责时才创建，禁止空壳目录和万能 `utils.py`、`common.py`。

## 4. 依赖方向

固定方向：

```text
API / Celery entry
  -> Application service
     -> Domain rules
     -> Repository / Port interfaces
        <- Infrastructure implementations
```

强制规则：

- API 路由不直接访问 ORM、Chroma、Redis、本地文件或供应商 SDK。
- Celery task 只解析任务参数并调用 application service，不复制业务流程。
- 业务模块不能直接查询或修改另一个模块拥有的表；通过明确的查询服务或端口协作。
- `retrieval` 不读取机器人表；`bots` 调用知识库检索服务。
- `knowledge_bases` 不调用 MinerU；它只引用 `parsing` 已完成的不可变解析版本。
- `channels` 只做协议适配，不实现检索和回答算法。
- 基础设施实现不能反向依赖 API 层。
- 领域对象不依赖 FastAPI、Celery、SQLAlchemy、Chroma SDK 或具体供应商 SDK。

## 5. 数据真源

| 数据 | 第一版真源 | 说明 |
|---|---|---|
| 管理员、配置、绑定、状态 | PostgreSQL | 唯一业务真源 |
| 任务和重试状态 | PostgreSQL | Celery result backend 不能作为后台任务真源 |
| 原始文件和解析产物 | StorageAdapter/local | PostgreSQL 保存校验和与逻辑路径 |
| chunks 及来源关系 | PostgreSQL | 向量库只保存检索所需副本和 ID |
| 关键词索引 | PostgreSQL `pg_trgm` | 与 chunk 代次绑定 |
| 向量索引 | Chroma | 可重建，不保存唯一业务状态 |
| 队列、短缓存、限流 | Redis | 丢失后不得造成业务数据丢失 |
| Trace 大字段 | PostgreSQL | 敏感载荷加密，按保留策略清理 |

禁止以 Redis、浏览器状态、Celery 内部状态或 Chroma collection 是否存在来推断业务最终状态。

## 6. 事务与异步可靠性

Celery 采用至少一次投递语义，所有 Worker 必须幂等。

### 6.1 Transactional Outbox

凡是“提交数据库状态后必须发布 Celery 任务”的用例，必须在同一 PostgreSQL 事务中写入：

1. 业务对象变更。
2. `operation_task` 任务记录。
3. `task_outbox` 待发布事件。

Outbox dispatcher 发布成功后标记已发布。这样避免“数据库已提交但消息没发出”或“消息已发出但任务记录不存在”。

### 6.2 幂等键

- 外部命令接口支持 `Idempotency-Key`。
- 内部操作以 `operationType + targetId + targetRevision` 形成唯一业务幂等键。
- 重复投递只返回已有操作，不重复创建 MinerU 任务、不重复收费、不重复写向量。
- 向量 ID、chunk ID 和索引写入使用确定性标识，允许安全重试/upsert。
- 手动“重新执行”必须创建新的 operation ID，并明确是继续旧上游任务还是创建新解析版本。

### 6.3 并发控制

- 可编辑资源保存 `revision` 整数。
- 更新请求携带 `expectedRevision`；不匹配返回 HTTP 409 和 `RESOURCE_REVISION_CONFLICT`。
- 同一解析版本、同一知识库构建修订不能同时存在两个有效运行操作。
- 唯一约束和 PostgreSQL 行锁是最终防线，前端按钮置灰不是并发控制。

### 6.4 跨存储一致性

PostgreSQL 与 Chroma/文件存储没有分布式事务，采用“先写暂存、校验、再切换可见指针”的方式：

1. 为新构建代次写独立目录、chunk 记录和 collection。
2. 校验数量、维度、来源引用和抽样检索。
3. 在 PostgreSQL 单事务中切换 `activeGenerationId`。
4. 旧代次延迟清理。

运行时只读取 PostgreSQL 指向的活动代次。

## 7. Adapter 与 Strategy

第一版明确实现：

- `ParserAdapter`: `mineru_precision_api`、`builtin_text`。
- `StorageAdapter`: `local`。
- `VectorStoreAdapter`: `chroma`。
- `KeywordStoreAdapter`: `postgres_trigram`。
- `ModelProviderAdapter`: OpenAI、OpenAI-Compatible、DeepSeek、通义千问。
- `ChannelAdapter`: `webhook_api`。

后续候选能力只能通过注册表加入，不能在业务页面或 service 中增加供应商 `if/else` 链。

第一版采用代码内显式注册，不做运行时加载任意第三方 Python 插件，避免供应链和部署风险。

统一能力描述：

```ts
type CapabilityOption = {
  code: string;
  name: string;
  description: string;
  enabled: boolean;
  visible: boolean;
  version: string;
  category?: string;
  unavailableReason?: string;
  configSchema?: JsonSchema;
  uiSchema?: object;
  requiredSourceFeatures?: string[];
  preferredSourceFeatures?: string[];
};
```

规则：

- 前端有下拉，但选项由后端 capability API 返回。
- 保存时后端再次验证 capability、版本和配置 schema。
- `enabled=false` 的能力不能保存。
- 配置记录保存 capability code、version 和参数快照，不能只保存展示名称。
- capability 的稳定身份是 `category + code + version`；不同分类可以使用相同 code（例如查询重写和重排都使用 `off`），读取详情和保存校验必须携带 category，不能按 code 全局猜测。
- schema 发生不兼容变化时发布新 capability version，不静默改变历史配置含义。

## 8. API 契约

- 管理和外部接口统一以 `/api/v1` 开始。
- JSON 字段使用 `camelCase`；Python/数据库内部使用 `snake_case`。
- ID 使用 UUID 字符串；时间统一保存 UTC，API 返回带 `Z` 的 ISO 8601。
- 枚举使用稳定小写 code，展示中文由 capability/字典接口返回。
- 列表统一分页，不返回无限数组。
- 所有写接口使用明确 Request DTO，禁止接受任意字典后直接入库。
- 所有接口声明 `response_model`，前端类型和 client 从 OpenAPI 生成。
- 不在 API 中返回本地物理路径、密钥、供应商原始凭据或内部堆栈。

统一成功分页：

```ts
type PageResult<T> = {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
};
```

统一错误：

```ts
type ApiError = {
  code: string;
  message: string;
  traceId: string;
  details?: Record<string, unknown>;
};
```

HTTP 状态和业务错误码必须同时正确，不能所有错误都返回 200。

## 9. 配置管理

配置分三类：

- 环境启动配置：数据库、Redis、Chroma、存储根目录、加密主密钥、初始管理员。
- 后台系统配置：MinerU 凭据和默认解析参数、日志保留、渠道限流等。
- 业务对象配置：知识库、机器人、模型、渠道实例。

环境变量只保存启动系统所需内容。可由后台维护的密钥通过加密字段入库，不在 `.env` 和数据库之间维护两份可变真源。

启动时使用强类型配置校验；缺少生产必需项立即失败，不带危险默认值继续运行。

## 10. 可读性和健壮性强制约束

- 一个概念只有一个名称；术语表以领域模型真源为准。
- 一个业务规则只有一个详细归属文件；其他文档使用链接引用。
- 不允许路由、DTO、数据库字段和前端各自发明状态名称。
- 不允许字符串拼接本地路径、SQL、Prompt 引用标记或外部 URL。
- 不允许捕获所有异常后返回“失败”；异常必须映射为稳定错误码并保留 traceId。
- 不允许把“无检索结果”和“检索服务故障”当成同一种情况。
- 不允许在重建时先删除活动索引。
- 不允许用前端校验替代后端不变量。
- 所有跨模块 ID 在类型和字段名中表明对象，例如 `parsedSourceVersionId`，禁止都叫 `documentId`。
- 代码、迁移、OpenAPI 和文档必须在同一变更中更新。

## 11. 演进边界

可替换但第一版不实现：

- 本地 MinerU、私有 Parser 服务。
- MinIO/S3/OSS/COS。
- Qdrant/Milvus/pgvector/Weaviate。
- Elasticsearch/OpenSearch。
- 钉钉、企业微信、个人微信、飞书和客服适配器。
- 多租户、RBAC、组织架构。

“预留”只意味着接口和数据归属不封死，不意味着创建空表、空页面或未使用抽象。真实出现第二个实现时再提取共享逻辑。

## 12. 架构验收

- 后端模块依赖没有反向引用和跨模块 ORM 查询。
- FastAPI 与 Celery 入口调用同一 application service。
- 任务发布经过 outbox，重复投递不会重复创建外部任务。
- PostgreSQL、Chroma、Redis、存储中断均能返回可定位错误，且不会被记录为“知识库无命中”。
- 全库重建时旧索引持续服务，新索引校验成功后才切换。
- OpenAPI 能生成前端类型，前端无手写重复 DTO。
- 每个 capability 的可选状态与后端真实实现一致。
