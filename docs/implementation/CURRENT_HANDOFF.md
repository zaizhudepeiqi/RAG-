# 当前开发交接

> 更新时间：2026-07-26（Asia/Shanghai）
> 用途：会话恢复和阶段状态摘要；需求定义以 `docs/requirements` 为唯一真源。

## 1. 工作位置

- 仓库根目录：`D:\RAG知识库`
- Phase 03 worktree：`D:\RAG知识库\.worktrees\phase-03-knowledge-retrieval`
- Phase 03 分支：`codex/phase-03-knowledge-retrieval`
- Phase 03 入口提交：`f146a62 docs: hand off knowledge base implementation`
- 远端：`https://github.com/zaizhudepeiqi/RAG-.git`
- 不直接在 `main` 或旧 Phase worktree 开发下一阶段。

## 2. 当前状态

当前状态：**IMPLEMENTATION IN PROGRESS (PHASE 3)**。

Phase 01 和 Phase 02 已合并并推送到 `main`。Phase 03 独立分支和 worktree 已创建；Task 01-08 已完成并通过门禁，下一项是 Embedding 与 Chroma Adapter。

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
9. 下一项是 Task 09：Embedding 执行与 Chroma Adapter；随后实现 pg_trgm、generation Worker 和单库检索。
10. 模型配置可复用，但知识库索引、chunks、generation 和任务必须独立。

## 6. 保持不变的边界

- MinerU 是 Parser，不属于模型配置。
- 上传和解析不会自动创建或修改知识库；用户选择解析版本与完整构建配置后才创建知识库构建任务。
- 模型是全局可复用调用能力，不共享知识库索引、chunks、任务或机器人会话。
- 前端下拉由 capability 和后端 selector 驱动；前端仍显示下拉控件，但选项不散落硬编码。
- Token、signed URL、storage key、绝对路径和原始供应商 payload 不得进入 API、日志、Trace 或 Operation 结果。
- 知识库、检索、机器人、渠道和完整业务页面仍按后续阶段实现，不得用占位实现冒充完成。
- `knowledge_base.generation.requested` 与 `knowledge_base.cleanup.requested` 的 Worker/dispatch 实现在 Task 11/12；当前 Task 04 只保证 Operation/Outbox 原子落库，不应在本分支未完成前用于生产部署。
