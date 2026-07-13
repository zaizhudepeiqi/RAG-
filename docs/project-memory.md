# 项目继续沟通记忆点

更新时间：2026-07-13

## 当前阶段

- 尚未开始生产代码开发。
- 第一版需求阶段性真源已按业务依赖重新组织并收口，产品阻塞问题已按推荐方案决定。
- 已派生 API、数据库、状态机、页面/API 对照和第一版验收清单。
- 已创建 `docs/implementation/README.md` 分阶段路线图和 `01-foundation-implementation-plan.md` 第一阶段详细计划，Ant Design Pro 前端基线变更已同步，当前等待计划确认。
- Git 已初始化并推送到 `zaizhudepeiqi/RAG-`；生产代码尚未开始。
- `docs/prototype` 当前不存在，未擅自重建；低保真静态展示仍单独位于 `简单展示/`。
- 下一步是确认实施计划，然后从独立阶段分支开始 Monorepo 脚手架和基础设施开发。

## 唯一真源

- `docs/requirements/README.md` 是需求入口。
- `docs/requirements` 是唯一需求真源。
- `docs/api`、`docs/database`、`docs/state-machines`、`docs/frontend-api-map`、`docs/acceptance` 是由真源派生的开发契约。
- 原型和视觉文件不改变后端业务边界；发现冲突时先修改需求真源。

## 产品主流程

```text
数据清洗与解析
  -> ParsedSourceVersion
  -> 知识库选择具体解析版本
  -> 配置 Embedding/分块/索引/检索
  -> IndexGeneration 构建和原子激活
  -> 机器人绑定多个知识库
  -> 跨库按排名加权 RRF
  -> Webhook/API
  -> 回答、引用、Trace 和质量指标
```

## 核心架构结论

- Monorepo + 模块化单体 + 独立 Celery Workers，不拆微服务。
- 后端 FastAPI；前端固定 Ant Design Pro v6.0.2 Simple Mode、React 19、TypeScript、Umi Max 4 和 Ant Design 6。
- 前端模板固定 commit `2b453c67b535b76f5f95d6542397a4b987b61de2`；导入时先提交完整应用基线，再执行并审查官方 `npm run simple`，不跟随 `master`。
- 服务端状态使用 React Query；管理员/布局使用 Umi initialState/model；第一版 access 只作登录和强制改密守卫。
- 前端 API 只由 `@umijs/max-plugin-openapi` 从后端 OpenAPI 生成，统一经过 Umi request，不手写重复 DTO/client。
- PostgreSQL 是业务/任务真源；Redis 只做 broker/cache/限流；Chroma 是可重建向量索引；本地 StorageAdapter 保存文件。
- Transactional outbox + 幂等 Worker 解决 Celery 至少一次投递。
- 数据源、解析版本、知识库配置修订、索引代次、chunk 是不同对象。
- 知识库绑定具体不可变 parsedSourceVersionId，不追随 latest。
- 新索引暂存/校验后切 activeGenerationId，旧索引在重建失败时继续服务。
- 跨知识库禁止比较异构原始分数，固定使用本库排名的加权 RRF。

## 第一版主要能力

- MinerU Precision API + builtin_text，支持官方文档/图片/Office/HTML 和 txt/md/csv/json；ZIP 为安全批量容器。
- 多知识库、多机器人、多对多复用。
- Token/段落/标题/按页/语义分块。
- Chunk/Parent-Child 索引结构。
- Chroma HNSW + PostgreSQL pg_trgm。
- 向量/关键词/混合检索；HyDE/Multi-Query/Step-Back；Rerank/LLM 重排。
- 会话指代消解、无命中提示 + 可选通用 LLM 兜底、严格来源引用。
- 第一版渠道 Webhook/API；临时附件不入库，持久导入只进入解析模块。
- Operation/Trace/在线运行指标和带标注来源的离线 RAG 评测。
- Windows 开发 + Linux 单节点 Docker Compose 生产。

## 关键安全边界

- 单管理员、单工作区，不做假多租户/RBAC。
- MinerU Cloud 会外发企业文件，页面/部署必须明确。
- Provider/MinerU/callback secret 使用 AES-256-GCM；渠道 API Key 只存 SHA-256 hash。
- 上传统一执行大小、MIME/魔数、ZIP traversal/bomb 和 HTML sanitize。
- 检索文档是非可信内容；机器人无工具执行能力，引用 ID 受校验。

## 已生成开发契约

- `docs/api/v1-api-contract.md`
- `docs/database/schema.md`
- `docs/state-machines/state-machines.md`
- `docs/frontend-api-map/page-api-map.md`
- `docs/acceptance/v1-acceptance.md`

## 明确延期

- 多租户/RBAC/组织权限。
- 钉钉/企微/个人微信/飞书/客服真实 Adapter。
- 本地 MinerU、MCP、对象存储、其他向量库/全文引擎。
- 流式回答、语音/视频、长期记忆、图片语义检索、计费。
- Kubernetes/HA/灰度和用户可见索引回滚。

## 下一步固定顺序

1. 审阅并确认当前文档基线。
2. 创建实现计划，按“工程骨架 -> 基础设施 -> 模型/解析 -> 知识库/检索 -> 机器人/渠道 -> 前端 -> 可观测/部署”拆阶段。
3. 建立 Monorepo、CI、OpenAPI 生成和 Docker 开发依赖。
4. 每个阶段先写/更新测试和契约，再实现。
5. 任何新约束先进入对应真源，再修改代码。
