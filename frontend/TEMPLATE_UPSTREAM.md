# Ant Design Pro 上游记录

- Repository: https://github.com/ant-design/ant-design-pro
- Release: v6.0.2
- Commit: 2b453c67b535b76f5f95d6542397a4b987b61de2
- License: MIT，见 `LICENSE.ant-design-pro`
- Package manager: npm，传递依赖以 `package-lock.json` 为准

导入顺序：完整应用基线提交 -> 官方 `npm run simple` 提交 -> 本项目产品壳提交。
沿用：React、Umi Max、Ant Design、ProLayout/ProComponents、Router、request、initialState/model、React Query、OpenAPI 和测试基础。
替换：Mock、演示业务、上游品牌/外链/分析、Token 认证和无后端对应的静态 DTO。
约束：Cookie + CSRF、全中文产品文案、后端 OpenAPI 生成唯一 service，业务功能按本项目真源实现。

本地兼容：Jest 的 `.worktrees` 忽略规则锚定到 `frontend` 根目录，避免项目位于父级 worktree 时误排除全部测试；Express 锁定为 Umi request-record 兼容的 `4.22.1`；Windows 中文工作区禁用会触发字符边界 panic 的 Utoopack 1.4.3，使用 Umi 默认 Webpack 并启用 `esbuildMinifyIIFE`。
运行时资源：`Welcome.tsx` 直接导入的两份 cheatsheet 从上述固定 commit 原样保留在 `docs/`，其余上游仓库文档未导入。
