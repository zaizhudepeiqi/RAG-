# API v1 接口契约

> 上游真源：`docs/requirements`。
> 本文件固定第一版路径、鉴权、请求/响应模型、HTTP 状态和错误码归属；实现中的 FastAPI OpenAPI 必须与本文一致。

## 1. 通用约定

- Base path：`/api/v1`。
- JSON：UTF-8、`application/json`、字段 `camelCase`。
- 文件上传：`multipart/form-data`，流式处理。
- ID：UUID 字符串。
- 时间：UTC ISO 8601，例如 `2026-07-12T02:00:00Z`。
- 枚举：稳定小写 code。
- 管理员写接口带 `X-CSRF-Token`；会创建资源或 Operation 的非幂等 POST 还必须带 `Idempotency-Key`。外部渠道所有 POST 必须带 `Idempotency-Key`。
- 可编辑资源返回 `revision`；更新请求必须提供 `expectedRevision`。
- 所有响应返回/响应头可关联 `traceId`；错误一定包含 traceId。
- 生产 OpenAPI 可关闭；契约文件仍由 CI 导出和生成客户端。

### 1.1 管理员鉴权

- JWT 位于 HttpOnly Cookie `rag_admin_access`。
- CSRF 可读 Cookie `rag_csrf`，写请求头 `X-CSRF-Token` 必须匹配。
- 除 login、health 和外部渠道端点外，全部需要管理员身份。

### 1.2 外部渠道鉴权

```http
Authorization: Bearer <channelApiKey>
Idempotency-Key: <8-128 chars>
```

外部 Key 只能访问路径中的同一 channelInstanceId。

### 1.3 命令幂等

- 管理员前端为创建资源/Operation 的 POST 生成 UUID Idempotency-Key；login/logout 和纯读取式 test result GET 除外。
- 外部渠道所有 POST 强制该 Header。
- 作用域为 `actorType + actorId + endpointCode + keyHash`，保留 24 小时。
- 相同 key + 相同 requestHash 返回原资源/Operation/响应；相同 key + 不同 requestHash 返回 409。
- PATCH/PUT/DELETE 主要由 expectedRevision 防并发，若同时创建 Operation 仍接受 Idempotency-Key。

### 1.4 分页

请求：

- `page` 默认 1，最小 1。
- `pageSize` 默认 20，可选 20/50/100，最大 100。
- `sort` 使用白名单字段，前缀 `-` 表示倒序。

```ts
type PageResult<T> = {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
};
```

### 1.5 统一错误

```ts
type ApiError = {
  code: string;
  message: string;
  traceId: string;
  details?: {
    fieldErrors?: Array<{ field: string; code: string; message: string }>;
    references?: Array<{ type: string; id: string; name: string }>;
    retryAfterSeconds?: number;
    operationId?: string;
    [key: string]: unknown;
  };
};
```

HTTP 状态：

- 400 协议/参数格式错误。
- 401 未认证或 Key 无效。
- 403 已认证但被安全策略禁止。
- 404 资源不存在/已删除。
- 409 revision、幂等、状态或唯一约束冲突。
- 413 请求/文件过大。
- 422 业务字段/跨字段校验失败。
- 429 限流。
- 500 未知内部错误。
- 502 上游返回不可用/非法响应。
- 503 依赖不可用或没有可运行配置。
- 504 同步超时。

### 1.6 异步操作

```ts
type OperationRef = {
  operationId: string;
  status: "queued" | "running" | "succeeded" | "partial_succeeded" | "failed" | "cancelled";
  statusUrl: string;
  targetType: string;
  targetId: string;
};
```

创建异步操作返回 HTTP 202；“创建资源并立即异步构建”返回 HTTP 201，响应同时包含资源和 operation。

## 2. 通用 DTO

```ts
type ResourceRef = { id: string; name: string };

type CapabilityOption = {
  code: string;
  name: string;
  description: string;
  enabled: boolean;
  visible: boolean;
  version: string;
  category?: string;
  unavailableReason?: string;
  configSchema?: Record<string, unknown>;
  uiSchema?: Record<string, unknown>;
  requiredSourceFeatures?: string[];
  preferredSourceFeatures?: string[];
};

type OperationDetail = OperationRef & {
  taskType: string;
  stageCode?: string;
  stageLabel?: string;
  progressCurrent?: number;
  progressTotal?: number;
  progressUnit?: string;
  attempt: number;
  maxAttempts: number;
  warningCount: number;
  errorCode?: string;
  errorMessage?: string;
  retryable: boolean;
  resultSummary?: Record<string, unknown>;
  queuedAt: string;
  startedAt?: string;
  finishedAt?: string;
  heartbeatAt?: string;
};
```

## 3. 管理员与健康

| 方法 | 路径 | Request | Response | 成功 |
|---|---|---|---|---|
| POST | `/auth/login` | `LoginRequest` | `LoginResponse` + Cookie | 200 |
| POST | `/auth/logout` | 无 | `{ success: true }` | 200 |
| GET | `/auth/me` | 无 | `AdminProfile` | 200 |
| POST | `/auth/change-password` | `ChangePasswordRequest` | `{ success: true }` + 新 Cookie | 200 |
| GET | `/health/live` | 无 | `HealthResponse` | 200 |
| GET | `/health/ready` | 无 | `HealthResponse` | 200/503 |
| GET | `/health/dependencies` | 无 | `DependencyHealthResponse` | 200/503 |

