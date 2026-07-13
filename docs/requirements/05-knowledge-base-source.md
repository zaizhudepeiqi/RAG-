# 知识库构建阶段性真源

> 文档职责：定义多知识库、解析版本选择、配置修订、构建代次、原子切换、局部失败、编辑、停用和删除。
> 分块和检索算法参数见 [06-retrieval-source.md](./06-retrieval-source.md)。

## 1. 模块定位

知识库是“已解析内容如何被组织、分块、索引和检索”的独立配置与运行单元。

系统支持：

- 创建任意多个知识库。
- 一个知识库选择多个已解析数据源版本。
- 一个解析版本被多个知识库复用。
- 每个知识库独立选择 Embedding 模型、分块、索引和检索策略。
- 一个知识库被多个机器人复用。

知识库不负责原始文件上传和 MinerU 解析。知识库页面不能偷偷创建解析任务，只能选择数据解析模块中 `succeeded/degraded` 的 `ParsedSourceVersion`。

## 2. 对象结构

`KnowledgeBase`：

- `id / name / description`。
- `enabled`。
- `revision`。
- `activeGenerationId`。
- `activeRetrievalRevisionId`。
- `pendingBuildConfigRevisionId`。
- `pendingRetrievalRevisionId`。
- `latestBuildOperationId`。
- `createdAt / updatedAt / deletedAt`。

`KnowledgeBaseConfigRevision` 是不可变快照，分为：

- 数据源绑定快照。
- 构建配置快照。
- 检索配置快照。
- 创建者和创建时间。

`IndexGeneration`：

- `id / knowledgeBaseId / generationNumber`。
- `configRevisionId`。
- `status`。
- `collectionName / keywordNamespace`。
- `sourceCount / successfulSourceCount / failedSourceCount`。
- `chunkCount / vectorCount`。
- `validationReport`。
- `startedAt / finishedAt / activatedAt`。

## 3. 创建流程

创建页采用一个纵向长页面，按折叠区分为六部分：

1. 基础信息。
2. 已解析数据源。
3. Embedding 与向量索引。
4. 分块与索引结构。
5. 检索、查询重写和重排序。
6. 最终确认。

必要条件：

- 名称非空且在未删除知识库中唯一，最长 100 字符。
- 至少选择一个 `succeeded/degraded` 解析版本。
- 必须选择一个已启用、验证通过的 Embedding 模型。
- 所有 capability 已启用且配置通过 schema 校验。
- 分块、索引和检索参数通过跨字段校验。

选择数据源、修改下拉或折叠区不会执行任务。只有点击最终“创建并构建”才在一个事务中：

1. 创建 KnowledgeBase。
2. 创建初始不可变配置修订。
3. 保存解析版本绑定。
4. 创建初始 IndexGeneration 和 Operation。
5. 写入 outbox，异步提交构建。

请求失败不得留下半个知识库。前端可把未提交表单保存在浏览器本地草稿，但第一版不创建服务器端半成品草稿。

## 4. 数据源选择

选择器只显示解析模块返回的可选版本，支持按名称、格式、状态、时间和来源筛选。

每一项展示：

- 数据源名称和 `sourcePath`。
- 格式、大小、SHA-256 摘要。
- 解析版本号、Parser、参数摘要和完成时间。
- `full/degraded` 质量标识。
- 可用结构能力：正文、页码、标题、坐标、资产、表格、公式。
- 已被多少知识库活动代次使用。

规则：

- 知识库绑定具体 `parsedSourceVersionId`，不绑定“最新版本”。
- 同一知识库配置修订不能重复选择同一解析版本。
- 同一数据源可以选择多个解析版本，但默认禁止；管理员必须在高级操作中确认“这会产生重复内容”，以免无意重复索引。
- 数据源产生新解析版本后，知识库只显示“有新版本可用”，不自动替换和重建。
- 替换版本属于构建配置变更，必须创建新配置修订和新构建代次。

分块兼容性在保存/构建前校验：

- 所有策略都要求 `hasText=true`。
- `page` 策略要求每个选中版本 `hasPages=true`；任一不满足则不允许保存，不到 Worker 才失败。
- `heading` 策略把 `hasHeadings` 作为 preferred feature；缺失时按已定义 fallback 降级并在构建确认中警示。
- 坐标、资产、表格和公式不是普通文本检索的硬要求，但影响引用展示能力。
- capability API 返回 required/preferred source features，前端逐项显示兼容性；后端是最终校验者。

## 5. Embedding 和索引隔离

每个知识库保存自己的：

