# Phase 03：知识库构建与检索实施计划

> 状态：执行中。需求语义以 `docs/requirements/` 为唯一真源；本文件只定义实现顺序、测试和提交边界。

## 1. 目标与退出条件

本阶段交付从“选择已解析版本”到“可追溯单知识库检索”的完整闭环。完成后系统必须支持多个互相隔离的知识库、不可变构建/检索配置修订、五种分块、两种索引结构、Chroma HNSW cosine、PostgreSQL `pg_trgm`、三种检索、两种混合融合、四种查询重写状态、三种重排状态、构建代次原子激活以及不写入 ChatRun 的检索测试。

退出门禁：

- 需求验收 `docs/acceptance/v1-acceptance.md` 第 6、7、8 节全部有自动化证据。
- 所有新 API、DTO、错误码、表和状态转换与对应契约一致。
- 首次全成功、首次部分成功、首次全失败、已有活动代次重建失败、失败项重试、活动 partial 修复和迟到 Worker 均有集成测试。
- Chroma distance 转 relevance score 可复算，关键词查询计划使用 `chunks_searchable_trgm_idx`。
- 检索响应包含 generation、revision、chunk、解析版本、block、asset、页码和各阶段分数/耗时。
- Ruff、strict mypy、非集成/集成 pytest、OpenAPI 漂移、前端生成客户端、TypeScript、Biome、Jest 和 production build 全部通过。

## 2. 不在本阶段实现

- 不实现机器人、多知识库融合、会话记忆、回答生成和引用裁剪；这些属于 Phase 04。
- 不实现微信、飞书、钉钉、企业微信或 Webhook 渠道；这些属于 Phase 05。
- 不实现完整知识库管理页面；本阶段只保证 API 和 generated client，页面属于 Phase 06。
- 不把检索测试写入 ChatRun、在线命中率或正式评测指标。
- 不开放未经 Chroma 契约测试验证的 `l2/ip`、Elasticsearch/OpenSearch 或 QA 索引结构。

## 3. 固定实现边界

### 3.1 模块和端口

- `app/modules/knowledge_bases`：聚合、配置修订、generation 状态机、API 和业务服务。
- `app/modules/chunking`：TokenCounter、标准化输入、五种 Strategy、Parent-Child 组装和来源映射。
- `app/modules/retrieval`：单库流水线、融合、重写、重排、上下文扩展和测试 DTO。
- `app/infrastructure/vector`：Chroma collection 生命周期、批量 upsert/query/copy/delete。
- `app/infrastructure/keyword`：PostgreSQL `pg_trgm` 候选查询和分数规范化。
- `app/infrastructure/embeddings`：复用已验证模型配置执行 embedding，业务层不直接判断 Provider 字符串。
- `app/infrastructure/reranking`：Rerank/LLM Adapter 端口实现，候选 ID 契约固定。

领域层不得导入 FastAPI、SQLAlchemy、Chroma 或具体 Provider SDK。外部网络/存储调用不得持有数据库事务。

### 3.2 确定性和快照

- config hash 对 canonical JSON 做 SHA-256，列表中数据源顺序保留，其余对象键排序。
- chunk UUID 由 generation ID、解析版本 ID、chunk kind、order index 和算法版本确定。
- collection 名和 keyword namespace 只使用内部 ID，不包含用户名称。
- generation 一旦激活即冻结；所有查询开始时冻结 active generation/retrieval revision 快照。
- 模型身份、维度、token counter、capability code/version 和 Adapter score version写入不可变修订或结果。

## 4. 任务与提交顺序

每个任务严格执行：先写失败测试，再写最小实现，运行目标测试和静态检查，最后独立提交。后续任务不能用临时占位结果绕过当前任务验收。

### Task 01：注册知识库与检索 capability

文件范围：

- `backend/app/modules/capabilities/registry.py`
- `backend/tests/unit/capabilities/test_knowledge_retrieval_capabilities.py`
- `backend/tests/api/test_capabilities_api.py`

实现：

- `index_structure`：`chunk`、`parent_child`；`qa` 可见但 disabled。
- `chunk_strategy`：`token`、`paragraph`、`heading`、`page`、`semantic`，携带完整 JSON Schema、UI schema、required/preferred source features。
- `vector_store`：`chroma`；`vector_index`：`hnsw` + cosine。
- `keyword_store`：`postgres_trigram`。
- `retrieval_type`：`vector`、`keyword`、`hybrid`。
- `fusion_strategy`：`rrf`、`weighted_score`。
- `query_rewrite`：`off`、`hyde`、`multi_query`、`step_back`。
- `rerank`：`off`、`rerank_model`、`llm_rerank`。

验证：schema 默认值/范围/跨字段元数据存在，disabled 项不能作为可保存能力，API 返回结构可供前端动态表单使用。

### Task 02：0004 迁移和 ORM 映射

文件范围：

- `backend/migrations/versions/0004_knowledge_retrieval.py`
- `backend/app/infrastructure/database/models/knowledge_bases.py`
- `backend/app/infrastructure/database/base.py`
- `backend/tests/integration/database/test_knowledge_retrieval_schema.py`
- `backend/tests/integration/database/test_migrations.py`

