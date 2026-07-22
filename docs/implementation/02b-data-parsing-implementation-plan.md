# 第二阶段 B：数据上传与解析 Implementation Plan

> **For agentic workers:** 按任务执行 RED -> GREEN -> refactor。每个任务独立提交；需求语义以 `docs/requirements/03-data-parsing-source.md` 为真源。

**Goal:** 在 Phase 02A 的模型与 MinerU 设置基础上，交付安全上传、SourceBlob 去重、ZIP 展开、不可变 ParsedSourceVersion、builtin_text、真实 MinerU Precision Adapter、标准化产物和可恢复异步解析闭环。

**Architecture:** parsing 模块拥有 DataSource、ParsedSourceVersion、Parser registry 和状态机；StorageAdapter 只处理逻辑 storage key 与原子文件操作；MinerU 协议只存在于 infrastructure adapter。PostgreSQL 是状态和元数据真源，文件系统保存 blob/原始归档/标准化产物。API 事务只创建或转换业务状态、Operation 和 Outbox，不持有事务等待文件上传或外部网络。

**Tech Stack:** FastAPI、Pydantic、SQLAlchemy、Alembic、PostgreSQL、Celery、httpx、标准库 `zipfile/csv/json/html.parser/xml.etree`、pytest/respx、Umi OpenAPI generator。

---

## 0. 执行边界与成功标准

本计划实现：

1. parser/input type capability。
2. 流式上传、类型交叉校验、SourceBlob 去重和安全下载。
3. ZIP 路径/压缩炸弹/加密/嵌套/entry 限制与独立 DataSource 展开。
4. ParsedSourceVersion 创建、复用、强制新版本、状态机与 Operation/Outbox。
5. builtin_text 对 txt/md/csv/json 的确定性标准化。
6. MinerU signed upload、批次查询、下载 full_zip 和标准化 Adapter。
7. 解析详情、Markdown、blocks、assets、artifacts、恢复查询和异步删除。
8. MinerU 设置真实完整连接测试；不创建独立伪 ping。
9. OpenAPI、generated TypeScript client、迁移和安全回归。

本计划不实现：

- 知识库、chunk、Embedding、Chroma 索引或机器人。
- 解析内容在线编辑。
- MinerU 本地版、MCP、callback 或供应商删除能力。
- 管理后台完整解析页面；阶段 6 使用本阶段 API。
- 音频、视频、网页抓取、数据库连接器或对象存储。

成功标准：

- 上传不把完整文件读入内存；失败临时文件被删除。
- 用户文件名不参与物理 storage key；下载不泄露绝对路径。
- 扩展名、声明 MIME 和文件签名/容器结构交叉验证。
- ZIP 所有安全上限均由后端强制，危险 archive 不产生 DataSource。
- 相同 SHA-256 只保存一个 SourceBlob，referenceCount 在同一事务正确更新。
- 相同 source/parser/config 可复用，force_new 产生新版本且 MinerU `no_cache=true`。
- 重复 Worker delivery 不重复提交 MinerU；恢复下载/标准化不重新提交。
- succeeded/degraded 内容冻结且可选，failed/cancelled 不可选。
- Token、完整 signed URL、物理路径和原始供应商 payload 不进入响应、日志或 Trace。
- 空库迁移、根门禁、全部集成、OpenAPI 二次生成和依赖审计通过。

## 1. 文件结构锁定

```text
backend/app/
  infrastructure/database/models/parsing.py
  infrastructure/database/repositories/parsing.py
  infrastructure/parsers/
    __init__.py
    builtin_text.py
    mineru_precision.py
    registry.py
  infrastructure/storage/local.py
  modules/capabilities/registry.py
  modules/parsing/
    api.py
    domain.py
    normalization.py
    ports.py
    repository.py
    schemas.py
    service.py
    tasks.py
    validation.py
    settings_*.py
backend/migrations/versions/0003_source_parsing.py
backend/tests/
  api/test_data_sources_api.py
  api/test_parsed_source_versions_api.py
  integration/parsing/
  unit/parsing/
docs/api/openapi.json
frontend/src/services/ragApi/
```

模块约束：

