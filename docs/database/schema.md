# PostgreSQL 与索引数据设计

> 上游真源：`docs/requirements/02-domain-model-source.md` 及各模块真源。
> 本文件是第一版 Alembic 迁移、ORM 和 Repository 的数据库契约。

## 1. 通用规则

- PostgreSQL 作为业务和任务唯一真源。
- 表/列使用 `snake_case`，API 使用 `camelCase`。
- 主键 `uuid`，应用生成 UUID；所有 FK 同型。
- 时间 `timestamptz`，统一 UTC。
- 金额第一版无。
- 状态使用 `text + CHECK`，不使用难迁移的 PostgreSQL native enum。
- 所有可编辑聚合根有 `revision integer NOT NULL DEFAULT 1`。
- 软删除资源有 `deleted_at timestamptz NULL`。
- 子资源优先 `ON DELETE RESTRICT`；仅纯快照子表可在清理事务中显式级联。
- JSONB 只用于 capability 参数、不可变快照和外部原始摘要；身份、FK、状态、筛选字段必须正规列。
- 密钥不明文；加密字段拆成 ciphertext/nonce/key_version。
- 所有表至少有 `created_at`，可编辑表再有 `updated_at`。

启用扩展：

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

## 2. 认证、安全和设置

### `administrators`

| 列 | 类型 | 约束 |
|---|---|---|
| id | uuid | PK |
| username | text | NOT NULL |
| password_hash | text | NOT NULL，Argon2id |
| first_login_required | boolean | NOT NULL default true |
| auth_version | integer | NOT NULL default 1 |
| revision | integer | NOT NULL |
| last_login_at | timestamptz | null |
| created_at/updated_at | timestamptz | NOT NULL |

唯一索引：`lower(username)`。

### `mineru_settings`

单行配置，固定逻辑 key `default`：

- id uuid PK。
- base_url text not null。
- token_ciphertext bytea、token_nonce bytea、token_key_version text、token_prefix text，均可空但加密字段必须成组存在。
- token_revision integer not null default 1 check >=1。
- default_parse_config jsonb not null。
- poll_timeout_seconds integer not null check 300-7200。
- cloud_processing_confirmed_at timestamptz/null。
- cloud_processing_confirmed_by uuid/null FK administrators RESTRICT。
- cloud_processing_terms_version text/null。
- revision integer not null default 1 check >=1、created_at、updated_at。

### `retention_settings`

- id uuid PK，单行。
- chat_trace_days 7-365 default 30。
- conversation_days 1-365 default 30。
- operation_days 7-365 default 90。
- audit_days 30-3650 default 180。
- temp_attachment_hours 1-168 default 24。
- metric_days 30-3650 default 365。
- revision、timestamps。

### `audit_logs`

- id uuid PK。
- occurred_at timestamptz not null。
- actor_type/actor_id。
- event_code text not null。
- target_type/target_id/target_name_snapshot。
- trace_id uuid/null。
- source_ip inet/null、user_agent text/null。
- change_summary jsonb not null default `{}`。
- result_status text check `succeeded/failed/denied`。
- error_code text/null。

索引：`occurred_at desc`、`event_code, occurred_at`、`target_type,target_id`。审计表不支持普通业务删除。

## 3. 模型配置

### `model_providers`

- id uuid PK。
- provider_type text not null。
- display_name text not null。
- base_url text not null。
- credential_ciphertext/nonce/key_version。
- credential_prefix text/null。
- credential_revision integer not null default 1；每次凭据轮换递增。
- supported_model_types jsonb array，只允许 llm/embedding/rerank/vision。
- enabled boolean not null default true。
- revision integer not null。
- created_at/updated_at/deleted_at。

部分唯一索引：`lower(display_name) WHERE deleted_at IS NULL`。

### `model_configs`

- id uuid PK。
- provider_id uuid FK model_providers RESTRICT。
- model_name text not null。
- display_name text not null。
- model_type text check `llm/embedding/rerank/vision`。
- enabled boolean default false。
- verification_status text check `untested/passed/failed/stale`。
- context_window integer/null check >0。
- max_output_tokens integer/null check >0。
- embedding_dimension integer/null check >0。
- capability_version text not null。
- default_params jsonb not null default `{}`。
- config_schema jsonb not null default `{}`。
- revision、timestamps、deleted_at。

