# 第二阶段 A：模型注册与 MinerU 设置 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Phase 01 基础上交付可持久化、可加密、可验证、可供后续知识库/机器人选择的模型能力池，并完成 MinerU Cloud 设置的安全保存；不在本计划创建数据源、解析版本或假 MinerU 测试。

**Architecture:** 后端继续采用模块化单体。Model Provider、Model Config 和 Model Verification 归属 models 模块；供应商 HTTP 细节只存在于 adapters，业务服务只依赖端口。PostgreSQL 是模型状态和发现结果真源，AES-256-GCM 密文绑定资源 AAD；真实连接测试通过 Operation + Outbox + Celery maintenance queue 执行。MinerU 设置归属 parsing/settings 边界，完整连接测试在 02B 复用真实 MinerUPrecisionAdapter 后注册。

**Tech Stack:** FastAPI 0.139.0、Pydantic 2.13.4、SQLAlchemy 2.0.51、Alembic 1.18.5、PostgreSQL 17.10、Celery 5.6.3、httpx 0.28.1、respx 0.23.1、AES-256-GCM、pytest 9.1.1、Umi OpenAPI generator。

---

## 0. 执行边界与成功标准

本计划实现：

1. model_provider/model_type capability。
2. Model Provider CRUD、凭据轮换、连接测试和模型发现。
3. Model Config CRUD、分类型验证、启用/停用、选择查询和引用查询。
4. OpenAI、OpenAI-Compatible、DeepSeek、Qwen Adapter 的真实 HTTP 协议实现。
5. MinerU 设置保存、Token 加密、云处理确认和默认 ParseConfig。
6. OpenAPI、生成 TypeScript client、迁移和安全回归。

本计划不实现：

- 数据源上传、ZIP、ParsedSourceVersion、MinerU 文件提交、轮询、下载或标准化。
- 知识库、机器人或渠道表。
- 模型配置管理页面；完整业务页面按路线图在阶段 6 实现。
- 价格或伪造成本。

成功标准：

- API 和数据库从不返回/记录明文模型凭据或 MinerU Token。
- Provider 凭据轮换同事务递增 credentialRevision 并把所属模型标为 stale。
- 未测试、failed、stale、disabled 或类型不匹配模型不能通过 selector/service guard。
- LLM、Embedding、Rerank、Vision 验证使用不同请求和响应校验。
- Operation/Outbox 同事务；重复 delivery 只产生一个 verification/discovery 副作用。
- 后端单元、API、PostgreSQL 集成、OpenAPI 漂移和根门禁通过。

## 1. 文件结构锁定

~~~text
backend/app/
  core/network_security.py
  infrastructure/database/models/models.py
  infrastructure/database/repositories/models.py
  infrastructure/database/repositories/mineru_settings.py
  infrastructure/model_providers/
    __init__.py
    base.py
    openai_compatible.py
    registry.py
  modules/models/
    __init__.py
    adapters.py
    api.py
    domain.py
    errors.py
    ports.py
    repository.py
    schemas.py
    service.py
    tasks.py
    verification.py
  modules/parsing/
    __init__.py
    settings_api.py
    settings_domain.py
    settings_ports.py
    settings_repository.py
    settings_schemas.py
    settings_service.py
backend/migrations/versions/0002_models_and_mineru_settings.py
backend/tests/
  api/test_model_providers_api.py
  api/test_models_api.py
  api/test_mineru_settings_api.py
  integration/models/
  unit/models/
  unit/parsing/
docs/api/openapi.json
frontend/src/services/ragApi/
~~~

模块约束：

- API 路由只做 DTO、鉴权、事务边界和 service 调用。
- models service 不导入 httpx；Provider Adapter 不导入 ORM。
- Adapter 不接收数据库密文，只接收已在 service 边界解密的 SecretStr/bytes。
- response_summary 只能保存短摘要、维度、数量、usage 和 request ID，不能保存完整模型输出。
- provider/model 枚举只在 capability/registry 定义，不在 API 页面分支复制。

## 2. 全阶段命令

所有命令在 Phase 02 worktree 根执行：

~~~powershell
uv run --project backend pytest backend/tests/unit/models -v
uv run --project backend pytest backend/tests/api/test_model_providers_api.py -v
uv run --project backend pytest backend/tests/api/test_models_api.py -v
uv run --project backend ruff format --check backend/app backend/tests
uv run --project backend ruff check backend/app backend/tests
uv run --project backend mypy backend/app

