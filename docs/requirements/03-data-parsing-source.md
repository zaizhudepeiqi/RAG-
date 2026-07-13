# 数据清洗与解析阶段性真源

> 文档职责：定义原始文件上传、Parser 选择、MinerU 调用、解析版本、标准化产物、处理前后对比及解析错误。
> 知识库只能消费本模块产出的不可变解析版本，不能在知识库模块内上传或解析原始文件。

## 1. 模块定位

“数据清洗与解析”是独立一级模块，也是侧边栏第一个业务入口。

固定流程：

```text
上传原始文件
  -> 校验和安全扫描
  -> 创建 DataSource / SourceBlob
  -> 选择或确认解析参数
  -> 提交解析
  -> Parser 处理
  -> 下载并标准化结果
  -> 处理前后对比
  -> 产出可复用 ParsedSourceVersion
  -> 知识库创建页选择该版本
```

解析成功不会自动进入任何知识库，不会自动分块、Embedding 或写入 Chroma。

## 2. 支持范围

“支持所有形式的数据源”的可执行定义是：**支持 Parser capability 明确声明、通过文件校验且后端真实实现的全部格式**。不能承诺任意未知格式均可解析。

第一版：

| 类型 | 扩展名 | Parser |
|---|---|---|
| PDF | `pdf` | MinerU Precision API |
| 图片 | `png/jpg/jpeg/jp2/webp/gif/bmp` | MinerU Precision API，支持 OCR |
| Word | `doc/docx` | MinerU Precision API |
| PowerPoint | `ppt/pptx` | MinerU Precision API |
| Excel | `xls/xlsx` | MinerU Precision API |
| HTML | `html/htm` | MinerU Precision API，`MinerU-HTML` |
| 纯文本 | `txt/md` | `builtin_text`，保留原始结构 |
| 结构化文本 | `csv/json` | `builtin_text`，规范化后保留原始值 |
| 批量容器 | `zip` | 系统安全解压；其中每个文件分别路由 Parser |

规则：

- 前端允许格式来自 `parser-input-types` capability，不能维护另一份列表。
- 扩展名、MIME 和文件魔数必须交叉校验；只改扩展名不能绕过限制。
- `zip` 不是 Parser 输入格式，不生成一个“大 ZIP 文档”；每个合法 entry 成为独立数据源。
- 第一版不递归展开 ZIP 内 ZIP，不支持加密 ZIP。
- 不支持格式在上传前后端均返回 `SOURCE_TYPE_UNSUPPORTED`。

后续通过 `ParserAdapter` 增加音频、视频、网页抓取、数据库连接器、对象存储或自定义格式。

## 3. 上传约束

第一版固定限制：

- 单文件最大 200 MB。
- 单次普通上传最多 20 个文件。
- ZIP 内最多 100 个文件。
- ZIP 解压后总大小最大 1 GB。
- 单个 ZIP entry 仍受 200 MB 限制。
- ZIP 最大压缩比 100:1；超过则拒绝，防止 ZIP bomb。
- 文件名最大 255 字符，ZIP 相对路径最大 1024 字符。
- 禁止绝对路径、盘符、`..` 路径穿越、符号链接和设备文件。
- 空文件拒绝。

上传采用流式落盘并同步计算 SHA-256，不把整个文件读入内存。文件先写 `.uploading` 临时路径，完成大小和校验和验证后原子移动到正式 blob 路径。

批量上传是部分成功语义：每个文件返回自己的结果；一个文件失败不回滚其他成功文件。响应包含 `accepted[]` 和 `rejected[]`。

## 4. 数据源和文件去重

`SourceBlob` 使用 SHA-256 标识物理内容；同一内容只保存一份物理文件，可被多个逻辑数据源引用。

`DataSource` 保存：

- `id`。
- `displayName`。
- `sourcePath`，ZIP 上传时保留包内相对路径。
- `originalFileName`。
- `extension`、`mimeType`、`sizeBytes`、`sha256`。
- `originType`: `admin_upload / channel_ingest / future_connector`。
- `sourceBlobId`。
- `createdAt / deletedAt`。

