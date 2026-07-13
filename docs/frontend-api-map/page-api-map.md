# 前端页面 / 控件 / API 对照表

> 上游：`docs/requirements/09-frontend-source.md`、`docs/api/v1-api-contract.md`。
> 每个可交互控件必须出现在本表；新增控件前先更新本文件。

## 1. 全局布局

| UI | 行为 | API/数据 |
|---|---|---|
| 应用初始化 | 读取管理员、能力和运行摘要 | `GET /auth/me`；按页面加载 capabilities |
| 退出 | 清 Cookie，回登录 | `POST /auth/logout` |
| 顶部全局任务入口 | 显示 running/failed 数和最近任务 | `GET /operations?status=queued,running,failed&pageSize=10` |
| traceId 复制 | 复制当前错误 traceId | 纯前端，不发请求 |
| 通用能力下拉 | 按 category 拉 enabled/disabled options | `GET /capabilities?category=...&includeDisabled=true` |

所有创建资源/Operation 的 POST 由 API client 自动生成 UUID `Idempotency-Key`；同一次用户提交和网络重试复用同一个 key，新一次人工操作生成新 key。

所有表中列出的后端请求必须调用 `@umijs/max-plugin-openapi` 生成的 `src/services/ragApi` service，并统一经过 `src/app.tsx` 导出的 Umi `request` 配置。页面不得手写重复 DTO、URL wrapper 或第二套 Axios/fetch client。

侧栏：

| 项 | 主点击 | `+` | 下拉箭头 |
|---|---|---|---|
| 数据清洗与解析 | `/parsing` | 无 | 无 |
| 仪表盘 | `/dashboard` | 无 | 无 |
| 知识库管理 | `/knowledge-bases` | `/knowledge-bases/create` | 最近访问 + 全部；最近项来自 KB list API |
| 机器人管理 | `/bots` | `/bots/create` | 最近访问 + 全部；最近项来自 Bot list API |
| 模型配置 | `/models` | 无 | 无 |
| 渠道接入 | `/channels` | 无 | 无 |
| 任务中心 | `/tasks` | 无 | 无 |
| 问答日志 | `/chat-logs` | 无 | 无 |
| 系统设置 | `/settings`，固定底部 | 无 | 无 |

最近访问存在小型 Umi model/local persistence，只保存 ID 和时间；展示时仍调用 detail/list 验证资源存在，不能保存业务快照作为真源。

## 2. 登录 `/login`

| 控件 | DTO 字段 | API | 成功 | 错误 |
|---|---|---|---|---|
| 用户名 | username | `POST /auth/login` | 设置 Cookie/CSRF | 字段下/页面错误 |
| 密码 | password | 同上 | 跳目标页或改密 | 不区分用户名/密码 |
| 登录 | LoginRequest | 同上 | `firstLoginRequired` 时 `/settings?tab=security` | 429 显示 Retry-After |

首次改密弹窗/页：oldPassword/newPassword/confirmPassword -> `POST /auth/change-password`。

## 3. 数据清洗与解析 `/parsing`

### Tab：上传与解析任务

加载：

- `GET /capabilities?category=parser_input_type`。
- `GET /settings/mineru`（只读默认值/Token configured）。
- `GET /operations?taskType=parse_source_version&page=1&pageSize=20`。

| 控件/动作 | API | 结果 |
|---|---|---|
| 选择/拖拽文件 | 无，先本地检查 extension/size/count | 待上传队列 |
| 上传 | `POST /data-sources/uploads` multipart | 每文件 accepted/rejected |
| 解析参数“使用默认/本次覆盖” | capability schema + ParseConfig | 只改变表单 |
| 开始解析 | 每 source 调 `POST /data-sources/{id}/parse` | version + operation |
| 完全重复“复用” | parse request reuseMode=reuse_if_exact | 已有 version/ref |
| 强制重解析 | reuseMode=force_new | 新 version/operation |
| 查看任务 | `GET /operations/{id}` | 右侧任务抽屉 |
| 取消 | `POST /operations/{id}:cancel` | 仅 queued |