. ./deploy/scripts/import-env.ps1 -Path deploy/env/.env.development
$env:RAG_TEST_DATABASE_URL = $env:DATABASE_URL -replace '/rag_kb$', '/rag_kb_test'
uv run --project backend alembic -c backend/alembic.ini upgrade head
uv run --project backend pytest backend/tests -m integration -v

uv run --project backend python backend/scripts/export_openapi.py
npm --prefix frontend run generate:api
pwsh -NoProfile -File scripts/check.ps1
~~~

### Task 1: 登记阶段计划和状态

**Files:**
- Create: `docs/implementation/02a-model-registry-implementation-plan.md`
- Modify: `docs/implementation/README.md`
- Modify: `docs/requirements/99-development-readiness.md`
- Modify: `docs/implementation/CURRENT_HANDOFF.md`

- [ ] **Step 1: 将阶段状态改为 IMPLEMENTATION IN PROGRESS (PHASE 2A)**

只更新执行状态，不改变业务需求。记录分支 `codex/phase-02-models-parsing`、入口提交 `f78e5cf`、Phase 01 已合并及冷启动验证证据。

- [ ] **Step 2: 在路线图增加 02A/02B 计划链接**

`docs/implementation/README.md` 的阶段 2 后增加：

~~~text
详细步骤：
- 02A：docs/implementation/02a-model-registry-implementation-plan.md
- 02B：docs/implementation/02b-data-parsing-implementation-plan.md（02A 完成后创建）
~~~

- [ ] **Step 3: 运行文档门禁**

Run:

~~~powershell
pwsh -NoProfile -File scripts/check-docs.ps1
git diff --check
~~~

Expected: exit 0。

- [ ] **Step 4: 提交**

~~~powershell
git add docs/implementation docs/requirements/99-development-readiness.md
git commit -m "docs: add phase two model registry plan"
~~~

### Task 2: 注册模型 Provider 和类型 capability

**Files:**
- Modify: `backend/app/modules/capabilities/registry.py`
- Modify: `backend/app/bootstrap/dependencies.py`
- Test: `backend/tests/unit/capabilities/test_registry.py`

- [ ] **Step 1: 写失败测试**

测试 `build_capability_registry()` 返回以下启用项：

~~~python
expected_provider_codes = {"openai", "openai_compatible", "deepseek", "qwen"}
expected_model_types = {"llm", "embedding", "rerank", "vision"}
~~~

并断言 Provider 的 `config_schema` 声明 baseUrl/credential，model_type 声明类型代码和中文名。未知/未来 Provider 不注册 enabled 项。

- [ ] **Step 2: 运行 RED**

~~~powershell
uv run --project backend pytest backend/tests/unit/capabilities/test_registry.py -v
~~~

Expected: FAIL，因为 builder 尚不存在。

- [ ] **Step 3: 实现固定 catalog builder**

新增：

~~~python
def build_capability_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for option in MODEL_PROVIDER_CAPABILITIES + MODEL_TYPE_CAPABILITIES:
        registry.register(option)
    return registry
~~~

Provider capability 必须声明真实类型集合：

| Provider | llm | embedding | rerank | vision | discovery |
|---|---:|---:|---:|---:|---:|
| openai | yes | yes | no | yes | yes |
| openai_compatible | schema-controlled | schema-controlled | schema-controlled | schema-controlled | optional |
| deepseek | yes | no | no | no | yes |
| qwen | yes | yes | yes | yes | yes |

`openai_compatible` 的支持类型由 Provider 保存时管理员从 schema 允许集合中选择并由真实验证证明，不按 modelName 猜测。

- [ ] **Step 4: 装配唯一 registry**

`build_application_dependencies` 使用 builder，不再实例化空 registry。

- [ ] **Step 5: 运行 GREEN 并提交**

~~~powershell
uv run --project backend pytest backend/tests/unit/capabilities backend/tests/api/test_capabilities_api.py -v
git add backend/app/modules/capabilities backend/app/bootstrap/dependencies.py backend/tests/unit/capabilities
git commit -m "feat: register model provider capabilities"
~~~

### Task 3: 创建模型和 MinerU 设置迁移

**Files:**
- Create: `backend/migrations/versions/0002_models_and_mineru_settings.py`
- Create: `backend/app/infrastructure/database/models/models.py`
- Modify: `backend/app/infrastructure/database/models/settings.py`
- Modify: `backend/app/infrastructure/database/models/__init__.py`
- Modify: `docs/database/schema.md`
- Test: `backend/tests/integration/database/test_models_schema.py`
- Test: `backend/tests/integration/database/test_migrations.py`

