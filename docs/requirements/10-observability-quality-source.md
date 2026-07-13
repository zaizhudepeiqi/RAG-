# 可观测性、任务与 RAG 质量阶段性真源

> 文档职责：定义 Operation/任务中心、结构化日志、Chat Trace、审计日志、在线运行指标、离线 RAG 质量评测和保留规则。

## 1. 设计目标

后台日志不追求“模式多”，只追求能够回答：

- 哪个请求失败了？
- 失败在哪个阶段？
- 使用了哪个对象版本和配置？
- 是否重试、降级或部分失败？
- 用户最终看到了什么？
- 系统质量变差是检索、生成、模型还是基础设施问题？

三个层级：

- `Operation`：异步业务操作和进度。
- `ChatRun/ChatTrace`：一次问答业务全链路。
- 结构化运行日志/指标：开发和运维诊断。

## 2. Operation 和任务中心

任务类型：

- `mineru_connection_test`。
- `model_connection_test`。
- `parse_source_version`。
- `build_index_generation`。
- `retry_generation_items`。
- `async_chat`。
- `temporary_attachment_parse`。
- `channel_callback_delivery`。
- `cleanup_retention_data`。
- `aggregate_metrics`。
- `evaluate_rag_dataset`。

Operation 状态：

```text
queued -> running -> succeeded
                  -> partial_succeeded
                  -> failed
queued -> cancelled
```

Outbox/Worker 的 `eventType + schemaVersion` 必须命中代码内显式任务注册。部署版本无法识别时，不得猜测 payload 或调用任意 task name；对应 outbox 进入不可自动重试的 failed，Operation 进入 failed 并记录稳定错误码 `TASK_SCHEMA_UNSUPPORTED`，由部署兼容性检查和人工处理解决。

运行中子阶段和重试不污染顶层状态：

- `stageCode / stageLabel`。
- `progressCurrent / progressTotal / progressUnit`。
- `attempt / maxAttempts`。
- `heartbeatAt`。

任务字段：

- operationId、taskType、targetType、targetId、targetRevision。
- status、stage、进度。
- celeryTaskId（诊断字段）。
- idempotencyKeyHash。
- queuedAt、startedAt、finishedAt、heartbeatAt。
- errorCode、errorMessage、retryable、errorDetailSnapshot。
- resultSummary、warningCount、childItemCounts。

Worker 每 30 秒更新 heartbeat。运行中超过 2 分钟无 heartbeat 标记 `stalled` 告警，但不自动改业务终态；管理员可查看并按具体任务恢复。

## 3. 重试和取消

- Provider 调用重试、Operation 执行重试和管理员重新执行分开记录。
- 只有规则明确为幂等且 retryable 的阶段自动重试。
- 解析任务不能因 Celery 重试自动重复提交 MinerU。
- 构建 generation 默认只重试失败 item。
- 只允许取消尚未开始的 queued operation。
- 第一版运行中不提供假取消；界面明确“运行中不可取消”。
- 管理员重新执行创建新 Operation，并关联 `retryOfOperationId`。

## 4. 结构化日志

JSON 日志公共字段：

- timestamp、level、service、environment、version。
- traceId、operationId、chatRunId、requestId。
- module、eventCode、message。
- actorType、actorId。
- targetType、targetId。
- durationMs、attempt。
- errorCode、exceptionClass（仅服务端日志）。

规则：

- 不记录 API Key、Token、JWT、完整签名 URL、密码和加密主密钥。
- 用户输入、文档正文、Prompt 和模型响应默认不写普通运行日志。
- 堆栈只写服务端受控日志，不返回 API。
- 同一外部请求、异步 operation 和供应商调用通过 traceId/correlation IDs 关联。
- 健康检查高频成功日志降级采样，失败全量记录。

## 5. ChatRun 和 Trace

ChatRun 摘要：

- id、traceId、source、status。
- botId/name/revision。
- channelInstanceId/name。
- conversationId、messageId。
- requestAt、responseAt、totalLatencyMs。
- retrievalStatus：`not_run/succeeded/partial_failed/failed`。
- isHit、fallbackUsed、answerBasis。
- attempted/hit/failed/skipped knowledge base counts。
- finalContextCount、citationCount。
- answerModelId、tokenUsage、errorCode。

Trace 分阶段：

1. 规范化请求和会话快照。
2. standaloneQuery 改写。
3. 知识库可用性和 generation 快照。
4. 每库检索配置、候选、过滤、融合、重排和耗时。
5. 跨库 RRF 输入、权重、排名和去重。
6. token 预算、实际上下文和来源。
7. 最终 Prompt、模型请求/响应和 usage。
8. 引用校验/修复。
9. 降级、错误、重试和最终响应。

大字段保存为受控加密 payload 或对象存储引用，列表不直接加载。Trace payload 有独立 schemaVersion，便于后续演进。

## 6. 审计日志

第一版即使单管理员也记录：

- 登录成功/失败、密码修改。
- Provider/MinerU/渠道凭据创建和轮换。
- 模型启停和危险字段变更尝试。
- 数据源/解析版本/机器人删除，以及知识库/渠道删除和停用。
- 知识库 generation 激活和构建重试。
- 查看敏感 Trace 正文。
- 日志清理和保留设置修改。

审计日志只保存变更摘要和敏感字段已变更标记，不保存秘密值。第一版保留 180 天，不通过普通日志清理页面删除；手动清理需独立危险操作和审计记录。

## 7. 在线运行指标

在线指标只回答运行情况，不冒充答案质量：

### 系统概览

