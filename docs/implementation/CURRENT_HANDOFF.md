# 当前开发交接

> 更新时间：2026-07-14（Asia/Shanghai）
> 用途：会话恢复与执行状态交接，不替代需求真源或实施计划。
> 明日指令：读取本文件和 `docs/implementation/01-foundation-implementation-plan.md`，从 Task 12 当前断点继续。

## 1. 工作位置

- 仓库根目录：`D:\RAG知识库`
- 当前隔离 worktree：`D:\RAG知识库\.worktrees\phase-01-foundation`
- 当前分支：`codex/phase-01-foundation`
- 远端：`https://github.com/zaizhudepeiqi/RAG-.git`
- 禁止直接在 `main` 或仓库根工作区继续开发。
- 最近完成的代码检查点：`3b1ee27 feat: add explicit capability registry`
- 当前分支已与 `origin/codex/phase-01-foundation` 同步。

## 2. 已完成并推送

Phase 01 的 Task 1-11 已完成。最近检查点：

- `3b1ee27`：显式 Capability Registry 和两个只读 API。
- `42fe77a`：Transactional Outbox、Celery 四队列、Redis 故障恢复和幂等 Worker。
- `6b2dd5d`：Operation 状态管理。
- `b6afe51`：依赖健康检查。
- `c7ba774`：管理员认证。
- `b8eecff`：Argon2id、JWT、CSRF、AES-GCM。
- `3e22230`：SQLAlchemy、Alembic 和基础表。

Task 11 提交前的最新完整证据：

- 后端全量测试：`92 passed`，使用 `-W error`。
- Ruff：通过。
- Ruff format：通过。
- strict mypy：通过，检查 72 个源文件。
- `uv lock --check`：通过。
- Alembic check：`No new upgrade operations detected`。

## 3. 当前任务

正在执行 `01-foundation-implementation-plan.md` 的 **Task 12：导入固定 Ant Design Pro 并形成 Simple Mode 基线**。

尚未提交的工作只有整个 `frontend/`，Git 状态为：

```text
?? frontend/
```

不要删除或重新复制 `frontend/`；当前目录已经包含需要保留的上游基线和兼容修复。

## 4. Task 12 已完成部分

已从 GitHub 获取并验证：

- Release：`v6.0.2`
- Commit：`2b453c67b535b76f5f95d6542397a4b987b61de2`
- 临时 clone 已在确认位于系统 Temp 后安全删除。

已按计划复制完整应用基线到 `frontend/`，并添加：

- `frontend/LICENSE.ant-design-pro`
- `frontend/TEMPLATE_UPSTREAM.md`

已完成依赖安装：

```powershell
npm --prefix frontend ci --ignore-scripts
```

上游锁文件安装报告 55 个漏洞：10 low、27 moderate、17 high、1 critical。当前任务要先保留固定、可复现基线，**不要运行 `npm audit fix`**，因为它会无审查地改变锁文件和上游版本。后续应单独做依赖安全治理。

## 5. 已定位的上游兼容问题

### 5.1 Umi 类型生成目录

`npm ci --ignore-scripts` 会跳过上游 `prepare` 中的 `max setup`。直接执行 `npm run tsc` 会因 `src/.umi` 不存在而报告大量 `@umijs/max` 导出缺失。

正确做法是在 `frontend` 目录执行 setup：

```powershell
Push-Location frontend
npm exec max -- setup
Pop-Location
```

之后 `npm --prefix frontend run tsc` 已真实通过一次。

不要使用 `npm --prefix frontend exec max -- setup`。该写法曾错误地在 Monorepo 根生成 `.umi/`；错误目录已经安全删除，目前：

- `frontend/src/.umi`：存在，属于生成且被忽略的目录。
- 仓库根 `.umi`：不存在。

### 5.2 Jest 误排除整个 worktree

上游 `frontend/jest.config.ts` 使用：

```ts
testPathIgnorePatterns: ['/node_modules/', '/.worktrees/']
```

Jest 按绝对路径匹配，当前项目本身位于 `.worktrees` 下，因此所有测试被排除。已最小修改为：

