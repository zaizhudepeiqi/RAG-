# 分块、索引与检索阶段性真源

> 文档职责：定义知识库构建使用的分块/索引算法和查询期检索/重写/重排流水线。
> 所有下拉选项来自 capability API；第一版标记为可用的选项必须真实实现并通过契约测试。

## 1. 配置归属和流水线

每个知识库独立保存分块、索引和检索配置。机器人不能覆盖单库算法，只负责跨知识库融合和上下文总预算。

单库检索顺序固定为：

```text
standaloneQuery
  -> query rewrite
  -> per-query vector/keyword recall
  -> threshold filtering
  -> multi-query fusion
  -> optional rerank
  -> index-structure context expansion
  -> neighboring context window
  -> deduplication
  -> knowledge-base finalTopK
  -> return ranked contexts with provenance
```

任何阶段失败都必须在结果中区分“降级继续”和“检索失败”，不能统一返回空数组。

## 2. Token 计数

第一版提供统一 `TokenCounter`：

- 对可获得官方 tokenizer 的模型使用其 tokenizer。
- 其他模型使用固定版本的 `tiktoken cl100k_base` 作为系统近似计数器。
- 近似时记录 `tokenCountEstimated=true`。
- 分块、上下文预算、Prompt 和日志使用同一个计数服务。
- chunk 保存 `tokenCount / tokenCounterCode / tokenCounterVersion`。

模型真实输入限制以 Provider 返回/配置的 context window 为最终上限；近似计数必须保留安全余量。

## 3. 索引结构

第一版可用：

- `chunk`。
- `parent_child`。

后续 `qa` 由 capability 返回 `enabled=false`，不能保存。

### 3.1 Chunk

分块策略直接生成检索块。向量和关键词索引均索引该 chunk，最终上下文也使用该 chunk 加可选相邻窗口。

### 3.2 Parent-Child

- Parent 是较大、结构完整的上下文块。
- Child 是较小的召回块。
- 向量和关键词索引只索引 Child。
- 重排优先使用 Child 文本。
- 最终上下文返回对应 Parent，同一 Parent 多个命中 Child 去重。
- Parent 超过机器人上下文预算时，以命中 Child 附近内容做确定性截断，同时保留 Parent/Child 来源映射。
- Child 不能跨 Parent，Parent/Child 都不能跨解析版本。

默认参数：

- `parentChunkSize=1024` tokens，范围 256-4096。
- `childChunkSize=256` tokens，范围 64-1024。
- `childChunkOverlap=32` tokens，范围 0 到 `< childChunkSize`。
- `parentChunkSize >= 2 * childChunkSize`。

## 4. 分块策略

第一版全部实现：

- `token`。
- `paragraph`。
- `heading`。
- `page`。
- `semantic`。

所有参数可编辑，有默认值、范围、单位和跨字段校验；默认值只是预填。

### 4.1 通用规则

- 不跨解析版本或原始数据源合并。
- 保留 headingPath、pageRange、sourceBlockIds、assetIds 和 blockPageMap。
- 空白内容不生成 chunk。
- 标题、表格、公式、图片 OCR 可合并为 `searchableText`，原文和检索文本分开保存。
- 每个 chunk 保存前后相邻 ID，供 contextWindow 使用。
- 分块算法和版本写入 generation 快照。

### 4.2 Token 分块

- `chunkSize` 默认 512，范围 64-4096 tokens。
- `chunkOverlap` 默认 64，范围 0 到 `< chunkSize`，且不超过 chunkSize 的 50%。
- 优先在段落/句子边界截断；没有边界时才按 token 硬切。

### 4.3 段落分块

- `maxChunkSize` 默认 512，范围 64-4096 tokens。
- `minChunkSize` 默认 100，范围 0 到 `< maxChunkSize`。
- `overlapParagraphs` 默认 1，范围 0-5。
- 短段落按顺序聚合到最小大小；单段超长按 token 继续拆分。

### 4.4 标题层级分块

- 标题优先来自标准化 blocks，降级使用 Markdown 标题，再降级为段落策略。
- `maxHeadingLevel` 默认 3，范围 1-6。
- `maxChunkSize` 默认 768，范围 128-4096 tokens。
- `includeHeadingPath=true` 默认开启。
- chunk 保存 `headingSource=parser_blocks/markdown/fallback` 和降级原因。
- 章节超长时在章节内部按段落/token 拆分，不跨章节拼接。

### 4.5 按页分块

- 要求所有输入解析版本 `hasPages=true`；不满足时构建配置校验失败，不自动改成 token 策略。
- `maxChunkSize` 默认 1024，范围 128-4096 tokens。
- `chunkOverlap` 默认 64，范围 0 到 `< maxChunkSize`。
- MinerU 明确识别的跨页段落允许合并并保存 `pageRange`。
- 合并后超出最大大小继续拆分；不能仅为维持单页而破坏明确跨页语义。
- `primaryPageNumber` 使用首个主要命中 block 页码。