- `embeddingModelId`。
- 模型身份和维度快照。
- 知识库级 Embedding 参数。
- 向量索引 capability、算法和参数。
- generation 独立 collection 名。
- keyword generation 独立 namespace。

两个知识库选择同一模型时仍独立执行分块、Embedding 和写入。collection 命名使用不可猜测的内部 ID，不使用用户名称，例如：

```text
kb_{knowledgeBaseId}_gen_{generationNumber}
```

Embedding 模型或维度变化必须全量构建新 generation。不同维度向量永远不能写入同一 collection。

## 6. 配置变更分类

### 6.1 仅元数据变更

- 名称。
- 描述。

保存后立即生效，不需要构建。

### 6.2 查询期配置变更

- 检索类型和 Top K。
- 分数阈值。
- 混合融合参数。
- 查询重写及模型。
- 重排序及模型。
- 上下文窗口。

保存为新的检索配置修订，校验成功后原子更新 `activeRetrievalRevisionId`，不重建 chunks/向量。新请求使用新修订，进行中的请求继续使用开始时快照。

如果不存在未发布构建变更，查询期修订可立即激活；如果已有未发布构建变更，且新检索配置依赖该新索引结构/能力，则保存为 `pendingRetrievalRevisionId`，等待 generation 激活。

### 6.3 构建期配置变更

- 增加、移除或替换解析版本。
- Embedding 模型或参数。
- 向量索引算法、距离度量或构建参数。
- 索引结构 Chunk/Parent-Child。
- 分块策略和参数。
- 关键词索引引擎或生成规则。

保存只创建待构建配置修订，并把界面标记为“存在未发布构建变更”；不会污染活动代次。管理员点击“构建新索引”后才创建 generation。

如果同时修改构建期和查询期配置，查询期变更保存为 pending retrieval revision；新 generation 明确绑定该 retrieval revision，激活事务同时切换 `activeGenerationId` 和 `activeRetrievalRevisionId`，不能先应用到不兼容的旧索引。

## 7. 构建流水线

```text
validate_snapshot
  -> prepare_generation
  -> chunk_sources
  -> embed_chunks
  -> build_keyword_index
  -> build_vector_index
  -> validate_generation
  -> activate_or_hold
  -> schedule_cleanup
```

每个解析版本有一个 `IndexGenerationItem`，阶段和错误独立记录。构建项的中间输出只能写入 generation 暂存命名空间。

校验至少包括：

- 所有成功 item 的 chunk 数大于 0。
- chunk 到解析 block/asset 的来源映射完整。
- 向量数与需要向量化的检索 chunk 数一致。
- 向量维度与模型快照一致。
- Chroma collection 可读取并完成抽样查询。
- 关键词索引行数与检索 chunk 数一致。
- 不存在跨知识库或跨 generation ID。

## 8. 首次构建和重建切换

### 8.1 首次构建

- 全部数据源成功：激活 generation，知识库 `ready`。
- 部分成功：激活成功部分，知识库 `partial_ready`；失败数据源不参与检索，界面持续显示警告。
- 全部失败：不激活 generation，知识库 `unavailable`。

采用部分激活是为了让成功文档可用，但必须在机器人 Trace 和后台界面暴露缺失数据源，不能把部分成功伪装成完整就绪。

一旦部分 generation 被激活，它立即冻结。后续修复失败项不能向活动 collection 直接追加，必须创建继任 repair generation。

### 8.2 已有活动代次的重建

- 新 generation 全部成功：自动原子切换。
- 新 generation 部分成功或全部失败：保留旧活动 generation，不自动降级切换。
- 暂存 generation 保留成功项，管理员默认执行“只重试失败数据源”。
- 独立提供“放弃本次构建”和“从头全量重建”。
- 第一版不提供“强制激活部分重建”操作，避免无意丢失旧活动内容。

这条规则解决两个问题：重建期间不停服，重建失败不破坏已经可用的知识库。

## 9. 失败项重试

默认策略：只重试当前暂存 generation 中失败的 `IndexGenerationItem`。

- 对尚未激活的暂存 generation：在同一 generation 内继续失败 item；成功项不重新分块、不重新调用 Embedding。
- 对已经激活的 `partial_ready` generation：创建继任 repair generation，复制成功项的 chunks、关键词记录和现有向量，不重新调用 Embedding，只处理上一代失败 item；验证后原子切换。
- repair generation 使用同一不可变配置修订，但拥有新的 generationId，保证历史代次含义不变化。
- 如果配置已变化，不能把新配置混入旧 generation；必须新建 generation。
- 管理员可选择全库重建，创建新的 operation 和 generation。
- 重试达到上限后保持失败，等待人工处理。