```ts
type LoginRequest = { username: string; password: string };
type LoginResponse = { admin: AdminProfile; csrfToken: string; firstLoginRequired: boolean };
type AdminProfile = { id: string; username: string; firstLoginRequired: boolean };
type ChangePasswordRequest = { oldPassword: string; newPassword: string; confirmPassword: string };
```

登录失败统一 `AUTH_INVALID_CREDENTIALS`；首次改密限制返回 `AUTH_PASSWORD_CHANGE_REQUIRED`。

## 4. Capability

| 方法 | 路径 | Query | Response |
|---|---|---|---|
| GET | `/capabilities` | `category? includeDisabled?` | `CapabilityOption[]` |
| GET | `/capabilities/{code}/versions/{version}` | `category`（必填） | `CapabilityOption` |

category 第一版包括：`parser/input_type/model_provider/model_type/vector_store/vector_index/keyword_store/index_structure/chunk_strategy/retrieval_type/fusion_strategy/query_rewrite/rerank/channel_adapter`。

稳定身份为 `category + code + version`，允许不同分类复用同一 code（例如 `off`）。未知 category/code/version 返回 `CAPABILITY_NOT_FOUND`；disabled 保存由业务接口返回 `CAPABILITY_DISABLED`。

## 5. 系统设置

| 方法 | 路径 | Request/Response |
|---|---|---|
| GET | `/settings/mineru` | `MinerUSettingsView` |
| PATCH | `/settings/mineru` | `UpdateMinerUSettingsRequest` -> view |
| POST | `/settings/mineru:test` | `MinerUSettingsTestRequest` + `Idempotency-Key` -> `OperationRef`，202 |
| GET | `/settings/retention` | `RetentionSettings` |
| PATCH | `/settings/retention` | `expectedRevision + values` -> settings |
| POST | `/retention-cleanups` | `RetentionCleanupRequest` -> `OperationRef`，202 |
| GET | `/settings/runtime` | 只读 `RuntimeSettingsView` |

```ts
type MinerUSettingsView = {
  baseUrl: string;
  tokenConfigured: boolean;
  tokenMasked?: string;
  defaultParseConfig: ParseConfig;
  pollTimeoutSeconds: number;
  cloudProcessingConfirmedAt?: string;
  termsVersion?: "mineru-cloud-v1";
  revision: number;
};

type CloudProcessingConsent = {
  accepted: true;
  termsVersion: "mineru-cloud-v1";
};

type UpdateMinerUSettingsRequest = {
  expectedRevision: number;
  baseUrl: string;
  token?: string;
  defaultParseConfig: ParseConfig;
  pollTimeoutSeconds: number;
  cloudProcessingConsent?: CloudProcessingConsent;
};

type MinerUSettingsTestRequest = {
  expectedRevision: number;
};
```

MinerU 测试 Operation 使用内置最小 PDF，真实执行 signed upload、轮询、结果下载和标准化；不得退化为 HTTP ping。Operation 结果不返回 Token、signed URL 或 storage key。

Token 留空表示不替换；首次配置 Token 必须同时确认 `mineru-cloud-v1` 云处理条款，后续轮换沿用已保存的确认。响应永不返回明文或确认管理员 ID。真实连接测试在 MinerU Precision Adapter 完成后注册，本阶段不提供伪测试端点。

## 6. 模型供应商

| 方法 | 路径 | Request | Response |
|---|---|---|---|
| GET | `/model-providers` | `search/enabled/page/pageSize/sort` | `PageResult<ModelProviderView>` |
| POST | `/model-providers` | `CreateModelProviderRequest` | view，201 |
| GET | `/model-providers/{providerId}` | 无 | view |
| PATCH | `/model-providers/{providerId}` | `UpdateModelProviderRequest` | view |
| DELETE | `/model-providers/{providerId}` | `expectedRevision` | 204 |
| POST | `/model-providers/{providerId}:test` | `expectedRevision` | `OperationRef` |
| POST | `/model-providers/{providerId}:discover-models` | `expectedRevision` | `OperationRef` |
| GET | `/model-providers/{providerId}/discovered-models` | 状态/类型 | `DiscoveredModel[]` |

```ts
type ModelProviderView = {
  id: string;
  providerType: string;
  displayName: string;
  baseUrl: string;
  credentialConfigured: boolean;
  credentialMasked?: string;
  enabled: boolean;
  modelCount: number;
  revision: number;
  createdAt: string;
  updatedAt: string;
};

type CreateModelProviderRequest = {
  providerType: string;
  displayName: string;
  baseUrl: string;
  credential: string;
};
```

Provider 有模型引用时修改 baseUrl/providerType 或删除返回 `MODEL_PROVIDER_IN_USE`。

## 7. 模型配置