- [ ] **Step 1: 写数据库约束失败测试**

测试以下反例被 PostgreSQL 拒绝：

- model_providers 当前 displayName 大小写重复。
- model_configs 重复 provider/modelName/modelType。
- 非法 modelType/verificationStatus。
- credentialRevision/revision 小于 1。
- Embedding 维度小于 1。
- model_verifications 负 latency。
- MinerU pollTimeout 不在 300..7200。

- [ ] **Step 2: 运行 RED**

~~~powershell
uv run --project backend pytest backend/tests/integration/database/test_models_schema.py -v -m integration
~~~

Expected: FAIL，表不存在。

- [ ] **Step 3: 建立 0002 migration**

创建：

- `model_providers`
- `model_configs`
- `model_verifications`
- `model_discovered_candidates`
- `mineru_settings`

`model_discovered_candidates` 补足 API 已要求但旧 schema 未落表的发现结果：

~~~text
id uuid PK
provider_id uuid FK RESTRICT
discovery_operation_id uuid FK operations RESTRICT
model_name text
suggested_types jsonb (array, only llm/embedding/rerank/vision)
provider_status text (available/unavailable/unknown)
raw_metadata_summary jsonb
discovered_at timestamptz
unique(provider_id, discovery_operation_id, model_name)
~~~

`mineru_settings`：

~~~text
id uuid singleton PK
base_url text
token_ciphertext bytea/null
token_nonce bytea/null
token_key_version text/null
token_prefix text/null
token_revision integer >= 1
default_parse_config jsonb
poll_timeout_seconds integer 300..7200
cloud_processing_confirmed_at timestamptz/null
cloud_processing_confirmed_by uuid/null FK administrators
cloud_processing_terms_version text/null
revision integer >= 1
created_at/updated_at
~~~

- [ ] **Step 4: ORM 与 migration 同构**

ORM 枚举字段仍用 text + CheckConstraint，避免 PostgreSQL enum 演进锁定。所有 JSON 使用 JSONB，不存 SecretStr。

- [ ] **Step 5: 验证空库升级和 downgrade/upgrade**

~~~powershell
uv run --project backend pytest backend/tests/integration/database/test_migrations.py backend/tests/integration/database/test_models_schema.py -v -m integration
uv run --project backend alembic -c backend/alembic.ini check
~~~

Expected: PASS；Alembic 无漂移。

- [ ] **Step 6: 提交**

~~~powershell
git add backend/migrations backend/app/infrastructure/database/models docs/database/schema.md backend/tests/integration/database
git commit -m "feat: add model registry persistence"
~~~

### Task 4: 建立 Provider URL 和凭据安全边界

**Files:**
- Create: `backend/app/core/network_security.py`
- Create: `backend/app/modules/models/domain.py`
- Create: `backend/app/modules/models/errors.py`
- Test: `backend/tests/unit/core/test_network_security.py`
- Test: `backend/tests/unit/models/test_provider_credentials.py`

- [ ] **Step 1: 写 URL 安全 RED 测试**

覆盖：

~~~python
blocked = [
    "http://169.254.169.254/latest/meta-data",
    "https://127.0.0.1/v1",
    "https://[::1]/v1",
    "https://user:password@example.com/v1",
    "file:///etc/passwd",
]
~~~

生产/测试环境只允许 HTTPS 公网目标。开发环境仅在显式 `allow_local_provider_http=true` 时允许 localhost HTTP；仍禁止元数据地址和 URL 凭据。解析后的每个 DNS 地址都必须通过 `ipaddress.ip_address(...).is_global`，调用时禁用自动跨主机 redirect。

- [ ] **Step 2: 运行 RED**

~~~powershell
uv run --project backend pytest backend/tests/unit/core/test_network_security.py -v
~~~

- [ ] **Step 3: 实现 `validate_outbound_base_url`**

函数接收注入的 resolver，返回无 query/fragment、无尾部重复斜杠的规范 URL。错误统一为 `PROVIDER_BASE_URL_FORBIDDEN`，details 不回显凭据。

- [ ] **Step 4: 写凭据加密 RED 测试**

定义 AAD：

~~~python
def provider_credential_aad(provider_id: UUID) -> bytes:
    return f"model-provider:{provider_id}:credential:v1".encode("ascii")
~~~

