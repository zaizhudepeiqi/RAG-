# 开发就绪审计

审计时间：2026-07-13

当前结论：**IMPLEMENTATION PLAN IN REVIEW**。需求和开发契约基线已形成，分阶段路线图和第一阶段详细计划已提交审阅；尚未开始生产代码。计划确认前不得创建生产工程骨架，也不重新询问已收口默认值。

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
| 用户基线审阅 | 已进入实施计划审阅 | 用户已要求按既定顺序编写计划 |
| 分阶段实施计划 | 待确认 | `docs/implementation/README.md`、`01-foundation-implementation-plan.md` |
| 生产代码 | 未开始 | 实施计划确认后 |

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

实施计划确认后，第一阶段只做工程和基础设施，不直接跳到 RAG 页面：

1. Monorepo 目录和依赖锁。
2. FastAPI bootstrap、配置、错误、traceId、健康接口。
3. PostgreSQL/Alembic、Redis、Chroma、Storage 基础 Adapter。
4. Operation/outbox/Celery Worker 骨架和幂等测试。
5. Ant Design Pro v6.0.2 Simple Mode 基座、Umi OpenAPI 生成和登录壳。
6. CI 的 lint/typecheck/unit/integration 最小闭环。

通过该阶段验收后，再按模块实现模型/解析、知识库/检索、机器人/渠道和前端业务。

## 5. 审阅重点

用户审阅不需要检查每个 SQL 类型，优先确认：

- 数据解析和知识库的业务顺序是否完全符合预期。
- 第一版功能范围是否接受，包括附件、质量评测、安全和生产部署。
- 页面导航和少页面/长滚动原则是否符合原型方向。
- 第一版明确延期项是否接受。

技术字段若发现歧义，先修正文档再写实施计划。

## 6. Git 状态说明

`D:\RAG知识库` 已初始化为 Git 仓库，默认分支为 `main`，远端为 `https://github.com/zaizhudepeiqi/RAG-.git`。首个文档基线提交为 `79dccc14475c77f1138dceedd967ac39a08fa4e5`；生产代码开始后使用独立阶段分支，不直接在 `main` 开发。
