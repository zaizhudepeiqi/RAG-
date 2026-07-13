# 企业级 RAG 知识库系统主需求

> 状态：第一版需求基线。
> 详细规则只在对应阶段性真源定义；本文件负责项目定位、业务闭环、范围和总体验收。

## 1. 项目定位

本项目是面向企业私有化部署的 RAG 知识库后台管理系统。

管理员在独立“数据清洗与解析”模块上传原始文件，系统通过 MinerU Precision API 或内置文本 Parser 生成不可变解析版本；管理员再创建多个知识库，选择解析版本并配置 Embedding、分块、索引和检索；随后创建多个机器人，为每个机器人绑定多个知识库和回答模型，并通过第一版 Webhook/API 对外提供问答。

核心价值：

- 企业资料结构化、可复用、可追溯。
- 多知识库、多机器人灵活组合。
- 回答优先基于企业知识，并返回原始片段、页码、图片/表格等来源。
- 知识库无命中时按配置明确提示并可用通用 LLM 兜底。
- 解析、构建、检索、生成、引用和错误全链路可排查。
- 未来替换 Parser、模型、向量库、存储和渠道时不重写整个系统。

## 2. 第一版用户和边界

- 单企业、单工作区、单管理员。
- 后台管理系统是第一版唯一产品界面。
- 管理员负责模型、数据源、知识库、机器人、渠道和系统配置。
- 外部终端通过 Webhook/API 调用机器人。
- 不做 SaaS、多租户、RBAC、组织架构和终端用户管理。

“企业级”在第一版指：边界清晰、数据可追溯、配置可复现、任务可靠、错误可排查、安全和部署有最低生产基线；不代表已经具备高可用、多租户或无限容量。

## 3. 端到端业务闭环

```text
管理员登录
  -> 配置并测试 MinerU
  -> 配置并测试模型供应商/模型
  -> 在数据解析模块上传原始文件
  -> MinerU/Parser 解析和标准化
  -> 处理前后对比
  -> 得到可复用的 ParsedSourceVersion
  -> 创建知识库并选择一个或多个解析版本
  -> 配置 Embedding、分块、索引、检索、重写、重排
  -> 最终确认后异步构建 IndexGeneration
  -> 检索测试和质量评测
  -> 创建机器人，选择回答模型并绑定多个知识库
  -> 配置多库融合、token 预算、记忆、兜底、引用
  -> 创建 Webhook/API 渠道实例
  -> 外部系统同步/异步提问
  -> 返回回答、来源、conversationId 和 traceId
  -> 后台查看任务、问答 Trace、运行指标和 RAG 评测
```

解析成功不会自动进入知识库；选择数据源和编辑参数不会立即构建；只有最终明确命令才创建异步操作。

## 4. 一级业务模块

### 4.1 数据清洗与解析

- 固定在左侧导航顶部。
- 上传 PDF、图片、Office、HTML、文本、结构化文本和 ZIP 批量容器。
- MinerU 负责 OCR、版面、表格、公式和结构提取；文本 Parser 处理已是文本的格式。
- 保存原始文件、MinerU zip、解压产物和标准化 blocks/assets。
- 同一原始文件支持多个解析版本和复用。
- 展示原文/解析结果左右对比。
- 解析版本只有完成后才进入知识库选择器。

### 4.2 模型配置

- 供应商和模型分层管理。
- 第一版 Adapter：OpenAI、OpenAI-Compatible、DeepSeek、通义千问。
- 模型类型：LLM、Embedding、Rerank、Vision。
- 创建、测试和启用是独立状态。
- 业务页面只选择已配置、启用、验证通过且类型匹配的模型。
- 凭据后端加密，不在前端回显。

### 4.3 知识库管理

- 支持多个知识库。
- 一个解析版本可被多个知识库复用。
- 每个知识库独立 chunks、关键词索引和 Chroma generation。
- 创建页面完整配置后点击“创建并构建”才运行任务。
- 重建使用新 generation，旧索引持续服务，成功后原子切换。
- 首次部分成功可以 `partial_ready`；已有索引的部分失败重建不自动替换旧索引。