### 4.6 语义分块

- 使用当前知识库自己的 Embedding 模型。
- `minChunkSize` 默认 200，范围 64-1024 tokens。
- `maxChunkSize` 默认 800，范围 256-4096 tokens。
- `similarityThreshold` 默认 0.75，范围 0-1。
- `sentenceWindow` 默认 3，范围 1-10。
- 对相邻候选单元生成向量，低于阈值优先形成边界。
- 过小块向后合并，过大块按 token 拆分。
- Embedding 调用失败使对应构建项失败，不静默切换为普通分块。

## 5. 向量索引

第一版：

- Store：Chroma。
- 算法 capability：`hnsw`，第一版唯一可用选项。
- 距离度量：默认 `cosine`；`l2/ip` 仅在锁定的 Chroma 版本和模型能力契约测试通过后由 capability 开放。

高级配置由 Chroma Adapter schema 返回，第一版 UI 至少展示：

- `algorithm=HNSW`，只读/单选。
- `metric=cosine` 默认。
- 构建搜索精度参数使用 Adapter 的固定安全默认值；若具体 Chroma 版本支持并完成验证，可通过 capability schema 开放 M、constructionEf、searchEf，不能在业务代码写死供应商字段名。

配置创建 generation 后不可变。向量 Adapter 统一返回：

- `rawDistance`。
- `metric`。
- `relevanceScore`，规范为 0-1 且越大越相关。
- `scoreTransformVersion`。

不同模型/知识库的 relevanceScore 也不允许用于跨知识库直接比较。

## 6. 关键词索引

第一版使用 PostgreSQL `pg_trgm`，不是无索引的全表 `ILIKE`，也不宣称使用中文分词全文检索。

- 对 `searchableText` 建 `GIN (gin_trgm_ops)` 索引。
- 查询先规范化 Unicode、折叠多余空白，不做大小写敏感匹配。
- 使用 trigram similarity 召回，完整短语、headingPath 命中增加确定性加权。
- 长查询按空白和标点拆分候选 term；中文连续文本保留完整 query，同时生成受限 n-gram。
- 1-2 字极短查询使用受限前缀/包含降级，并设置严格 candidate limit；Trace 标记 `shortQueryFallback=true`。
- 所有分数统一为越大越相关并记录 `keywordScoreVersion`。

第一版关键词质量适合中小规模验证。后续替换 Elasticsearch/OpenSearch 时由 `KeywordStoreAdapter` 承担，不改变上层 DTO。

## 7. 检索类型

### 7.1 向量检索 `vector`

- `vectorTopK` 默认 20，范围 1-200。
- `vectorScoreThreshold` 默认 0.30，范围 0-1。
- 最终按 relevanceScore 倒序和稳定 ID 排序。

### 7.2 关键词检索 `keyword`

- `keywordTopK` 默认 20，范围 1-200。
- `keywordScoreThreshold` 默认 0.10，范围 0-1。
- 最终按规范化 keyword score 倒序和稳定 ID 排序。

### 7.3 混合检索 `hybrid`

两路并行召回，各自先应用本路阈值和 Top K，再融合。

融合策略：

- `rrf`，默认推荐。
- `weighted_score`。

通用：

- `finalTopK` 默认 10，范围 1-100。
- `finalScoreThreshold` 默认 0；RRF 和 Weighted Score 的阈值含义不同，前端按策略显示。

#### RRF

- `rrfK` 默认 60，范围 1-1000。
- `rrfScore = Σ 1 / (rrfK + rank_i)`，rank 从 1 开始。
- 未出现在某一路时该路贡献 0。
- RRF 不比较两路原始分数量纲。

#### Weighted Score

- `vectorWeight` 默认 0.5，`keywordWeight` 默认 0.5，范围 0-10，不能同时为 0。
- 各路候选在本路内部做 min-max 归一化。
- 一路只有一个结果或所有原始分相同时，该路结果归一分均为 1，并在 Trace 标记退化情况。
- 公式按权重和归一：

```text
(vectorNormalized * vectorWeight + keywordNormalized * keywordWeight)
/ (vectorWeight + keywordWeight)
```

Weighted Score 对候选集合敏感，界面明确标记“实验性调参”；默认仍使用 RRF。

## 8. 查询重写

第一版：

- `off`。
- `hyde`（假设性文档）。
- `multi_query`（多查询扩展）。
- `step_back`（回退抽象提问）。

非关闭时必须选择验证通过的 LLM。

参数：

- HyDE：生成 1 个假设文档，并保留原问题共同检索。
- Multi-Query：`queryCount` 默认 3，范围 2-5；保留原问题，结果按 RRF 融合。
- Step-Back：生成 1 个抽象问题，并保留原问题共同检索。
- `rewriteMaxTokens` 默认 256，范围 32-1024。
- temperature 默认 0。