## 10. 并发和幂等

- 同一知识库最多一个 `queued/building/validating` generation。
- 重复“创建并构建”或“构建新索引”请求通过 Idempotency-Key 返回同一 operation。
- 配置保存使用 `expectedRevision`，过期页面返回 409。
- 构建任务的 chunk ID 由 generation、解析版本和块序号确定，重跑可安全 upsert。
- 激活使用 PostgreSQL 事务和条件更新，仅当 generation 仍是当前待激活目标时切换。
- 旧 operation 完成时不得覆盖后来 generation 的活动指针。

## 11. 可用性状态

数据库不使用一个万能 status，界面状态由以下字段派生：

- `enabled`：管理员是否允许运行时检索。
- `activeGenerationId`：是否有活动索引。
- `activeGeneration.completeness`：`full / partial`。
- `latestBuildStatus`：`not_started / queued / building / validating / succeeded / partial_failed / failed / cancelled`。
- `hasUnpublishedBuildChanges`。

界面展示：

- `ready`：启用、有完整活动代次。
- `partial_ready`：启用、有部分活动代次。
- `building`：正在构建且无活动代次。
- `rebuilding`：正在构建但旧活动代次仍服务。
- `config_changed`：有未发布构建变更。
- `unavailable`：无活动代次。
- `disabled`：管理员停用。

这些展示值不能作为后端状态机输入。

## 12. 知识库详情

一个详情页使用 Tabs：

- 概览：可用性、活动代次、数据统计、警告、绑定机器人。
- 数据源：当前绑定、版本替换、增加/移除、解析详情跳转。
- 构建配置：Embedding、索引、分块和未发布变更。
- 检索配置：检索、重写、重排和上下文窗口。
- 检索测试：单库调试，不生成回答。
- 质量评测：评测集和历史运行。
- 构建历史：generation、任务阶段、失败项和操作。

复杂编辑使用完整页面和 Tabs；任务、错误、Trace 快速查看使用抽屉。

## 13. 检索测试

只调用当前知识库。默认使用活动 generation 和活动检索修订；有未发布构建变更时不能假装测试了新分块。

允许临时覆盖查询期配置，点击“测试”不保存；“保存为检索配置”创建检索修订。测试结果不写问答日志、不计在线命中率，但写轻量操作日志和可选评测运行。

完整响应要求见检索真源。

## 14. 停用、启用和删除

停用：

- 不删除任何数据。
- 新机器人请求跳过该知识库并在 Trace 记录原因。
- 正在进行的请求使用开始时快照完成。
- 构建任务可继续，完成后不改变停用状态。
- 可重新启用；有可用活动代次时立即恢复检索。

删除：

- 被任一未删除机器人绑定时拒绝删除，返回机器人清单，管理员必须先解除绑定。
- 存在运行构建时拒绝删除。
- 二次确认显示数据源数、generation 数、chunk/向量数、存储占用和历史问答引用数。
- 删除后立即业务不可见，异步清理 collection、关键词索引、chunks 和配置；不删除解析模块的数据源和解析产物。
- 历史 ChatRun 保留知识库和来源快照。

## 15. generation 保留

- 活动 generation 永不由自动清理删除。
- 成功切换后保留上一个活动 generation 7 天，且每个知识库最多保留一个上一个活动 generation。
- 失败/放弃的暂存 generation 默认保留 7 天供排查。
- 第一版没有用户可见回滚按钮；保留旧代次仅用于故障恢复和排查。
- 清理任务必须确认 generation 不是活动指针、不是正在构建且已超过保留期。

## 16. 列表和排序

列表字段：名称、可用状态、数据源数、可检索数据源数、活动 chunk 数、Embedding 模型、索引结构、检索类型、绑定机器人数量、最新构建时间、更新时间。

支持名称搜索、状态筛选、Embedding/检索类型筛选。默认按 `updatedAt DESC, id ASC` 稳定排序。

## 17. 验收

- 可以创建多个互不影响的知识库和任意多机器人绑定关系。
- 创建时只能选择解析完成的具体版本，选择不会立即运行任务。
- 最终提交后异步构建，刷新页面可继续查看 operation。
- 重建时旧索引持续服务，新索引成功后原子切换。
- 重建部分失败保留旧活动索引，只重试失败数据源。
- 首次部分成功明确显示 `partial_ready`，失败数据源不参与检索。
- 查询期配置修改不触发重建，构建期配置修改不会直接污染活动索引。
- 知识库删除不删除共享解析数据源，被机器人引用时后端拒绝。
