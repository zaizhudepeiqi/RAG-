# 当前开发交接

> 更新时间：2026-07-20（Asia/Shanghai）
> 用途：会话恢复和阶段状态摘要；需求定义以 `docs/requirements` 为唯一真源。

## 1. 工作位置

- 仓库根目录：`D:\RAG知识库`
- 当前 worktree：`D:\RAG知识库\.worktrees\phase-02-models-parsing`
- 当前分支：`codex/phase-02-models-parsing`
- Phase 02 入口提交：`f78e5cf fix: generate Umi types before frontend checks`
- 远端：`https://github.com/zaizhudepeiqi/RAG-.git`
- 禁止直接在 `main` 或 Phase 01 worktree 开发 Phase 02。

## 2. 已完成基线

Phase 01 已 fast-forward 合并并推送到 `main`。合并验证发现并修复两个冷启动缺陷：

- `19ffe3b`：为 `.jsx` 强制 LF，并在仓库检查中锁定该属性。
- `f78e5cf`：前端 `check` 显式先运行 `max setup`，不再依赖残留 `.umi`。

在全新 Phase 02 worktree 中确认初始没有 `.umi`；`npm ci` 后仍没有；随后 `npm run check` 显式生成并通过 Biome、TypeScript、15 个 Jest 测试和生产构建。后端锁定环境也已通过 `uv sync --frozen --all-groups` 安装。

## 3. 当前任务

当前状态：**IMPLEMENTATION IN PROGRESS (PHASE 2A)**。

执行计划：`docs/implementation/02a-model-registry-implementation-plan.md`。

02A 实现：

1. model provider/model type capability。
2. Provider/Model/Verification/Discovery 数据模型和 API。
3. OpenAI、OpenAI-Compatible、DeepSeek、Qwen Adapter。
4. 分类型真实模型验证和 Operation/Outbox 幂等执行。
5. MinerU 设置、Token 加密和云处理确认。
6. OpenAPI 和 generated TypeScript client。

MinerU 完整连接测试必须复用真实文件上传、轮询、下载和标准化，因此安排在 02B；02A 不注册假测试接口。

## 4. 下一步

从 02A Task 1 开始：先提交计划和状态文档，然后严格按 RED -> GREEN -> refactor 执行 Task 2。每个任务独立提交，不把 Provider、Model、MinerU 设置和数据解析混成一个提交。

## 5. 保持不变的边界

- MinerU 是 Parser，不属于模型配置。
- 模型是全局可复用调用能力，不共享知识库索引、chunks、任务或机器人会话。
- 前端下拉由 capability 和后端 selector 驱动，不能散落硬编码。
- 密钥不得进入响应、OpenAPI 示例、日志或 Trace。
- 知识库、检索、机器人、渠道和完整业务页面仍按后续阶段实现。