上传按钮和开始解析分开；上传成功不自动解析。

### Tab：处理前后对比

- 数据源/版本选择：`GET /data-sources`、`GET /data-sources/{id}/versions`。
- 原文：`GET /data-sources/{id}/original?disposition=inline`。
- Markdown：`GET /parsed-source-versions/{id}/markdown`。
- Blocks：`GET /parsed-source-versions/{id}/blocks?pageNumber=&blockType=`。
- Assets：`GET /parsed-source-versions/{id}/assets`，资源流 endpoint。
- 任务/错误：version detail + operation detail。

左右页码联动是前端状态，不调用写 API。

### Tab：已解析数据源

加载：`GET /data-sources`。

| 动作 | API |
|---|---|
| 重命名显示名 | `PATCH /data-sources/{id}` + expectedRevision |
| 查看版本 | 路由 `/parsing/sources/:id` |
| 重新解析 | `POST /data-sources/{id}/parse` |
| 删除 | `DELETE /data-sources/{id}` + expectedRevision |
| 查看引用 | detail 的 reference summary；需要时使用 KB 筛选 |

## 4. 数据源详情 `/parsing/sources/:dataSourceId`

加载：

- `GET /data-sources/{id}`。
- `GET /data-sources/{id}/versions`。

版本行操作：

- 查看对比 -> `/parsing/versions/:parsedSourceVersionId`。
- 继续查询上游 -> `POST /parsed-source-versions/{id}:resume-provider-query`。
- 基于当前配置重新解析 -> `POST /parsed-source-versions/{id}:create-reparse`。
- 删除版本 -> `DELETE /parsed-source-versions/{id}`。

删除被引用时 `details.references` 在确认弹窗/错误抽屉展示，不把按钮简单隐藏。

## 5. 仪表盘 `/dashboard`

并行加载：

- `GET /analytics/overview`。
- `GET /analytics/tasks`。
- `GET /analytics/rag`。
- `GET /analytics/models`。
- `GET /analytics/problem-queries?pageSize=20`。

时间范围/机器人/知识库筛选写 URL query，并作为 API query。图表点击跳对应列表并携带筛选，不触发业务写操作。

“无命中”和“检索失败”分 Tab；加入评测集操作打开弹窗，最终调用 dataset case 创建 API。

## 6. 知识库列表 `/knowledge-bases`

加载：`GET /knowledge-bases?search=&status=&modelId=&retrievalType=&page=&sort=`。

| 动作 | API/路由 |
|---|---|
| 创建 | `/knowledge-bases/create` |
| 查看/编辑 | `/knowledge-bases/:id` |
| 启用 | `POST /knowledge-bases/{id}:enable` |
| 停用 | `POST /knowledge-bases/{id}:disable` |
| 删除 | `DELETE /knowledge-bases/{id}` |
| 查看构建任务 | operation 抽屉 |

列表展示 API 返回的 derivedDisplayStatus/allowedActions，不在表格按 task 文本推断。

## 7. 创建知识库 `/knowledge-bases/create`

提交：`POST /knowledge-bases`。

### 基础信息

| UI | DTO |
|---|---|
| 名称 | name |
| 描述 | description |

### 已解析数据源

- 选择器数据：`GET /data-sources?parseStatus=succeeded,degraded`，再加载版本。
- 保存：`parsedSourceVersionIds[]`。
- degraded 显示警告；重复同一 data source 多版本要求二次确认。
- 选择器展示 featureFlags；分块策略选择后按 capability required/preferred features 即时标记不兼容项，硬不兼容时禁用最终提交。

### Embedding/向量索引

- 模型：`GET /models?modelType=embedding&enabled=true&verificationStatus=passed`。
- vector store/index：capability API。
- 字段：buildConfig.embeddingModelId/embeddingParams/vectorStoreCode/vectorIndexCode/vectorIndexParams。

### 分块/索引结构

- capabilities：index_structure、chunk_strategy。
- 字段：buildConfig.indexStructure/chunkStrategyCode/chunkParams。
- SchemaForm 按策略切换，清除不适用字段。

### 检索/重写/重排

