# 企业级 RAG 知识库需求真源索引

更新时间：2026-07-12

本目录是项目唯一需求真源。原型、实现计划、代码注释和口头沟通若与本目录冲突，以本目录最新已确认内容为准；发现冲突必须先修正文档，不能让代码自行选择一种解释。

## 1. 阅读顺序

1. [00-master-requirements.md](./00-master-requirements.md)：产品范围、业务闭环、技术基线和总体验收。
2. [01-architecture-source.md](./01-architecture-source.md)：工程边界、模块依赖、Adapter、outbox 和 API 基线。
3. [02-domain-model-source.md](./02-domain-model-source.md)：术语、实体关系、身份、不可变边界和跨模块不变量。
4. [03-data-parsing-source.md](./03-data-parsing-source.md)：原始数据源、MinerU、解析版本和标准化。
5. [04-model-registry-source.md](./04-model-registry-source.md)：供应商、模型、凭据和连接测试。
6. [05-knowledge-base-source.md](./05-knowledge-base-source.md)：知识库配置修订、数据源绑定和索引代次。
7. [06-retrieval-source.md](./06-retrieval-source.md)：分块、索引、检索、重写、重排和测试。
8. [07-bot-runtime-source.md](./07-bot-runtime-source.md)：多库融合、记忆、兜底、回答和引用。
9. [08-channel-integration-source.md](./08-channel-integration-source.md)：Webhook/API 和未来平台 Adapter。
10. [09-frontend-source.md](./09-frontend-source.md)：导航、页面、表单、动态能力和交互。
11. [10-observability-quality-source.md](./10-observability-quality-source.md)：任务、Trace、指标和 RAG 评测。
12. [11-security-source.md](./11-security-source.md)：认证、密钥、文件、网络和模型安全。
13. [12-deployment-source.md](./12-deployment-source.md)：开发/生产部署、队列、健康、备份和容量。
14. [13-engineering-quality-source.md](./13-engineering-quality-source.md)：代码质量、测试、CI 和完成定义。
15. [90-decision-register.md](./90-decision-register.md)：已收口决策和明确延期范围。
16. [99-development-readiness.md](./99-development-readiness.md)：文档门禁、冲突修复和进入实施计划的条件。

## 2. 规则归属

| 规则 | 唯一详细归属 |
|---|---|
| 模块和代码依赖 | 架构真源 |
| 对象名称、关系、删除和版本 | 领域模型真源 |
| MinerU、文件、解析状态 | 数据解析真源 |
| Provider/模型/测试 | 模型配置真源 |
| 知识库构建和 generation | 知识库真源 |
| 分块/索引/检索算法 | 检索真源 |
| 多库融合/记忆/兜底/引用 | 机器人真源 |
| 外部协议/平台 Adapter | 渠道真源 |
| 页面/控件/交互 | 前端真源 |
| Operation/Trace/指标/评测 | 可观测性真源 |
| 认证/密钥/攻击面 | 安全真源 |
| Docker/Worker/备份/容量 | 部署真源 |
| 静态检查/测试/CI/完成定义 | 工程质量真源 |

其他文件只能摘要或链接，不能复制一份不同默认值。

## 3. 冲突优先级

1. 用户新确认并已经写入对应模块真源的规则。
2. 对应模块阶段性真源。
3. 主需求摘要。
4. 决策台账。
5. 原型文档和视觉设计。

同层冲突不是让开发者选择，而是阻塞开发并修正文档。

## 4. 变更流程

```text
提出变更
  -> 确认影响模块/对象/状态/接口/数据迁移
  -> 修改唯一需求真源
  -> 更新决策台账
  -> 更新 API/数据库/状态机/页面映射/验收
  -> 生成 OpenAPI 类型
  -> 修改代码和测试
```

禁止：

- 先改代码，后补文档。
- 只改前端枚举或数据库字段。
- 在 PR 评论/聊天里形成永久接口约定但不入库。
- 用 `TBD/TODO/大概/可能` 作为开发所需的核心规则。
- 把第三方供应商原始字段直接变成领域字段。

## 5. 开发前派生文档

需求真源冻结后必须补齐：

- `docs/api/`：路径、方法、DTO、HTTP 状态、错误码、鉴权、幂等和示例。
- `docs/database/`：表、字段、约束、索引、迁移、删除和快照。
- `docs/state-machines/`：解析、构建、Operation、ChatRun、渠道等状态转换。
- `docs/frontend-api-map/`：页面、按钮、字段、API 和 DTO 对照。
- `docs/acceptance/`：功能、接口、E2E、安全、部署、恢复和 RAG 评测。

这些文件是需求的派生实现契约，不能反向创造新业务要求。

## 6. 质量检查

每次需求基线更新至少执行：

- 搜索 `TBD/TODO/待确认/建议/是否`，核心行为不得残留未决项。
- 搜索旧术语和重复状态枚举。
- 检查主流程是否仍为“解析 -> 选择解析版本 -> 构建 -> 机器人 -> 渠道”。
- 检查每个异步操作是否有幂等、状态、重试和失败补偿。
- 检查每个删除是否有引用阻止和历史快照。
- 检查每个下拉是否有真实 capability/模型来源和后端校验。
- 检查每个质量指标是否有明确公式、分母和排除项。

## 7. 当前开发门禁

阶段性需求真源完成后，先生成并审阅第 5 节派生契约，再进入功能编码。该顺序是此前已确认的防返工规则，不因“代码可以先跑”而跳过。

当前派生契约已完成，实施路线图和第一阶段详细计划正在审阅。状态以 [99-development-readiness.md](./99-development-readiness.md) 为准；实施资料统一位于 [实施计划目录](../implementation/README.md)，生产代码在计划确认前保持为空。