部分唯一索引：`(provider_id, model_name, model_type) WHERE deleted_at IS NULL`。

### `model_verifications`

- id uuid PK。
- model_id uuid FK RESTRICT。
- operation_id uuid FK operations（通过可延迟迁移添加）。
- tested_model_revision/tested_provider_revision integer。
- tested_credential_revision integer。
- status text check `succeeded/failed/timeout`。
- latency_ms integer、provider_request_id text/null。
- response_summary jsonb、error_code/error_message。
- tested_at timestamptz。

索引：`model_id, tested_at desc`。

### `model_discovered_candidates`

- id uuid PK。
- provider_id uuid FK model_providers RESTRICT。
- discovery_operation_id uuid FK operations RESTRICT。
- model_name text not null。
- suggested_types jsonb array，只允许 `llm/embedding/rerank/vision`。
- provider_status text check `available/unavailable/unknown`。
- raw_metadata_summary jsonb not null default `{}`，不保存完整供应商响应。
- discovered_at timestamptz not null。

唯一约束：`provider_id, discovery_operation_id, model_name`。

## 4. 原始数据源和解析

### `source_blobs`

- id uuid PK。
- sha256 char(64) not null unique。
- size_bytes bigint not null check >=0。
- storage_key text not null unique；只存逻辑 key，不存绝对路径。
- mime_type text not null。
- reference_count integer not null check >=0。
- created_at、last_referenced_at。
- purge_after timestamptz/null。

reference_count 由同一事务内 service 维护，并由维护任务定期校验；不能只靠前端。

### `data_sources`

- id uuid PK。
- source_blob_id uuid FK RESTRICT。
- display_name text not null。
- source_path text not null。
- original_file_name text not null。
- extension/mime_type text not null。
- size_bytes bigint not null。
- sha256 char(64) not null，冗余快照用于查询/审计。
- origin_type text check `admin_upload/channel_ingest/future_connector`。
- origin_ref jsonb not null default `{}`，仅脱敏来源元数据。
- revision、timestamps、deleted_at。

索引：`lower(display_name) gin_trgm_ops`、`sha256`、`origin_type, created_at desc`。

### `parsed_source_versions`

- id uuid PK。
- data_source_id uuid FK RESTRICT。
- version_number integer not null。
- parser_code/parser_version/normalizer_version text not null。
- config_snapshot jsonb not null。
- config_hash char(64) not null。
- source_sha256 char(64) not null。
- status text check `queued/submitting/uploading/provider_pending/parsing/downloading/normalizing/succeeded/degraded/failed/cancelled`。
- quality_level text/null check `full/degraded`。
- progress_current/progress_total integer/null、progress_unit text/null。
- provider_batch_id/provider_task_id/provider_data_id/provider_trace_id text/null；本地批量上传至少保存 batch_id 和 data_id，task_id 仅在供应商实际返回时保存。
- raw_result_storage_key/normalized_storage_key text/null。
- page_count/block_count/asset_count integer not null default 0。
- markdown_char_count bigint not null default 0。
- feature_flags jsonb not null；由固定 JSON Schema 校验上述七个 boolean，API 不接受任意扩展字段。
- error_code/error_message text/null、retryable boolean default false。
- operation_id uuid/null。
- started_at/finished_at/created_at。

约束：unique `(data_source_id, version_number)`。
复用查询索引：`(source_sha256, parser_code, parser_version, config_hash, status)`。

### `parsed_blocks`

- id uuid PK。
- parsed_source_version_id uuid FK RESTRICT。
- block_type text not null。
- order_index integer not null。
- text_content text、markdown_content text。
- heading_level integer/null、heading_path text[]。
- page_number integer/null。
- bounding_box jsonb/null。
- raw_locator jsonb/null。
- content_hash char(64) not null。
- created_at。

约束：unique `(parsed_source_version_id, order_index)`。
索引：`parsed_source_version_id,page_number,order_index`。

### `parsed_assets`