- API 只做 DTO、鉴权、CSRF、事务边界和 service 调用。
- service 不导入 `httpx`、ORM 或绝对文件路径。
- Parser Adapter 不接收数据库密文，只接收已解密 Token 和逻辑 storage handle。
- Worker 的外部网络调用不在数据库事务内执行。
- 标准化结果写临时 key，数据库事务成功后才成为可见版本产物。
- Parser 原始响应只保存脱敏定位字段，不保存完整 payload。

## 2. 全阶段命令

所有命令在 `D:\RAG知识库\.worktrees\phase-02-models-parsing` 执行：

```powershell
uv run --project backend pytest backend/tests/unit/parsing -v
uv run --project backend pytest backend/tests/api/test_data_sources_api.py -v
uv run --project backend pytest backend/tests/api/test_parsed_source_versions_api.py -v
uv run --project backend ruff format --check backend/app backend/tests
uv run --project backend ruff check backend/app backend/tests
uv run --project backend mypy backend/app

. ./deploy/scripts/import-env.ps1 -Path deploy/env/.env.development
$env:RAG_TEST_DATABASE_URL = $env:DATABASE_URL -replace '/rag_kb$', '/rag_kb_test'
uv run --project backend alembic -c backend/alembic.ini upgrade head
uv run --project backend pytest backend/tests -m integration -v

uv run --project backend python backend/scripts/export_openapi.py
npm --prefix frontend run generate:api
pwsh -NoProfile -File scripts/check.ps1
```

### Task 1: 登记 02B 计划和入口状态

**Files:**
- Create: `docs/implementation/02b-data-parsing-implementation-plan.md`
- Modify: `docs/implementation/README.md`
- Modify: `docs/implementation/CURRENT_HANDOFF.md`

1. 将路线图的 02B 占位改为本计划链接。
2. 交接下一步改为 Task 2 parser/input capability。
3. 运行 `scripts/check-docs.ps1` 和 `git diff --check`。
4. 提交：`docs: add phase two parsing plan`。

### Task 2: 注册 Parser 和输入类型 capability

**Files:**
- Modify: `backend/app/modules/capabilities/registry.py`
- Test: `backend/tests/unit/capabilities/test_registry.py`

1. RED：断言启用 `mineru_precision_api`、`builtin_text` 和全部第一版输入扩展；ZIP 只标记 container，不属于 Parser 输入。
2. capability schema 声明 parser version、支持扩展、默认路由、ParseConfig JSON Schema 和参数适用性。
3. HTML 固定 MinerU + `MinerU-HTML`；txt/md/csv/json 固定 builtin；其他支持类型固定 MinerU。
4. GREEN：运行 capability 单元/API 测试。
5. 提交：`feat: register parser capabilities`。

### Task 3: 创建 source/parsing 迁移和 ORM

**Files:**
- Create: `backend/migrations/versions/0003_source_parsing.py`
- Create: `backend/app/infrastructure/database/models/parsing.py`
- Modify: `backend/app/infrastructure/database/models/__init__.py`
- Modify: `docs/database/schema.md` only if implementation requires a clarified constraint
- Test: `backend/tests/integration/database/test_parsing_schema.py`
- Modify: `backend/tests/integration/database/test_migrations.py`

1. RED：表不存在、非法状态/quality/revision/count/hash/featureFlags 被 PostgreSQL 拒绝。
2. 创建 `source_blobs`、`data_sources`、`parsed_source_versions`、`parsed_blocks`、`parsed_assets`、`parsed_block_assets`、`parsed_artifacts`。
3. 使用 text + CHECK、JSONB、FK RESTRICT、部分索引和复用索引；不创建知识库表或假引用。
4. 验证空库 upgrade、downgrade/upgrade 和 `alembic check`。
5. 提交：`feat: add source parsing persistence`。

### Task 4: 建立原子 Storage 和文件类型安全边界

**Files:**
- Modify: `backend/app/infrastructure/storage/local.py`
- Create: `backend/app/modules/parsing/validation.py`
- Create: `backend/app/modules/parsing/ports.py`
- Test: `backend/tests/unit/parsing/test_storage.py`
- Test: `backend/tests/unit/parsing/test_file_validation.py`

