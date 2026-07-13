# 渠道与外部接口阶段性真源

> 文档职责：定义第一版 Webhook/API、统一消息边界、鉴权、幂等、同步/异步、附件与数据源导入，以及后续平台 Adapter 契约。

## 1. 第一版范围

第一版真实实现 `webhook_api` Channel Adapter，用于外部系统调用机器人。

后续预留但不实现：

- `dingtalk` 钉钉。
- `wecom` 企业微信。
- `wechat_personal` 个人微信。
- `feishu` 飞书。
- `customer_service` 客服系统。
- `custom` 自定义平台。

未实现平台可以在能力列表显示 `enabled=false` 和“后续版本”，不能创建实例、填写假配置或调用空接口。

## 2. 三层概念

- `ChannelAdapter`：某平台协议实现。
- `ChannelInstance`：该 Adapter 的一份真实凭据、限流和机器人绑定配置。
- `NormalizedChannelEvent/Response`：渠道层与机器人运行时之间的稳定内部协议。

第一版一个 ChannelInstance 绑定一个机器人，`routeMode=single_bot`。以后一个平台实例多机器人路由通过独立 Router 扩展，不修改机器人接口。

## 3. Channel Adapter 接口

```text
describe_capability()                 返回平台配置 schema 和消息能力
verify_inbound(request)               校验平台签名/凭据/时间戳
deduplicate(event)                    生成稳定 platformEventId
normalize_inbound(request)            映射为 NormalizedChannelEvent
acknowledge(event)                    按平台时限返回接收确认
render_response(botResponse, options) 将统一回答映射为平台格式
send_outbound(response)               主动发送或异步回复
map_error(error)                      映射平台可识别错误
health_check(instance)                检测凭据和回调配置
```

平台专属字段只能存在于 Adapter/instance config，机器人运行时不得出现钉钉、企微、飞书条件分支。

后续平台端点独立命名：

```text
POST /api/v1/integrations/dingtalk/{instanceId}/events
POST /api/v1/integrations/wecom/{instanceId}/events
POST /api/v1/integrations/feishu/{instanceId}/events
```

不同平台的签名、challenge、ACK 时限和消息 ID 分别由对应 Adapter 处理，不能共享一个含大量可选字段的万能回调 DTO。

## 4. Webhook/API 渠道实例

字段：

- `id / name / adapterCode=webhook_api`。
- `botId`。
- `enabled`。
- `apiKeyHash / apiKeyPrefix / rotatedAt`。
- `rateLimitPerMinute`，默认 60，范围 1-6000。
- `maxConcurrentRequests`，默认 5，范围 1-100。
- `allowedCitationDetailLevels`。
- 可选异步 callback 配置。
- `revision / createdAt / updatedAt / deletedAt`。

创建和连接检测分开：

- 创建实例只保存配置并生成 API Key。
- “检测”执行鉴权、机器人可用性和依赖健康测试，返回分阶段结果。
- 检测失败不删除实例；实例可保持 disabled 修复后重测。

## 5. API Key

- 后端使用 CSPRNG 生成至少 256-bit 随机值。
- 数据库只保存 API Key 的 SHA-256 校验值和可显示前缀；Key 具备至少 256-bit 随机熵，因此不使用可逆加密，也不需要对低熵密码设计的慢哈希。
- 明文只在创建或轮换成功响应中展示一次。
- `Authorization: Bearer <apiKey>`。
- 轮换后旧 Key 默认立即失效；第一版不做双 Key 灰度期。
- 前端不能再次读取明文，只能重新生成。
- 不同渠道实例 Key 不能复用。

后台管理员 JWT 与外部 API Key 使用不同鉴权依赖和错误码。

## 6. 外部端点

第一版 `/api/v1/channel-instances/{channelInstanceId}` 下提供：

