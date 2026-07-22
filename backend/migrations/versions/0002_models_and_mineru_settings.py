"""Add model registry and MinerU settings persistence.

Revision ID: 0002_models_and_mineru_settings
Revises: 0001_foundation
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_models_and_mineru_settings"
down_revision: str | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MODEL_TYPES_JSON = '\'["llm", "embedding", "rerank", "vision"]\'::jsonb'


def create_model_providers() -> None:
    op.create_table(
        "model_providers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_type", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("supported_model_types", postgresql.JSONB(), nullable=False),
        sa.Column("credential_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("credential_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("credential_key_version", sa.Text(), nullable=False),
        sa.Column("credential_prefix", sa.Text(), nullable=True),
        sa.Column("credential_revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "credential_revision >= 1",
            name=op.f("model_providers_credential_revision_positive_ck"),
        ),
        sa.CheckConstraint(
            "provider_type IN ('openai', 'openai_compatible', 'deepseek', 'qwen')",
            name=op.f("model_providers_provider_type_valid_ck"),
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name=op.f("model_providers_revision_positive_ck"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(supported_model_types) = 'array' "
            f"AND supported_model_types <@ {MODEL_TYPES_JSON}",
            name=op.f("model_providers_supported_model_types_valid_ck"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("model_providers_pkey")),
    )
    op.create_index(
        "model_providers_lower_display_name_uq",
        "model_providers",
        [sa.text("lower(display_name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def create_model_configs() -> None:
    op.create_table(
        "model_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("model_type", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "verification_status", sa.Text(), server_default=sa.text("'untested'"), nullable=False
        ),
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("embedding_dimension", sa.Integer(), nullable=True),
        sa.Column("capability_version", sa.Text(), nullable=False),
        sa.Column(
            "default_params",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "config_schema",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "context_window IS NULL OR context_window > 0",
            name=op.f("model_configs_context_window_positive_ck"),
        ),
        sa.CheckConstraint(
            "embedding_dimension IS NULL OR embedding_dimension > 0",
            name=op.f("model_configs_embedding_dimension_positive_ck"),
        ),
        sa.CheckConstraint(
            "max_output_tokens IS NULL OR max_output_tokens > 0",
            name=op.f("model_configs_max_output_tokens_positive_ck"),
        ),
        sa.CheckConstraint(
            "model_type IN ('llm', 'embedding', 'rerank', 'vision')",
            name=op.f("model_configs_model_type_valid_ck"),
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("model_configs_revision_positive_ck")),
        sa.CheckConstraint(
            "verification_status IN ('untested', 'passed', 'failed', 'stale')",
            name=op.f("model_configs_verification_status_valid_ck"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["model_providers.id"],
            name=op.f("model_configs_provider_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("model_configs_pkey")),
    )
    op.create_index("model_configs_provider_id_idx", "model_configs", ["provider_id"])
    op.create_index(
        "model_configs_provider_identity_uq",
        "model_configs",
        ["provider_id", "model_name", "model_type"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def create_model_verifications() -> None:
    op.create_table(
        "model_verifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("tested_model_revision", sa.Integer(), nullable=False),
        sa.Column("tested_provider_revision", sa.Integer(), nullable=False),
        sa.Column("tested_credential_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("provider_request_id", sa.Text(), nullable=True),
        sa.Column(
            "response_summary",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "tested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name=op.f("model_verifications_latency_nonnegative_ck"),
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed', 'timeout')",
            name=op.f("model_verifications_status_valid_ck"),
        ),
        sa.CheckConstraint(
            "tested_credential_revision >= 1",
            name=op.f("model_verifications_tested_credential_revision_positive_ck"),
        ),
        sa.CheckConstraint(
            "tested_model_revision >= 1",
            name=op.f("model_verifications_tested_model_revision_positive_ck"),
        ),
        sa.CheckConstraint(
            "tested_provider_revision >= 1",
            name=op.f("model_verifications_tested_provider_revision_positive_ck"),
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["model_configs.id"],
            name=op.f("model_verifications_model_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.id"],
            name=op.f("model_verifications_operation_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("model_verifications_pkey")),
        sa.UniqueConstraint("operation_id", name=op.f("model_verifications_operation_id_uq")),
    )
    op.create_index(
        "model_verifications_model_tested_idx",
        "model_verifications",
        ["model_id", sa.text("tested_at DESC")],
    )


def create_model_discovered_candidates() -> None:
    op.create_table(
        "model_discovered_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("discovery_operation_id", sa.Uuid(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("suggested_types", postgresql.JSONB(), nullable=False),
        sa.Column("provider_status", sa.Text(), nullable=False),
        sa.Column(
            "raw_metadata_summary",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider_status IN ('available', 'unavailable', 'unknown')",
            name=op.f("model_discovered_candidates_provider_status_valid_ck"),
        ),
        sa.CheckConstraint(
            f"jsonb_typeof(suggested_types) = 'array' AND suggested_types <@ {MODEL_TYPES_JSON}",
            name=op.f("model_discovered_candidates_suggested_types_valid_ck"),
        ),
        sa.ForeignKeyConstraint(
            ["discovery_operation_id"],
            ["operations.id"],
            name=op.f("model_discovered_candidates_discovery_operation_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["model_providers.id"],
            name=op.f("model_discovered_candidates_provider_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("model_discovered_candidates_pkey")),
        sa.UniqueConstraint(
            "provider_id",
            "discovery_operation_id",
            "model_name",
            name="model_discovered_candidates_operation_model_uq",
        ),
    )
    op.create_index(
        "model_discovered_candidates_provider_discovered_idx",
        "model_discovered_candidates",
        ["provider_id", "discovered_at"],
    )


def create_mineru_settings() -> None:
    op.create_table(
        "mineru_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("token_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("token_nonce", sa.LargeBinary(), nullable=True),
        sa.Column("token_key_version", sa.Text(), nullable=True),
        sa.Column("token_prefix", sa.Text(), nullable=True),
        sa.Column("token_revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "default_parse_config",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "poll_timeout_seconds", sa.Integer(), server_default=sa.text("1800"), nullable=False
        ),
        sa.Column("cloud_processing_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cloud_processing_confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("cloud_processing_terms_version", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "poll_timeout_seconds BETWEEN 300 AND 7200",
            name=op.f("mineru_settings_poll_timeout_seconds_range_ck"),
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("mineru_settings_revision_positive_ck")),
        sa.CheckConstraint(
            "(token_ciphertext IS NULL AND token_nonce IS NULL "
            "AND token_key_version IS NULL AND token_prefix IS NULL) "
            "OR (token_ciphertext IS NOT NULL AND token_nonce IS NOT NULL "
            "AND token_key_version IS NOT NULL)",
            name=op.f("mineru_settings_token_encryption_complete_ck"),
        ),
        sa.CheckConstraint(
            "token_revision >= 1",
            name=op.f("mineru_settings_token_revision_positive_ck"),
        ),
        sa.ForeignKeyConstraint(
            ["cloud_processing_confirmed_by"],
            ["administrators.id"],
            name=op.f("mineru_settings_cloud_processing_confirmed_by_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("mineru_settings_pkey")),
    )


def upgrade() -> None:
    create_model_providers()
    create_model_configs()
    create_model_verifications()
    create_model_discovered_candidates()
    create_mineru_settings()


def downgrade() -> None:
    op.drop_table("mineru_settings")
    op.drop_index(
        "model_discovered_candidates_provider_discovered_idx",
        table_name="model_discovered_candidates",
    )
    op.drop_table("model_discovered_candidates")
    op.drop_index("model_verifications_model_tested_idx", table_name="model_verifications")
    op.drop_table("model_verifications")
    op.drop_index("model_configs_provider_identity_uq", table_name="model_configs")
    op.drop_index("model_configs_provider_id_idx", table_name="model_configs")
    op.drop_table("model_configs")
    op.drop_index("model_providers_lower_display_name_uq", table_name="model_providers")
    op.drop_table("model_providers")