1. RED：流式写入计算 SHA-256/size，超限或异常删除 `.uploading`，最终 `os.replace` 原子可见。
2. 逻辑 key 固定由内容 hash/UUID 生成，拒绝 `..`、绝对路径、盘符和 root escape。
3. RED：覆盖 PDF、图片、OOXML、OLE Office、HTML、txt/md/csv/json 的扩展/MIME/signature 交叉校验和伪造反例。
4. 不引入平台相关 libmagic；容器格式使用 `zipfile` + XML/entry 结构验证。
5. 提交：`feat: add safe source storage`。

### Task 5: 实现普通文件上传和 DataSource 查询

**Files:**
- Create: `backend/app/modules/parsing/domain.py`
- Create: `backend/app/modules/parsing/repository.py`
- Create: `backend/app/modules/parsing/schemas.py`
- Create: `backend/app/modules/parsing/service.py`
- Create: `backend/app/modules/parsing/api.py`
- Create: `backend/app/infrastructure/database/repositories/parsing.py`
- Modify: `backend/app/bootstrap/dependencies.py`
- Modify: `backend/app/bootstrap/application.py`
- Test: `backend/tests/api/test_data_sources_api.py`
- Test: `backend/tests/integration/parsing/test_source_repository.py`

1. RED：multipart 最多 20 个、200 MB、空文件、部分成功、全部无效 422、请求超限 413。
2. 保存 SourceBlob + DataSource + audit；相同 SHA 复用 blob，`reuse/create_alias` 语义和 referenceCount 正确。
3. 实现 list/get/rename/original download；读需认证，写需 CSRF，下载使用安全 Content-Type/Disposition。
4. 响应不暴露 storageKey/绝对路径；列表分页/筛选/排序固定。
5. 提交：`feat: upload and manage data sources`。

### Task 6: 实现安全 ZIP 展开

**Files:**
- Create: `backend/app/modules/parsing/archive.py`
- Modify: `backend/app/modules/parsing/service.py`
- Test: `backend/tests/unit/parsing/test_zip_safety.py`
- Test: `backend/tests/integration/parsing/test_zip_upload.py`

1. RED：拒绝 `../`、绝对路径、盘符、symlink/device、加密、嵌套 ZIP、超过 100 entries、1 GB、200 MB entry、100:1 和 1024 path。
2. archive 在创建任何 DataSource 前完成目录级安全预检。
3. 合法 entry 独立流式落盘、校验、去重并保留 POSIX 相对 sourcePath；用户路径不参与物理 key。
4. ZIP 本身不创建 DataSource；entry 仍采用部分成功类型语义。
5. 提交：`feat: safely expand source archives`。

### Task 7: 实现 ParseConfig 规范化、版本创建和复用

**Files:**
- Modify: `backend/app/modules/parsing/domain.py`
- Modify: `backend/app/modules/parsing/repository.py`
- Modify: `backend/app/modules/parsing/schemas.py`
- Modify: `backend/app/modules/parsing/service.py`
- Modify: `backend/app/modules/parsing/api.py`
- Test: `backend/tests/unit/parsing/test_parse_config.py`
- Test: `backend/tests/api/test_parsed_source_versions_api.py`
- Test: `backend/tests/integration/parsing/test_parse_operation.py`

1. RED：后端按输入类型最终路由，移除不适用 UI 参数，规范 JSON + parser/normalizer version 产生稳定 configHash。
2. `POST /data-sources/{id}/parse` 同事务创建 ParsedSourceVersion、Operation、Outbox；business key 含 source/config/parser/intent。
3. `reuse_if_exact` 返回已有 succeeded/degraded；`force_new` 分配新 versionNumber 并在 snapshot 固定 no_cache intent。
4. stale expectedRevision、非法配置、软删除 source 和未确认 MinerU Cloud 均拒绝。
5. 提交：`feat: create reusable parse versions`。

### Task 8: 实现 builtin_text 标准化