实现 `knowledge_bases`、`kb_build_config_revisions`、`kb_build_config_sources`、`kb_retrieval_revisions`、`index_generations`、`index_generation_items`、`chunks`、`chunk_source_blocks`、`chunk_assets`，包括延迟 FK、部分唯一索引、GIN trigram、JSON 类型 CHECK、枚举 CHECK、计数非负约束和 frozen generation 写保护触发器。

验证：空库 upgrade、重复 upgrade、downgrade/upgrade、约束负例、活动指针 FK 和 frozen 写保护。

### Task 03：领域配置、状态机和校验

文件范围：

- `backend/app/modules/knowledge_bases/domain.py`
- `backend/app/modules/knowledge_bases/validation.py`
- `backend/app/modules/knowledge_bases/errors.py`
- `backend/tests/unit/knowledge_bases/`

实现：

- BuildConfig、RetrievalConfig、source snapshot 和 canonical hash。
- 数值范围及跨字段校验：overlap、parent/child、权重、Top K、阈值、模型类型。
- ParsedSourceVersion feature compatibility，`page` 硬拒绝、`heading` fallback warning。
- IndexGeneration/Item 合法转换、知识库展示状态和 allowed actions。
- 仅允许 `succeeded/degraded` 且 `hasText=true` 的具体解析版本。

### Task 04：知识库持久化与创建事务

文件范围：

- `backend/app/modules/knowledge_bases/ports.py`
- `backend/app/modules/knowledge_bases/repository.py`
- `backend/app/modules/knowledge_bases/service.py`
- `backend/app/modules/knowledge_bases/schemas.py`
- `backend/app/modules/knowledge_bases/api.py`
- API/集成测试

实现创建、列表、详情、元数据更新、启用/停用、引用保护删除。创建必须在同一事务写 KB、初始 build/retrieval revision、source bindings、generation、items、Operation 和 Outbox。请求幂等、名称唯一和 expectedRevision 冲突沿用现有统一机制。

### Task 05：pending 配置和 generation 管理 API

实现 build config 读取/保存/放弃、retrieval revision 自动激活或 pending、generation 创建/列表/详情/放弃/失败项重试。相同 build config hash 复用 revision；同 KB 只允许一个活动构建。返回后端派生展示状态，前端不推断任务文本。

### Task 06：TokenCounter 与规范化分块输入

新增锁定版本的 tokenizer 依赖并更新 `uv.lock`。实现统一 token 计数、句子/段落边界、Unicode/空白规范化、parsed block/asset/page/bbox 映射、确定性 ID 和相邻链。近似计数记录 `tokenCountEstimated`，不跨解析版本。

### Task 07：五种分块 Strategy

逐个提交或在同一任务内保持独立测试组：

- Token：边界优先、硬切 fallback、可编辑 size/overlap。
- Paragraph：短段聚合、超长段 token 拆分、段落 overlap。
- Heading：parser heading、Markdown heading、paragraph fallback 和 warning。
- Page：页能力硬守卫、跨页段落、pageRange/primaryPage。
- Semantic：使用本 KB Embedding 模型、句窗相似度切分，调用失败使 item 失败。

每种策略使用固定输入输出 fixture，验证文本、token、来源、页、资产和稳定 ID。

### Task 08：Chunk 与 Parent-Child 索引结构

实现 Strategy 输出到索引块的组装。Parent-Child 只索引 child，parent 保留完整上下文；child 不跨 parent，parent/child 都不跨解析版本。验证 parent 大小约束、child overlap、去重和来源并集。

### Task 09：Embedding 执行与 Chroma Adapter

扩展模型调用端口以支持批量 document/query embedding，验证维度和响应数量。Chroma 每 generation 一个 collection，锁定 cosine HNSW，metadata 使用契约白名单。实现幂等 upsert、查询、item copy、collection validate/delete；测试 raw cosine distance 到 0-1 relevance score 和 collection 隔离。

### Task 10：PostgreSQL `pg_trgm` KeywordStoreAdapter

实现查询规范化、term/n-gram、极短查询受限 fallback、完整短语/heading 确定性加权、generation 强制过滤、候选硬限制和稳定排序。集成测试执行 `EXPLAIN` 并断言使用 GIN 索引，禁止退化为跨 generation 全表扫描。

### Task 11：generation Worker、checkpoint 和原子激活

实现 `validate_snapshot -> prepare -> chunk -> embed -> keyword -> vector -> validate -> activate/hold -> cleanup`。每 item 独立 checkpoint，Celery 重复投递幂等。Chroma 在事务外暂存；激活事务锁 KB 并同时切 generation/retrieval revision、清 pending、冻结 generation、设置旧代次 retainUntil。

覆盖首次 full/partial/no-success、重建 full/partial/no-success、迟到 Worker、validation conflict 和旧索引持续服务。

### Task 12：失败项重试和 repair generation

