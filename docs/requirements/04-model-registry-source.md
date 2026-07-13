# 模型配置阶段性真源

> 文档职责：定义供应商、凭据、模型发现、模型类型、连接测试、业务引用和模型变更边界。
> MinerU 属于 Parser，不属于模型配置；其规则见数据解析真源。

## 1. 模块边界

模型配置是全局可复用能力池，管理：

- `ModelProvider`：调用协议、Base URL 和凭据。
- `ModelConfig`：具体模型名、类型、能力和默认参数。
- `ModelVerification`：一次真实连接测试结果。

知识库和机器人只引用 `modelConfigId` 并保存自己的业务级参数快照，不在业务页面填写 API Key，也不修改全局模型。

一个模型配置可被任意数量知识库或机器人引用；共享的是调用能力，不共享 chunks、向量集合、索引、会话或任务。

## 2. 第一版 Provider Adapter

真实实现：

- `openai`。
- `openai_compatible`。
- `deepseek`。
- `qwen`（通义千问）。

后端根据 Adapter 声明其真实支持的模型类型和接口。前端不能假设某供应商天然支持 LLM、Embedding、Rerank、Vision 全部能力。

后续候选：Azure OpenAI、智谱、Gemini、Anthropic、Ollama、vLLM、Custom HTTP。第一版表单不可保存未实现 Provider。

## 3. 供应商配置

字段：

- `id / providerType / displayName`。
- `baseUrl`。
- `credentialStatus`，不返回密钥本身。
- `enabled`。
- `revision`。
- `createdAt / updatedAt`。

规则：

- API Key/Token 由后端使用 AES-256-GCM 认证加密保存，主密钥来自部署 secret。
- 响应只返回 `configured=true` 和脱敏摘要；编辑时留空表示不替换。
- 日志、Trace、导出和异常中不得出现凭据。
- `openai_compatible` 的 Base URL 必须是 HTTPS；仅开发环境显式开关允许 localhost HTTP。
- Base URL 执行 SSRF 校验，不允许云元数据地址、私网跳转或凭据嵌入 URL。
- 供应商凭据可以轮换；调用目标、协议或 Base URL 被模型引用后不能原地改变，应创建新供应商配置。

凭据轮换后，该 Provider 下所有模型的 `verificationStatus` 立即变为 `stale`，因为旧连接测试不再证明新凭据有效。已有知识库/机器人配置不被自动停用，运行时仍尝试调用并按真实结果报错；但模型在重新验证通过前不能被新建/编辑业务配置选择。

供应商创建和连接检测必须分开。允许先保存，再显式测试；保存成功不等于可用于业务。

## 4. 模型配置

字段：

```ts
type ModelConfig = {
  id: string;
  providerId: string;
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
  configSchema: JsonSchema;
  revision: number;
};
```

模型类型不能只靠模型名称猜测。自动发现只创建候选，管理员确认类型后执行该类型连接测试；测试返回结构也必须符合类型。

第一版 `vision` 可以登记和测试（仅 Provider 真支持时），但不参与知识库图片语义理解；未实现业务入口不得显示为可选。

## 5. 自动发现和手动添加

- Provider 支持模型列表接口时可以“发现模型”。
- 发现只更新候选清单，不自动启用、不自动删除现有配置。
- 同一 provider 下 `modelName + modelType` 唯一。
- Provider 不支持发现时手动添加。
- 模型从供应商列表消失时标记发现状态异常，不自动删除和停用。

发现结果与创建模型是两个操作。管理员可选择多个候选批量创建，但每个模型仍需分别完成类型测试。

## 6. 分类型连接测试

### 6.1 LLM

- 输入：`请只回复 OK`。
- `temperature=0`，输出 token 上限 8。
- 成功标准：鉴权成功、模型存在、返回非空文本。
- 记录耗时、请求 ID、输出短摘要和 token 使用，不记录完整凭据。

### 6.2 Embedding

- 输入固定短文本：`RAG knowledge base embedding connection test`。
- 成功标准：返回非空有限数值向量，维度大于 0且每次一致。
- 成功后保存 `embeddingDimension`。
- 返回 NaN、Infinity、空向量或维度不一致均失败。

### 6.3 Rerank

- 使用一个 query 和两段一相关一无关候选文本。
- 成功标准：结果与候选一一对应，分数为有限数，排序结构可解析。
- Adapter 统一转换为“分数越大越相关”。

### 6.4 Vision

- 仅 Provider Adapter 声明支持时测试。
- 使用内置极小测试图片和固定问题。
- 第一版测试通过也不代表 RAG 多模态检索已实现。

测试结果：

- `passed / failed / timeout`。
- `testedModelRevision / testedProviderRevision`。
- `latencyMs / errorCode / errorMessage / providerRequestId / testedAt`。

模型或供应商调用相关配置改变后，原测试状态变为 `stale`。业务下拉只展示 `enabled=true && verificationStatus=passed` 且测试修订仍匹配的模型。