名称不是唯一键。同名不同内容允许存在，界面同时显示大小、SHA-256 短摘要和上传时间，避免误选。

发现相同 SHA-256 时：

- 默认复用已有 `SourceBlob`。
- 如果已有相同逻辑数据源，前端提示并默认复用该数据源；管理员仍可创建新的逻辑别名。
- 复用物理文件不代表复用解析结果；是否复用解析版本还要比较 Parser 和 `configHash`。

## 5. Parser 路由

前端解析方式默认显示“自动”，由后端根据文件类型选择：

- MinerU 官方支持格式 -> `mineru_precision_api`。
- 已是可读文本的 `txt/md/csv/json` -> `builtin_text`。
- HTML -> `mineru_precision_api` + `MinerU-HTML`。

后端最终决定并返回实际 `parserCode`、`parserVersion` 和原因。第一版不允许用户选择尚未实现的 Parser。

`ParserAdapter` 统一契约至少包括：

```text
describe_capability()
validate_input(source, config)
submit(source, config, idempotency_key)
poll(provider_task_id)
download_result(provider_task_id)
normalize(raw_result)
```

领域层不依赖 MinerU 的字段名和状态值；Adapter 将其映射为系统状态和统一产物。

## 6. 解析配置

系统设置保存全局默认值；上传/重新解析时可展开“本次解析设置”覆盖。覆盖只影响新建解析版本，不修改全局默认，也不改变已有版本。

统一解析配置：

```ts
type ParseConfig = {
  parserCode: string;
  modelVersion: "pipeline" | "vlm" | "MinerU-HTML" | "builtin";
  language: string;
  ocrEnabled: boolean;
  tableEnabled: boolean;
  formulaEnabled: boolean;
  pageRanges?: string;
  extraFormats: string[];
  forceProviderRefresh: boolean;
};
```

第一版默认：

- 非 HTML MinerU 模型：`pipeline`。
- HTML 自动强制：`MinerU-HTML`。
- `language = ch`。
- `ocrEnabled = false`，扫描件或图片由管理员按需开启。
- `tableEnabled = true`。
- `formulaEnabled = true`。
- `extraFormats = []`，Markdown/JSON 为 MinerU 默认产物。
- `forceProviderRefresh = false`。

参数由 Parser capability 的 JSON Schema/UI Schema 渲染。后端按文件类型处理“参数不适用”，不能假装已生效。

`configHash` 使用规范化 JSON 计算，必须包含 Parser code/version、有效参数、标准化器版本。键顺序和无效 UI 字段不能改变 hash。

## 7. 解析版本与复用

`ParsedSourceVersion` 字段至少包括：

- `id / dataSourceId / versionNumber`。
- `parserCode / parserVersion / normalizerVersion`。
- `configSnapshot / configHash`。
- `sourceSha256`。
- `status / progress`。
- `providerTaskId / providerTraceId`。
- `qualityLevel: full / degraded`。
- `rawResultPath / normalizedResultPath`。
- `blockCount / assetCount / pageCount / markdownCharCount`。
- `featureFlags`：`hasText/hasPages/hasHeadings/hasBoundingBoxes/hasAssets/hasTables/hasFormulas`。
- `createdAt / startedAt / finishedAt`。
- `errorCode / errorMessage / retryable`。

复用键：

```text
sourceSha256 + parserCode + parserVersion + configHash
```

完全匹配且已有 `succeeded/degraded` 版本时，界面提供：

- “复用已有解析结果”：默认推荐，不调用 MinerU。
- “强制重新解析”：创建新版本；MinerU Precision Adapter 请求设置 `no_cache=true`。

参数不同或 Parser 版本不同必须创建新解析版本。新版本不会自动替换任何知识库绑定。

## 8. MinerU Precision API

第一版只集成官方 Token 模式的 Precision API，不依赖 Windows 桌面端，也不实现 MinerU MCP。

官方协议基线（2026-07-12 核对）：