测试密文不包含 plaintext、资源间不可互换解密、遮罩只显示固定前缀和末四位、解密失败不包含密文。

- [ ] **Step 5: 实现并运行 GREEN**

复用 `encrypt_secret/decrypt_secret`，不创建第二套 AES helper。新增 `mask_credential` 只接收临时 plaintext，数据库只保存无敏感的 prefix。

~~~powershell
uv run --project backend pytest backend/tests/unit/core/test_network_security.py backend/tests/unit/models/test_provider_credentials.py -v
~~~

- [ ] **Step 6: 提交**

~~~powershell
git add backend/app/core backend/app/modules/models backend/tests/unit/core backend/tests/unit/models
git commit -m "feat: secure provider endpoints and credentials"
~~~

### Task 5: 实现 Model Provider CRUD

**Files:**
- Create: `backend/app/modules/models/ports.py`
- Create: `backend/app/modules/models/repository.py`
- Create: `backend/app/modules/models/schemas.py`
- Create: `backend/app/modules/models/service.py`
- Create: `backend/app/modules/models/api.py`
- Create: `backend/app/infrastructure/database/repositories/models.py`
- Modify: `backend/app/bootstrap/dependencies.py`
- Modify: `backend/app/bootstrap/application.py`
- Test: `backend/tests/api/test_model_providers_api.py`
- Test: `backend/tests/integration/models/test_provider_repository.py`

- [ ] **Step 1: 写 CRUD API RED 测试**

覆盖创建 201、分页、详情、改显示名、轮换凭据、expectedRevision 409、同名 409、密文/nonce/Token 不在响应、删除 204。

Request DTO：

~~~python
class CreateModelProviderRequest(ApiModel):
    provider_type: str
    display_name: str
    base_url: AnyHttpUrl
    credential: SecretStr
    supported_model_types: list[ModelType] | None = None

class UpdateModelProviderRequest(ApiModel):
    expected_revision: int
    display_name: str | None = None
    credential: SecretStr | None = None
~~~

被 model_config 引用时不能修改 providerType/baseUrl 或删除。第一版 PATCH 不接受这两个身份字段，避免“接受后忽略”。

- [ ] **Step 2: 运行 RED**

~~~powershell
uv run --project backend pytest backend/tests/api/test_model_providers_api.py -v
~~~

- [ ] **Step 3: 实现 repository 映射**

Repository 只处理领域对象和 ORM；列表统一 page 1-based、pageSize 20/50/100、sort `display_name/-display_name/created_at/-created_at`。

- [ ] **Step 4: 实现 service 事务**

创建流程：校验 capability -> URL 安全 -> 生成 UUID -> AAD 加密 -> insert -> audit。凭据轮换在同一事务：

1. 锁 Provider。
2. 校验 expectedRevision。
3. 写新密文并递增 credentialRevision/revision。
4. 将 provider 下未删除模型 verificationStatus 更新为 stale。
5. 写不含 credential 的 audit summary。

- [ ] **Step 5: 装配 API**

所有端点使用 `require_current_administrator`、response_model 和统一 AppError。Provider view 只返回 `credentialConfigured/credentialMasked`。

- [ ] **Step 6: GREEN 和集成验证**

~~~powershell
uv run --project backend pytest backend/tests/api/test_model_providers_api.py backend/tests/integration/models/test_provider_repository.py -v
~~~

- [ ] **Step 7: 提交**

~~~powershell
git add backend/app/modules/models backend/app/infrastructure/database/repositories/models.py backend/app/bootstrap backend/tests/api/test_model_providers_api.py backend/tests/integration/models
git commit -m "feat: add model provider management"
~~~

### Task 6: 建立 Provider Adapter 注册和错误映射

**Files:**
- Create: `backend/app/modules/models/adapters.py`
- Create: `backend/app/infrastructure/model_providers/base.py`
- Create: `backend/app/infrastructure/model_providers/openai_compatible.py`
- Create: `backend/app/infrastructure/model_providers/registry.py`
- Test: `backend/tests/unit/models/test_adapter_registry.py`
- Test: `backend/tests/unit/models/test_provider_error_mapping.py`

- [ ] **Step 1: 写 Adapter contract RED 测试**

协议：