- id uuid PK。
- parsed_source_version_id uuid FK RESTRICT。
- asset_type/mime_type text not null。
- page_number integer/null、bounding_box jsonb/null。
- storage_key text not null、sha256 char(64)、size_bytes bigint。
- caption/ocr_text text/null。
- order_index integer not null。
- created_at。

### `parsed_block_assets`

- block_id uuid FK parsed_blocks RESTRICT。
- asset_id uuid FK parsed_assets RESTRICT。
- primary key `(block_id, asset_id)`。

### `parsed_artifacts`

- id uuid PK。
- parsed_source_version_id uuid FK RESTRICT。
- artifact_type text、display_name text、storage_key text、sha256 char(64)、size_bytes bigint。
- is_downloadable boolean default false。
- created_at。

## 5. 知识库配置和构建

### `knowledge_bases`

- id uuid PK。
- name text not null。
- description text/null。
- enabled boolean not null default true。
- active_generation_id uuid/null（延迟 FK index_generations）。
- active_retrieval_revision_id uuid/null（延迟 FK kb_retrieval_revisions）。
- pending_build_config_revision_id uuid/null（延迟 FK kb_build_config_revisions）。
- pending_retrieval_revision_id uuid/null（延迟 FK kb_retrieval_revisions）。
- latest_build_operation_id uuid/null。
- revision integer not null。
- created_at/updated_at/deleted_at。

部分唯一索引：`lower(name) WHERE deleted_at IS NULL`。

### `kb_build_config_revisions`

- id uuid PK。
- knowledge_base_id uuid FK RESTRICT。
- revision_number integer not null。
- embedding_model_id uuid FK model_configs RESTRICT。
- embedding_model_snapshot jsonb not null。
- embedding_params jsonb not null。
- vector_store_code/vector_store_version text not null。
- vector_index_code/vector_index_version text not null。
- vector_index_params jsonb not null。
- keyword_store_code/keyword_store_version text not null。
- index_structure text check `chunk/parent_child`。
- chunk_strategy_code/chunk_strategy_version text not null。
- chunk_params jsonb not null。
- token_counter_snapshot jsonb not null。
- config_hash char(64) not null。
- created_at。

约束：unique `(knowledge_base_id, revision_number)`、unique `(knowledge_base_id, config_hash)`；提交相同 hash 时 service 返回已有修订 ID，不重复插入。

### `kb_build_config_sources`

- config_revision_id uuid FK RESTRICT。
- parsed_source_version_id uuid FK RESTRICT。
- order_index integer not null。
- created_at。
- primary key `(config_revision_id, parsed_source_version_id)`。
- unique `(config_revision_id, order_index)`。

### `kb_retrieval_revisions`

- id uuid PK。
- knowledge_base_id uuid FK RESTRICT。
- revision_number integer not null。
- retrieval_type text check `vector/keyword/hybrid`。
- vector_config/keyword_config/fusion_config jsonb not null。
- query_rewrite_code/version text not null。
- query_rewrite_model_id uuid/null FK model_configs RESTRICT。
- query_rewrite_params jsonb not null。
- rerank_code/version text not null。
- rerank_model_id uuid/null FK model_configs RESTRICT。
- rerank_params jsonb not null。
- context_window integer not null。
- final_top_k integer not null。
- config_hash char(64) not null。
- created_at。

约束：unique `(knowledge_base_id, revision_number)`。

### `index_generations`

- id uuid PK。
- knowledge_base_id uuid FK RESTRICT。
- generation_number integer not null。
- build_config_revision_id uuid FK RESTRICT。
- retrieval_revision_id uuid FK kb_retrieval_revisions RESTRICT；该 generation 激活时要一起发布的检索修订。
- status text check `queued/building/validating/succeeded/partial_ready/partial_failed/failed/cancelled/discarded`。
- completeness text/null check `full/partial`。
- collection_name text not null unique。
- keyword_namespace uuid not null unique。
- source_count/successful_source_count/failed_source_count integer default 0。
- chunk_count/vector_count bigint default 0。
- validation_report jsonb not null default `{}`。
- operation_id uuid/null。
- is_frozen boolean not null default false。
- started_at/finished_at/activated_at/retain_until/created_at。

