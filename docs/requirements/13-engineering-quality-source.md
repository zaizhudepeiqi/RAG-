# 工程质量阶段性真源

> 文档职责：定义代码组织、静态检查、测试层级、契约测试、标准数据集、CI、评审和完成定义。

## 1. 目标

可读性和健壮性是第一版最高工程要求：

- 新开发者能从目录和类型理解模块，不靠聊天历史。
- 核心业务规则有可执行测试，不靠人工点页面猜。
- 前后端、数据库、任务和第三方 Adapter 有契约防漂移。
- 失败可复现、可定位、可恢复。
- 代码只实现已确认范围，不用无效抽象掩盖复杂度。

## 2. 语言和工具基线

后端：

- Python 版本由 `pyproject.toml` 和容器固定，不使用浮动系统 Python。
- Ruff：格式和 lint。
- mypy 或 pyright：严格类型检查，至少覆盖 domain/application/API DTO。
- pytest：单元、集成和契约测试。
- Alembic：唯一数据库迁移方式。

前端：

- TypeScript `strict=true`。
- ESLint + Prettier。
- Vitest：纯逻辑、composable 和组件测试。
- Playwright：关键后台流程 E2E 和截图检查。
- OpenAPI generator：API 类型/client。

依赖使用锁文件；CI 和本机使用同一命令。

## 3. 代码可读性规则

- 按领域模块组织，不建立跨项目巨大 `services.py`、`types.ts` 或 `utils`。
- 函数做一件事；路由和 Celery task 保持薄。
- 命名使用领域模型术语，避免 `data/info/item/document` 等无上下文名称。
- 类型中区分 ID；必要时使用 NewType/值对象，防止 dataSourceId 和 parsedSourceVersionId 混传。
- 复杂算法先写输入/输出和不变量测试，再实现。
- 注释只解释为什么和边界，不复述代码。
- 不做与当前功能无关的重构；发现问题记录后在对应范围处理。
- 不复制 Provider SDK 响应到业务 DTO。
- 每个公共函数/接口定义错误语义，禁止用 `None/false` 同时表示无结果和失败。

## 4. 测试层级

### 单元测试

无数据库/网络，覆盖：

- 配置和跨字段校验。
- 分块边界、Parent-Child、来源映射。
- RRF、Weighted Score、阈值、去重和稳定排序。
- token 预算和无命中分类。
- 状态转换、删除引用规则、优先级权重。
- 错误码映射和敏感数据脱敏。

### 集成测试

使用真实 PostgreSQL、Redis、Chroma 和临时文件目录，覆盖：

- Repository 约束、事务、revision 冲突和 Alembic。
- Outbox 发布、Celery 重复投递和 Worker 幂等。
- generation 构建、失败保留旧代次、原子切换和清理。
- pg_trgm 和 Chroma 实际检索。
- 文件上传/ZIP 安全和存储原子写。

### Adapter 契约测试

- MinerU HTTP 使用录制/构造的官方成功、运行、失败、限流和结构变更响应；至少有一个可选真实 smoke test。
- 每个 ModelProvider 用统一测试套件验证 LLM/Embedding/Rerank 能力和错误映射。
- Chroma Adapter 验证锁定版本的 collection 配置、距离转换、upsert/delete/query。
- Channel Adapter 验证鉴权、幂等、消息规范化和响应映射。

线上凭据测试不进入默认 CI；通过明确环境开关运行，日志仍脱敏。

### API 测试

- pytest + httpx 是可执行接口真源。
- 覆盖成功、401、404、409、413、422、429、5xx 和幂等重复。
- 校验 response_model、错误结构、分页、revision 和 traceId。
- CI 导出 `openapi.json` 并检测 breaking diff。
- 提供版本控制的 Bruno collection，用于人工调试；从 OpenAPI/已测示例生成，不手工维护第二套字段。

### 前端测试

- 动态 SchemaForm 条件字段和 disabled capability。
- 表单后端错误定位、409 冲突、离开未保存提示。
- 任务轮询停止/退避和旧响应竞态。
- 状态摘要、长名称、错误文本和空状态。

### E2E

Playwright 覆盖最小生产闭环：

1. 初始化管理员和登录/改密。
2. 创建/测试模型和 MinerU 配置。
3. 上传并解析标准文档，查看前后对比。
4. 创建知识库、等待构建、检索测试。
5. 创建机器人、绑定多库、问答和引用。
6. 创建 Webhook/API 渠道，调用同步/异步接口。
7. 查看任务和问答 Trace。
8. 触发重建失败并验证旧索引仍可用。

## 5. 标准 RAG 测试数据集

仓库提供不含真实企业敏感数据的小型测试集：