### 4.4 分块、索引和检索

- 索引结构：Chunk、Parent-Child。
- 分块：Token、段落、标题层级、按页、语义。
- 向量：Chroma HNSW。
- 关键词：PostgreSQL `pg_trgm`。
- 检索：向量、关键词、混合。
- 查询重写：关闭、HyDE、Multi-Query、Step-Back。
- 重排序：关闭、Rerank Model、LLM 重排。
- 所有关键 Top K、阈值、大小、Overlap 和策略参数可编辑。
- 检索测试支持临时调参、完整 JSON 和来源追溯。

### 4.5 机器人管理

- 支持多个机器人。
- 一个机器人绑定多个知识库，一个知识库被多个机器人复用。
- 机器人配置回答 LLM、系统 Prompt、知识库优先级、上下文条数/token、短期记忆、无命中和引用。
- 跨知识库固定使用按本库排名的加权 RRF，不直接比较异构原始分数。
- 会话历史只用于指代消解。
- 真正无命中先明确提示，再按配置使用通用 LLM；检索故障不得伪装无命中。

### 4.6 渠道接入

- 第一版只实现 Webhook/API，钉钉、企微、个人微信、飞书、客服等只定义 Adapter 边界。
- 一个渠道实例第一版绑定一个机器人。
- 独立 API Key、幂等、限流、同步/异步、结果查询和可选签名 callback。
- 临时问答附件不进入知识库；持久渠道导入只进入数据解析模块，不自动修改知识库。
- 引用返回支持 none/simple/standard/full。

### 4.7 任务、日志和质量

- Celery + Redis 执行异步任务，PostgreSQL 是任务状态真源。
- Transactional outbox、幂等任务、分队列和失败重试。
- Chat Trace 保存每阶段快照、候选、分数、Prompt、回答、引用、token、耗时和错误。
- 仪表盘展示命中、无命中、失败、降级、引用、延迟和模型调用。
- 命中率不冒充答案准确率。
- 第一版提供标注来源的评测集和 Hit@K、Recall@K、MRR、No-hit accuracy。

### 4.8 系统设置

- MinerU Token、默认解析参数和完整连接测试。
- 日志/会话/任务/临时附件保留。
- 管理员修改密码。
- 运行依赖和存储健康摘要。

## 5. 技术基线

- Monorepo。
- 后端：FastAPI。
- 业务数据库：PostgreSQL。
- 向量库：Chroma。
- 关键词：PostgreSQL `pg_trgm`。
- 队列：Celery + Redis。
- 文件：第一版本地 StorageAdapter。
- Parser：MinerU Cloud Precision API + builtin_text。
- 前端：Ant Design Pro v6.0.2 Simple Mode + React 19 + TypeScript + Umi Max 4 + Ant Design 6。
- 开发：Windows + Docker Desktop。
- 生产：Linux 单节点 Docker Compose。
- 工程门禁：强类型、单元/集成/契约/E2E、OpenAPI diff、迁移和安全扫描。

## 6. 扩展原则

- 能力注册、Adapter 和 Strategy 用于真实可替换点。
- 前端有下拉，但选项/参数 schema 来自后端 capability。
- 未实现能力 disabled 或隐藏，不能保存。
- 配置保存 capability code/version 和参数快照。
- 第一版代码内显式注册，不运行任意第三方插件。
- 不为“以后可能”创建空服务、空表或空接口；出现第二实现时按既有 port 扩展。

## 7. 数据和状态最高原则

- 原始数据源、解析版本、知识库绑定、构建代次和 chunk 是不同对象。
- 知识库绑定具体不可变解析版本，不追随 latest。
- 活动索引只由 `activeGenerationId` 指定。
- 配置表单当前值不能直接解释旧活动索引。
- 任务、供应商原始状态和业务状态分开。
- “无命中”“部分失败”“全部失败”“配置不可用”分开。
- 历史回答保存配置/来源快照，不能靠当前名称重建历史。

## 8. 第一版明确不做

