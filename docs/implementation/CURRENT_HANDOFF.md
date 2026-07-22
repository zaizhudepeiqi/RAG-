# 当前开发交接

> 更新时间：2026-07-23（Asia/Shanghai）
> 用途：会话恢复和阶段状态摘要；需求定义以 `docs/requirements` 为唯一真源。

## 1. 工作位置

- 仓库根目录：`D:\RAG知识库`
- 当前 worktree：`D:\RAG知识库\.worktrees\phase-02-models-parsing`
- 当前分支：`codex/phase-02-models-parsing`
- Phase 02 入口提交：`f78e5cf fix: generate Umi types before frontend checks`
- 远端：`https://github.com/zaizhudepeiqi/RAG-.git`
- 禁止直接在 `main` 或 Phase 01 worktree 开发 Phase 02。

## 2. 已完成阶段

Phase 01 已 fast-forward 合并并推送到 `main`。Phase 02A 已在当前分支完成，交付：

1. Provider/model type capability 与固定 Provider Adapter registry。
2. Provider、Model Config、Verification、Discovery 持久化、CRUD、选择守卫和 Operation/Outbox 幂等处理。
3. OpenAI、OpenAI-Compatible、DeepSeek、Qwen 分类型真实 HTTP Adapter 与错误映射。
4. AES-256-GCM Provider 凭据轮换、revision race 防护和最小验证摘要。
5. MinerU 设置单例、Token AES-256-GCM 加密、云处理确认和严格 ParseConfig。
6. 稳定 OpenAPI operationId 与唯一 Umi generated TypeScript client。

02A 提交：

```text
256e754 docs: add phase two model registry plan
c96602c feat: register model provider capabilities
454b7da feat: add model registry persistence
79ddace feat: secure provider endpoints and credentials
0a50457 feat: add model provider management
17c05d7 feat: add model provider adapters
a7457ad feat: add provider discovery operations
7d2e459 feat: add reusable model configurations
b869dde feat: verify models by capability type
4293fc7 feat: store MinerU settings securely
58281e7 chore: generate model registry api client
c83abff test: use scanner-safe credential fixtures
```

## 3. 当前任务

当前状态：**IMPLEMENTATION IN PROGRESS (PHASE 2B)**。

02A 计划 `docs/implementation/02a-model-registry-implementation-plan.md` 已执行完成。Phase 02 尚未完成；02B 需要先依据解析需求真源创建详细计划，再实现数据上传与解析闭环。

02A 最终验证（2026-07-23）：

- `scripts/check.ps1` exit 0：Ruff、strict mypy、后端非集成 `131 passed`、前端 Jest `7 suites / 16 tests`、Biome、TypeScript、production build 和 OpenAPI 二次生成无漂移。
- Docker PostgreSQL/Redis/Chroma healthy；完整集成组 `59 passed`。
- Alembic 空库升级测试和 `alembic check` 通过，无新迁移操作。
- Provider/MinerU 密文字节与 audit `change_summary` 已知明文命中数均为 0；仓库密钥扫描通过。
- `pip-audit 2.10.1` 无未豁免漏洞，保留 `PYSEC-2026-311` 已登记例外；npm 生产依赖 high 门槛通过，保留 1 项 moderate `dompurify` 上游报告。

MinerU 完整连接测试必须复用真实文件上传、轮询、下载和标准化，因此安排在 02B；02A 不注册假测试接口。

## 4. 下一步

1. 从 `docs/requirements/03-data-parsing-source.md` 和现有路线图创建 `docs/implementation/02b-data-parsing-implementation-plan.md`。
2. 继续使用当前 `codex/phase-02-models-parsing` 分支和 worktree，不在 `main` 直接开发。
3. 02B 实现真实 MinerUPrecisionAdapter 后再注册 `POST /settings/mineru:test`，并完成上传、ZIP 安全、ParsedSourceVersion、轮询、下载和标准化。
4. 保持 TDD、每任务独立提交，以及根门禁/集成/安全审计闭环。

## 5. 保持不变的边界

- MinerU 是 Parser，不属于模型配置。
- 模型是全局可复用调用能力，不共享知识库索引、chunks、任务或机器人会话。
- 前端下拉由 capability 和后端 selector 驱动，不能散落硬编码。
- 密钥不得进入响应、OpenAPI 示例、日志或 Trace。
- 知识库、检索、机器人、渠道和完整业务页面仍按后续阶段实现。
