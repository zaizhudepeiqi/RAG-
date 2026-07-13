# 第一版开发与发布验收清单

> 上游：`docs/requirements`、API、数据库、状态机和页面/API 对照表。
> 所有勾选项需要自动化测试、截图、日志、导出结果或恢复记录等证据；口头说明不算通过。

## 1. 验收环境

- [ ] 记录应用 commit/version、OpenAPI hash、数据库 migration revision、Docker image digest。
- [ ] 使用全新 PostgreSQL/Redis/Chroma/Storage 完成首次部署。
- [ ] 使用上一发布 schema 完成升级部署。
- [ ] 标准测试数据集版本和 SHA-256 已记录。
- [ ] MinerU/模型真实凭据使用专用测试账号，日志确认无密钥泄露。
- [ ] 浏览器至少覆盖 Chromium；布局验证 1280x720、1440x900、1920x1080。

## 2. 管理员和安全

- [ ] 空库首次启动创建一个管理员；第二次启动不覆盖。
- [ ] 生产弱初始密码导致启动失败。
- [ ] 初始管理员首次登录强制修改密码。
- [ ] Argon2id 密码哈希不包含明文；错误响应不区分用户名不存在和密码错误。
- [ ] 10 次失败触发 429/Retry-After，成功/失败均有审计。
- [ ] JWT 在 HttpOnly Cookie，写接口缺少/错误 CSRF 返回 403。
- [ ] logout 使当前 JWT 失效；修改密码使其他登录态失效。
- [ ] Redis 清空/重启后，已 logout 或改密失效的旧 JWT 仍不可使用。
- [ ] CORS、CSP、nosniff、frame-ancestors、Referrer-Policy 响应头正确。
- [ ] 生产 OpenAPI 默认不可公网访问。

## 3. MinerU 和模型配置

- [ ] MinerU Token 创建/更新后数据库为 AES-256-GCM 密文，API 只返回 configured/masked。
- [ ] MinerU “保存”和“测试”是两个操作；完整测试创建可查询 Operation。
- [ ] 连接测试覆盖 signed upload、轮询、下载 zip、标准化最小结果。
- [ ] OpenAI、OpenAI-Compatible、DeepSeek、通义 Provider Adapter 可创建/错误校验。
- [ ] LLM、Embedding、Rerank 使用不同真实测试，不用同一个 ping。
- [ ] Embedding 测试保存维度，空/NaN/维度不一致失败。
- [ ] 未测试、失败、stale、disabled、类型不匹配模型不进入业务选择器且后端拒绝 ID 绕过。
- [ ] 被引用模型的身份字段不能修改/停用/删除，返回引用清单。
- [ ] Provider 凭据轮换使其模型 verification stale；旧业务配置不静默停用，新配置不能选直到重测通过。
- [ ] API Key/Token、签名 URL 不出现在页面、OpenAPI 示例、结构化日志、Trace 或异常。

## 4. 文件上传安全

- [ ] PDF/图片/Doc/Docx/Ppt/Pptx/Xls/Xlsx/HTML/txt/md/csv/json 按 capability 路由。
- [ ] ZIP 展开为独立数据源并保留安全相对 sourcePath。
- [ ] 单文件 >200 MB、空文件、伪扩展名、危险 MIME 被拒绝。
- [ ] ZIP `../`、绝对路径、盘符、symlink、加密包、嵌套 ZIP、>100 entries、>1 GB 解压、>100:1 压缩比被拒绝。
- [ ] 上传使用流式落盘，失败临时文件被清理；不使用用户文件名拼物理路径。
- [ ] 危险 HTML/Markdown 预览不执行 script/event/iframe/javascript URL。
- [ ] 文件下载要求管理员/渠道授权并设置安全 Content-Type/Disposition。

## 5. 数据源和解析版本