| 方法与路径 | 作用 | 执行方式 |
|---|---|---|
| `POST /chat:sync` | 文本或已解析临时附件问答 | 同步，最多 60 秒 |
| `POST /chat:async` | 长耗时问答/附件解析问答 | 异步，返回 operationId |
| `GET /operations/{operationId}` | 查询本渠道异步结果 | 轮询 |
| `POST /attachments` | 上传临时问答附件 | 流式 multipart，返回 attachmentId |
| `POST /data-sources` | 上传持久数据源并解析 | 异步，不自动加入知识库 |

API 文档同时生成 curl、JavaScript 和 Python 示例。

所有 POST 强制携带 `Idempotency-Key`，长度 8-128；同一渠道实例和 endpoint 内 24 小时唯一。相同 key 和相同请求 hash 返回原结果；相同 key 不同请求返回 409 `IDEMPOTENCY_KEY_REUSED`。

## 7. 统一问答请求

```ts
type ExternalChatRequest = {
  conversationId?: string;
  messageId?: string;
  senderId?: string;
  text: string;
  attachmentIds?: string[];
  citationOptions?: {
    detailLevel: "none" | "simple" | "standard" | "full";
  };
  callback?: boolean;
  metadata?: Record<string, string>;
};
```

规则：

- `text` 非空，最大 20000 字符；只有附件时可为空。
- `conversationId` 不传由系统生成并返回。
- `messageId` 用于平台追溯，不替代 Idempotency-Key。
- `metadata` 最多 20 项，键和值各限制长度，只用于追溯，不进入 Prompt。
- attachment 必须属于同一 channel instance、未过期且状态 ready。
- 第一版 `audio/voice/video` capability 为 disabled，接口返回 `MESSAGE_TYPE_UNSUPPORTED`。

## 8. 同步和异步

### 同步

- 总超时固定 60 秒。
- 仅接受文本或已完成解析的 attachmentId。
- 不在同步请求内等待 MinerU 解析。
- 超时返回 HTTP 504、`SYNC_CHAT_TIMEOUT` 和 traceId；不能返回半截答案或伪装无命中。
- 底层调用无法取消时继续记录最终 operation 状态，但同步 HTTP 连接不再补发响应。

### 异步

- 接收后返回 HTTP 202、`operationId/statusUrl/conversationId`。
- 后台执行附件解析和机器人问答。
- 客户端可轮询；配置 callback 时完成后异步推送完整结果。
- operation 只有创建该实例的 API Key 可以查询。

## 9. 临时问答附件

附件格式与数据解析 capability 对齐，但“格式可解析”不表示能在 60 秒内同步完成。

- 上传创建 `TemporaryAttachment` 和临时 SourceBlob 引用。
- 使用相同 ParserAdapter、上传安全校验和标准化规则。
- 不进入数据源库可见列表，不生成知识库 chunk、不写 Chroma/关键词索引。
- 最多 5 个附件、每个最多 50 MB、总计最多 100 MB；仍不能超过 Parser 限制。
- 解析后的文本与知识库上下文分别标记，回答引用 `sourceType=chat_attachment`。
- 临时附件内容只用于该次 ChatRun；不能成为企业长期事实来源。
- 默认保存 24 小时，之后清理文件和解析产物；ChatTrace 保留附件名称、hash、引用片段快照和“已过期”状态。
- 附件解析失败使异步问答失败，不能静默忽略附件继续回答。

## 10. 持久数据源导入

`POST /data-sources` 用于外部渠道把文件送入“数据清洗与解析”模块：

- 复用后台上传校验、SourceBlob 去重、Parser 路由和解析版本状态机。
- 创建 `DataSource.originType=channel_ingest`。
- 返回 dataSourceId、parsedSourceVersionId、operationId 和状态查询地址。
- **不会自动绑定任何知识库，也不会自动构建索引。**
- 解析成功后管理员在知识库页面明确选择该解析版本并构建。