- SaaS、多租户、RBAC、组织架构、知识权限。
- 钉钉、企微、个人微信、飞书、客服真实 Adapter。
- Kubernetes、HA、多区域和自动扩缩。
- MinerU MCP、桌面端依赖、本地 MinerU。
- MinIO/S3、Milvus/Qdrant/pgvector、Elasticsearch/OpenSearch。
- 手动编辑解析结果和 chunk、可视化 chunk 合并/拆分。
- QA 索引。
- 图片视觉语义检索；第一版只使用 OCR/结构资产并支持引用。
- 语音/视频消息。
- 流式 SSE/WebSocket 回答。
- 长期用户记忆、画像和推荐。
- 自动 LLM Judge 作为质量真源。
- 低置信度自动策略。
- 计费系统。
- 用户可见索引回滚和复杂灰度发布。

## 9. 非功能要求

### 可读性

- 按业务模块组织代码和文档。
- 一个概念一个名称，一个规则一个真源。
- API、数据库、前端和日志状态保持同源。

### 健壮性

- 异步命令经过 outbox，Worker 幂等。
- 配置 revision 防止过期覆盖。
- 索引暂存、验证、活动指针切换。
- 第三方故障有超时、有限重试、降级边界和 traceId。
- 备份恢复必须演练。

### 安全

- 管理员认证、密码哈希、凭据加密、API Key 哈希。
- TLS、限流、CSRF/CORS、文件/ZIP/SSRF/HTML 安全。
- 文档 Prompt 注入防护。
- 明确 MinerU Cloud 会外发企业文件。

### 可观测性

- 每个 HTTP/Operation/ChatRun/Provider 调用可关联。
- 失败定位到阶段和对象修订。
- 指标不混淆空结果与系统错误。

## 10. 第一版总体验收

1. 管理员首次登录、强制改密、配置并完整测试 MinerU。
2. 创建并测试 LLM、Embedding、Rerank 模型，类型错误不能业务引用。
3. 上传官方支持格式和文本格式，安全处理 ZIP，得到可追溯解析版本。
4. 原文/结果按页和 block 对比，新解析版本不自动影响知识库。
5. 创建多个知识库并选择多个解析版本，最终提交后异步构建。
6. 五种分块、两种索引结构、三种检索、三种重写和两种重排真实运行。
7. 重建失败不影响旧活动索引，失败数据源可单独重试。
8. 创建多个机器人、绑定多个知识库，跨库 RRF 规则可复算。
9. 多轮追问完成指代消解，知识事实只来自最终上下文。
10. 无命中按配置明确提示/LLM 兜底；检索故障返回错误。
11. Webhook/API 同步、异步、幂等、限流、附件和 signed callback 可验证。
12. 回答引用能回到解析版本、原文页码/block/asset。
13. 任务中心和 Chat Trace 足以排查每个阶段。
14. 在线指标口径正确，评测集能比较 generation/检索配置。
15. Windows 开发和 Linux Compose 生产部署、备份恢复通过验收。

## 11. 开发文档门禁

`docs/requirements` 是唯一需求真源。需求冻结后，开发前仍需由真源派生并确认：

- API 接口文档。
- 数据库设计文档。
- 状态机文档。
- 页面/API 对照表。
- 验收清单和标准测试数据集。

任何字段、枚举、错误码、状态流、页面/API 关系变化必须先修改真源，再更新派生文档和代码。不能通过口头约定或只改代码变更契约。

## 12. 外部依据

- MinerU GitHub：`https://github.com/opendatalab/MinerU`
- MinerU API：`https://mineru.net/apiManage/docs`
- MinerU ecosystem：`https://mineru.net/OpenSourceTools/Extractor/ecosystem`
- Ant Design Pro：`https://github.com/ant-design/ant-design-pro/tree/v6.0.2`
- Ant Design Pro Simple Mode：`https://github.com/ant-design/ant-design-pro/blob/v6.0.2/docs/cheatsheet.en-US.md`

第三方文档会变化；实现必须锁定依赖/协议版本并保存契约测试，不能只凭网页当前内容运行。
