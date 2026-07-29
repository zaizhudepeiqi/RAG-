# 当前开发交接

> 更新时间：2026-07-29（Asia/Shanghai）
> 用途：会话恢复和阶段状态摘要；需求定义以 `docs/requirements` 为唯一真源。

## 1. 工作位置

- 仓库根目录：`D:\RAG知识库`
- Phase 03 worktree：`D:\RAG知识库\.worktrees\phase-03-knowledge-retrieval`
- Phase 03 分支：`codex/phase-03-knowledge-retrieval`
- Phase 03 入口提交：`f146a62 docs: hand off knowledge base implementation`
- 远端：`https://github.com/zaizhudepeiqi/RAG-.git`
- 不直接在 `main` 或旧 Phase worktree 开发下一阶段。

## 2. 当前状态

当前状态：**PHASE 03 ACCEPTED / READY FOR PHASE 04 PLANNING**。

Phase 01、Phase 02 和 Phase 03 的实现及验收均已完成。Phase 03 源提交为 `6d2d021`；本次交接完成后合并并推送到 `main`。下一次开发先编写并确认 Phase 04 实施计划，不直接开始机器人代码。

## 3. Phase 02 已交付

### 3.1 模型与 MinerU 设置

1. Provider/model type capability 与固定 Provider Adapter registry。
2. Provider、Model Config、Verification、Discovery 持久化、CRUD、选择守卫和 Operation/Outbox 幂等处理。
3. OpenAI、OpenAI-Compatible、DeepSeek、Qwen 分类型真实 HTTP Adapter 与错误映射。
4. AES-256-GCM Provider 凭据轮换、revision race 防护和最小验证摘要。
5. MinerU 设置单例、Token 加密、云处理确认、严格 ParseConfig 和完整连接测试 Operation。

### 3.2 数据上传与解析

1. parser/input type capability 是输入路由和 ParseConfig schema 的唯一目录。
2. 流式原子上传、扩展名/MIME/签名交叉校验、SHA-256 SourceBlob 去重和引用计数。
3. ZIP 路径穿越、绝对路径、符号链接、加密、嵌套、数量、大小和压缩比限制。
4. 不可变 ParsedSourceVersion、精确配置复用、强制新版本和 Operation/Outbox。
5. builtin_text 对 txt/md/csv/json 的确定性标准化。
6. MinerU Precision signed upload、PUT、batchId/dataId checkpoint、轮询、full ZIP 下载和标准化。
7. Markdown、blocks、assets、artifacts 与 page/bbox/rawLocator 来源查询。
8. timeout/poll/download 失败继续查询原上游任务，不重新提交；重解析始终创建新版本。
9. 数据源/解析版本引用查询、`SOURCE_IN_USE`、软删除和不可取消 cleanup Operation。
10. OpenAPI 与 `frontend/src/services/ragApi` 已同步，前端不维护手写重复 DTO。

Phase 02B 提交序列：

```text
bbd63c0 docs: add phase two parsing plan
778be21 feat: register parser capabilities
716ee6f feat: add source parsing persistence
ca5177a feat: add safe source storage
ecfff2c feat: upload and manage data sources
d13c378 feat: safely expand source archives
88e2309 feat: create reusable parse versions
733e460 feat: parse builtin text sources
408214c feat: add MinerU precision adapter
31175ca feat: execute resumable MinerU parsing
ae8e809 feat: normalize and query parsed content
a0cd8ad feat: recover and clean parsing resources
e7b0c7d chore: generate parsing api client
533993f test: make MinerU archive fixture deterministic
```

## 4. Phase 02 最终验证

2026-07-24 本机验证：

- `scripts/check.ps1` exit 0：Ruff、strict mypy、后端非集成 `230 passed`、前端 Jest `7 suites / 16 tests`、Biome、TypeScript、production build 和 generated API 漂移检查通过。
- Docker PostgreSQL、Redis、Chroma 均为 healthy；完整 PostgreSQL 集成组 `104 passed`。
- 0003 已在开发库升级到 head；空库迁移测试和 `alembic check` 均通过，无新 upgrade operation。
- ZIP/上传/解析内容/Provider/MinerU 安全专项 `35 passed`；OpenAPI 和 generated client 未发现 storage key、signed/upload URL 或密钥材料字段；仓库密钥扫描通过。
- `pip-audit 2.10.1` 无未豁免漏洞，保留到 2026-08-31 的 `PYSEC-2026-311` 例外。
- `npm audit --omit=dev --audit-level=high` 通过，生产依赖仅报告 1 项 moderate `dompurify` 上游问题。完整开发工具链报告仍受 `docs/security/frontend-toolchain-audit-exception.md` 的 2026-08-31 到期门禁约束。
- MinerU ZIP fixture 曾因 ZIP 条目时间戳造成一次二进制比较不稳定；已改为单次生成并复用，同一目标测试连续 3 次和完整集成组均通过。