- capabilities：retrieval_type/fusion_strategy/query_rewrite/rerank。
- 条件模型下拉按 llm/rerank 类型加载。
- 字段：retrievalConfig 完整对象。

### 最终确认

- 前端只做摘要；点击“创建并构建”发送完整 DTO。
- 201 后跳 `/knowledge-bases/:id?tab=overview&operationId=...`。
- 422 根据 fieldErrors 自动展开/定位对应分区。

## 8. 知识库详情 `/knowledge-bases/:id`

共同加载：`GET /knowledge-bases/{id}`。

### 概览

- active generation：detail。
- latest operation：`GET /operations/{id}`。
- 绑定机器人：`GET /bots?knowledgeBaseId={id}`（API 实现该筛选）。
- 启停/删除调用列表同端点。

### 数据源

- 活动与 pending source snapshot：`GET /knowledge-bases/{id}/build-config`。
- 增加/移除/替换只修改本地 pending 表单。
- 保存 pending：`PUT /knowledge-bases/{id}/pending-build-config`。
- 不直接触发 build。

### 构建配置

- 活动/待发布 config 同 endpoint。
- 保存：同 pending-build-config。
- 放弃：`DELETE /knowledge-bases/{id}/pending-build-config`。
- 构建：`POST /knowledge-bases/{id}/generations`。

### 检索配置

- 加载 `GET /knowledge-bases/{id}/retrieval-config`。
- 保存 `PUT /knowledge-bases/{id}/retrieval-config`。
- 没有 pending build changes 时使用 `activationMode=auto` 并立即激活。
- 存在不兼容 pending build changes 时使用 `activationMode=with_pending_generation`；响应显示“等待新索引一起生效”，不能把 pending 参数展示成当前活动参数。

### 检索测试

- `POST /knowledge-bases/{id}/retrieval-tests`。
- 复制 JSON纯前端。
- 保存临时参数调用 retrieval-config PUT。

### 质量评测

- dataset/cases/runs API 见接口契约。
- 运行返回 operation，轮询 operation + run detail。

### 构建历史

- `GET /knowledge-bases/{id}/generations`。
- 查看：generation detail。
- 重试失败：`:retry-failed`。
- 放弃暂存：`:discard`。

## 9. 模型配置 `/models`

### Provider 列表/详情

- 列表：`GET /model-providers`。
- 创建：`POST /model-providers`。
- 保存和测试分开：PATCH 与 `:test`。
- 发现模型：`:discover-models`，随后加载 discovered list。
- 删除：DELETE；被引用/有模型时展示 references error。

字段：providerType/displayName/baseUrl/credential。credential 留空不替换。

### Model 列表/详情

- 列表：`GET /models`。
- 创建：POST。
- 测试：`:verify`。
- 启用/停用：对应 action endpoint。
- 引用：`GET /models/{id}/references`。
- 删除：DELETE。

业务身份字段被引用时只读；displayName 可 PATCH。

## 10. 机器人列表与创建

列表 `/bots`：`GET /bots`；删除 `DELETE /bots/{id}`。

创建 `/bots/create`：

| 分区 | 数据/API | DTO |
|---|---|---|
| 基础 | 无 | name/description |
| 回答模型 | LLM model list | answerModelId/answerModelParams |
| Prompt | `GET /bots/defaults` | systemPrompt |
| 知识库 | `GET /knowledge-bases?status=ready,partial_ready` | knowledgeBases[]/priority |
| 融合预算 | 固定 rank_fusion | mergeConfig |
| 记忆 | 固定字段 | memoryConfig |
| 无命中 | enum | noHitPolicy |

提交 `POST /bots`，成功跳详情。

## 11. 机器人详情 `/bots/:botId`

- 加载 `GET /bots/{id}`。
- 保存完整配置：`PUT /bots/{id}` + expectedRevision。
- 测试：`POST /bots/{id}/chat-tests`。
- 渠道 Tab：`GET /channel-instances?botId={id}`。
- 日志 Tab：`GET /chat-runs?botId={id}`。
- 删除：DELETE；有渠道绑定时展示 references。