约束：unique `(knowledge_base_id, generation_number)`；`activated_at IS NOT NULL -> is_frozen=true` 由 service + CHECK/trigger 验证。

### `index_generation_items`

- id uuid PK。
- index_generation_id uuid FK RESTRICT。
- parsed_source_version_id uuid FK RESTRICT。
- status text check `queued/chunking/embedding/keyword_indexing/vector_indexing/validating/succeeded/failed`。
- stage_progress jsonb not null default `{}`。
- chunk_count/vector_count integer default 0。
- source_copy_from_item_id uuid/null self FK。
- error_code/error_message text/null、retryable boolean default false。
- started_at/finished_at/created_at。

约束：unique `(index_generation_id, parsed_source_version_id)`。

### `chunks`

- id uuid PK；确定性生成。
- index_generation_id uuid FK RESTRICT。
- generation_item_id uuid FK RESTRICT。
- parsed_source_version_id uuid FK RESTRICT。
- chunk_kind text check `chunk/parent/child`。
- parent_chunk_id uuid/null self FK。
- order_index integer not null。
- text_content text not null。
- searchable_text text not null。
- normalized_text_hash char(64) not null。
- token_count integer not null。
- token_counter_code/version text not null。
- heading_path text[]。
- page_range integer[]。
- primary_page_number integer/null。
- bounding_boxes jsonb/null。
- previous_chunk_id/next_chunk_id uuid/null self FK。
- created_at。

约束：unique `(index_generation_id, generation_item_id, chunk_kind, order_index)`。

索引：

```sql
CREATE INDEX chunks_generation_kind_idx
  ON chunks(index_generation_id, chunk_kind);

CREATE INDEX chunks_searchable_trgm_idx
  ON chunks USING gin (searchable_text gin_trgm_ops);

CREATE INDEX chunks_source_idx
  ON chunks(parsed_source_version_id, index_generation_id);
```

关键词查询必须先过滤 generation，再使用 trigram 候选；SQL 计划纳入集成测试。

### `chunk_source_blocks`

- chunk_id uuid FK chunks RESTRICT。
- parsed_block_id uuid FK parsed_blocks RESTRICT。
- order_index integer not null。
- primary key `(chunk_id, parsed_block_id)`。
- unique `(chunk_id, order_index)`。

### `chunk_assets`

- chunk_id uuid FK chunks RESTRICT。
- parsed_asset_id uuid FK parsed_assets RESTRICT。
- primary key `(chunk_id, parsed_asset_id)`。

来源映射通过上述 join tables 保证 FK；API/Trace 中的 sourceBlockIds/assetIds 是查询投影，不是无约束真源。

数据库触发器 `reject_frozen_generation_mutation` 必须阻止对已 `is_frozen=true` generation 的 items、chunks、chunk_source_blocks 和 chunk_assets 执行 INSERT/UPDATE/DELETE。清理 frozen generation 只能由受控 purge transaction 先确认不是活动/保留引用，再使用专用维护角色执行。

## 6. Chroma 契约

每个 generation 一个 collection。向量记录：

- ID = chunk UUID 字符串。
- document = `searchable_text` 检索文本副本，固定写入，便于 Chroma 调试和契约测试。
- embedding = 模型输出。
- metadata：knowledgeBaseId、indexGenerationId、generationItemId、parsedSourceVersionId、chunkKind、parentChunkId、tokenCount。

禁止把完整路径、密钥、用户可变名称写入 metadata。PostgreSQL 校验 chunk/generation 是活动真源；Chroma metadata 仅用于过滤和排查。

## 7. 机器人配置

### `bots`

- id uuid PK。
- name、description。
- active_config_revision_id uuid/null（延迟 FK）。
- revision integer。
- created_at/updated_at/deleted_at。

部分唯一索引：`lower(name) WHERE deleted_at IS NULL`。

### `bot_config_revisions`

