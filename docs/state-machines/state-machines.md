# 第一版状态机契约

> 上游真源：`docs/requirements`。
> 状态转换只能由 application service 执行；API、Celery task 和前端不能直接写状态。

## 1. 通用规则

- 每次转换在 PostgreSQL 事务内比较当前状态和 revision。
- 非法转换返回 409 `INVALID_STATE_TRANSITION`，details 包含 current/event/allowedEvents。
- 外部 Provider 原始状态先映射，不直接写领域状态。
- 任务重投必须幂等；终态重复事件返回当前结果，不反向转换。
- `failed` 不一定都可重试；以 `retryable` 和失败阶段为准。
- 派生展示状态不允许作为转换输入。

## 2. Operation

状态：`queued / running / succeeded / partial_succeeded / failed / cancelled`。

| 当前 | 事件 | 下一状态 | 守卫/副作用 |
|---|---|---|---|
| - | create | queued | 同事务写 outbox |
| queued | worker_claim | running | 幂等 key 唯一，设置 started/heartbeat |
| queued | cancel | cancelled | 未被 Worker claim |
| running | complete | succeeded | 目标业务已达到完整成功 |
| running | complete_partial | partial_succeeded | 业务真源允许部分成功 |
| running | fail | failed | 保存 error/retryable |
| terminal | duplicate_delivery | terminal | no-op，返回已有结果 |

规则：

- `running` 第一版不可取消。
- retry 创建新 operation，设置 `retryOfOperationId`，旧 operation 不回到 queued。
- heartbeat 过期只标记诊断 `stalled=true`，不直接改 status；reconciler 判断 Worker/目标状态后决定失败或恢复。

## 3. ParsedSourceVersion

状态：

```text
queued
submitting
uploading
provider_pending
parsing
downloading
normalizing
succeeded
degraded
failed
cancelled
```

### 3.1 主流程

| 当前 | 事件 | 下一状态 | 说明 |
|---|---|---|---|
| - | create_parse_version | queued | 保存不可变 config/hash |
| queued | claim_mineru | submitting | MinerU 格式 |
| queued | claim_builtin | normalizing | builtin_text 跳过 Provider |
| queued | cancel | cancelled | 仅 queued |
| submitting | upload_urls_received | uploading | 本地文件 signed upload |
| submitting | provider_task_created | provider_pending | URL/可直接提交模式 |
| uploading | upload_completed | provider_pending | 保存 batch/task 标识 |
| provider_pending | provider_running | parsing | 官方 pending/running 映射 |
| provider_pending | provider_done | downloading | 极快完成 |
| parsing | provider_running | parsing | 更新进度，自循环 |
| parsing | provider_done | downloading | 有 full_zip_url |
| downloading | archive_verified | normalizing | 原始 zip 校验完成 |
| normalizing | normalized_full | succeeded | block/asset/sourceMap 完整 |
| normalizing | normalized_degraded | degraded | 有可索引正文但缺结构/坐标 |

任一非终态在明确不可恢复错误时 -> failed；保存发生阶段和 retryable。

### 3.2 失败恢复

| 当前 | 事件 | 下一状态 | 守卫 |
|---|---|---|---|
| failed | resume_provider_query | provider_pending | providerTaskId 存在；失败原因为本地超时/轮询/下载 |
| failed | redownload_result | downloading | 上游已 done 且结果 URL 可重新获取 |
| failed | renormalize | normalizing | 原始归档有效，错误只在标准化 |

重新提交 MinerU 不修改原 version，而是创建新 ParsedSourceVersion。

### 3.3 终态

- succeeded/degraded：可选，内容冻结。
- failed/cancelled：不可选。
- succeeded/degraded 不允许原地变 failed；后续完整性巡检异常通过独立告警和禁用选择标记处理，不能改写历史结果。

## 4. TemporaryAttachment

状态：`uploaded / queued / parsing / ready / failed / expired / deleted`。

| 当前 | 事件 | 下一状态 |
|---|---|---|
| - | upload | uploaded |
| uploaded | enqueue_parse | queued |
| queued | worker_claim | parsing |
| parsing | parse_success | ready |
| parsing | parse_failure | failed |
| uploaded/queued/parsing/ready/failed | ttl_elapsed | expired |
| expired | cleanup_success | deleted |