~~~python
class ModelProviderAdapter(Protocol):
    descriptor: ProviderDescriptor
    def test_provider(self, request: ProviderConnectionRequest) -> ProviderConnectionResult: ...
    def discover_models(self, request: DiscoverModelsRequest) -> tuple[DiscoveredModel, ...]: ...
    def verify_llm(self, request: ModelVerificationRequest) -> VerificationResult: ...
    def verify_embedding(self, request: ModelVerificationRequest) -> VerificationResult: ...
    def verify_rerank(self, request: ModelVerificationRequest) -> VerificationResult: ...
    def verify_vision(self, request: ModelVerificationRequest) -> VerificationResult: ...
~~~

Registry 必须拒绝重复 providerType，并对不支持类型抛 `MODEL_TYPE_MISMATCH`。

- [ ] **Step 2: 写 HTTP 错误映射 RED 测试**

使用 respx 固定：

| HTTP/异常 | 系统错误 | retryable |
|---|---|---:|
| 401/403 | MODEL_AUTH_FAILED | no |
| 404 model | MODEL_NOT_FOUND | no |
| 400/422 | MODEL_BAD_REQUEST | no |
| 429 | MODEL_RATE_LIMITED | yes |
| timeout | MODEL_TIMEOUT | yes |
| 5xx/network | MODEL_PROVIDER_ERROR | yes |
| malformed JSON/shape | MODEL_RESPONSE_INVALID | no |

最多额外重试 2 次，仅 network/429/5xx；测试注入 sleeper/jitter，禁止真实等待。

- [ ] **Step 3: 实现共享 OpenAI-compatible transport**

请求头只在内存组装；日志字段禁止 headers、body 中的输入正文和 signed URL。httpx Client 设置 timeout、`follow_redirects=False`，每次调用前重新验证 baseUrl 解析结果。

- [ ] **Step 4: 实现四个 descriptor**

- OpenAI：`/models`、`/chat/completions`、`/embeddings`；vision 复用 chat multimodal。
- DeepSeek：OpenAI-compatible chat/models；只声明 llm。
- Qwen：按官方 DashScope compatible/native endpoint 分别实现 llm/embedding/rerank/vision。
- OpenAI-Compatible：保存时声明支持类型和 endpoint schema；只有声明且验证通过的类型可用。

供应商请求/响应 fixture 必须来自版本化测试数据，不能凭模型名称推断类型。

- [ ] **Step 5: GREEN 和提交**

~~~powershell
uv run --project backend pytest backend/tests/unit/models/test_adapter_registry.py backend/tests/unit/models/test_provider_error_mapping.py -v
git add backend/app/modules/models/adapters.py backend/app/infrastructure/model_providers backend/tests/unit/models
git commit -m "feat: add model provider adapters"
~~~

### Task 7: 实现 Provider 测试和模型发现 Operation

**Files:**
- Create: `backend/app/modules/models/tasks.py`
- Modify: `backend/app/modules/models/service.py`
- Modify: `backend/app/modules/models/api.py`
- Modify: `backend/app/modules/tasks/tasks.py`
- Modify: `backend/app/bootstrap/dependencies.py`
- Test: `backend/tests/integration/models/test_provider_operations.py`
- Test: `backend/tests/unit/models/test_provider_tasks.py`

- [ ] **Step 1: 写同事务 RED 测试**

`:test` 和 `:discover-models` 必须在同一事务创建：

- Operation targetType=model_provider。
- TaskOutboxEvent schemaVersion=1。
- 管理员 idempotency record。

重复 Idempotency-Key + 相同请求返回原 Operation；不同请求返回 409。

- [ ] **Step 2: 运行 RED**

~~~powershell
uv run --project backend pytest backend/tests/integration/models/test_provider_operations.py -v -m integration
~~~

- [ ] **Step 3: 注册 dispatch definitions**

~~~python
TaskDispatchDefinition(
    event_type="model.provider.test.requested",
    schema_version="1",
    celery_task_name="app.tasks.maintenance.test_model_provider",
    queue="maintenance",
)
TaskDispatchDefinition(
    event_type="model.provider.discovery.requested",
    schema_version="1",
    celery_task_name="app.tasks.maintenance.discover_provider_models",
    queue="maintenance",
)
~~~

- [ ] **Step 4: 实现幂等 Handler**

Handler 从 Operation target 读取 provider 当前快照、解密凭据、调用 Adapter。发现结果按 operationId upsert candidates；重复 delivery 不增加行。若 provider revision 在调用期间变化，结果保存但标记 stale，不覆盖新状态。

- [ ] **Step 5: 端点和查询**

`GET /model-providers/{id}/discovered-models` 默认返回最新成功 discovery operation 的候选；可按 modelType/status 过滤，不返回 raw provider payload。