## 5. Phase 3 当前执行顺序

1. Task 01-03 已完成：capability、0004 迁移/ORM、领域配置和状态机。
2. Task 04 已完成：知识库创建事务、幂等、列表/详情、元数据、启用/停用、删除守卫与 OpenAPI/generated client。
3. Task 05 已完成：pending build/retrieval revision、显式 generation 创建、列表/详情、重试请求和 discard。
4. Task 06 已完成：锁定 tiktoken、统一计数快照、Unicode/空白规范化、来源映射、确定性 ID 和相邻链。
5. Task 07 已完成：Token、段落、标题、按页和语义五种分块策略；覆盖硬上限、重叠、标题降级、页边界、Semantic 小块合并、Embedding 响应校验、来源和稳定 ID。
6. Task 07 门禁：Ruff、strict mypy 通过；后端非集成 `291 passed`；分块单元测试 `26 passed`；知识库集成 API `6 passed`。
7. Task 08 已完成：Chunk 与 Parent-Child 领域组装；明确全部块、可索引块和上下文块，Child 不跨 Parent，只映射实际相交来源，ID 和相邻链稳定。
8. Task 08 门禁：Ruff、格式和 strict mypy 通过；后端非集成 `298 passed`；分块/索引结构专项 `33 passed`；知识库集成 API `6 passed`。
9. Task 09 已完成：批量 document/query Embedding 契约与响应校验；Chroma cosine HNSW collection、白名单 metadata、幂等 upsert、查询、item copy、validate/delete 和 0-1 relevance score。
10. Task 09 门禁：Ruff、格式和 strict mypy 通过；后端非集成 `313 passed`；模型/向量专项 `60 passed`；知识库 API 加真实 Chroma 合约 `7 passed`。
11. Task 10 已完成：PostgreSQL `pg_trgm` KeywordStoreAdapter；包括 Unicode 查询规范化、受限 term/中文 n-gram、短查询 fallback、generation 强过滤、候选硬限制、短语/标题加权和稳定排序。
12. Task 10 门禁：Ruff、格式和 strict mypy 通过；后端非集成 `320 passed`；知识库 API、真实 Chroma 与真实 pg_trgm 组合集成 `9 passed`；EXPLAIN 证明 generation 索引约束且 trigram GIN 可用。
13. Task 11 已完成：generation Worker 按 item 执行分块、Embedding、关键词、向量和校验 checkpoint；Celery 已接通 `knowledge_base.generation.requested`；失败 item 清理 PostgreSQL chunks/来源/资产和 Chroma records。
14. 激活事务同时切换 active generation/retrieval revision、清 pending 指针、冻结新代次并为旧代次设置 7 天保留；首次 partial 可激活，已有活动代次的 partial/no-success 重建继续服务旧索引，迟到 Worker 和激活冲突不能覆盖新指针。
15. Task 11 门禁：`scripts/check.ps1` 通过；Ruff、格式和 strict mypy（`140 source files`）通过；后端非集成 `321 passed`；前端 Jest `7 suites / 16 tests`、TypeScript、Biome、production build 和 generated API 漂移通过；Task 11、真实 Chroma、pg_trgm 和 Celery/Redis 组合 `12 passed`。
16. 仓库凭据扫描已精确区分 `tiktoken`/代码能力键 `token` 与 `api_token`、`access_token` 等凭据字段，并内置分类器回归契约；整体凭据扫描范围未放宽。
17. 下一项是 Task 12：失败项重试和 repair generation；不得提前混入单库检索。
18. Task 12 已完成：暂存 `failed/partial_failed` generation 只将失败 item 重新排队；活动 `partial_ready` 创建继任 repair generation，成功 item 通过 `source_copy_from_item_id` 复制，失败 item 才重新分块/Embedding。
19. Repair 的数据库 chunks 使用目标 generation 的确定性新 ID；Chroma 复制支持 source/target chunk ID 与 parent ID 映射，避免旧 generation 数据跨代复用；旧代次保持 frozen。
20. Task 12 门禁：完整 `scripts/check.ps1` 通过；strict mypy `142 source files`；后端非集成 `321 passed`；真实 PostgreSQL/Chroma/pg_trgm/Celery 组合 `14 passed`；前端 Jest `7 suites / 16 tests`、TypeScript、Biome、production build 和 generated API 漂移通过。
21. Task 13 已完成：新增统一 `RetrievalCandidate` 和单库 `SingleKnowledgeBaseRetriever`，支持 vector、keyword、hybrid 三种召回；各路先执行 Top K/threshold，hybrid 支持可复算 RRF 与 Weighted Score，稳定 ID 排序，核心故障返回明确错误码。
22. Task 13 门禁：strict mypy `144 source files`；融合/引擎单测 `8 passed`；此前真实 PostgreSQL/Chroma/pg_trgm/Celery 组合 `14 passed`；前端和 OpenAPI 门禁在 Task 12 后保持通过。
23. Task 14 已完成：新增 query rewrite 服务，支持 `off/hyde/multi_query/step_back`；原 query 始终保留，输出限长/去重，模型可恢复错误降级为原 query 并记录 `QUERY_REWRITE_DEGRADED`，不可恢复错误返回 `QUERY_REWRITE_FAILED`。
24. Task 14 门禁：strict mypy `145 source files`；检索引擎/融合/query rewrite 单测 `14 passed`；此前完整工程门禁和真实依赖组合保持通过。
25. Task 15 已完成：新增 rerank adapter/service，支持 `off`、`rerank_model`、`llm_rerank`，候选硬限制、topK/threshold、0-1 响应校验、稳定排序；可恢复模型故障返回 `RERANK_DEGRADED` 并保留原顺序，不可恢复配置/响应错误返回检索失败。
26. Task 15 已完成 Parent/Child 上下文扩展、contextWindow 相邻块加载、generation/解析版本/Parent 守卫、Parent 去重和命中 Child 合并；新增 SQLAlchemy ContextStore，仅加载目标 generation 的候选/Parent/有限邻居。
27. Task 15 门禁：检索专项 `36 passed`；后端非集成 `341 passed, 135 deselected`；Ruff、格式和 strict mypy 通过。完整 API/集成测试需要配置 `RAG_TEST_DATABASE_URL`。
28. Task 16 已完成：`POST /api/v1/knowledge-bases/{knowledgeBaseId}/retrieval-tests` 使用活动 generation/retrieval revision 快照，允许临时完整查询期配置覆盖；不写 ChatRun、Operation、Outbox 或任何配置修订。返回实际配置、rewrite、逐候选分数/rank、contexts、block/asset/page 来源和 warning。
29. Task 16 已完成：多查询先独立召回并以 RRF 融合，之后只执行一次 rerank/context expansion；原单 query 检索 API 保持兼容。运行时已接通全局模型配置的 Embedding、LLM rewrite/LLM rerank 和 Rerank model，Provider 响应结构与鉴权错误不伪装为 no-hit。
30. Task 17 已完成：OpenAPI、新生成前端 service 与 operationId 契约同步；新增 API 集成测试验证活动代次读取和不新增 Operation。
31. 本轮验证：检索单元 `39 passed`；知识库 API 集成 `7 passed`；完整 PostgreSQL 集成 `136 passed`；后端非集成 `344 passed`；前端 `npm run check`（Biome、TypeScript、Jest `7 suites / 16 tests`、build）通过；strict mypy `152 source files` 通过。
32. Task 18 已完成：`scripts/check.ps1` 从干净提交完整通过；Ruff、strict mypy `152 source files`、后端非集成 `344 passed`、前端 Jest `7 suites / 16 tests`、Biome、TypeScript、production build 和 generated API 零漂移全部通过。
33. 真实 PostgreSQL、Redis、Chroma 组合集成 `136 passed`；Alembic 已升级到 `0004_knowledge_retrieval` 且 `alembic check` 无新增操作。
34. 后端生产依赖审计无已知漏洞，保留既有 `PYSEC-2026-311` 临时例外；前端生产依赖按 high 门槛通过，保留既有 1 项 `dompurify` moderate 上游问题。
35. 后续入口：先为 Phase 04（机器人、多知识库融合、会话记忆、回答生成与引用）编写独立实施计划并确认边界；渠道和前端业务页面仍属于后续阶段，不得提前混入。
36. 模型配置可复用，但知识库索引、chunks、generation 和任务必须独立。

## 6. 保持不变的边界

- MinerU 是 Parser，不属于模型配置。
- 上传和解析不会自动创建或修改知识库；用户选择解析版本与完整构建配置后才创建知识库构建任务。
- 模型是全局可复用调用能力，不共享知识库索引、chunks、任务或机器人会话。
- 前端下拉由 capability 和后端 selector 驱动；前端仍显示下拉控件，但选项不散落硬编码。
- Token、signed URL、storage key、绝对路径和原始供应商 payload 不得进入 API、日志、Trace 或 Operation 结果。
- 知识库、检索、机器人、渠道和完整业务页面仍按后续阶段实现，不得用占位实现冒充完成。
- `knowledge_base.generation.requested` 与 `knowledge_base.cleanup.requested` 的 Worker/dispatch 实现在 Task 11/12；当前 Task 04 只保证 Operation/Outbox 原子落库，不应在本分支未完成前用于生产部署。