```ts
testPathIgnorePatterns: ['/node_modules/', '<rootDir>/.worktrees/']
```

修复后 Jest 能真实收集并运行 1 个 suite、2 个登录测试，不再是“无测试”。

### 5.3 Express 5 与 Umi request-record 不兼容

Umi 生成的 `src/.umi-test/startMock.js` 使用 Express 4 路由语法：

```js
app.get('*', handler)
```

上游项目根依赖原为 `express@5.2.1`，会由新版 `path-to-regexp` 抛出：

```text
Missing parameter name at index 1: *
```

依赖树同时显示 `@umijs/request-record@1.1.4` 使用 `express@4.22.1`。已将 `frontend/package.json` 的根 Express 精确锁定为 `4.22.1`，并更新 `package-lock.json`。当前验证：

```text
ant-design-pro@6.0.2
+-- @umijs/request-record@1.1.4 -> express@4.22.1 deduped
`-- express@4.22.1
```

不要修改生成的 `src/.umi-test/startMock.js`，也不要通过更新快照掩盖 mock server 崩溃。

## 6. 中断点与未确认状态

最后执行的组合命令是：

```powershell
npm --prefix frontend install --package-lock-only --ignore-scripts
npm --prefix frontend ci --ignore-scripts
Push-Location frontend
npm exec max -- setup
Pop-Location
npm --prefix frontend test -- --runInBand
```

该命令在运行期间被用户主动中断。当前没有遗留的本项目 npm、Node 或 Jest 进程，但**不能把这次 Jest 视为通过**。

中断前已经确认：

- `package.json` 和 `package-lock.json` 均锁定 Express `4.22.1`。
- `node_modules` 当前依赖树已 dedupe 到 Express `4.22.1`。
- `frontend/src/.umi` 已生成。
- 仓库根错误 `.umi` 不存在。

## 7. 明日恢复顺序

先在正确 worktree 执行：

```powershell
Set-Location 'D:\RAG知识库\.worktrees\phase-01-foundation'
git branch --show-current
git status --short --branch
```

预期分支是 `codex/phase-01-foundation`，只有 `frontend/` 未跟踪。

然后执行完整、可复现验证：

```powershell
npm --prefix frontend ci --ignore-scripts
Push-Location frontend
npm exec max -- setup
Pop-Location
npm --prefix frontend run tsc
npm --prefix frontend test -- --runInBand
npm --prefix frontend run build
git diff --check
```

处理规则：

1. 如果 Jest 通过，记录 suite/test 数量，不能只看退出码。
2. 如果 Jest 失败，先确认是否仍有 `path-to-regexp`/Express 错误；不要直接更新 snapshot。
3. 如果只剩动态 CSS class snapshot 差异，先判断是否由前一个测试超时造成的级联污染，再决定是否属于上游固定版本问题。
4. 如果 build 失败，按系统化调试定位，不升级 `master` 或整套依赖。
5. 不运行 `npm audit fix`。

完整基线全部通过后：

```powershell
git add frontend
git diff --cached --check
git commit -m "chore: import pinned ant design pro baseline"
git push origin codex/phase-01-foundation
```

随后继续 Task 12 Step 5-6：

```powershell
Push-Location frontend
npm run simple
Pop-Location
npm --prefix frontend install --package-lock-only --ignore-scripts
git diff --name-status HEAD -- frontend
git diff HEAD -- frontend/package.json frontend/config/routes.ts
```

必须审查官方 Simple Mode 的删除范围，再重新运行 ci、setup、tsc、Jest、build，提交：

```text
chore: apply ant design pro simple mode
```

## 8. 后续计划

Task 12 完成后依次执行：

1. Task 13：稳定 OpenAPI operationId、确定性导出、Umi 唯一生成 client。
2. Task 14：删除剩余上游演示业务，建立本项目中文产品壳。
3. 后续 CI、根脚本、可观测性和 Phase 01 验收。

始终遵守：需求文档是真源；按任务小提交并推送；严格 RED -> GREEN -> refactor；不在页面硬编码后端 capability；不在生产 registry 注册 demo/noop/test 能力。