测试视图按 BotChatResponse 和 Trace 阶段展示，不自行复算后端 RRF。

## 12. 渠道接入 `/channels`

- 列表：`GET /channel-instances`。
- 创建：`POST /channel-instances`；弹窗一次性展示 apiKey，可下载/复制但不可再次读取。
- 编辑：PATCH。
- 检测：`:test`，与保存分开。
- 启停：`:enable/:disable`。
- 轮换：`:rotate-api-key` / `:rotate-callback-secret`，危险确认。
- 删除：DELETE。
- 调用示例：由 OpenAPI/Bruno 示例数据生成 curl/JS/Python，不手写字段。

未来 Adapter disabled 项显示 unavailableReason，不能进入创建下一步。

## 13. 任务中心 `/tasks`

- 列表：`GET /operations`。
- 详情抽屉：`GET /operations/{id}`。
- 取消：`:cancel`，仅 allowedActions 包含 cancel。
- 重试：`:retry`，返回新 operationId 并跳新任务。
- generation item 失败详情来自 operation items + generation detail。

轮询策略按前端真源。终态停止；stalled 只提示，不自动变 failed。

## 14. 问答日志 `/chat-logs`

- 列表：`GET /chat-runs`。
- 摘要：`GET /chat-runs/{id}`。
- 脱敏 Trace：`GET /chat-runs/{id}/trace`。
- 敏感正文：`POST /chat-runs/{id}:reveal-sensitive`，先输入查看理由/确认，后端审计。
- 复制 traceId/导出摘要纯前端；大导出走 operation。

各阶段折叠与 API Trace schema 顺序一致。

## 15. 系统设置 `/settings`

### MinerU

- GET/PATCH `/settings/mineru`。
- 测试 `/settings/mineru:test`，返回 operation。
- Token 留空不替换；连接测试提示云端外发/额度。

### 保留

- GET/PATCH `/settings/retention`。
- 手动清理通过 maintenance operation endpoint（API 实现 `POST /retention-cleanups`，在正式 OpenAPI 加入）并二次确认。

### 管理员安全

- `POST /auth/change-password`。
- 首次改密强制。

### 运行环境

- `GET /settings/runtime`、`GET /health/dependencies` 只读。
- 物理 storage path 只展示脱敏/逻辑信息，不允许页面修改。

## 16. 通用错误映射

| HTTP/code | UI |
|---|---|
| 401 admin | 清登录态，跳 `/login` |
| AUTH_PASSWORD_CHANGE_REQUIRED | 强制改密页 |
| 409 RESOURCE_REVISION_CONFLICT | 页面阻塞弹窗，重新加载，不自动覆盖 |
| 409 *_IN_USE | 引用清单抽屉，提供跳转 |
| 422 fieldErrors | 定位字段和折叠区 |
| 429 | 显示 Retry-After，按钮暂时禁用 |
| 502/503 | 页面依赖错误状态，保留已有数据并可重试 |
| 504 | 同步超时，展示 traceId；有 operationId 时跳任务 |
| 5xx | 通用错误区/抽屉，不只 toast |

## 17. Loading/Empty/Error

每个页面都需要：

- 首次 skeleton/loading。
- 空列表和清晰主操作。
- 部分 API 失败（例如概览成功、图表失败）局部错误，不清空整页。
- 重试只重发失败 query。
- 旧数据 + refreshing 状态，避免轮询闪烁。
- 删除/终态后 query cache 精确失效，不全局刷新所有 API。

## 18. 页面/API 验收

- 所有可见按钮均能在本文件找到唯一 endpoint 或明确纯前端行为。
- KB 创建字段完整映射 CreateKnowledgeBaseRequest。
- Bot 字段完整映射 CreateBotRequest，finalContextTopK 不与 KB finalTopK 混淆。
- 保存/检测、上传/解析、保存配置/构建任务均为独立操作。
- 前端不调用未列出的 URL，不使用 Mock DTO 进入生产。
- 409、422、429、503 和 operation 轮询有 E2E 覆盖。
- 侧栏菜单、`+`、下拉和底部系统设置在所有路由一致。
