# 第一版决策台账

> 目的：记录已收口选择和明确延期内容。详细规则仍以对应阶段性真源为准。
> 当前没有阻塞需求基线的开放产品问题。

## 1. 产品与架构

| ID | 决策 | 结论 |
|---|---|---|
| D-001 | 产品形态 | 企业私有化、单工作区、单管理员后台 |
| D-002 | 工程组织 | Monorepo，模块化单体，独立 Worker 进程 |
| D-003 | 后端/前端 | FastAPI；Vue 3 + Vite + TypeScript + Element Plus + v3-admin-vite |
| D-004 | 数据组件 | PostgreSQL + Redis/Celery + Chroma + 本地 StorageAdapter |
| D-005 | 可靠任务 | PostgreSQL transactional outbox + Celery 至少一次投递 + 幂等 Worker |
| D-006 | 能力扩展 | 代码内显式 Adapter/Strategy 注册，后端 capability 驱动前端下拉 |
| D-007 | 接口契约 | `/api/v1`、OpenAPI 生成 TypeScript、统一错误和 revision 并发控制 |

## 2. 数据解析

| ID | 决策 | 结论 |
|---|---|---|
| D-101 | 模块边界 | 数据清洗与解析是独立一级模块，知识库不上传/解析原始文件 |
| D-102 | 第一版 Parser | MinerU Precision API Token 模式 + builtin_text；不使用桌面端/MCP |
| D-103 | 格式 | MinerU 官方格式 + txt/md/csv/json 内置解析；ZIP 作为安全批量容器 |
| D-104 | 解析身份 | 原始 DataSource 可产生多个不可变 ParsedSourceVersion |
| D-105 | 去重 | SHA-256 blob 去重；source hash + Parser/version + configHash 判断解析复用 |
| D-106 | 参数 | 系统全局默认，单次解析可覆盖；参数快照/哈希保存 |
| D-107 | 版本传播 | 新解析版本不自动影响知识库，管理员显式替换并构建 |
| D-108 | 可用结果 | succeeded/degraded 可选，failed 不可选；降级明确警示 |

## 3. 模型

| ID | 决策 | 结论 |
|---|---|---|
| D-201 | Provider | OpenAI、OpenAI-Compatible、DeepSeek、通义千问真实实现 |
| D-202 | 模型池 | 全局可复用，业务保存模型 ID 和自己的参数快照 |
| D-203 | 类型测试 | LLM/Embedding/Rerank/Vision 分别执行真实测试 |
| D-204 | 选择规则 | enabled、verification passed、类型匹配缺一不可 |
| D-205 | 引用锁定 | 被引用模型身份/协议/维度不可原地修改；凭据允许安全轮换 |
| D-206 | 密钥 | Provider/MinerU 凭据使用独立主密钥 AEAD 加密 |

## 4. 知识库与检索

| ID | 决策 | 结论 |
|---|---|---|
| D-301 | 多对多 | 多知识库、多机器人；解析版本/知识库/机器人均可复用组合 |
| D-302 | 绑定 | 知识库绑定具体 parsedSourceVersionId，不绑定 latest |
| D-303 | 创建时机 | 完成全部配置后点击“创建并构建”才创建 operation |
| D-304 | 独立索引 | 每知识库独立 chunks、关键词 namespace、Chroma generation |
| D-305 | 原子重建 | 新 generation 暂存/校验，成功后切活动指针，旧索引持续服务 |
| D-306 | 局部失败 | 首次部分成功可 partial_ready；已有活动代次的部分重建不自动切换 |
| D-307 | 重试 | 默认只处理失败 items；活动 partial 通过继任 repair generation 修复，成功项只复制不重算 |
| D-308 | 索引结构 | Chunk、Parent-Child；QA 延后 |
| D-309 | 分块 | Token、段落、标题、按页、语义第一版全部实现，参数可编辑 |
| D-310 | 向量索引 | Chroma HNSW，默认 cosine；Adapter 隔离供应商参数 |
| D-311 | 关键词索引 | PostgreSQL pg_trgm + GIN，不用无索引全表 ILIKE 冒充企业检索 |
| D-312 | 检索 | 向量、关键词、混合；混合 RRF 默认，Weighted Score 可调 |
| D-313 | 查询重写 | 关闭、HyDE、Multi-Query、Step-Back 全实现 |
| D-314 | 重排 | 关闭、Rerank Model、LLM 重排全实现 |
| D-315 | 低置信度 | 第一版不定义；不展示低置信度指标 |

## 5. 机器人

