# 开发就绪审计

审计时间：2026-07-20

当前结论：**IMPLEMENTATION IN PROGRESS (PHASE 2A)**。第一阶段已合并并推送到 `main`；第二阶段在 `codex/phase-02-models-parsing` 分支按“02A 模型注册与 MinerU 设置 -> 02B 数据上传与解析”顺序实施。知识库、检索、机器人和渠道仍留在后续阶段，不提前创建假实现。

## 1. 文档门禁

| 门禁 | 状态 | 产物 |
|---|---|---|
| 主需求和阶段性真源 | 完成 | `docs/requirements` 00-13 |
| 统一领域模型 | 完成 | `02-domain-model-source.md` |
| 已确认决策台账 | 完成 | `90-decision-register.md` |
| API 契约 | 完成 | `docs/api/v1-api-contract.md` |
| 数据库设计 | 完成 | `docs/database/schema.md` |
| 状态机 | 完成 | `docs/state-machines/state-machines.md` |
| 页面/API 对照 | 完成 | `docs/frontend-api-map/page-api-map.md` |
| 第一版验收清单 | 完成 | `docs/acceptance/v1-acceptance.md` |
| 用户基线审阅 | 完成 | 用户已完成基线审阅 |
| 分阶段实施计划 | Phase 01 完成，Phase 02A 已锁定 | `docs/implementation/README.md`、`01-foundation-implementation-plan.md`、`02a-model-registry-implementation-plan.md` |
| 生产代码 | 第二阶段 A 实施中 | `codex/phase-02-models-parsing` |

## 2. 已消除的高风险冲突

- 主流程统一为“独立解析 -> 具体解析版本 -> 知识库构建 -> 机器人 -> 渠道”，不再在知识库内上传/解析。
- 数据源、解析版本、知识库绑定、构建代次和 chunk 不再共用 `documentId`。
- 重建改为 staging generation + 原子活动指针，旧索引不先删除。
- 首次 partial 和已有活动代次的 partial rebuild 有不同激活规则。
- 活动 partial 修复创建继任 generation，不修改历史代次。
- 关键词检索统一 PostgreSQL pg_trgm，不再同时声称 tsvector 和全表 ILIKE。
- 跨知识库统一按排名加权 RRF，不再直接比较异构原始分数。
- 正常无命中、部分检索失败、全部失败和全部不可用分开。
- 低置信度未实现，因此从第一版指标移除。
- 线上命中率明确不是答案准确率；增加带标准来源的离线评测。
- 渠道持久导入只进入解析数据源，不自动修改知识库。
- 模型、MinerU 保存和连接测试分开；模型类型分别真实测试。
- 页面每个关键按钮已映射唯一 API；机器人 defaults 和手动 retention cleanup 已补接口。
- Celery 任务通过 PostgreSQL outbox 和全局业务幂等键防丢/防重。

## 3. 实施计划中锁定的工程事实

以下不需要重新讨论产品行为，但在创建工程时必须固定：

- Python、Node、npm、FastAPI、SQLAlchemy、Celery、PostgreSQL、Redis、Chroma、React、Umi Max 和 Ant Design 的精确版本。
- Chroma 锁定版本支持的 HNSW 配置字段和 score contract fixture。
- MinerU 批次查询精确路径/item 字段和删除能力通过官方真实响应 fixture 锁定；内部只依赖 batchId/dataId 映射，不假设 taskId 必然存在。
- Ant Design Pro v6.0.2 固定 commit、完整基线/Simple Mode 双提交及精简删除审计。
- `@umijs/max-plugin-openapi` 的 schema、projectName、requestLibPath 和确定性生成命令。
- Ruff/mypy/pytest/Biome/Jest/React Testing Library/Playwright/Bruno 的具体配置。
- Docker image digest、Compose healthcheck 命令和开发端口。
- 标准 RAG 测试文件的许可证、内容和 SHA-256。

这些属于实施计划和依赖锁，不允许改变本需求定义的对象、状态和接口含义。

## 4. 首个实施阶段边界

当前第一阶段只做工程和基础设施，不直接跳到 RAG 页面：

1. Monorepo 目录和依赖锁。
2. FastAPI bootstrap、配置、错误、traceId、健康接口。
3. PostgreSQL/Alembic、Redis、Chroma、Storage 基础 Adapter。
4. Operation/outbox/Celery Worker 骨架和幂等测试。
5. Ant Design Pro v6.0.2 Simple Mode 基座、Umi OpenAPI 生成和登录壳。
6. CI 的 lint/typecheck/unit/integration 最小闭环。

通过该阶段验收后，再按模块实现模型/解析、知识库/检索、机器人/渠道和前端业务。

## 5.1 第一阶段验证证据（2026-07-20）

- 根质量门禁：`scripts/check.ps1` exit 0；后端非集成测试 67 passed，前端 Jest 7 suites/14 tests passed，Ruff、strict mypy、Biome、TypeScript、生产构建和 OpenAPI 生成漂移检查通过。
- PostgreSQL/Redis/Chroma 集成组：28 passed，覆盖认证、迁移、数据库约束、依赖健康、Celery/Redis、Operation/outbox 幂等和恢复。
- 依赖审计：导出 `uv.lock` 后运行固定版本 `pip-audit 2.10.1`，无未豁免已知漏洞；ChromaDB 例外有单独到期门禁。前端生产依赖 `npm audit --omit=dev --audit-level=high` 通过，报告 1 项已知 moderate `dompurify` 上游问题。
- 本机 Edge E2E：1 passed；覆盖未登录拦截、管理员登录、首次改密、HttpOnly Cookie 重载、健康页、任务页、退出和再次拦截。
- Docker Desktop：PostgreSQL、Redis、Chroma 均为 healthy；E2E 临时数据库和 API/前端进程已回收。

本地 Chromium 下载未完成，因此本次本机浏览器证据使用系统 Edge；CI 仍安装并使用 Playwright Chromium。代理代码审查因服务端 429 未返回结果，提交前已完成同范围人工代码和需求复核。

## 6. 基线审阅重点（已完成）

用户基线审阅已完成，审阅时优先确认以下内容，不需要检查每个 SQL 类型：

- 数据解析和知识库的业务顺序是否完全符合预期。
- 第一版功能范围是否接受，包括附件、质量评测、安全和生产部署。
- 页面导航和少页面/长滚动原则是否符合原型方向。
- 第一版明确延期项是否接受。

技术字段若发现歧义，先修正文档再写实施计划。

## 7. Git 状态说明

`D:\RAG知识库` 已初始化为 Git 仓库，默认分支为 `main`，远端为 `https://github.com/zaizhudepeiqi/RAG-.git`。首个文档基线提交为 `79dccc14475c77f1138dceedd967ac39a08fa4e5`；生产代码当前在独立阶段分支 `codex/phase-01-foundation` 开发，不直接在 `main` 开发。