## 7. 业务选择规则

| 使用位置 | 允许类型 | 是否必填 |
|---|---|---|
| 知识库 Embedding | `embedding` | 是 |
| 语义分块 | 知识库同一 `embedding` | 选择语义分块时是 |
| 查询重写 | `llm` | 重写非关闭时是 |
| Rerank Model | `rerank` | 选择该策略时是 |
| LLM 重排 | `llm` | 选择该策略时是 |
| 机器人回答 | `llm` | 是 |
| 追问改写 | 默认机器人回答 `llm` | 记忆改写开启时是 |

业务保存时后端再次校验模型存在、未删除、已启用、类型匹配、验证通过。任一条件不满足都不允许保存，不能仅提示警告。

下拉展示 `displayName / provider / modelName / modelType / context或维度 / 最近测试时间`，保存只使用 ID 和业务参数。

## 8. 参数归属

全局模型保存协议级默认参数和 schema；业务对象保存自己的调用参数：

- 知识库 Embedding：批大小、并发、维度选项（仅模型允许时）、请求参数。
- 查询重写：temperature、输出限制、策略参数。
- 重排：候选上限、输出限制、策略参数。
- 机器人回答：temperature、maxOutputTokens、超时范围。

业务参数来自模型 `configSchema` 与业务策略 schema 的组合，前端动态渲染，后端验证。业务参数不能反向修改模型默认值。

## 9. 引用锁定和变更

模型被引用后：

允许修改：

- 展示名称。
- 说明。
- 供应商高熵凭据轮换。

禁止原地修改：

- providerId / providerType / baseUrl。
- modelName / modelType。
- Embedding 维度和改变语义空间的默认参数。
- 调用协议和 capability version。

这些变化必须新建模型配置，再由知识库或机器人显式替换。

Embedding 模型替换必须创建新知识库配置修订并全量构建新代次；旧代次继续服务直到切换。LLM/Rerank 替换只创建新业务配置修订，不重建向量，保存后用于新请求。

## 10. 启用、停用和删除

- 新模型默认 `enabled=false`，测试通过后由管理员显式启用。
- 测试失败不会自动停用正在运行的模型，但标记健康异常并告警；运行调用仍按错误处理。
- 被任一未删除业务配置的当前草稿或活动版本引用时，不允许停用或删除，返回 `MODEL_IN_USE` 和引用清单。
- 未引用模型可停用；停用后不进入新选择器。
- 第一版模型删除采用软删除，不提供恢复 UI。
- 供应商仍有模型配置时不能删除。

## 11. 超时、重试和并发

默认单次调用超时：

- LLM：60 秒。
- Embedding：60 秒。
- Rerank：30 秒。
- Vision：60 秒。

网络错误、HTTP 429、HTTP 5xx 最多额外重试 2 次，退避 1 秒、2 秒并加 jitter。鉴权、模型不存在、参数和类型错误不重试。

Embedding 构建任务：

- 默认 batch size 32，可按模型 schema 在 1 至 256 调整。
- 默认每个模型配置并发 2，可在 1 至 8 调整。
- Adapter 对供应商限流实施统一 semaphore 和退避。
- 每批保存进度和确定性 chunk IDs，任务重跑不重复生成已持久化成功批次。

Provider 调用重试次数与 Celery task 重试次数必须分字段记录。

## 12. 统一模型错误

- `MODEL_AUTH_FAILED`。
- `MODEL_NOT_FOUND`。
- `MODEL_TYPE_MISMATCH`。
- `MODEL_BAD_REQUEST`。
- `MODEL_RATE_LIMITED`。
- `MODEL_TIMEOUT`。
- `MODEL_PROVIDER_ERROR`。
- `MODEL_RESPONSE_INVALID`。
- `MODEL_VERIFICATION_REQUIRED`。
- `MODEL_IN_USE`。

业务运行时模型错误不能被改写成“知识库无命中”。

## 13. 成本和调用记录

每次调用记录：

- provider/model ID 和当时名称快照。
- purpose：test、embedding、rewrite、rerank、chat、fallback 等。
- input/output token 或字符/候选数量。
- 调用次数、重试次数、耗时、状态和错误。
- 供应商返回用量与估算用量分开标记。

第一版不做计费，但保留可聚合的调用量；不知道价格时不能伪造成本金额。

## 14. 验收

- 创建和测试是两个独立操作，未测试模型不能在业务页面选择。
- LLM、Embedding、Rerank 按类型执行真实测试，不用同一“ping”冒充。
- 模型类型不匹配时前后端均不能保存。
- 被引用模型不能修改身份或停用，返回完整引用清单。
- 两个知识库引用同一 Embedding 模型仍生成独立 collection 和任务。
- 凭据不在列表、详情、日志、OpenAPI 示例和异常中泄漏。
- Provider 临时失败有明确重试和错误，不被记录为无命中。