| ID | 决策 | 结论 |
|---|---|---|
| D-401 | 参数归属 | 回答模型、Prompt、多库融合、上下文预算、记忆、兜底、引用归机器人 |
| D-402 | 跨库合并 | 使用本库排名的加权 RRF，禁止直接比较异构原始分数 |
| D-403 | 优先级 | 1-10，1 最高，固定公式映射到 1.0-2.0 权重 |
| D-404 | 会话记忆 | 最近 3 轮、30 分钟会话，LLM 生成 standaloneQuery；历史不是事实来源 |
| D-405 | 无命中 | 明确提示；可再用回答 LLM 兜底并标识通用模型来源 |
| D-406 | 故障边界 | 检索故障/全部知识库不可用不算无命中，不进行常识兜底掩盖故障 |
| D-407 | 引用 | 只引用进入 Prompt 的上下文，保留页码/block/asset，校验来源 ID |
| D-408 | 状态 | 第一版机器人无启停开关；停止外部调用通过渠道实例 |

## 6. 渠道

| ID | 决策 | 结论 |
|---|---|---|
| D-501 | 第一版渠道 | 只实现 Webhook/API，其他平台仅 Adapter 边界 |
| D-502 | 路由 | 一个渠道实例绑定一个机器人 |
| D-503 | 鉴权 | 每实例独立高熵 API Key，数据库只存 hash，明文只显示一次 |
| D-504 | API 运行 | 同步 60 秒 + 异步 operation 查询 + 可选 HMAC callback |
| D-505 | 幂等/限流 | 所有外部 POST 强制 Idempotency-Key，Redis 令牌桶和并发限制 |
| D-506 | conversationId | 调用方不传时系统生成并返回 |
| D-507 | 临时附件 | 异步解析、不进知识库、24 小时清理、可按临时来源引用 |
| D-508 | 持久导入 | 只创建解析数据源，不自动绑定/构建知识库 |
| D-509 | 语音/视频 | 第一版不实现，capability disabled |

## 7. 前端、质量与运维

| ID | 决策 | 结论 |
|---|---|---|
| D-601 | 导航 | 数据解析顶部；知识库/机器人有 `+` 和下拉；系统设置固定底部 |
| D-602 | 页面 | 少页面、长页面滚动、Tabs/折叠；复杂编辑用完整页，快速详情用抽屉 |
| D-603 | 动态能力 | 前端显示下拉，选项/schema 后端提供，disabled 不可保存 |
| D-604 | 任务刷新 | 第一版自适应轮询，不做 SSE/WebSocket |
| D-605 | 日志 | 完整可排查 Trace，敏感大字段受控加密，普通日志不记录正文 |
| D-606 | 在线命中率 | 仅表示正常检索后的上下文非空，系统失败不进分母 |
| D-607 | 真实质量 | 第一版评测集计算 Hit@K、Recall@K、MRR、No-hit accuracy |
| D-608 | 保留 | Trace/会话 30 天、Operation 90 天、审计 180 天、临时附件 24 小时 |
| D-609 | 部署 | Windows 开发；Linux 单节点 Docker Compose 生产 |
| D-610 | 生产恢复 | 每日备份，默认 RPO 24h/RTO 4h，发布前实际恢复演练 |
| D-611 | API 测试集 | pytest/httpx 为可执行真源，提供由已测契约生成的 Bruno collection |
| D-612 | E2E | Playwright 覆盖解析、知识库、机器人、渠道、任务和重建失败主闭环 |
| D-613 | 标准数据集 | 仓库提供多格式、中文检索、无答案和安全攻击样例及来源标注 |
| D-614 | CI 门禁 | lint/typecheck/unit/integration/OpenAPI/E2E/migration/security 全部通过才合并 |

## 8. 明确延期，不是待确认

- SaaS、多租户、RBAC、组织架构、知识权限。
- 钉钉、企微、个人微信、飞书、客服真实接入。
- 本地 MinerU/私有 Parser、MCP 和桌面端依赖。
- 对象存储、其他向量库和外部全文搜索引擎。
- 流式回答、语音/视频、长期记忆、用户画像。
- Chunk 手工编辑、QA 索引、图片语义检索。
- 低置信度自动策略、自动 LLM Judge、计费。
- Kubernetes、HA、灰度和用户可见索引回滚。

## 9. 外部契约实施要求

以下不是开放产品问题，而是实现期必须锁定并测试的外部事实：

- MinerU 官方 API 字段、状态和错误码采用 2026-07-12 核对基线，并通过 Adapter 契约测试。
- Chroma 版本和 HNSW 可配置字段在依赖锁中固定，不能用 floating latest。
- 各模型 Provider 的模型类型和参数通过真实连接测试确认，不能按名字猜测。

外部事实变化只更新 Adapter 和 capability version，不能静默改变领域 DTO。

## 10. 决策变更规则

改变上述结论必须：

1. 说明原因和影响范围。
2. 修改对应阶段性真源。
3. 在本台账新增 superseded 记录，不覆盖历史理由。
4. 更新 API、数据库、状态机、前端映射、验收和迁移方案。

聊天中的临时说法不构成变更，除非已经写入真源。