- [ ] 上传不自动解析；开始解析创建 ParsedSourceVersion + Operation。
- [ ] 相同 SHA-256 复用 SourceBlob，引用计数正确。
- [ ] 相同 source/config/parser 可复用；强制解析创建新版本并 no_cache。
- [ ] 参数覆盖不修改全局默认，config snapshot/hash 可复算。
- [ ] MinerU pending/running/converting/done/failed 正确映射。
- [ ] 轮询超时保留 providerTaskId；继续查询不重复提交上游。
- [ ] zip 下载 3 次失败后明确错误；恢复下载/标准化不重提 MinerU。
- [ ] succeeded/degraded 可选；failed/cancelled 不可选。
- [ ] 处理前后左右对比、页码、block、asset、bbox 映射正确；降级时不伪造坐标。
- [ ] 新解析版本不自动改变任何知识库绑定。
- [ ] 被 KB 草稿/活动/保留 generation 或保留期历史引用的版本不能物理删除。

## 6. 知识库创建和构建

- [ ] 创建页完成六区配置，选择/改参数不提交任务。
- [ ] 至少一个可选解析版本、验证通过 Embedding 和 capability 是后端硬校验。
- [ ] CreateKnowledgeBaseRequest 事务失败不留下半资源。
- [ ] 成功创建同时产生 config revision、generation、operation/outbox。
- [ ] 每知识库 collection/keyword namespace/chunks 独立；同模型不会共享索引状态。
- [ ] Token/段落/标题/按页/语义五种分块都有固定输入输出回归。
- [ ] 无页码的 txt/HTML/degraded 版本不能选择 page 分块并绕过后端；heading 缺失按明确 fallback 警示。
- [ ] Chunk/Parent-Child 两种结构的检索块、上下文块和来源映射正确。
- [ ] generation chunk/vector/keyword counts、维度和抽样查询验证通过后才激活。
- [ ] 首次全部成功 -> ready；部分成功 -> partial_ready；全部失败 -> unavailable。
- [ ] partial_ready 的失败数据源不参与检索并在界面/Trace 警示。

## 7. 重建可靠性

- [ ] 构建期配置保存只产生 pending revision，不修改 active generation。
- [ ] 查询期检索配置原子发布且不重建索引。
- [ ] 查询期和构建期同时变更时，retrieval revision 与 generation 绑定并在同一事务激活，不提前作用于旧索引。
- [ ] 新 generation 构建期间旧活动索引持续响应。
- [ ] 新 generation 全部成功后单事务切 active pointer 并冻结。
- [ ] 新 generation 部分/全部失败时旧 active 不变。
- [ ] 暂存 generation “只重试失败项”不重算成功项。
- [ ] 活动 partial 修复创建继任 generation，不修改已激活 generation。
- [ ] 迟到旧 Worker 完成不能覆盖较新 active pointer。
- [ ] 重复 Celery delivery 不重复创建 generation/chunk/vector/上游请求。
- [ ] 放弃/清理 generation 不会删除 active/上一个保留 generation。

## 8. 单库检索算法

- [ ] Chroma Adapter 真实使用 HNSW/锁定 metric；raw distance 到 relevanceScore 转换有单元测试。
- [ ] PostgreSQL pg_trgm GIN 被查询计划使用；不是无索引全表扫描。
- [ ] 向量、关键词、混合三种检索真实执行。
- [ ] RRF 固定样例可复算；rank 从1、rrfK 生效。
- [ ] Weighted Score 每路归一、单候选/同分边界和权重和归一正确。
- [ ] TopK、threshold、overlap、chunk 大小范围/跨字段校验前后端一致。
- [ ] HyDE、Multi-Query、Step-Back 真实调用选定 LLM；Multi-Query 数量/去重/RRF 正确。
- [ ] 重写可恢复失败降级原 query 并记录 warning。
- [ ] Rerank Model/LLM 重排类型校验、候选限制、稳定 ID 输出正确。
- [ ] 可恢复重排失败退回原顺序；配置错误使单库检索失败。
- [ ] contextWindow 不跨解析版本/Parent，去重和稳定排序正确。
- [ ] 检索测试返回完整 JSON并能复算；不写 ChatRun/在线指标。

## 9. 机器人和多库融合