**Files:**
- Create: `backend/app/infrastructure/parsers/builtin_text.py`
- Create: `backend/app/infrastructure/parsers/registry.py`
- Create: `backend/app/modules/parsing/normalization.py`
- Create: `backend/app/modules/parsing/tasks.py`
- Modify: `backend/app/modules/tasks/tasks.py`
- Modify: `backend/app/bootstrap/dependencies.py`
- Test: `backend/tests/unit/parsing/test_builtin_text.py`
- Test: `backend/tests/integration/parsing/test_builtin_parse_operation.py`

1. RED：txt/md 保留结构，CSV 确定性 Markdown table，JSON 规范化且不丢原始值；非法编码/结构有稳定错误。
2. Parser registry 拒绝重复 code/version 和输入类型不匹配。
3. Worker duplicate delivery 单副作用，queued -> normalizing -> succeeded/degraded/failed；产物和业务终态同事务发布。
4. 标准化保存 Markdown、blocks、artifacts 和七个 feature flags，不伪造页码/bbox。
5. 提交：`feat: parse builtin text sources`。

### Task 9: 锁定并实现 MinerU Precision 协议 Adapter

**Files:**
- Create: `backend/app/infrastructure/parsers/mineru_precision.py`
- Create: `backend/tests/fixtures/mineru/*.json`
- Test: `backend/tests/unit/parsing/test_mineru_adapter.py`

1. 实现前先核对 MinerU 官方文档，记录核对日期和批次查询精确 path/shape；fixture 必须来自版本化官方/脱敏真实响应。
2. RED：申请 signed upload、PUT、batchId/dataId 映射、pending/running/converting/done/failed、full_zip_url 和错误映射。
3. Adapter 最多 3 次重试，仅 network/429/5xx；轮询连续网络错误上限 5，成功后清零。
4. 绝不记录 Authorization、原文件正文或完整 signed URL；redirect 默认关闭，下载 URL 重新执行 SSRF/DNS 规则。
5. 提交：`feat: add MinerU precision adapter`。

### Task 10: 实现 MinerU 解析 Worker 和 checkpoint

**Files:**
- Modify: `backend/app/modules/parsing/tasks.py`
- Modify: `backend/app/modules/tasks/tasks.py`
- Modify: `backend/app/bootstrap/dependencies.py`
- Test: `backend/tests/integration/parsing/test_mineru_parse_operation.py`
- Test: `backend/tests/unit/parsing/test_parse_state_machine.py`

1. RED：状态严格按契约转换；只有 queued 可取消；终态重复事件 no-op。
2. signed upload 前保存 batch/data ID checkpoint；重复 delivery 根据 checkpoint 查询，不再次申请/提交。
3. 轮询调度 3s/10s/30s、总超时设置、providerTaskId 保留；网络/限流错误不自动创建新上游任务。
4. done 后立即下载到版本独立临时 key，SHA-256 校验成功才进入 normalizing。
5. 提交：`feat: execute resumable MinerU parsing`。

### Task 11: 实现 full_zip 标准化和解析内容查询

**Files:**
- Modify: `backend/app/modules/parsing/normalization.py`
- Modify: `backend/app/modules/parsing/repository.py`
- Modify: `backend/app/infrastructure/database/repositories/parsing.py`
- Modify: `backend/app/modules/parsing/api.py`
- Test: `backend/tests/unit/parsing/test_mineru_normalization.py`
- Test: `backend/tests/api/test_parsed_source_content_api.py`

1. RED：archive unsafe/invalid/empty/unsupported、已知 Markdown/JSON 结构、内容特征 fallback 和 degraded 规则。
2. blocks/assets/sourceMap 保持 page/bbox/rawLocator；没有坐标时 null + degraded，不生成假坐标。
3. 实现 detail/markdown/blocks/assets/artifacts；资产下载鉴权且不暴露物理 key。
4. succeeded/degraded 内容冻结；重复 normalize 以版本为键幂等覆盖暂存后单次发布。
5. 提交：`feat: normalize and query parsed content`。

### Task 12: 实现恢复、真实 MinerU 测试和异步删除