- 知识库总数/ready/partial/unavailable。
- 已解析数据源、解析失败版本。
- 机器人和启用渠道实例数量。
- 今日外部问答、后台测试问答。

### 任务健康

- queued/running/stalled/failed operations。
- 解析、构建、模型和 callback 失败率。
- 队列等待和执行耗时 P50/P95/P99。

### RAG 运行指标

- `retrievalHitRate = 正常完成且 isHit 的 ChatRun / 正常完成检索的 ChatRun`。
- `noHitRate = 正常完成且 !isHit / 正常完成检索的 ChatRun`。
- 检索失败率单独展示，不进入命中率分母。
- 平均/分位召回候选数、最终上下文数、引用数。
- Rewrite/Rerank 降级率。
- 部分知识库失败率。
- 响应耗时 P50/P95/P99，按阶段拆分。

### 模型指标

- LLM/Embedding/Rerank 调用、失败、429、超时和重试。
- input/output tokens、Embedding 文本数、Rerank 候选数。
- 按模型和 purpose 过滤。

不展示“低置信度回答占比”，因为第一版没有低置信度定义。平均分数只能在相同算法/模型/配置范围内聚合；跨异构知识库不计算一个没有意义的平均相似度。

## 8. 在线指标维度和时间

- 默认时间范围：最近 24 小时；可选 7 天、30 天和自定义最多 90 天。
- 按机器人、知识库、渠道、source、模型和状态筛选。
- 时间桶：24 小时按小时，7/30 天按天。
- 所有查询使用 UTC 存储，界面显示本地时区。
- 机器人测试默认不进入“外部业务量”，但可单独筛选。
- 知识库检索测试永不进入在线 ChatRun 指标。

指标聚合由异步任务每 5 分钟更新；最近 15 分钟可以查询原始摘要补齐。仪表盘显示数据更新时间，不能让用户误以为严格实时。

## 9. 离线 RAG 质量评测

仅凭线上“最终上下文非空”无法判断 RAG 好坏。第一版必须提供最小离线评测能力，否则所谓“企业级质量指标”只是漂亮但虚假的数字。

### 9.1 评测集

每个知识库可创建多个 Dataset：

- 名称和说明。
- question。
- `shouldHit`。
- expectedSource：parsedSourceVersionId + 可选 pageRange/sourceBlockIds。
- 可选 referenceAnswer。

支持后台逐条维护和 CSV 导入/导出。第一版不自动用 LLM 生成标准答案。

### 9.2 评测运行

运行绑定：

- knowledgeBaseId。
- activeGenerationId 或明确 generationId。
- retrievalConfigRevisionId 或临时配置快照。
- datasetRevision。

结果不可变，便于比较调参前后。

### 9.3 第一版确定性指标

- Hit@K：应命中问题的前 K 结果包含任一 expectedSource。
- Recall@K：expected sources 被前 K 覆盖的比例。
- MRR：第一个正确来源排名的倒数均值。
- No-hit accuracy：`shouldHit=false` 的问题正确返回无命中的比例。
- Retrieval latency P50/P95。
- Error rate。

没有 expectedSource 的样本不参与 Hit@K/Recall/MRR，只计运行状态。

第一版不把 LLM Judge 作为默认质量真源；后续可增加 faithfulness、answer correctness 和 citation correctness，但必须保存 judge 模型、Prompt 和版本。

## 10. 低命中问题列表

名称改为“无命中与检索失败问题”：

- 正常无命中和系统失败分 Tab 展示。
- 显示问题、机器人、知识库、standaloneQuery、时间、最高本库分数（仅同库语境）、错误阶段和 traceId。
- 支持一键加入某知识库评测集，但必须由管理员补 expected source/shouldHit。
- 不显示含义不明的跨库“最高分”。

## 11. 保留与清理

默认：

- ChatRun 摘要和 Trace：30 天，可在 7-365 天调整。
- 会话历史：30 天，可在 1-365 天调整。
- Operation：90 天。
- 审计日志：180 天。
- 临时附件：24 小时。
- 聚合指标：365 天。
- 离线评测集和结果：直到管理员删除。

清理规则：

- 不混用各类 retention 配置。
- 分批删除，每批最多 1000 行/对象，避免长事务。
- 先清 payload/文件，再清摘要；失败可幂等重试。
- 清理不影响聚合指标和审计要求。
- 手动清理先预估数量和时间范围，二次确认并写审计。
- 原始数据源和解析产物不按日志保留期清理，只按业务删除规则处理。

## 12. 告警和健康

第一版后台告警中心至少显示：

- 连续 MinerU/模型鉴权失败。
- 队列堆积和 Worker heartbeat 丢失。
- Chroma/PostgreSQL/Redis/存储不可用。
- 知识库重建失败或 partial_ready。
- 外部 callback 最终失败。
- 磁盘空间低于 15%，严重低于 5%。

第一版不集成短信/邮件告警，可通过结构化日志和健康端点接入外部监控。

## 13. 验收

- 一个 traceId 能关联 HTTP、Operation、Provider 调用和 ChatRun。
- 任务中心能明确显示失败阶段、重试和部分成功，不依赖 Celery UI。
- 在线命中率排除检索系统失败，不冒充准确率。
- 仪表盘不再展示未定义的低置信度指标和跨异构平均分。
- 标准评测集能计算 Hit@K、Recall@K、MRR 和 no-hit accuracy，并绑定 generation/config revision。
- 日志清理不会删除原始数据源或破坏历史聚合。
- 密钥和文档正文不出现在普通结构化日志。
