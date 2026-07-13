"""Create the foundation persistence schema.

Revision ID: 0001_foundation
Revises:
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def create_administrators() -> None:
    op.create_table(
        "administrators",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "first_login_required", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("auth_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("administrators_pkey")),
    )
    op.create_index(
        "administrators_lower_username_uq",
        "administrators",
        [sa.text("lower(username)")],
        unique=True,
    )


def create_retention_settings() -> None:
    op.create_table(
        "retention_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chat_trace_days", sa.Integer(), server_default=sa.text("30"), nullable=False),
        sa.Column("conversation_days", sa.Integer(), server_default=sa.text("30"), nullable=False),
        sa.Column("operation_days", sa.Integer(), server_default=sa.text("90"), nullable=False),
        sa.Column("audit_days", sa.Integer(), server_default=sa.text("180"), nullable=False),
        sa.Column(
            "temp_attachment_hours", sa.Integer(), server_default=sa.text("24"), nullable=False
        ),
        sa.Column("metric_days", sa.Integer(), server_default=sa.text("365"), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "audit_days BETWEEN 30 AND 3650",
            name=op.f("retention_settings_audit_days_range_ck"),
        ),
        sa.CheckConstraint(
            "chat_trace_days BETWEEN 7 AND 365",
            name=op.f("retention_settings_chat_trace_days_range_ck"),
        ),
        sa.CheckConstraint(
            "conversation_days BETWEEN 1 AND 365",
            name=op.f("retention_settings_conversation_days_range_ck"),
        ),
        sa.CheckConstraint(
            "metric_days BETWEEN 30 AND 3650",
            name=op.f("retention_settings_metric_days_range_ck"),
        ),
        sa.CheckConstraint(
            "operation_days BETWEEN 7 AND 365",
            name=op.f("retention_settings_operation_days_range_ck"),
        ),
        sa.CheckConstraint(
            "temp_attachment_hours BETWEEN 1 AND 168",
            name=op.f("retention_settings_temp_attachment_hours_range_ck"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("retention_settings_pkey")),
    )


def create_audit_logs() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("event_code", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("target_name_snapshot", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=True),
        sa.Column("source_ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "change_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("result_status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "result_status IN ('succeeded', 'failed', 'denied')",
            name=op.f("audit_logs_result_status_valid_ck"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("audit_logs_pkey")),
    )
    op.create_index("audit_logs_occurred_at_idx", "audit_logs", [sa.text("occurred_at DESC")])
    op.create_index("audit_logs_event_occurred_idx", "audit_logs", ["event_code", "occurred_at"])
    op.create_index("audit_logs_target_idx", "audit_logs", ["target_type", "target_id"])


def create_operations() -> None:
    op.create_table(
        "operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("target_revision", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("stage_code", sa.Text(), nullable=True),
        sa.Column("stage_label", sa.Text(), nullable=True),
        sa.Column("progress_current", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column("progress_unit", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("celery_task_id", sa.Text(), nullable=True),
        sa.Column("business_idempotency_key", sa.CHAR(length=64), nullable=False),
        sa.Column("retry_of_operation_id", sa.Uuid(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "queued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "result_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("warning_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempt >= 0", name=op.f("operations_attempt_nonnegative_ck")),
        sa.CheckConstraint("max_attempts >= 1", name=op.f("operations_max_attempts_positive_ck")),
        sa.CheckConstraint(
            "progress_current >= 0",
            name=op.f("operations_progress_current_nonnegative_ck"),
        ),
        sa.CheckConstraint(
            "progress_total IS NULL OR progress_total >= 0",
            name=op.f("operations_progress_total_nonnegative_ck"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'partial_succeeded', "
            "'failed', 'cancelled')",
            name=op.f("operations_status_valid_ck"),
        ),
        sa.CheckConstraint(
            "warning_count >= 0",
            name=op.f("operations_warning_count_nonnegative_ck"),
        ),
        sa.ForeignKeyConstraint(
            ["retry_of_operation_id"],
            ["operations.id"],
            name=op.f("operations_retry_of_operation_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("operations_pkey")),
        sa.UniqueConstraint(
            "business_idempotency_key",
            name="operations_business_idempotency_key_uq",
        ),
    )


def create_operation_items() -> None:
    op.create_table(
        "operation_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("item_type", sa.Text(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("stage_code", sa.Text(), nullable=True),
        sa.Column("stage_label", sa.Text(), nullable=True),
        sa.Column("progress_current", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column("progress_unit", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "result_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "progress_current >= 0",
            name=op.f("operation_items_progress_current_nonnegative_ck"),
        ),
        sa.CheckConstraint(
            "progress_total IS NULL OR progress_total >= 0",
            name=op.f("operation_items_progress_total_nonnegative_ck"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'partial_succeeded', "
            "'failed', 'cancelled')",
            name=op.f("operation_items_status_valid_ck"),
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.id"],
            name=op.f("operation_items_operation_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("operation_items_pkey")),
    )


def create_task_outbox() -> None:
    op.create_table(
        "task_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("publish_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "publish_attempts >= 0",
            name=op.f("task_outbox_publish_attempts_nonnegative_ck"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'publishing', 'published', 'failed')",
            name=op.f("task_outbox_status_valid_ck"),
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.id"],
            name=op.f("task_outbox_operation_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("task_outbox_pkey")),
        sa.UniqueConstraint("operation_id", "event_type", name="task_outbox_operation_event_uq"),
    )
    op.create_index(
        "task_outbox_status_next_attempt_idx",
        "task_outbox",
        ["status", "next_attempt_at"],
    )


def create_admin_api_idempotency_records() -> None:
    op.create_table(
        "api_idempotency_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("administrator_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint_code", sa.Text(), nullable=False),
        sa.Column("idempotency_key_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("request_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["administrator_id"],
            ["administrators.id"],
            name=op.f("api_idempotency_records_administrator_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.id"],
            name=op.f("api_idempotency_records_operation_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("api_idempotency_records_pkey")),
    )
    op.create_index(
        "api_idempotency_admin_scope_uq",
        "api_idempotency_records",
        ["administrator_id", "endpoint_code", "idempotency_key_hash"],
        unique=True,
        postgresql_where=sa.text("administrator_id IS NOT NULL"),
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    create_administrators()
    create_retention_settings()
    create_audit_logs()
    create_operations()
    create_operation_items()
    create_task_outbox()
    create_admin_api_idempotency_records()


def downgrade() -> None:
    op.drop_index("api_idempotency_admin_scope_uq", table_name="api_idempotency_records")
    op.drop_table("api_idempotency_records")
    op.drop_index("task_outbox_status_next_attempt_idx", table_name="task_outbox")
    op.drop_table("task_outbox")
    op.drop_table("operation_items")
    op.drop_table("operations")
    op.drop_index("audit_logs_target_idx", table_name="audit_logs")
    op.drop_index("audit_logs_event_occurred_idx", table_name="audit_logs")
    op.drop_index("audit_logs_occurred_at_idx", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("retention_settings")
    op.drop_index("administrators_lower_username_uq", table_name="administrators")
    op.drop_table("administrators")