| 方法 | 路径 | Request | Response |
|---|---|---|---|
| GET | `/models` | `providerId/modelType/enabled/verificationStatus/search/page/pageSize/sort` | `PageResult<ModelView>` |
| POST | `/models` | `CreateModelRequest` | view，201 |
| GET | `/models/{modelId}` | 无 | view |
| PATCH | `/models/{modelId}` | `UpdateModelRequest` | view |
| POST | `/models/{modelId}:verify` | `expectedRevision` | `OperationRef` |
| POST | `/models/{modelId}:enable` | `expectedRevision` | view |
| POST | `/models/{modelId}:disable` | `expectedRevision` | view |
| GET | `/models/{modelId}/references` | 无 | `ModelReference[]` |
| DELETE | `/models/{modelId}` | `expectedRevision` | 204 |

```ts
type ModelView = {
  id: string;
  provider: ResourceRef;
  modelName: string;
  displayName: string;
  modelType: "llm" | "embedding" | "rerank" | "vision";
  enabled: boolean;
  verificationStatus: "untested" | "passed" | "failed" | "stale";
  contextWindow?: number;
  maxOutputTokens?: number;
  embeddingDimension?: number;
  capabilityVersion: string;
  defaultParams: Record<string, unknown>;
  configSchema: Record<string, unknown>;
  lastVerification?: { status: string; latencyMs?: number; testedAt: string; errorCode?: string };
  usedByKnowledgeBaseCount: number;
  usedByBotCount: number;
  revision: number;
};
```

## 8. 数据源上传和解析

### 8.1 上传

`POST /data-sources/uploads`：multipart，可重复 `files`，附加 JSON part `options`：

```ts
type UploadOptions = {
  originType?: "admin_upload";
  duplicateAction?: "reuse" | "create_alias";
};

type UploadBatchResult = {
  accepted: Array<{ dataSource: DataSourceSummary; duplicateOfDataSourceId?: string }>;
  rejected: Array<{ fileName: string; code: string; message: string }>;
};
```

成功可以是 200 部分成功；全部无效返回 422。请求级超限返回 413。

### 8.2 资源

| 方法 | 路径 | Request/Query | Response |
|---|---|---|---|
| GET | `/data-sources` | `extension/originType/parseStatus/search/page/pageSize/sort` | page summary |
| GET | `/data-sources/{dataSourceId}` | 无 | `DataSourceDetail` |
| GET | `/data-sources/{dataSourceId}/references` | 无 | `DataSourceReference[]` |
| PATCH | `/data-sources/{dataSourceId}` | `displayName + expectedRevision` | detail |
| DELETE | `/data-sources/{dataSourceId}` | `expectedRevision` | `OperationRef`，202 |
| GET | `/data-sources/{dataSourceId}/versions` | 分页 | `PageResult<ParsedSourceVersionSummary>` |
| POST | `/data-sources/{dataSourceId}/parse` | `CreateParseVersionRequest` | `CreateParseVersionResponse`；复用200，新建201 |
| GET | `/data-sources/{dataSourceId}/original` | download/inline query | 文件流 |

```ts
type DataSourceSummary = {
  id: string;
  displayName: string;
  sourcePath: string;
  originalFileName: string;
  extension: string;
  mimeType: string;
  sizeBytes: number;
  sha256Short: string;
  originType: string;
  latestParsedVersion?: ParsedSourceVersionSummary;
  versionCount: number;
  activeKnowledgeBaseReferenceCount: number;
  revision: number;
  createdAt: string;
};

type ParseConfig = {
  parserCode: string;
  modelVersion: "pipeline" | "vlm" | "MinerU-HTML" | "builtin";
  language: string;
  ocrEnabled: boolean;
  tableEnabled: boolean;
  formulaEnabled: boolean;
  pageRanges?: string;
  extraFormats: string[];
  forceProviderRefresh: boolean;
};

type CreateParseVersionRequest = {
  expectedRevision: number;
  config: ParseConfig;
  reuseMode: "reuse_if_exact" | "force_new";
};

type CreateParseVersionResponse = {
  version: ParsedSourceVersionSummary;
  reused: boolean;
  reusedFromParsedSourceVersionId?: string;
  operation?: OperationRef;
};

type CreateReparseRequest = {
  expectedRevision: number;
  config: ParseConfig;
};
```

### 8.3 解析版本

| 方法 | 路径 | Response/作用 |
|---|---|---|
| GET | `/parsed-source-versions/{parsedSourceVersionId}` | 版本详情/进度/错误/统计 |
| GET | `/parsed-source-versions/{id}/markdown` | 规范化 Markdown |
| GET | `/parsed-source-versions/{id}/blocks` | 分页/按页/类型筛选 blocks |
| GET | `/parsed-source-versions/{id}/assets` | 分页资产 |
| GET | `/parsed-source-versions/{id}/assets/{assetId}` | 鉴权文件流 |
| GET | `/parsed-source-versions/{id}/artifacts` | 产物清单，不暴露物理路径 |
| GET | `/parsed-source-versions/{id}/references` | `DataSourceReference[]` |
| POST | `/parsed-source-versions/{id}:resume-provider-query` | 创建 operation，202 |
| POST | `/parsed-source-versions/{id}:create-reparse` | `CreateReparseRequest`，强制新版本，201 |
| DELETE | `/parsed-source-versions/{id}` | 无引用时异步清理，202 |