**Files:**
- Modify: `backend/app/modules/parsing/service.py`
- Modify: `backend/app/modules/parsing/api.py`
- Modify: `backend/app/modules/parsing/tasks.py`
- Modify: `backend/app/modules/parsing/settings_api.py`
- Test: `backend/tests/integration/parsing/test_parse_recovery.py`
- Test: `backend/tests/api/test_mineru_settings_api.py`
- Test: `backend/tests/api/test_parsed_source_versions_api.py`

1. `resume-provider-query` 只允许带 provider ID 且属于 timeout/poll/download 的 failed version；不重新提交。
2. `create-reparse` 创建新版本；原上游明确 failed/not-found 后才能新提交。
3. `POST /settings/mineru:test` 使用内置最小测试文件走 signed upload -> poll -> download -> normalize 完整链并返回 Operation。
4. 删除 source/version 先固定真实空引用查询接口；有引用 409，无引用创建 cleanup Operation，物理 blob 仅 referenceCount=0 且 purgeAfter 到期删除。
5. 提交：`feat: recover and clean parsing resources`。

### Task 13: 同步 OpenAPI 和 generated client

**Files:**
- Modify: `backend/tests/api/test_openapi_contract.py`
- Modify: `docs/api/v1-api-contract.md` only for implementation clarifications
- Generate: `docs/api/openapi.json`
- Generate: `frontend/src/services/ragApi/*`
- Test: `frontend/tests/features/toolchain.test.ts`

1. RED：锁定 dataSources/parsedSourceVersions/mineruSettingsTest operationId 和路径。
2. 导出 OpenAPI、生成 Umi client，确认 response 无 storageKey/Token/signed URL。
3. 二次生成 `git diff --exit-code`。
4. 提交：`chore: generate parsing api client`。

### Task 14: Phase 02 全量验收与交接

**Files:**
- Modify: `docs/implementation/CURRENT_HANDOFF.md`
- Modify: `docs/requirements/99-development-readiness.md`
- Modify: `.github/workflows/ci.yml` only if integration discovery requires it

1. 运行 `scripts/check.ps1`。
2. 启动 Docker dependencies，运行全部 integration 和 `alembic check`。
3. 安全专项：数据库/文件/响应/日志扫描无明文 Token、signed URL 或绝对 storage path；危险 ZIP 固定样例全拒绝。
4. 运行固定 `pip-audit` 和 `npm audit --omit=dev --audit-level=high`。
5. 状态改为 `IMPLEMENTATION IN PROGRESS (PHASE 3)`；不得提前写知识库已完成。
6. 提交 `docs: hand off knowledge base implementation` 并推送当前分支。

## 3. 最终审阅清单

- [ ] Parser/input capability 是前后端格式和路由唯一 catalog。
- [ ] 上传流式、原子、失败清理且不信任文件名。
- [ ] MIME/扩展/signature 或容器结构交叉验证。
- [ ] ZIP 全部安全上限由后端测试锁定。
- [ ] SourceBlob 去重和引用计数事务正确。
- [ ] ParsedSourceVersion/config snapshot/hash 不可变且可复算。
- [ ] Operation/Outbox 同事务，duplicate delivery 单副作用。
- [ ] builtin_text 输出确定性且不丢 CSV/JSON 原始值。
- [ ] MinerU batchId/dataId 映射不依赖 taskId 必然存在。
- [ ] 超时/下载/标准化恢复不重新提交 MinerU。
- [ ] full_zip 无固定文件名假设；无坐标明确 degraded。
- [ ] succeeded/degraded 才 selectable，终态内容冻结。
- [ ] API/log/OpenAPI/generated client 无 Token、signed URL、storage key。
- [ ] 0003 空库升级、Alembic check、根门禁和全部 integration 通过。

## 4. 预期提交序列

```text
docs: add phase two parsing plan
feat: register parser capabilities
feat: add source parsing persistence
feat: add safe source storage
feat: upload and manage data sources
feat: safely expand source archives
feat: create reusable parse versions
feat: parse builtin text sources
feat: add MinerU precision adapter
feat: execute resumable MinerU parsing
feat: normalize and query parsed content
feat: recover and clean parsing resources
chore: generate parsing api client
docs: hand off knowledge base implementation
```

不压缩为单一提交。每个功能提交必须有可重复的 RED/GREEN 证据，且只包含直接相关文件。