改写输出执行长度、空值和重复检查。重写模型失败时默认降级使用原 query，Trace 记录 `QUERY_REWRITE_DEGRADED`；原 query 仍可正常检索。管理员可在测试页看到改写前后文本。

## 9. 重排序

第一版：

- `off`。
- `rerank_model`。
- `llm_rerank`。

参数：

- `rerankCandidateLimit` 默认 20，范围 2-100。
- `rerankTopK` 默认 10，范围 1 到 candidateLimit。
- `rerankScoreThreshold` 默认 0，按 Adapter 0-1 规范分数。
- LLM 重排 temperature 固定 0，必须输出候选 ID 和排序，不允许自由改写候选文本。

Rerank Model 必须选择 `rerank` 类型，LLM 重排必须选择 `llm` 类型。

重排模型出现超时、限流或可恢复服务错误时，默认降级使用重排前顺序并记录 `RERANK_DEGRADED`；返回结构明确 `rerankApplied=false`。配置/鉴权/响应结构错误属于不可恢复配置错误，本知识库检索失败，不能静默降级掩盖错误。

## 10. 上下文扩展

`contextWindow` 是命中块前后相邻数量：

- 默认 0，范围 0-5。
- 只在同一解析版本和同一 generation 内扩展。
- 不能跨 Parent；Parent-Child 已返回 Parent 时默认不再扩展 Child 相邻块。
- 扩展后按文档顺序稳定排列，重复块去重。
- 扩展内容不获得命中分数，但记录 `expandedFromChunkId`。

单库结果最终仍受机器人总上下文 token 预算约束。

## 11. 去重和稳定排序

- 单知识库同一 chunk ID 必须去重。
- Parent-Child 以 Parent ID 去重，保留所有命中 Child IDs。
- 完全相同来源范围（同 parsedSourceVersionId、sourceBlockIds、文本 hash）可合并来源贡献。
- 只因文本相似但来源不同不能自动合并。
- 所有排序最后增加稳定 ID 作为 tie-breaker，相同输入和索引代次必须得到可复现顺序。

## 12. 命中定义

只有经过全部单库检索阶段并最终返回至少一个可进入机器人候选池的上下文，才算该知识库命中。

正式 ChatRun 的整体 `isHit`：经过跨库融合、去重和机器人 token 截断后，最终进入 Prompt 的知识库上下文数量大于 0。

以下不算命中：

- 初召回有结果但全部被阈值过滤。
- 重排/最终阈值后为空。
- token 预算后没有任何内容进入 Prompt。
- 知识库不可用或检索执行失败。

但“执行失败”必须另记 `retrievalStatus=failed/partial_failed`，不能只用 `isHit=false` 掩盖故障。

第一版不定义低置信度，也不展示低置信度占比。命中不等于正确，命中率不能被称为答案准确率。

## 13. 检索测试

测试页允许临时覆盖所有查询期参数，不保存构建期参数。响应至少包含：

- query 和实际 standaloneQuery。
- knowledgeBaseId、activeGenerationId、retrievalRevisionId。
- 实际临时检索配置。
- rewriteResult 和降级信息。
- 每路候选数量、过滤数量、融合数量和重排数量。
- 每个候选的 raw/normalized/fusion/rerank 分数与 rank。
- 最终上下文预览、来源、页码、block/asset IDs。
- 各阶段耗时、模型调用和 errors/warnings。

操作：

- 测试：只运行，不保存。
- 保存为检索配置：创建查询期修订。
- 恢复当前配置。
- 复制完整 JSON。

测试不写问答日志、不计在线指标；可显式加入质量评测集。

## 14. 性能和错误边界

- 每个知识库检索默认超时 20 秒。
- 向量和关键词召回可以并行；查询改写必须先于依赖改写 query 的召回。
- 候选数量在进入 LLM/Rerank 前必须硬限制，防止成本失控。
- Chroma 不可用 -> `VECTOR_STORE_UNAVAILABLE`。
- PostgreSQL 关键词查询失败 -> `KEYWORD_STORE_UNAVAILABLE`。
- Embedding query 调用失败 -> `QUERY_EMBEDDING_FAILED`。
- 配置引用失效模型 -> `RETRIEVAL_CONFIG_INVALID`。

只有明确允许的重写/重排降级可以继续；核心召回引擎故障不能伪装成空结果。

## 15. 验收

- 五种分块策略和两种索引结构产生可追溯、稳定 chunks。
- 分块参数可编辑且前后端执行同一跨字段校验。
- 向量、关键词和混合检索均真实执行，RRF/Weighted Score 公式可通过固定样例验证。
- 查询重写和两种重排使用类型正确的模型，关闭时显示“无”。
- Rerank 可恢复故障按规则降级，核心检索故障明确失败。
- 同一 query、generation 和配置重复执行结果顺序稳定。
- 检索测试 JSON 足以复算每一步排序和过滤。
- 命中率不包含检索测试，也不混入系统故障。