`ParsedSourceVersionSummary.status` 枚举严格采用解析真源；只有 succeeded/degraded 返回 `selectable=true`。

`resume-provider-query` 只接受保留原 `batchId/dataId` checkpoint 且错误属于 timeout/poll/download 的可恢复 failed 版本；它不得重新申请上传 URL。数据源和解析版本删除前都查询 references，有引用返回 `SOURCE_IN_USE` 与 `details.references`。cleanup Operation 在 queued 状态也不可取消。

## 9. 知识库

### 9.1 创建和列表

| 方法 | 路径 | Request | Response |
|---|---|---|---|
| GET | `/knowledge-bases` | `status/modelId/retrievalType/botId/search/page/pageSize/sort` | page summary |
| POST | `/knowledge-bases` | `CreateKnowledgeBaseRequest` | `KnowledgeBaseDetail + OperationRef`，201 |
| GET | `/knowledge-bases/{knowledgeBaseId}` | 无 | detail |
| PATCH | `/knowledge-bases/{id}/metadata` | name/description/expectedRevision | detail |
| POST | `/knowledge-bases/{id}:enable` | expectedRevision | detail |
| POST | `/knowledge-bases/{id}:disable` | expectedRevision | detail |
| DELETE | `/knowledge-bases/{id}` | expectedRevision | `OperationRef`，202 |

```ts
type CreateKnowledgeBaseRequest = {
  name: string;
  description?: string;
  parsedSourceVersionIds: string[];
  buildConfig: KnowledgeBaseBuildConfig;
  retrievalConfig: RetrievalConfig;
};

type KnowledgeBaseBuildConfig = {
  embeddingModelId: string;
  embeddingParams: Record<string, unknown>;
  vectorStoreCode: "chroma";
  vectorIndexCode: "hnsw";
  vectorIndexParams: Record<string, unknown>;
  keywordStoreCode: "postgres_trigram";
  indexStructure: "chunk" | "parent_child";
  chunkStrategyCode: string;
  chunkParams: Record<string, unknown>;
};
```

### 9.2 配置和 generation

| 方法 | 路径 | Request/Response |
|---|---|---|
| GET | `/knowledge-bases/{id}/build-config` | 活动/待构建 config view |
| PUT | `/knowledge-bases/{id}/pending-build-config` | expectedRevision + sources + buildConfig |
| DELETE | `/knowledge-bases/{id}/pending-build-config` | expectedRevision，放弃未发布变更 |
| GET | `/knowledge-bases/{id}/retrieval-config` | 活动 retrieval config |
| PUT | `/knowledge-bases/{id}/retrieval-config` | `UpdateRetrievalConfigRequest` -> `RetrievalConfigRevisionView`；立即或 pending 由响应说明 |
| POST | `/knowledge-bases/{id}/generations` | expectedRevision + pendingBuildConfigRevisionId + pendingRetrievalRevisionId? -> operation |
| GET | `/knowledge-bases/{id}/generations` | generation page |
| GET | `/knowledge-bases/{id}/generations/{generationId}` | generation/items/validation |
| POST | `/knowledge-bases/{id}/generations/{generationId}:retry-failed` | operation |
| POST | `/knowledge-bases/{id}/generations/{generationId}:discard` | expectedRevision |

`KnowledgeBaseDetail` 同时返回 `enabled/activeGeneration/latestBuild/hasUnpublishedBuildChanges/derivedDisplayStatus`，前端不自己读取任务表推断。

### 9.3 检索测试

`POST /knowledge-bases/{id}/retrieval-tests`

```ts
type RetrievalTestRequest = {
  query: string;
  temporaryConfig?: RetrievalConfig;
};

type RetrievalTestResponse = {
  query: string;
  knowledgeBaseId: string;
  activeGenerationId: string;
  retrievalRevisionId: string;
  retrievalConfig: RetrievalConfig;
  rewriteResult?: Record<string, unknown>;
  candidateStats: Record<string, number>;
  results: Array<Record<string, unknown>>;
  contextPreview: Array<Record<string, unknown>>;
  timing: Record<string, number>;
  warnings: ApiError[];
  errors: ApiError[];
};
```

## 10. RAG 评测集

| 方法 | 路径 | 作用 |
|---|---|---|
| GET/POST | `/knowledge-bases/{id}/evaluation-datasets` | 列表/创建 |
| GET/PATCH/DELETE | `/evaluation-datasets/{datasetId}` | 详情/改名/删除 |
| POST | `/evaluation-datasets/{id}/cases:import` | CSV/JSON 导入 |
| GET/POST | `/evaluation-datasets/{id}/cases` | case 列表/创建 |
| PATCH/DELETE | `/evaluation-cases/{caseId}` | 修改/删除 |
| POST | `/evaluation-datasets/{id}/runs` | generation/config -> OperationRef |
| GET | `/evaluation-runs/{runId}` | 指标和逐 case 结果 |

