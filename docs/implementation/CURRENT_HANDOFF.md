# 当前开发交接

> 更新时间：2026-07-22（Asia/Shanghai）
> 用途：会话恢复和阶段状态摘要；需求定义以 `docs/requirements` 为唯一真源，执行细节以实施计划和代码为准。

## 1. 工作位置

- 仓库根目录：`D:\RAG知识库`
- 当前隔离 worktree：`D:\RAG知识库\.worktrees\phase-01-foundation`
- 当前分支：`codex/phase-01-foundation`
- 远端：`https://github.com/zaizhudepeiqi/RAG-.git`
- 禁止直接在 `main` 或仓库根工作区继续开发。
- 当前实施基线提交：`f3ea460 fix: complete foundation integration validation`

## 2. Phase 01 结论

当前状态：**READY FOR BASELINE REVIEW**。Task 1-15 的工程骨架、基础设施、认证、健康检查、Operation/outbox、能力注册、Ant Design Pro Simple Mode、Umi OpenAPI 生成、中文管理壳、CI 和本地验证均已完成。

本阶段明确没有创建 MinerU、模型 Provider、数据解析、知识库、检索、机器人或渠道的空接口/假实现。下一阶段应先依据 `docs/requirements` 和对应实施计划继续，不要为了填菜单提前创建业务占位表。

## 3. 本轮修复和验证

- `OperationPageSize` 使用 `IntEnum`，修复生成客户端显式发送 `pageSize=20` 时的 422；新增集成回归测试。
- OpenAPI 产物和 Umi 类型已重新生成，二次生成无漂移。
- 首次改密后使用 `window.location.replace('/dashboard')`，避免旧 Umi access 闭包把新会话拦回改密页。
- Playwright 认证用例放宽首屏编译等待并兼容 Ant Design 中文可访问名称；本机 Edge E2E `1 passed`。
- `swagger-ui-dist@4.19.1` 提升到前端项目根依赖，修复 OpenAPI 插件从根解析失败；增加工具链回归测试。
- 实施计划已改为 CI 实际采用的 `uv export --frozen` 临时 requirements 审计链路。
- 2026-07-22 复核运行时，前端生产依赖审计仍为 0 high/critical；完整工具链审计随 npm advisory 数据库更新为 60 项，已同步临时例外计数。

验证证据：

```text
scripts/check.ps1                         exit 0
后端非集成测试                             67 passed
后端集成测试                               28 passed
前端 Jest                                  7 suites / 14 tests passed
frontend production build                  exit 0
OpenAPI generated drift                    clean
pip-audit 2.10.1                           no known vulnerabilities, 1 documented exception
npm audit --omit=dev --audit-level=high    exit 0; 1 moderate dompurify advisory
Playwright Edge                             1 passed
```

本机 Chromium 下载未完成，因此浏览器证据使用系统 Edge；CI 仍使用正式 Chromium。Docker PostgreSQL、Redis、Chroma 均已验证 healthy，临时 E2E 数据库已删除，8001/5173 服务已停止。

## 4. 当前工作区状态

- Phase 01 实现修复、生成产物和回归测试已提交并推送。
- 前端工具链审计例外已按 2026-07-22 的 npm advisory 数据库复核并推送。
- 本机专用的 Edge 配置已删除，期望工作区无未提交变更。

## 5. 继续操作顺序

1. 等用户选择保留分支、创建 PR 或合并。
2. 创建 PR 后以 GitHub Actions 的正式 Chromium integration job 作为 Linux CI 证据。
3. 未经用户选择，不合并分支、不删除 worktree。

## 6. 下一阶段边界

下一阶段才实现模型配置和 MinerU API Adapter，再按数据解析 -> 解析版本 -> 知识库构建 -> 分块/索引/检索 -> 机器人 -> 渠道的顺序推进。每个模块先补 API、数据库、状态机、页面/API 对照和验收条目，再编码；前端下拉继续由后端 capability/schema 驱动，不能把算法选项散落硬编码在页面。