第一版不接受 `targetKnowledgeBaseId`，不提供“渠道自动写入活动知识库”。这是为了保持“解析先完成、管理员选择数据源和构建配置后才入库”的已确认流程。

## 11. 引用返回粒度

- `none`：响应 answer 移除内联 `[Sx]`，不返回 citations。
- `simple`：文档名、知识库名、页码和简短 snippet。
- `standard`：再包含稳定 ID、标题路径、sourcePath 和资产缩略信息。
- `full`：再包含 chunk 文本、block IDs、boundingBox 和检索分数，仅管理员明确允许的实例可启用。

机器人内部始终生成并验证引用；detailLevel 只影响外部呈现。历史 ChatTrace 保存标准引用快照。

## 12. 异步 Callback

callback URL 在渠道实例后台配置，不允许每个外部请求传任意 URL，减少 SSRF 和数据外传风险。

- 默认只允许 HTTPS。
- 解析 DNS 后阻止 loopback、link-local 和云元数据地址。
- 私有网络 callback 仅在私有化部署显式 `ALLOW_PRIVATE_CALLBACKS=true` 时允许，并在后台警示。
- 请求头包含 `X-RAG-Timestamp`、`X-RAG-Event-Id`、`X-RAG-Signature`。
- 使用渠道 callback secret 对 `timestamp + '.' + rawBody` 做 HMAC-SHA256。
- callback secret 与 API Key 分离，明文仅创建时展示一次。
- 首次投递失败后最多重试 5 次（总计最多 6 次）：5 秒、30 秒、2 分钟、10 分钟、30 分钟。
- HTTP 2xx 为成功；4xx（除 408/409/425/429）不重试；网络、408、429、5xx 重试。
- 每次投递保存状态、HTTP code、耗时和脱敏响应摘要。
- callback 最终失败不改变 ChatRun 成功状态，只标记 delivery failed，可人工重发。

## 13. 限流、配额和负载

- Redis 令牌桶按 channelInstanceId 限制每分钟请求。
- 并发超限返回 HTTP 429 和 `Retry-After`。
- 请求 JSON 最大 1 MB；文件走 multipart 流式上传。
- source URL 直接抓取第一版不开放，防止 SSRF；调用方必须上传文件。
- API Key 校验使用常量时间比较。
- 记录 IP 和 User-Agent 的脱敏/保留策略见安全真源。

## 14. 错误与 HTTP 状态

- 400：参数错误、消息类型不支持。
- 401：`CHANNEL_UNAUTHORIZED`。
- 404：实例、operation 或机器人不存在。
- 409：幂等冲突、资源 revision 冲突。
- 413：请求/附件过大。
- 422：业务校验失败。
- 429：限流/并发超限。
- 500：内部未知错误。
- 502/503：上游模型、检索或 Parser 服务不可用。
- 504：同步超时。

所有错误使用统一 ApiError 和 traceId，不返回堆栈。

## 15. 删除和停用

- 渠道实例支持启用/停用；停用后新外部请求返回 `CHANNEL_DISABLED`。
- 删除前停用，软删除并使 API Key 立即失效。
- 运行中的 operation 使用开始时实例快照完成，但 callback 按删除状态停止并记录。
- 历史 ChatRun 保留渠道名称和 adapter 快照。
- 被渠道绑定的机器人不能删除，必须先删除/解绑渠道实例。

## 16. 验收

- 每个渠道实例使用独立不可回显 API Key，轮换后旧 Key 立即失效。
- 相同 Idempotency-Key 不重复回答、解析或导入。
- 同步超时返回明确 504；异步可轮询并可签名 callback。
- 临时附件不进入知识库，24 小时后清理但历史引用仍可解释。
- 持久导入只进入解析数据源库，不自动修改知识库。
- citation detailLevel 只控制返回内容，不改变机器人内部引用校验。
- 后续钉钉/企微/飞书各有独立 Adapter 和回调端点，机器人运行时没有平台分支。