暂存 `partial_failed` 在原 generation 只恢复失败 item；活动 `partial_ready` 创建继任 repair generation，复制成功 chunks/关键词/向量且不重复调用 Embedding。放弃和清理必须保护活动及保留代次。

### Task 13：vector、keyword、hybrid 召回与融合

实现单库 RetrievalEngine 和候选统一结构。向量/关键词应用各自 threshold/Top K；hybrid 并行两路并实现可复算 RRF 与 Weighted Score。覆盖 rank 从 1、单候选/同分归一、权重和归一、稳定 ID tie-breaker。

### Task 14：查询重写

实现 off、HyDE、Multi-Query、Step-Back。非 off 强制验证通过的 LLM；输出做长度、空值和去重检查。Multi-Query 保留原 query 并用 RRF 聚合。超时/限流等可恢复失败降级原 query 并返回 `QUERY_REWRITE_DEGRADED`，配置错误明确失败。

### Task 15：重排、上下文扩展和最终结果

实现 rerank model、LLM rerank、候选硬限制和模型类型校验。可恢复错误退回原顺序，不可恢复配置错误使单库失败。实现 Parent 扩展、邻居 contextWindow、provenance 精确去重、最终 threshold/Top K 和稳定排序。

### Task 16：检索测试 API

实现 `POST /knowledge-bases/{id}/retrieval-tests`，支持查询期临时参数覆盖但不保存。响应包含实际配置、改写、候选统计、逐阶段 score/rank、上下文预览、完整 provenance、模型调用摘要、耗时、warnings/errors。确认不创建 ChatRun、不增加在线指标。

### Task 17：OpenAPI、generated client 和前端契约测试

补全 operationId、中文 tag、错误响应和所有 DTO；导出 OpenAPI 并运行 Umi 生成。前端只消费 generated service，不新增手写重复接口。新增生成漂移和敏感字段扫描，确保无 token、storageKey、signed URL、绝对路径或供应商原始 payload。

### Task 18：全量回归和阶段交接

执行：

```powershell
pwsh scripts/check.ps1
pwsh scripts/test-integration.ps1
uv run --project backend alembic -c backend/alembic.ini check
uv run --project backend pip-audit
npm --prefix frontend audit --omit=dev --audit-level=high
```

另执行 Chroma 真实契约测试、pg_trgm explain 测试、Celery/Redis 重复投递测试和密钥扫描。更新路线图、交接文档和验收证据后再合并 Phase 03。

## 5. 实施时必须保持的故障语义

- 核心向量、关键词或 query embedding 故障返回明确失败，不可伪装成无命中。
- 只有 query rewrite 和 rerank 中契约明确的可恢复错误可以降级继续，并必须返回 warning。
- 首次 partial 可以激活；已有活动 generation 的 partial rebuild 不得激活。
- retrieval test 的空结果、正常无命中和执行失败必须可区分。
- 任何活动 generation、frozen 数据或较新活动指针都不能被重试、迟到 Worker 或清理任务覆盖。

## 6. 进度

- [x] Task 01：Capability
- [x] Task 02：0004 迁移和 ORM
- [x] Task 03：领域配置、状态机和校验
- [x] Task 04：知识库创建、查询和生命周期
- [x] Task 05：配置修订和 generation API
- [x] Task 06：TokenCounter 和输入规范化
- [x] Task 07：五种分块
- [x] Task 08：两种索引结构
- [x] Task 09：Embedding 与 Chroma
- [x] Task 10：pg_trgm
- [x] Task 11：构建 Worker 和激活
- [x] Task 12：重试和 repair
- [x] Task 13：三种检索与融合
- [x] Task 14：查询重写
- [x] Task 15：重排和上下文扩展
- [ ] Task 16：检索测试 API
- [ ] Task 17：OpenAPI/generated client
- [ ] Task 18：全量门禁和交接

### Task 15 交付证据

- `backend/app/modules/retrieval/reranking.py` 固定 `off`、`rerank_model`、`llm_rerank` 的 adapter 契约，执行 candidateLimit 硬限制、topK/scoreThreshold 校验、0-1 分数校验、稳定 ID 排序和可恢复错误 `RERANK_DEGRADED` 降级。
- `backend/app/modules/retrieval/context.py` 实现 Chunk/Parent-Child 上下文扩展、同 generation/解析版本/Parent 守卫、Parent 去重、命中 Child 合并和稳定文档顺序。
- `backend/app/infrastructure/database/retrieval_context.py` 提供 SQLAlchemy 上下文加载器，只加载目标 generation 的候选、Parent 和有限邻居。
- `SingleKnowledgeBaseRetriever` 在重排启用时提升召回请求上限，完成重排后再执行知识库 finalTopK，并返回 rerank 状态、warning 和 contexts。
- 验证：检索专项 `36 passed`；后端非集成 `341 passed, 135 deselected`；Ruff、格式检查和 strict mypy 通过。需要 PostgreSQL 的 API/集成组需按 `scripts/check.ps1` 或 `scripts/test-integration.ps1` 提供 `RAG_TEST_DATABASE_URL` 后运行。