ready 附件在 expiresAt 之前才可用于同步 chat。过期时运行中的 ChatRun 使用开始时已加载快照完成，不能新引用。

## 5. IndexGeneration

状态：

```text
queued
building
validating
succeeded
partial_ready
partial_failed
failed
cancelled
discarded
```

### 5.1 主转换

| 当前 | 事件 | 下一状态 | 守卫/副作用 |
|---|---|---|---|
| - | create_generation | queued | 同 KB 无其他活动构建 operation |
| queued | worker_claim | building | 创建 staging collection/namespace |
| queued | cancel | cancelled | 仅 queued |
| building | all_items_terminal | validating | 至少一个 item 进入终态 |
| validating | validation_full_success | succeeded | 所有 required item 成功；原子激活并 frozen |
| validating | validation_partial_first_build | partial_ready | 无旧 active 且至少一个 item 成功；激活成功项并 frozen |
| validating | validation_partial_rebuild | partial_failed | 有旧 active；不激活、不 frozen，旧代次继续服务 |
| validating | validation_no_success | failed | 不激活 |
| partial_failed | retry_failed_items | building | 仅失败 item 回到 queued/build stages |
| failed/partial_failed | discard | discarded | 无活动指针指向该 generation |

### 5.2 激活事务

激活必须在一个条件事务中：

1. 锁定 KnowledgeBase 行。
2. 确认 expected KB revision、pending config 和 generation 仍匹配。
3. 确认 validationReport 通过。
4. 设置 generation activatedAt/isFrozen。
5. 切换 activeGenerationId。
6. 切换为 generation 绑定的 activeRetrievalRevisionId。
7. 清空匹配的 pendingBuildConfigRevisionId 和 pendingRetrievalRevisionId。
8. 记录审计和旧代次 retainUntil。

条件失效返回 `GENERATION_ACTIVATION_CONFLICT`，generation 保持已验证但未激活，不能覆盖新操作。

### 5.3 活动 partial 修复

已激活 partial_ready 已冻结。`retry failed` 事件创建新的 repair generation：

- 配置 revision 相同。
- 成功 item 复制 chunks/关键词/向量到 staging，不重新模型调用。
- 只执行上一代失败 item。
- 完整成功后按正常激活切换。

## 6. IndexGenerationItem

状态：`queued / chunking / embedding / keyword_indexing / vector_indexing / validating / succeeded / failed`。

```text
queued -> chunking -> embedding -> keyword_indexing
       -> vector_indexing -> validating -> succeeded
任何执行态 -> failed
failed -> chunking（明确 retry，按 checkpoint 可从安全阶段恢复）
```

规则：

- 进入 embedding 前 chunk 输出完整并有确定性 ID。
- Embedding 成功批次 checkpoint 可复用。
- keyword/vector 写入 staging generation。
- validating 失败清理该 item 暂存记录或可幂等覆盖。
- generation frozen 后 item 不允许转换。

## 7. 知识库展示状态

不是数据库状态机，由字段派生：

| 条件 | 展示 |
|---|---|
| deletedAt != null | deleted |
| enabled=false | disabled |
| activeGeneration=null 且 latest build queued/running | building |
| activeGeneration=null 且 latest build failed | unavailable |
| activeGeneration full 且新 build running | rebuilding |
| activeGeneration partial 且新 build running | partial_ready + rebuilding |
| activeGeneration full | ready |
| activeGeneration partial | partial_ready |
| pendingBuildConfigRevision != null 且无 running build | config_changed（叠加 ready/partial） |

前端使用后端 `derivedDisplayStatus`，但按钮权限由原始字段和 allowedActions 决定。

## 8. 模型验证和启用

`verificationStatus`: `untested / passed / failed / stale`。

| 事件 | 转换 |
|---|---|
| create model | -> untested |
| verification success | any -> passed，记录 tested revisions |
| verification deterministic failure | any -> failed |
| provider credential rotation 或 model callable config changes | passed/failed -> stale |

`enabled` 独立 boolean：

- enable 守卫：verificationStatus=passed，tested revisions 当前。
- disable 守卫：无当前/待发布业务引用。
- 临时健康测试失败不自动把 enabled=false；运行错误单独记录。