- [ ] **Step 6: GREEN 和提交**

~~~powershell
uv run --project backend pytest backend/tests/unit/models/test_provider_tasks.py backend/tests/integration/models/test_provider_operations.py -v
git add backend/app/modules/models backend/app/modules/tasks/tasks.py backend/app/bootstrap/dependencies.py backend/tests
git commit -m "feat: add provider discovery operations"
~~~

### Task 8: 实现 Model Config CRUD 和选择守卫

**Files:**
- Modify: `backend/app/modules/models/domain.py`
- Modify: `backend/app/modules/models/ports.py`
- Modify: `backend/app/modules/models/repository.py`
- Modify: `backend/app/modules/models/schemas.py`
- Modify: `backend/app/modules/models/service.py`
- Modify: `backend/app/modules/models/api.py`
- Modify: `backend/app/infrastructure/database/repositories/models.py`
- Test: `backend/tests/api/test_models_api.py`
- Test: `backend/tests/unit/models/test_model_selection.py`

- [ ] **Step 1: 写 CRUD/守卫 RED 测试**

覆盖：

- 创建默认 enabled=false、untested。
- provider 不存在/disabled/type 不支持拒绝。
- modelName + type 唯一。
- identity 字段有引用时不可改。
- callable/defaultParams/configSchema 改变后变 stale。
- enable 仅 passed 且 tested revisions 当前。
- disable/delete 有引用返回 MODEL_IN_USE + references。
- selector 只返回 enabled + passed + revisions matching + expected type。

- [ ] **Step 2: 定义 selector 端口**

~~~python
class ModelSelectionService:
    def require_selectable(
        self,
        session: Session,
        model_id: UUID,
        expected_type: ModelType,
    ) -> SelectableModel: ...
~~~

后续知识库/机器人必须复用它，不能重写一套条件。

- [ ] **Step 3: 实现 revision 规则**

ModelVerification 保存 testedModelRevision/testedProviderRevision/testedCredentialRevision；`require_selectable` 同时比较三者。模型更名不 stale；modelName/type/capabilityVersion、影响调用的 defaultParams、Provider credential 变化均 stale。

- [ ] **Step 4: references 查询**

当前只有未来 KB/Bot 才会产生业务引用，因此 Phase 02A 的 repository 从已存在表返回真实空集合；接口结构固定为 `resourceType/resourceId/displayName/state`，02B 不创建假引用。

- [ ] **Step 5: GREEN 和提交**

~~~powershell
uv run --project backend pytest backend/tests/api/test_models_api.py backend/tests/unit/models/test_model_selection.py -v
git add backend/app/modules/models backend/app/infrastructure/database/repositories/models.py backend/tests
git commit -m "feat: add reusable model configurations"
~~~

### Task 9: 实现分类型 Model Verification Operation

**Files:**
- Create: `backend/app/modules/models/verification.py`
- Modify: `backend/app/modules/models/tasks.py`
- Modify: `backend/app/modules/models/service.py`
- Modify: `backend/app/modules/models/api.py`
- Modify: `backend/app/modules/tasks/tasks.py`
- Test: `backend/tests/unit/models/test_model_verification.py`
- Test: `backend/tests/integration/models/test_model_verification_operation.py`

- [ ] **Step 1: 写四种响应校验 RED 测试**

- LLM：非空文本，temperature=0，max tokens=8。
- Embedding：非空、全部 finite、维度 >0；重复验证维度变化失败。
- Rerank：候选索引一一对应、有限分数、统一高分更相关。
- Vision：Provider descriptor 支持时才发送内置最小图片；返回非空文本。

使用 `math.isfinite`，禁止只检查 JSON key 存在。

- [ ] **Step 2: 写并发 revision RED 测试**

验证运行期间 model/provider/credential revision 变化时：

- verification 历史仍保存。
- 当前模型状态必须是 stale。
- 旧结果不能重新把模型标 passed。

- [ ] **Step 3: 创建 Operation/Outbox**

event `model.verification.requested` schema 1，task `app.tasks.maintenance.verify_model`。业务 key 包含 modelId + modelRevision + providerRevision + credentialRevision；重复点击同修订复用，修订变化创建新 Operation。

- [ ] **Step 4: 持久化最小结果**

成功 responseSummary 仅允许：

~~~text
modelType, outputPresent, embeddingDimension, candidateCount,
usageInputTokens, usageOutputTokens, providerUsageReported
~~~