- [ ] 创建多个机器人并任意绑定多个 ready/partial KB。
- [ ] priority 1-10 与权重公式精确一致。
- [ ] 跨库只使用本库 rank/权重 RRF，不比较原始分数。
- [ ] exact provenance duplicate 合并贡献；仅文本相似不合并。
- [ ] finalContextTopK 与 KB finalTopK 字段/API/页面不混淆。
- [ ] token 预算含模型 window、Prompt、query、output reserve；不超限。
- [ ] 首条超长上下文确定性截断并保留来源，其他候选完整加入/跳过。
- [ ] 有历史时 standalone rewrite；失败用原问题；历史不进入企业事实来源。
- [ ] 每库检索 generation/revision 在请求开始冻结。
- [ ] 部分 KB 失败但有上下文继续回答并记录 warning。
- [ ] 部分 KB 失败且其余正常 no-hit 时整体失败，不提示“知识库没有”且不调用通用 LLM 兜底。
- [ ] 所有 KB failed 或全 skipped 返回服务错误，不伪装 no-hit。
- [ ] 正常 no-hit 固定提示；message_then_llm 标记 general_model，无 KB citations。
- [ ] 文档 Prompt 注入样例不能改变系统角色、泄露 Prompt 或触发工具执行。

## 10. 引用

- [ ] 每个进入 Prompt 的 context 有 S 编号和完整 provenance。
- [ ] 返回 citation 能追溯 KB/generation/chunk/parsed version/data source/page/block/asset。
- [ ] snippet 来自标准化原文，不是 LLM 重写。
- [ ] 模型未知 citation ID 被移除；一次修复失败标记 degraded。
- [ ] 不在 Prompt 的来源不能出现在 citations。
- [ ] none/simple/standard/full 正确裁剪，不泄露本地路径和后台分数。
- [ ] 数据源删除/临时附件过期后历史 citation 显示 deletedOrExpired，不跳错对象。

## 11. Webhook/API

- [ ] 创建渠道实例只显示一次 256-bit API Key，数据库只有 SHA-256 hash。
- [ ] API Key 错误统一 401，不泄露 instance 存在性。
- [ ] 轮换后旧 Key 立即失效。
- [ ] 所有外部 POST 缺 Idempotency-Key 被拒绝。
- [ ] 相同 key/body 返回同结果；同 key 不同 body 返回 409。
- [ ] conversationId 不传时系统生成并返回，复用后连续对话生效。
- [ ] 同步文本在60秒内返回；超时504不返回半截答案。
- [ ] 异步返回202/operationId，只有本实例 Key 可查询。
- [ ] 临时附件只允许 ready 用于 sync；解析型附件走 async，24h清理。
- [ ] 持久渠道上传只进入解析数据源库，不自动绑定 KB。
- [ ] rate limit/并发超限返回429和 Retry-After。
- [ ] callback HMAC/时间戳校验样例通过；初始投递后最多5次退避（总计6次）和永久4xx规则正确。
- [ ] callback 失败不修改成功 ChatRun；人工重发创建新 delivery。

## 12. Operation/Outbox/任务中心

- [ ] 业务事务、Operation、Outbox 原子提交。
- [ ] Redis 发布失败后 outbox 重试；queued超1分钟 reconciler 补发。
- [ ] Redis 清空后未完成任务恢复，已有 providerTaskId 不重提。
- [ ] Worker crash + ack_late 重投幂等。
- [ ] parsing/indexing/chat/maintenance 队列隔离。
- [ ] queued可取消，running界面不可假取消。
- [ ] heartbeat丢失显示 stalled但不直接改业务终态。
- [ ] 任务详情有阶段、item、attempt、错误、retryable、traceId。
- [ ] 未注册的 eventType/schemaVersion 不执行任意 task，Outbox/Operation 以 `TASK_SCHEMA_UNSUPPORTED` 非重试失败并可定位。

## 13. 日志、指标和评测

- [ ] 一个 traceId 关联 HTTP、Operation、Provider、ChatRun。
- [ ] 普通日志无正文、Prompt、密钥和签名 URL。
- [ ] 敏感 Trace 加密；查看动作二次确认并审计。
- [ ] 在线命中率分母排除检索 failed；no-hit 和 retrieval failure 分开。
- [ ] admin_test 不进入外部业务量；KB retrieval test 不进 ChatRun。
- [ ] 不展示低置信度占比和跨异构平均分。
- [ ] Dataset revision、generation、retrieval revision 固定后运行。
- [ ] Hit@K、Recall@K、MRR、No-hit accuracy 固定样例可手算一致。
- [ ] 指标响应含 generatedAt/dataThrough，前端显示更新时间。
- [ ] retention 按类型分批清理，不删除业务数据源/评测集。