- 鉴权：`Authorization: Bearer <Token>`。
- 单 URL 提交：`POST /api/v4/extract/task`。
- 本地批量上传 URL：`POST /api/v4/file-urls/batch`，每批最多 50 个 URL；后端把更大系统批次拆批。
- 单任务查询：`GET /api/v4/extract/task/{task_id}`。
- 单文件最大 200 MB、最大 200 页。
- 官方状态包括 `pending / running / converting / done / failed`。
- 完成后通过 `full_zip_url` 下载结果。
- 第一版使用轮询，不使用 MinerU callback。

MinerU API 细节只能存在于 `MinerUPrecisionAdapter`；业务 DTO 不向前端暴露供应商请求结构。

批量上传流程：

1. 后端已完成本地文件落盘和系统任务创建。
2. Worker 按兼容配置最多 50 个文件申请 signed upload URLs。
3. 每个文件传入稳定 `data_id=parsedSourceVersionId`，保存返回的 `batch_id`；不得假定申请上传 URL 后已经得到单文件 `task_id`。
4. Worker 逐个 PUT 上传；不得记录完整签名 URL。
5. 上传完成后 MinerU 自动提交任务；Adapter 使用官方批次结果查询能力按 `batch_id` 查询，并用 `data_id` 映射回每个 ParsedSourceVersion。
6. 如果官方批次响应明确返回单文件 task_id，则保存供诊断；业务流程不能依赖它一定存在。
7. Adapter 将批次项状态映射为系统状态。
8. 完成后立即下载 zip，因为签名下载 URL 可能过期。

MinerU 批次结果查询的精确供应商路径、字段和删除接口属于 `MinerUPrecisionAdapter` 版本化契约，不进入本系统 API。实现该 Adapter 时必须用当时官方文档和真实响应 fixture 锁定；字段变化发布新的 Adapter contract version，禁止凭记忆硬编码或把 batch_id 当 task_id。

轮询默认值：

- 前 1 分钟每 3 秒。
- 1 至 10 分钟每 10 秒。
- 10 分钟后每 30 秒。
- 总超时 30 分钟，可在系统设置 5 至 120 分钟内调整。
- 轮询网络瞬时错误最多连续 5 次；成功响应后连续错误计数清零。

官方任务超时后本系统标记失败但保留 `providerTaskId`。管理员点击“继续查询上游任务”时先查询原任务；只有确认原任务失败/不存在或管理员选择“创建新任务”时才重新提交，避免重复计费。

## 9. 状态机

解析版本状态：

```text
queued
  -> submitting
  -> uploading
  -> provider_pending
  -> parsing
  -> downloading
  -> normalizing
  -> succeeded | degraded | failed

queued -> cancelled
```

规则：

- `builtin_text` 可跳过 submitting/uploading/provider_pending/parsing/downloading，但必须进入 normalizing。
- `degraded` 表示可得到可索引文本，但缺少部分 block、坐标或资产；可以被知识库选择，界面必须警示质量影响。
- `failed` 不能被知识库选择。
- 只允许取消 `queued`；已向 MinerU 提交的任务第一版不宣称可以取消。
- 供应商原始状态保存到任务详情，不扩散成领域枚举。

进度为可选估算值，不能仅由 `progress=100` 判断成功，最终状态才是真源。

## 10. 结果标准化

所有 Parser 输出统一为：

```text
ParsedSourceVersion
  markdown
  pages[]
  blocks[]
  assets[]
  sourceMap
```

`ParsedBlock` 至少包含：

- `blockId / blockType / orderIndex`。
- `text / markdown`。
- `headingLevel / headingPath`。
- `pageNumber / boundingBox`。
- `assetIds`。
- `rawLocator`，用于追溯 Parser 原始结构。

`ParsedAsset` 至少包含：

- `assetId / assetType / mimeType`。
- `pageNumber / boundingBox`。
- `storageKey / sha256 / sizeBytes`。
- `caption / ocrText`。

来源关系必须能从标准化 block 回到原始页码、坐标和 MinerU 原始结构。无法提供精确坐标时字段为 null，并说明 `qualityLevel=degraded`，不能伪造坐标。

## 11. full_zip 兼容和安全