- id uuid PK。
- bot_id uuid FK RESTRICT。
- revision_number integer。
- answer_model_id uuid FK model_configs RESTRICT。
- answer_model_snapshot jsonb not null。
- answer_model_params jsonb not null。
- system_prompt text not null。
- merge_mode text check `rank_fusion`。
- rrf_k integer not null default 60。
- per_kb_limit integer not null。
- final_context_top_k integer not null。
- max_context_tokens integer not null。
- memory_config jsonb not null。
- no_hit_policy text check `message_only/message_then_llm`。
- config_hash char(64) not null。
- created_at。

### `bot_config_kb_bindings`

- bot_config_revision_id uuid FK RESTRICT。
- knowledge_base_id uuid FK RESTRICT。
- enabled boolean not null。
- priority integer not null check 1-10。
- created_at。
- primary key `(bot_config_revision_id, knowledge_base_id)`。

## 8. 渠道和幂等

### `channel_instances`

- id uuid PK。
- name text not null。
- adapter_code/version text not null。
- bot_id uuid FK bots RESTRICT。
- enabled boolean default false。
- api_key_hash char(64) not null unique。
- api_key_prefix text not null。
- callback_url text/null。
- callback_secret_ciphertext/nonce/key_version。
- rate_limit_per_minute integer not null。
- max_concurrent_requests integer not null。
- allowed_citation_levels text[] not null。
- config jsonb not null default `{}`。
- revision、timestamps、deleted_at、rotated_at。

### `api_idempotency_records`

- id uuid PK。
- administrator_id uuid/null FK administrators RESTRICT。
- channel_instance_id uuid/null FK channel_instances RESTRICT。
- endpoint_code text not null。
- idempotency_key_hash char(64) not null。
- request_hash char(64) not null。
- operation_id uuid/null。
- response_status integer/null。
- response_body jsonb/null（仅小型终态响应）。
- expires_at、created_at。

约束：CHECK 恰好一个 actor FK 非空；分别建立：

- unique `(administrator_id, endpoint_code, idempotency_key_hash) WHERE administrator_id IS NOT NULL`。
- unique `(channel_instance_id, endpoint_code, idempotency_key_hash) WHERE channel_instance_id IS NOT NULL`。

分阶段迁移时允许先建立仅含 `administrator_id` 的 expand 形态以服务后台命令幂等；创建 `channel_instances` 后必须在后续迁移增加 `channel_instance_id` FK 和“恰好一个 actor”CHECK。V1 发布验收以本节最终结构为准，不允许长期保留无 actor 约束的中间形态。

### `temporary_attachments`

- id uuid PK。
- channel_instance_id uuid FK RESTRICT。
- source_blob_id uuid FK RESTRICT。
- file_name/mime_type/size_bytes/sha256。
- status text check `uploaded/queued/parsing/ready/failed/expired/deleted`。
- parser_snapshot jsonb、normalized_storage_key text/null。
- operation_id uuid/null。
- error_code/error_message。
- expires_at not null、created_at/updated_at/deleted_at。

### `channel_callback_deliveries`

- id uuid PK。
- channel_instance_id uuid FK RESTRICT。
- chat_run_id uuid FK RESTRICT。
- event_id uuid not null。
- attempt integer not null。
- status text check `queued/sending/succeeded/retry_wait/failed`。
- next_attempt_at、http_status、duration_ms。
- request_hash/response_summary/error_code/error_message。
- created_at/finished_at。

索引：`status,next_attempt_at`；unique `(event_id, attempt)`。

## 9. 会话、问答和模型调用

### `conversations`

- id uuid PK。
- bot_id uuid FK RESTRICT。
- channel_instance_id uuid/null FK RESTRICT。
- external_conversation_id text not null。
- sender_id_hash text/null。
- last_active_at timestamptz。
- expires_at、created_at、deleted_at。

唯一索引使用 PostgreSQL `NULLS NOT DISTINCT`：`(bot_id, channel_instance_id, external_conversation_id) NULLS NOT DISTINCT WHERE deleted_at IS NULL`，使后台测试的 null channel 也具备唯一会话键。

### `conversation_messages`

- id uuid PK。
- conversation_id uuid FK RESTRICT。
- chat_run_id uuid/null FK。
- role text check `user/assistant`。
- content_ciphertext/nonce/key_version；会话正文按敏感载荷策略加密。
- token_count integer/null。
- created_at、expires_at。

### `chat_runs`