## 14. 前端

- [ ] 数据清洗与解析在侧栏第一项。
- [ ] 知识库/机器人同时有独立 `+` 和下拉箭头，点击互不冲突。
- [ ] 系统设置固定在问答日志下方和侧栏底部。
- [ ] 长页面只有一个主滚动容器，sticky 操作栏不遮挡最后字段。
- [ ] 1280/1440/1920 无重叠、按钮文字溢出和不可达内容。
- [ ] disabled capability 显示原因但不能提交。
- [ ] 保存/检测、上传/解析、保存构建配置/启动构建各自独立。
- [ ] 409 revision、422 fieldErrors、429、503、504 有专用 UI。
- [ ] URL 可恢复列表筛选、分页、Tab 和资源深链。
- [ ] operation polling 在终态/卸载停止，后台降频，无旧响应覆盖新状态。
- [ ] generated API client 无手写重复 DTO。

## 15. 数据库和迁移

- [ ] 空库 Alembic upgrade 到 head。
- [ ] 上一发布 schema upgrade 到 head，数据不丢。
- [ ] 所有 FK/unique/check/partial index 生效并有反例测试。
- [ ] generation frozen 后数据库/Repository 阻止 chunk/item 修改。
- [ ] `lower(name)` 部分唯一避免已删除对象阻塞新名称。
- [ ] pg_trgm extension/GIN 创建成功。
- [ ] ChatRun/citation 不被业务对象删除级联。
- [ ] Outbox active idempotency unique constraint 生效。
- [ ] 数据库无 Provider/MinerU/渠道明文 secret。

## 16. 部署、容量和恢复

- [ ] Windows Docker Desktop 依赖 + 本地 API/四类 Worker/前端可按文档启动。
- [ ] Linux Compose 完整栈从空机启动，数据库/Redis/Chroma无公网端口。
- [ ] 依赖镜像/包无 floating latest。
- [ ] `/health/live/ready/dependencies` 与退出码正确。
- [ ] PostgreSQL、Redis、Chroma、Storage、Worker、MinerU/模型分别中断时返回正确 degraded/error。
- [ ] 8vCPU/32GB基线完成 50 KB、5000 sources、50万 chunks 数据准备或等价可重复 benchmark。
- [ ] 10并发问答无数据损坏，记录 P50/P95/P99和错误率。
- [ ] 2并发解析/2并发构建不会队列饥饿或阻塞 chat。
- [ ] 磁盘低于15%告警、低于5%阻止新大写入但保持读取。
- [ ] 每日备份生成 manifest/checksum并存独立位置。
- [ ] 在干净环境实际恢复 PostgreSQL/Storage/Chroma或重建，抽测解析来源、检索、引用和机器人。
- [ ] 恢复记录满足默认 RPO24h/RTO4h或注明实际结果。

## 17. 工程质量

- [ ] Backend Ruff/typecheck/pytest 全通过。
- [ ] Frontend lint/typecheck/Vitest/Playwright 全通过。
- [ ] 核心 domain/algorithm line+branch coverage >=90%。
- [ ] 后端总体 line >=80%，前端业务逻辑/组件 >=75%。
- [ ] Adapter contract、故障注入、API状态码和OpenAPI breaking diff通过。
- [ ] Alembic、secret、依赖漏洞和容器配置扫描通过。
- [ ] Bruno collection 由已测 OpenAPI 示例生成并可执行。
- [ ] 仓库无 TBD/TODO 核心需求、明文 secret、临时文件和未归类生成物。

## 18. 发布结论

发布负责人填写：

- 应用版本：
- 数据库 revision：
- OpenAPI hash：
- 测试报告位置：
- E2E 截图/视频位置：
- 性能报告位置：
- 安全扫描位置：
- 备份恢复演练记录：
- 未通过项及已批准风险：
- 最终结论：`PASS / FAIL`。

任何 P0 闭环、安全秘密、活动索引保护、正常无命中/系统失败区分、恢复演练未通过时，最终结论必须为 FAIL。