case 必须包含 question、shouldHit；shouldHit=true 时至少一个 expectedSource。

## 11. 机器人

| 方法 | 路径 | Request/Response |
|---|---|---|
| GET | `/bots` | `knowledgeBaseId/channelInstanceId/search/page/pageSize/sort` -> page summary |
| GET | `/bots/defaults` | `BotDefaults` |
| POST | `/bots` | `CreateBotRequest` -> detail，201 |
| GET | `/bots/{botId}` | detail |
| PUT | `/bots/{botId}` | 完整 config + expectedRevision -> detail |
| DELETE | `/bots/{botId}` | expectedRevision -> 204 |
| POST | `/bots/{botId}/chat-tests` | `BotChatTestRequest` -> `BotChatResponse` |

```ts
type BotKnowledgeBaseInput = {
  knowledgeBaseId: string;
  enabled: boolean;
  priority: number;
};

type BotDefaults = {
  systemPrompt: string;
  answerModelParams: { temperature: number; maxOutputTokens: number };
  mergeConfig: {
    mode: "rank_fusion";
    perKnowledgeBaseLimit: number;
    finalContextTopK: number;
    maxContextTokens: number;
  };
  memoryConfig: {
    enabled: boolean;
    historyTurns: number;
    sessionTimeoutMinutes: number;
    standaloneRewriteEnabled: boolean;
  };
  noHitPolicy: "message_only" | "message_then_llm";
  defaultsVersion: string;
};

type CreateBotRequest = {
  name: string;
  description?: string;
  answerModelId: string;
  answerModelParams: { temperature: number; maxOutputTokens: number };
  systemPrompt: string;
  knowledgeBases: BotKnowledgeBaseInput[];
  mergeConfig: {
    mode: "rank_fusion";
    perKnowledgeBaseLimit: number;
    finalContextTopK: number;
    maxContextTokens: number;
  };
  memoryConfig: {
    enabled: boolean;
    historyTurns: number;
    sessionTimeoutMinutes: number;
    standaloneRewriteEnabled: boolean;
  };
  noHitPolicy: "message_only" | "message_then_llm";
};
```

`BotChatTestRequest`：text、conversationId?、citation detail；响应使用第 13 节统一回答。

## 12. 渠道实例管理

| 方法 | 路径 | Request/Response |
|---|---|---|
| GET | `/channel-instances` | `botId/enabled/search/page/pageSize/sort` -> page summary |
| POST | `/channel-instances` | config -> `ChannelCreateResponse`，201 |
| GET/PATCH | `/channel-instances/{id}` | detail/update + expectedRevision |
| POST | `/channel-instances/{id}:test` | OperationRef |
| POST | `/channel-instances/{id}:enable` | detail |
| POST | `/channel-instances/{id}:disable` | detail |
| POST | `/channel-instances/{id}:rotate-api-key` | `OneTimeSecretResponse` |
| POST | `/channel-instances/{id}:rotate-callback-secret` | `OneTimeSecretResponse` |
| POST | `/channel-instances/{id}:retry-callback` | deliveryId -> OperationRef |
| DELETE | `/channel-instances/{id}` | expectedRevision -> 204 |

```ts
type OneTimeSecretResponse = { value: string; prefix: string; shownOnce: true };
type ChannelCreateResponse = { channel: ChannelInstanceDetail; apiKey: OneTimeSecretResponse; callbackSecret?: OneTimeSecretResponse };
```

## 13. 统一机器人回答

```ts
type BotChatResponse = {
  chatRunId: string;
  traceId: string;
  conversationId: string;
  status: "succeeded" | "failed";
  answer?: string;
  answerBasis?: "knowledge_base" | "general_model";
  isHit: boolean;
  fallbackUsed: boolean;
  partialRetrievalFailure: boolean;
  citationValidationStatus?: "valid" | "degraded";
  citations: Citation[];
  warnings: Array<{ code: string; message: string }>;
  error?: ApiError;
  usage?: { inputTokens?: number; outputTokens?: number; totalTokens?: number };
};
```

Citation 字段按 channel detail level 裁剪；内部/管理员保留标准结构。

## 14. 外部 Webhook/API

| 方法 | 路径 | Request | Response |
|---|---|---|---|
| POST | `/channel-instances/{id}/chat:sync` | `ExternalChatRequest` | `BotChatResponse`，200 |
| POST | `/channel-instances/{id}/chat:async` | request | OperationRef + conversationId，202 |
| GET | `/channel-instances/{id}/operations/{operationId}` | 无 | operation + chat response |
| POST | `/channel-instances/{id}/attachments` | multipart | `TemporaryAttachmentView`，201/202 |
| POST | `/channel-instances/{id}/data-sources` | multipart + ParseConfig | sources + operations，202 |

```ts
type ExternalChatRequest = {
  conversationId?: string;
  messageId?: string;
  senderId?: string;
  text: string;
  attachmentIds?: string[];
  citationOptions?: { detailLevel: "none" | "simple" | "standard" | "full" };
  callback?: boolean;
  metadata?: Record<string, string>;
};
```

同步只接受 ready attachments；否则返回 409 `ATTACHMENT_NOT_READY` 并提示异步端点。