- id uuid PK。
- trace_id uuid not null unique。
- source text check `admin_test/webhook_api/future_channel`。
- status text check `running/succeeded/failed`。
- bot_id uuid FK RESTRICT、bot_config_revision_id uuid FK RESTRICT。
- channel_instance_id uuid/null FK。
- conversation_id uuid/null FK。
- message_id text/null、request_id_hash char(64)/null。
- retrieval_status text check `not_run/succeeded/partial_failed/failed`。
- is_hit boolean not null default false。
- fallback_used boolean default false、answer_basis text/null。
- partial_retrieval_failure boolean default false。
- attempted/hit/failed/skipped_kb_count integer default 0。
- final_context_count/citation_count integer default 0。
- answer_model_id uuid/null FK、input/output/total_tokens integer/null。
- citation_validation_status text/null。
- error_code/error_message text/null。
- requested_at/responded_at/total_latency_ms。
- created_at、expires_at。

索引：time、bot/time、channel/time、status/time、trace_id。

### `chat_run_kb_results`

- id uuid PK。
- chat_run_id uuid FK RESTRICT。
- knowledge_base_id uuid FK RESTRICT。
- index_generation_id uuid/null FK RESTRICT。
- retrieval_revision_id uuid/null FK RESTRICT。
- status text check `hit/no_hit/failed/skipped`。
- candidate_counts jsonb、timing jsonb。
- top_rank/weight numeric/null。
- error_code/error_message。
- created_at。

### `chat_run_contexts`

- id uuid PK。
- chat_run_id uuid FK RESTRICT。
- context_order integer not null。
- knowledge_base_ids uuid[] not null。
- chunk_ids uuid[] not null。
- parsed_source_version_id uuid FK RESTRICT。
- source_block_ids uuid[] not null。
- normalized_text_hash char(64)。
- token_count integer、cross_kb_rrf_score double precision。
- context_payload_ciphertext/nonce/key_version。
- created_at。

### `chat_run_citations`

- id uuid PK。
- chat_run_id uuid FK RESTRICT。
- citation_code text not null。
- context_id uuid FK chat_run_contexts RESTRICT。
- data_source_id uuid/null FK RESTRICT。
- parsed_source_version_id uuid/null FK RESTRICT。
- knowledge_base_ids uuid[]。
- source_name/path/type snapshots。
- page_range integer[]、source_block_ids uuid[]、asset_ids uuid[]。
- snippet_ciphertext/nonce/key_version。
- deleted_or_expired boolean default false。
- created_at。

### `chat_trace_payloads`

- chat_run_id uuid PK/FK RESTRICT。
- schema_version text not null。
- payload_ciphertext/nonce/key_version。
- payload_sha256 char(64)。
- created_at、expires_at。

### `model_call_logs`

- id uuid PK。
- trace_id/operation_id/chat_run_id 可空。
- model_id/provider_id FK。
- purpose text not null。
- status text、attempt_count、latency_ms。
- input/output/total_tokens、input_item_count。
- provider_request_id、error_code。
- created_at。

不存完整输入/输出；完整内容只在受控 Trace payload。

## 10. Operation 和 Outbox

### `operations`

- id uuid PK。
- task_type/target_type/target_id/target_revision。
- status text check `queued/running/succeeded/partial_succeeded/failed/cancelled`。
- stage_code/label。
- progress_current/total/unit。
- attempt/max_attempts。
- celery_task_id text/null。
- business_idempotency_key char(64) not null。
- retry_of_operation_id uuid/null self FK。
- heartbeat_at、queued_at、started_at、finished_at。
- error_code/error_message、retryable。
- result_summary jsonb。
- warning_count integer default 0。
- created_at、expires_at。

`business_idempotency_key` 全局唯一；相同命令即使已有终态也返回原 operation。管理员明确重试/重新执行必须生成包含新 operation intent 的新业务键。

```sql
UNIQUE (business_idempotency_key)
```

### `operation_items`

- id uuid PK。
- operation_id uuid FK RESTRICT。
- item_type/item_id。
- status/stage/progress/error/retryable/result_summary。
- timestamps。

### `task_outbox`