- 原始 zip 完整保存并记录 SHA-256。
- 解压前执行 ZIP 安全规则，解压到版本独立临时目录。
- 不能假设 zip 始终有固定文件名；先匹配已知结构，再按 JSON 内容特征识别。
- 至少识别全文 Markdown 或等价文本才能降级成功。
- 所有文件都无法识别时失败并保留原始产物供排查。
- 标准化器有独立版本；兼容规则升级不能原地改写历史版本，应创建新的标准化/解析版本。

错误码：

- `PARSER_ARCHIVE_INVALID`。
- `PARSER_ARCHIVE_UNSAFE`。
- `PARSER_OUTPUT_EMPTY`。
- `PARSER_OUTPUT_UNSUPPORTED`。
- `PARSER_NORMALIZATION_FAILED`。

## 12. 处理前后对比

解析详情使用同一页面的左右对比：

- 左侧：原始 PDF/图片/Office 转预览；不支持浏览器直接预览时提供文件信息和安全下载。
- 右侧 Tabs：Markdown、Blocks、OCR、表格、公式、Assets、原始产物清单。
- 页码联动：选择右侧 block 时跳到左侧页码并在存在 boundingBox 时高亮。
- 降级版本明确展示缺失能力，不能让用户误以为有精确坐标。
- 只读，不在第一版编辑 Markdown、OCR、block 或 asset。

数据源库列表展示：名称、格式、大小、SHA-256 摘要、来源、最新解析版本、版本数量、状态、创建时间、被多少知识库修订/活动代次引用。

## 13. 删除和保留

- 删除数据源先业务软删除。
- 任一解析版本仍被知识库草稿配置、活动代次或保留期内构建引用时，拒绝物理删除并返回引用清单。
- 无引用时异步清理解析版本、标准化产物并减少 `SourceBlob` 引用计数。
- blob 引用计数归零且无保留要求后才删除物理文件。
- 历史 ChatTrace 不依赖物理文件继续存在；引用快照可显示来源已删除。

## 14. 错误和重试

系统错误按阶段区分：

- 上传：`SOURCE_FILE_TOO_LARGE / SOURCE_FILE_EMPTY / SOURCE_TYPE_UNSUPPORTED`。
- MinerU 鉴权/限流：`MINERU_AUTH_FAILED / MINERU_RATE_LIMITED / MINERU_QUOTA_EXCEEDED`。
- 提交/上传/轮询：`MINERU_SUBMIT_FAILED / MINERU_UPLOAD_FAILED / MINERU_POLL_FAILED / MINERU_TIMEOUT`。
- 下载/解压/标准化：`MINERU_RESULT_DOWNLOAD_FAILED / PARSER_ARCHIVE_INVALID / PARSER_NORMALIZATION_FAILED`。

Provider Adapter 内部仅对网络错误、429、5xx 做最多 3 次短退避重试。整个解析 operation 不因 task 自动重试而重新提交 MinerU；需要由上述“继续查询/创建新任务”规则决定。

日志保存脱敏 `rawError`、发生阶段、providerTaskId、providerTraceId 和 retryable，绝不保存 Token 或完整签名 URL。

## 15. 合规提示

使用 MinerU Cloud API 意味着企业原始文件会上传至第三方云服务。系统设置、上传确认和部署文档必须明确显示这一事实。

第一版首次启用 MinerU 前必须由管理员确认；纯内网或敏感资料场景应等待后续 `mineru_local`/私有 Parser Adapter，不能把云 API 描述成完全私有化解析。

## 16. 验收

- 相同文件和相同配置可复用结果，强制重解析产生新版本。
- 新解析版本不会自动改变任何知识库。
- PDF、图片、Office、HTML 和文本格式按 capability 正确路由。
- ZIP 路径穿越、压缩炸弹、嵌套 ZIP 和伪造类型被拒绝。
- MinerU 任务重复投递不会创建重复上游任务。
- 处理前后可以按页和 block 追溯；无坐标时明确降级。
- 解析失败不会创建可选知识库数据源版本。
- 删除被引用解析版本会被后端阻止并返回引用清单。