## 9. Bot 配置

Bot 没有 enabled 状态。创建/更新：

```text
validate references
  -> create immutable BotConfigRevision
  -> atomic switch activeConfigRevisionId
  -> increment Bot revision
```

更新失败不影响旧 active revision。删除守卫：无活动 ChannelInstance；删除后软删除，旧 revisions 保留供 ChatRun 追溯。

## 10. ChatRun

顶层状态：`running / succeeded / failed`；stage 独立记录。

阶段：

```text
accepted
standalone_rewrite
resolving_knowledge_bases
retrieving
cross_kb_fusion
budgeting_context
generating_answer | handling_no_hit
validating_citations
persisting_result
completed
```

### 10.1 检索结果分类

| 条件 | retrievalStatus | 后续 |
|---|---|---|
| 全部可尝试 KB 正常，至少一条最终上下文 | succeeded/isHit=true | 知识回答 |
| 全部可尝试 KB 正常，最终上下文空 | succeeded/isHit=false | no-hit policy |
| 部分 failed，仍有最终上下文 | partial_failed/isHit=true | 知识回答 + warning |
| 部分 failed，其余正常 no-hit | failed/isHit=false | RETRIEVAL_INCOMPLETE_NO_ANSWER，不兜底 |
| 所有可尝试 KB failed | failed | ChatRun failed，不兜底 |
| 无任何 usable KB（全 skipped） | failed | BOT_NO_USABLE_KNOWLEDGE_BASE |

### 10.2 终态

- Answer/no-hit 流程成功并持久化 -> succeeded。
- 回答模型失败、上下文预算非法、所有检索失败、持久化失败 -> failed。
- 同步 HTTP 超时不一定改变 ChatRun；后台 operation 可继续到真实终态。
- ChatRun 终态不可修改；callback delivery 独立。

## 11. Conversation

- 创建：chat request 不传 conversationId 时服务生成。
- active：lastActiveAt 距当前 <= sessionTimeoutMinutes。
- inactive：超过会话超时，不用于 standalone rewrite；再次使用相同 ID 开启新的连续窗口，但仍归同一 Conversation 记录并标记 gap。
- expired：超过 retention，消息内容清理；Conversation 墓碑可保留用于去重/审计。

## 12. ChannelInstance

`enabled` 独立 boolean、`deletedAt` 软删除。

| 事件 | 守卫/结果 |
|---|---|
| enable | bot 存在且配置有效、Key 已配置、连接测试 passed |
| disable | 立即拒绝新请求；运行中按快照完成 |
| rotate key | 更新 hash/prefix，旧 key 立即无效 |
| delete | 无必须完成的管理操作；先 disabled，再软删除 |

## 13. CallbackDelivery

状态：`queued / sending / succeeded / retry_wait / failed`。

```text
queued -> sending
sending -> succeeded                 HTTP 2xx
sending -> retry_wait                网络/408/429/5xx，且已重试次数 < 5
retry_wait -> sending                nextAttemptAt 到期
sending -> failed                    永久 4xx 或初始投递 + 5 次重试均失败
failed -> queued                     管理员人工重发，创建新 delivery/eventId
```

delivery failed 不改变 ChatRun succeeded。

## 14. 删除和清理 Operation

业务删除：

```text
validate references/running operations
  -> set deletedAt immediately
  -> create cleanup Operation/outbox
  -> purge external indexes/files
  -> retain database tombstone/snapshots
```

清理失败时对象保持业务已删除，Operation failed/retryable；不能把对象恢复成可用，也不能静默漏存储。

## 15. 状态机验收

- 每个非法转换 API 返回 409 和 allowedEvents。
- 重复 Celery delivery 对终态 no-op。
- Parser 本地超时可恢复查询旧 providerTaskId，不重复创建上游任务。
- 已激活 generation 无法修改 item/chunk；数据库触发器/Repository 测试覆盖。
- 部分重建不会切换旧 active generation。
- 所有检索失败与正常 no-hit 走不同 ChatRun 终态。
- callback 最终失败不反向修改成功回答。
- 前端 derived status 与原始字段组合测试一致。