- id uuid PK。
- operation_id uuid FK RESTRICT。
- event_type text、schema_version text。
- payload jsonb not null（只含 ID/修订，不含密钥/正文）。
- status text check `pending/publishing/published/failed`。
- publish_attempts、next_attempt_at、published_at、last_error。
- created_at。

索引：`status,next_attempt_at`。unique `(operation_id,event_type)`。

## 11. 评测和指标

### `evaluation_datasets`

- id uuid PK、knowledge_base_id FK。
- name/description、revision、current_dataset_revision_id。
- timestamps、deleted_at。

### `evaluation_dataset_revisions`

- id uuid PK、dataset_id FK、revision_number、content_hash、created_at。

### `evaluation_cases`

- id uuid PK、dataset_revision_id FK。
- order_index、question text、should_hit boolean。
- expected_sources jsonb not null。
- reference_answer text/null。
- created_at。

### `evaluation_runs`

- id uuid PK、dataset_revision_id、knowledge_base_id、index_generation_id、retrieval_revision_id。
- temporary_retrieval_config jsonb/null。
- status、operation_id。
- hit_at_k/recall_at_k/mrr/no_hit_accuracy double precision/null。
- latency_percentiles jsonb、error_rate double precision。
- case_count/succeeded_count/failed_count。
- started_at/finished_at/created_at。

### `evaluation_case_results`

- id uuid PK、run_id、case_id。
- status、is_correct_hit、first_relevant_rank、retrieved_sources jsonb。
- latency_ms、error_code/error_message。

### `metric_buckets`

- id uuid PK。
- bucket_start/bucket_size_seconds。
- metric_code text。
- dimensions jsonb（固定低基数白名单）。
- dimensions_hash char(64) not null。
- count_value bigint、sum_value double precision、min/max_value。
- histogram jsonb/null。
- generated_at。

唯一 `(bucket_start,bucket_size_seconds,metric_code,dimensions_hash)`。

## 12. 删除和保留

- 业务删除先软删除聚合根，清理 operation 处理子资源和外部索引。
- 被当前配置/活动 generation/保留 generation 引用的解析版本使用 RESTRICT。
- 知识库被 bot revision 引用时 API 先阻止；历史 revisions 保留，清理逻辑区分 active/current reference。
- 机器人被 channel instance 引用时阻止。
- ChatRun/citation 保存快照；业务对象删除后不级联删除 ChatRun。
- retention 清理按 expires_at 小批执行。
- Blob 物理删除仅 reference_count=0、purge_after 到期且无 pending operation。

## 13. 事务边界

必须在单事务完成：

- 资源变更 + operation + outbox。
- 配置 revision 创建 + knowledge_base/bot 活动/待发布指针更新。
- generation 激活条件检查 + active_generation_id/active_retrieval_revision_id 同时切换 + pending 指针清理 + generation frozen。
- API Key 轮换 hash 更新 +审计日志。
- 删除 tombstone + 清理 operation/outbox。

Chroma/文件操作在事务外暂存；事务只切换可见指针。禁止长时间持有数据库事务等待 MinerU/模型/Chroma 网络调用。

## 14. 迁移顺序

第一版初始迁移按：

1. extensions/security/settings。
2. model registry。
3. source/parsing。
4. knowledge/retrieval。
5. bots/channels。
6. operations/outbox。
7. chats/observability/evaluation。
8. 延迟外键和索引。

CI 验证空库升级和重复升级。删除/重命名字段使用 expand-migrate-contract，不在一个发布内直接破坏。

## 15. 数据库验收

- 所有核心关系有 FK/唯一/check，不只靠 Pydantic；chunk 来源通过 join table 约束。
- 相同配置修订不能重复绑定解析版本。
- 同一 KB 只有一个 activeGenerationId，冻结代次不能新增/修改 chunks。
- pg_trgm 查询使用 GIN 并先过滤 generation。
- 模型/知识库/机器人/渠道删除引用规则由数据库和 service 双重保护。
- outbox 与业务对象同事务，Redis 丢失后可重发。
- 删除业务对象不会级联抹掉 ChatRun/citation 快照。
- 凭据、会话正文、Trace/snippet 敏感字段不明文。