errorMessage 必须经 Adapter 脱敏并限制长度；不保存 prompt/完整输出/credential。

- [ ] **Step 5: GREEN 和提交**

~~~powershell
uv run --project backend pytest backend/tests/unit/models/test_model_verification.py backend/tests/integration/models/test_model_verification_operation.py -v
git add backend/app/modules/models backend/app/modules/tasks/tasks.py backend/tests
git commit -m "feat: verify models by capability type"
~~~

### Task 10: 实现 MinerU 设置安全保存

**Files:**
- Create: `backend/app/modules/parsing/settings_domain.py`
- Create: `backend/app/modules/parsing/settings_ports.py`
- Create: `backend/app/modules/parsing/settings_repository.py`
- Create: `backend/app/modules/parsing/settings_schemas.py`
- Create: `backend/app/modules/parsing/settings_service.py`
- Create: `backend/app/modules/parsing/settings_api.py`
- Create: `backend/app/infrastructure/database/repositories/mineru_settings.py`
- Modify: `backend/app/bootstrap/dependencies.py`
- Modify: `backend/app/bootstrap/application.py`
- Modify: `docs/api/v1-api-contract.md`
- Test: `backend/tests/api/test_mineru_settings_api.py`
- Test: `backend/tests/unit/parsing/test_mineru_settings.py`

- [ ] **Step 1: 写 GET/PATCH RED 测试**

覆盖 singleton 默认值、Token 空缺、首次设置、留空不替换、轮换 tokenRevision、expectedRevision 409、明文不在响应/日志。

- [ ] **Step 2: 补齐云处理确认契约**

`UpdateMinerUSettingsRequest` 新增：

~~~python
class CloudProcessingConsent(ApiModel):
    accepted: Literal[True]
    terms_version: Literal["mineru-cloud-v1"]
~~~

首次配置 Token 必填 consent；后续不替换 Token 时可省略。View 返回 `cloudProcessingConfirmedAt/termsVersion`，不返回管理员账号或 Token。

- [ ] **Step 3: 实现 ParseConfig 固定 DTO**

字段严格为 parserCode/modelVersion/language/ocrEnabled/tableEnabled/formulaEnabled/pageRanges/extraFormats/forceProviderRefresh；额外字段 422。HTML/builtin 参数适用性在 02B Parser capability 校验。

- [ ] **Step 4: 实现加密与事务**

AAD 固定 `mineru-settings:{settingsId}:credential:v1`。PATCH 同事务更新密文、revision、confirmation 和审计；Token 留空保持旧 ciphertext/nonce，不重新加密。

- [ ] **Step 5: 不注册假测试端点**

`POST /settings/mineru:test` 的路由在 02B 完成真实 `MinerUPrecisionAdapter` 后注册。在此之前 OpenAPI 不出现该 operation，handoff 必须明确属于同一 Phase 02 未完成项。

- [ ] **Step 6: GREEN 和提交**

~~~powershell
uv run --project backend pytest backend/tests/api/test_mineru_settings_api.py backend/tests/unit/parsing/test_mineru_settings.py -v
git add backend/app/modules/parsing backend/app/infrastructure/database/repositories/mineru_settings.py backend/app/bootstrap docs/api/v1-api-contract.md backend/tests
git commit -m "feat: store MinerU settings securely"
~~~

### Task 11: 同步 OpenAPI 和生成客户端

**Files:**
- Modify: `backend/tests/api/test_openapi_contract.py`
- Modify: `docs/api/openapi.json` (generated)
- Modify/Create: `frontend/src/services/ragApi/*` (generated)
- Test: `frontend/tests/features/toolchain.test.ts`

- [ ] **Step 1: 写 operationId 契约 RED 测试**

固定以下前缀：`modelProvidersList/Create/Get/Update/Delete/Test/Discover`、`modelsList/Create/Get/Update/Verify/Enable/Disable/Delete/References`、`mineruSettingsGet/Update`。禁止路径变化造成中文文件名随机漂移。

- [ ] **Step 2: 导出和生成**

~~~powershell
uv run --project backend python backend/scripts/export_openapi.py
npm --prefix frontend run generate:api
~~~

- [ ] **Step 3: 检查唯一 client**

前端不得手写 Provider/Model DTO，不得新建 axios/fetch client。Secret 字段不得出现在 response type 或 example。

- [ ] **Step 4: 二次生成无漂移**