- 可检索 PDF：标题、跨页段落、表格、图片 OCR、公式。
- Word/PPT/Excel/HTML 和 txt/md/csv/json 样例。
- 扫描 PDF 与非 OCR 对比。
- 同名不同内容、同内容不同名和 ZIP 目录结构。
- 恶意 ZIP、危险 HTML、伪扩展名和空文件。
- 中文精确词、同义表达、英文、数字、短查询和无答案问题。
- 文档 Prompt 注入样例。

配套评测 case 固定 expected source/page/block，供分块、检索和引用回归。测试集的许可证和来源写清楚。

## 6. 故障注入

集成/E2E 至少覆盖：

- MinerU 429、5xx、超时、任务 done 但 zip 下载失败、异常 zip。
- Embedding 部分批次失败和维度变化。
- Chroma 写入中断、查询不可用。
- Redis 重启/清空、重复 Celery delivery、Worker 中途退出。
- PostgreSQL operation 已提交但消息尚未发布。
- 新 generation 部分失败和激活竞态。
- 所有知识库失败与正常无命中区分。
- 回答模型超时和引用非法。
- callback 429/5xx/永久 4xx。
- 磁盘空间不足和文件清理失败。

## 7. 覆盖率和质量阈值

- 核心 domain/algorithm 模块行覆盖率和分支覆盖率均不低于 90%。
- 后端总体行覆盖率不低于 80%。
- 前端业务逻辑/组件总体行覆盖率不低于 75%。
- 覆盖率不能代替边界测试；仅为提高数字而测试实现细节不计质量。
- 所有 P0/P1 业务不变量必须有明确命名测试，即使总体覆盖已达标。

## 8. CI 门禁

每个合并请求必须通过：

1. 文档链接/冲突/TBD 扫描。
2. Backend format、lint、typecheck。
3. Frontend lint、typecheck、format check。
4. 单元测试。
5. PostgreSQL/Redis/Chroma 集成测试。
6. OpenAPI 生成和 breaking diff。
7. 前端单元/组件测试。
8. 核心 Playwright E2E。
9. 依赖漏洞、secret 和容器配置扫描。
10. Alembic upgrade 从空库和上一发布版本测试。

不允许以“后面补测试”合并核心 RAG、任务、删除、安全或接口变更。

## 9. 数据库变更规则

- 新迁移必须有 upgrade；危险迁移还要有回滚/前向修复说明。
- 先扩展 schema、再发布兼容代码、再回填、最后删除旧字段。
- 大表新增非空列不得在单事务内全表锁死。
- 枚举变化先更新需求/状态机/OpenAPI，再迁移。
- CI 验证迁移重复执行防护和 schema 版本。

## 10. API 和前端契约

- 后端 OpenAPI 变化必须重新生成前端 client。
- generated 目录修改只通过生成命令，不手工补字段。
- breaking change 在第一版开发期可调整，但必须同步全部文档和调用点；发布后按 `/api/v2` 或兼容迁移处理。
- API 示例来自测试通过的 fixture，不能手写一个从未运行的 curl。

## 11. 代码评审重点

- 是否破坏模块依赖或跨模块直查表。
- 是否混淆数据源、解析版本、构建代次和 chunk。
- 是否有重复任务、重复外部调用或活动索引被提前删除风险。
- 是否把故障当成无命中。
- 是否泄露凭据、正文、本地路径或供应商签名 URL。
- 是否引入无必要抽象或重复 DTO。
- 是否新增状态/错误码却未更新文档和测试。
- 是否考虑删除引用、并发 revision 和失败恢复。

## 12. Definition of Done

一项功能只有同时满足以下条件才完成：

- 对应需求真源已确认且无未决核心规则。
- API/数据库/状态机/页面映射已更新。
- 实现遵守模块边界和类型检查。
- 单元、集成、契约/E2E 按风险覆盖并通过。
- 成功、空结果、失败、重试、并发和删除路径均验证。
- 日志/Trace/指标可排查且不泄密。
- OpenAPI 和前端 generated client 同步。
- 部署/迁移/回滚或恢复说明完整。
- 验收清单有证据，不以“看起来可以”作为通过。

## 13. 工程质量验收

- 一个命令可运行后端检查和测试，一个命令可运行前端检查和测试。
- CI 从空环境启动依赖并完成迁移/核心 E2E。
- Bruno/API 测试集与 OpenAPI 字段一致。
- 重复任务和外部错误故障注入不产生重复上游计费或损坏活动索引。
- 标准 RAG 数据集能稳定复现分块、检索和引用回归。
- 关键模块达到覆盖率阈值且测试命名能说明业务行为。