## 15. Operation、任务和日志

| 方法 | 路径 | Query/作用 |
|---|---|---|
| GET | `/operations` | `taskType/status/targetType/targetId/search/from/to/page/pageSize/sort` |
| GET | `/operations/{operationId}` | OperationDetail + items/events |
| POST | `/operations/{id}:cancel` | 仅 queued |
| POST | `/operations/{id}:retry` | 仅 retryable terminal -> 新 OperationRef |
| GET | `/chat-runs` | `source/status/botId/knowledgeBaseId/channelInstanceId/traceId/from/to/page/pageSize/sort` |
| GET | `/chat-runs/{chatRunId}` | 摘要和阶段索引 |
| GET | `/chat-runs/{chatRunId}/trace` | 默认脱敏 Trace |
| POST | `/chat-runs/{chatRunId}:reveal-sensitive` | 理由 + expectedRevision? -> 本次敏感 Trace，写审计 |
| GET | `/audit-logs` | event/target/time/page |

知识库检索测试不进入 ChatRun；机器人测试进入 `source=admin_test`。

## 16. 仪表盘和分析

| 方法 | 路径 | Query | Response |
|---|---|---|---|
| GET | `/analytics/overview` | timeRange | counts/availability |
| GET | `/analytics/tasks` | timeRange/type | queues/status/latency/failures |
| GET | `/analytics/rag` | timeRange/bot/kb/channel/source | hit/no-hit/failure/fallback/citation/latency |
| GET | `/analytics/models` | timeRange/model/purpose | calls/tokens/errors/latency |
| GET | `/analytics/problem-queries` | kind=no_hit/retrieval_failure | page |

响应包含 `generatedAt` 和 `dataThrough`，前端显示聚合延迟。

## 17. 文件和导出

- 文件下载只使用资源端点，响应 `Content-Disposition`、安全 Content-Type、ETag。
- 不返回 storage key/绝对路径。
- 大 JSON/CSV 导出创建 Operation，完成后返回有管理员鉴权、短有效期的下载 endpoint token；不直接返回本地路径。

## 18. 错误码目录

### Common/Protocol

`VALIDATION_ERROR`、`INVALID_STATE_TRANSITION`、`INTERNAL_ERROR`。

### Auth/Security

`AUTH_UNAUTHORIZED`、`AUTH_TOKEN_EXPIRED`、`AUTH_INVALID_CREDENTIALS`、`AUTH_PASSWORD_CHANGE_REQUIRED`、`AUTH_RATE_LIMITED`、`CSRF_INVALID`、`SSRF_BLOCKED`。

### Capability/Revision/Idempotency

`CAPABILITY_NOT_FOUND`、`CAPABILITY_DISABLED`、`CAPABILITY_VERSION_STALE`、`RESOURCE_REVISION_CONFLICT`、`IDEMPOTENCY_KEY_REQUIRED`、`IDEMPOTENCY_KEY_REUSED`。

### Source/Parser

`SOURCE_FILE_TOO_LARGE`、`SOURCE_FILE_EMPTY`、`SOURCE_TYPE_UNSUPPORTED`、`SOURCE_ARCHIVE_UNSAFE`、`SOURCE_IN_USE`、`PARSED_SOURCE_VERSION_NOT_FOUND`、`PARSED_VERSION_NOT_SELECTABLE`、`MINERU_AUTH_FAILED`、`MINERU_RATE_LIMITED`、`MINERU_QUOTA_EXCEEDED`、`MINERU_TIMEOUT`、`MINERU_RESULT_DOWNLOAD_FAILED`、`PARSER_NORMALIZATION_FAILED`。

### Model

`MODEL_PROVIDER_IN_USE`、`MODEL_AUTH_FAILED`、`MODEL_NOT_FOUND`、`MODEL_TYPE_MISMATCH`、`MODEL_RATE_LIMITED`、`MODEL_TIMEOUT`、`MODEL_RESPONSE_INVALID`、`MODEL_VERIFICATION_REQUIRED`、`MODEL_IN_USE`。

### Knowledge/Retrieval

`KNOWLEDGE_BASE_IN_USE`、`KNOWLEDGE_BASE_UNAVAILABLE`、`KNOWLEDGE_BASE_BUILD_RUNNING`、`BUILD_CONFIG_INVALID`、`GENERATION_NOT_ACTIVATABLE`、`VECTOR_STORE_UNAVAILABLE`、`KEYWORD_STORE_UNAVAILABLE`、`QUERY_EMBEDDING_FAILED`、`RETRIEVAL_CONFIG_INVALID`。

### Bot/Channel

`BOT_CONFIG_INVALID`、`BOT_MODEL_UNAVAILABLE`、`BOT_NO_USABLE_KNOWLEDGE_BASE`、`BOT_CONTEXT_BUDGET_INVALID`、`RETRIEVAL_INCOMPLETE_NO_ANSWER`、`ALL_RETRIEVALS_FAILED`、`ANSWER_MODEL_FAILED`、`CHANNEL_UNAUTHORIZED`、`CHANNEL_DISABLED`、`CHANNEL_RATE_LIMITED`、`MESSAGE_TYPE_UNSUPPORTED`、`ATTACHMENT_NOT_READY`、`SYNC_CHAT_TIMEOUT`。