~~~powershell
git add docs/api/openapi.json frontend/src/services/ragApi
uv run --project backend python backend/scripts/export_openapi.py
npm --prefix frontend run generate:api
git diff --exit-code -- docs/api/openapi.json frontend/src/services/ragApi
~~~

- [ ] **Step 5: 提交**

~~~powershell
git add backend/tests/api/test_openapi_contract.py docs/api/openapi.json frontend/src/services/ragApi
git commit -m "chore: generate model registry api client"
~~~

### Task 12: 02A 全量验收与交接

**Files:**
- Modify: `docs/implementation/CURRENT_HANDOFF.md`
- Modify: `docs/requirements/99-development-readiness.md`
- Modify: `.github/workflows/ci.yml` only if Phase 02 tests require an explicit new command

- [ ] **Step 1: 运行静态和非集成门禁**

~~~powershell
pwsh -NoProfile -File scripts/check.ps1
~~~

Expected: repository/docs/Compose、Ruff、mypy、非集成 pytest、前端 15+ tests、build、OpenAPI drift 全部 exit 0。

- [ ] **Step 2: 运行数据库集成**

~~~powershell
docker compose --env-file deploy/env/.env.development -f deploy/compose/compose.deps.yml up -d --wait
. ./deploy/scripts/import-env.ps1 -Path deploy/env/.env.development
$env:RAG_TEST_DATABASE_URL = $env:DATABASE_URL -replace '/rag_kb$', '/rag_kb_test'
uv run --project backend pytest backend/tests -v -m integration
~~~

- [ ] **Step 3: 安全专项**

验证数据库密文字段不含测试 plaintext；响应、OpenAPI 和结构化日志扫描无 API key。运行：

~~~powershell
pwsh -NoProfile -File scripts/check-docs.ps1
$auditRequirements = Join-Path $env:TEMP "rag-phase-02a-audit-requirements.txt"
uv export --project backend --frozen --no-dev --no-emit-project --output-file $auditRequirements
uvx --from pip-audit==2.10.1 pip-audit --ignore-vuln PYSEC-2026-311 -r $auditRequirements
npm --prefix frontend audit --omit=dev --audit-level=high
~~~

已记录 Chroma 例外继续受 2026-08-31 到期门禁约束。

- [ ] **Step 4: 更新状态**

02A 完成后状态写为 `IMPLEMENTATION IN PROGRESS (PHASE 2B)`，列出 02A 提交和验证数字；不得写 Phase 02 complete，因为 MinerU 完整测试和解析尚未实现。

- [ ] **Step 5: 最终提交和推送**

~~~powershell
git add docs/implementation/CURRENT_HANDOFF.md docs/requirements/99-development-readiness.md
git commit -m "docs: hand off phase two parsing implementation"
git push -u origin codex/phase-02-models-parsing
~~~

## 3. 02A 最终审阅清单

- [ ] Provider/Model/MinerU 密钥只以 AES-GCM 密文持久化，AAD 绑定资源。
- [ ] 所有 response DTO/OpenAPI example/log 不含 credential/token/ciphertext/nonce。
- [ ] Provider URL 在保存和调用时均做 SSRF/DNS 校验，redirect 不绕过。
- [ ] Provider credential rotation 原子 stale 所属模型。
- [ ] 模型分类型验证不是同一个 ping；Embedding/Rerank 数值严格 finite。
- [ ] verification revision race 不会把旧结果标记 passed。
- [ ] selector 是后续模块唯一模型选择守卫。
- [ ] Operation/Outbox/Idempotency 在同一事务，duplicate delivery 单副作用。
- [ ] 四个 Provider Adapter 的真实支持类型与 capability 一致。
- [ ] MinerU 保存和完整测试保持分离；02A 不注册假测试。
- [ ] 0002 空库升级、数据库约束和 Alembic check 通过。
- [ ] OpenAPI 二次生成无漂移，前端无手写重复 DTO。
- [ ] 根门禁和 PostgreSQL 集成全通过。

## 4. 预期提交序列

~~~text
docs: add phase two model registry plan
feat: register model provider capabilities
feat: add model registry persistence
feat: secure provider endpoints and credentials
feat: add model provider management
feat: add model provider adapters
feat: add provider discovery operations
feat: add reusable model configurations
feat: verify models by capability type
feat: store MinerU settings securely
chore: generate model registry api client
docs: hand off phase two parsing implementation
~~~

不压缩为一个提交。每个任务必须保留 RED 输出、GREEN 输出和直接相关 diff。