### Task/Storage

`OPERATION_NOT_CANCELLABLE`、`OPERATION_NOT_RETRYABLE`、`OPERATION_STALLED`、`TASK_SCHEMA_UNSUPPORTED`、`STORAGE_UNAVAILABLE`、`STORAGE_INSUFFICIENT_SPACE`、`DEPENDENCY_UNAVAILABLE`。

新错误码必须先更新需求真源/本文/OpenAPI/前端映射/测试，不能运行时临时造字符串。

## 19. DTO 完整定义

以下补充前文引用但未展开的稳定 DTO。动态算法参数仍以 capability JSON Schema 为准，不能在这里复制供应商专属字段。

```ts
type HealthResponse = {
  status: "healthy" | "degraded" | "unhealthy";
  version: string;
  timestamp: string;
  traceId: string;
};

type DependencyHealthResponse = HealthResponse & {
  dependencies: Array<{
    code: "postgresql" | "redis" | "chroma" | "storage" | "celery" | "mineru" | "models";
    status: "healthy" | "degraded" | "unhealthy" | "not_configured";
    latencyMs?: number;
    message?: string;
    checkedAt: string;
  }>;
};

type RetentionSettings = {
  chatTraceDays: number;
  conversationDays: number;
  operationDays: number;
  auditDays: number;
  tempAttachmentHours: number;
  metricDays: number;
  revision: number;
};

type RetentionCleanupRequest = {
  target: "chat_traces" | "conversations" | "operations" | "temporary_attachments" | "metrics";
  before: string;
  dryRun: boolean;
};

type RuntimeSettingsView = {
  environment: string;
  version: string;
  databaseRevision: string;
  storage: { type: "local"; configured: boolean; writable: boolean; freeBytes?: number };
  openApiEnabled: boolean;
};

type UpdateModelProviderRequest = {
  expectedRevision: number;
  displayName?: string;
  baseUrl?: string;
  credential?: string;
  enabled?: boolean;
};

type DiscoveredModel = {
  providerModelName: string;
  suggestedDisplayName: string;
  supportedModelTypes: Array<"llm" | "embedding" | "rerank" | "vision">;
  alreadyConfiguredModelIds: string[];
  discoveryMetadata: Record<string, unknown>;
};

type CreateModelRequest = {
  providerId: string;
  modelName: string;
  displayName: string;
  modelType: "llm" | "embedding" | "rerank" | "vision";
  contextWindow?: number;
  maxOutputTokens?: number;
  embeddingDimension?: number;
  defaultParams: Record<string, unknown>;
};

type UpdateModelRequest = {
  expectedRevision: number;
  displayName?: string;
  contextWindow?: number;
  maxOutputTokens?: number;
  defaultParams?: Record<string, unknown>;
};

type ModelReference = {
  referenceType: "kb_embedding" | "kb_query_rewrite" | "kb_rerank" | "bot_answer";
  resourceId: string;
  resourceName: string;
  configRevisionId: string;
  active: boolean;
};

type ParsedSourceVersionSummary = {
  id: string;
  dataSourceId: string;
  versionNumber: number;
  parserCode: string;
  parserVersion: string;
  configHash: string;
  status: "queued" | "submitting" | "uploading" | "provider_pending" | "parsing" | "downloading" | "normalizing" | "succeeded" | "degraded" | "failed" | "cancelled";
  qualityLevel?: "full" | "degraded";
  selectable: boolean;
  pageCount: number;
  blockCount: number;
  assetCount: number;
  featureFlags: {
    hasText: boolean;
    hasPages: boolean;
    hasHeadings: boolean;
    hasBoundingBoxes: boolean;
    hasAssets: boolean;
    hasTables: boolean;
    hasFormulas: boolean;
  };
  operationId?: string;
  errorCode?: string;
  errorMessage?: string;
  createdAt: string;
  finishedAt?: string;
};

type DataSourceDetail = DataSourceSummary & {
  sha256: string;
  latestVersions: ParsedSourceVersionSummary[];
  references: DataSourceReference[];
  deletedAt?: string;
};

type DataSourceReference = {
  knowledgeBaseId: string;
  knowledgeBaseName: string;
  configRevisionId: string;
  active: boolean;
};

type RetrievalConfig = {
  retrievalType: "vector" | "keyword" | "hybrid";
  vector: { topK: number; scoreThreshold: number };
  keyword: { topK: number; scoreThreshold: number };
  hybrid: {
    fusionStrategy: "rrf" | "weighted_score";
    rrfK?: number;
    vectorWeight?: number;
    keywordWeight?: number;
    finalScoreThreshold: number;
  };
  queryRewrite: {
    strategyCode: "off" | "hyde" | "multi_query" | "step_back";
    modelId?: string;
    params: Record<string, unknown>;
  };
  rerank: {
    strategyCode: "off" | "rerank_model" | "llm_rerank";
    modelId?: string;
    params: Record<string, unknown>;
  };
  contextWindow: number;
  finalTopK: number;
};

type UpdateRetrievalConfigRequest = {
  expectedRevision: number;
  config: RetrievalConfig;
  activationMode: "auto" | "with_pending_generation";
};

type RetrievalConfigRevisionView = {
  id: string;
  revisionNumber: number;
  config: RetrievalConfig;
  activationStatus: "active" | "pending_generation";
  activeGenerationId?: string;
  createdAt: string;
};

type GenerationSummary = {
  id: string;
  generationNumber: number;
  status: "queued" | "building" | "validating" | "succeeded" | "partial_ready" | "partial_failed" | "failed" | "cancelled" | "discarded";
  completeness?: "full" | "partial";
  configRevisionId: string;
  sourceCount: number;
  successfulSourceCount: number;
  failedSourceCount: number;
  chunkCount: number;
  vectorCount: number;
  operationId?: string;
  activatedAt?: string;
  createdAt: string;
};

type KnowledgeBaseSummary = {
  id: string;
  name: string;
  description?: string;
  enabled: boolean;
  derivedDisplayStatus: "ready" | "partial_ready" | "building" | "rebuilding" | "config_changed" | "unavailable" | "disabled";
  sourceCount: number;
  searchableSourceCount: number;
  activeChunkCount: number;
  embeddingModel?: ResourceRef;
  indexStructure?: "chunk" | "parent_child";
  retrievalType?: "vector" | "keyword" | "hybrid";
  botReferenceCount: number;
  revision: number;
  updatedAt: string;
  allowedActions: string[];
};

type KnowledgeBaseDetail = KnowledgeBaseSummary & {
  activeGeneration?: GenerationSummary;
  latestBuild?: OperationDetail;
  activeRetrievalRevisionId?: string;
  pendingBuildConfigRevisionId?: string;
  pendingRetrievalRevisionId?: string;
  hasUnpublishedBuildChanges: boolean;
  warnings: Array<{ code: string; message: string }>;
  createdAt: string;
};

type CreateChannelInstanceRequest = {
  name: string;
  adapterCode: "webhook_api";
  botId: string;
  rateLimitPerMinute: number;
  maxConcurrentRequests: number;
  allowedCitationDetailLevels: Array<"none" | "simple" | "standard" | "full">;
  callbackUrl?: string;
};

type UpdateChannelInstanceRequest = {
  expectedRevision: number;
  name?: string;
  botId?: string;
  rateLimitPerMinute?: number;
  maxConcurrentRequests?: number;
  allowedCitationDetailLevels?: Array<"none" | "simple" | "standard" | "full">;
  callbackUrl?: string | null;
};

type ChannelInstanceDetail = {
  id: string;
  name: string;
  adapterCode: "webhook_api";
  adapterVersion: string;
  bot: ResourceRef;
  enabled: boolean;
  apiKeyConfigured: boolean;
  apiKeyPrefix: string;
  callbackConfigured: boolean;
  callbackUrl?: string;
  rateLimitPerMinute: number;
  maxConcurrentRequests: number;
  allowedCitationDetailLevels: Array<"none" | "simple" | "standard" | "full">;
  lastTest?: { status: string; testedAt: string; operationId: string };
  revision: number;
  createdAt: string;
  updatedAt: string;
};

type TemporaryAttachmentView = {
  id: string;
  fileName: string;
  mimeType: string;
  sizeBytes: number;
  status: "uploaded" | "queued" | "parsing" | "ready" | "failed" | "expired" | "deleted";
  operationId?: string;
  expiresAt: string;
  error?: ApiError;
};

type Citation = {
  citationId: string;
  knowledgeBaseId?: string;
  knowledgeBaseName?: string;
  dataSourceId?: string;
  dataSourceName: string;
  sourcePath?: string;
  parsedSourceVersionId?: string;
  contextId: string;
  headingPath?: string[];
  pageRange?: number[];
  snippet?: string;
  assetRefs?: Array<{ assetId: string; assetType: string; url?: string }>;
  sourceBlockIds?: string[];
  boundingBoxes?: Array<Record<string, unknown>>;
  retrievalScores?: Record<string, number>;
  sourceType: "knowledge_base" | "chat_attachment";
  deletedOrExpired: boolean;
};

type EvaluationCaseInput = {
  question: string;
  shouldHit: boolean;
  expectedSources: Array<{
    parsedSourceVersionId: string;
    pageRange?: number[];
    sourceBlockIds?: string[];
    relevanceGrade?: number;
  }>;
  referenceAnswer?: string;
};
```

## 20. API 验收

- FastAPI OpenAPI paths、methods、DTO 和本文一致。
- 每个 endpoint 有成功、鉴权、校验、冲突和依赖失败测试。
- 管理员和外部渠道鉴权不能互换。
- 重复外部 Idempotency-Key 不重复执行；同 key 不同 body 返回 409。
- 所有异步命令返回可查询 operationId。
- 所有可编辑资源执行 revision 冲突测试。
- 所有流式文件接口不暴露路径/secret。
- OpenAPI 生成 TypeScript 和 Bruno collection 无手工字段补丁。
