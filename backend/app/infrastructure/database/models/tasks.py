from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, utc_now

OPERATION_STATUSES = "'queued', 'running', 'succeeded', 'partial_succeeded', 'failed', 'cancelled'"
OUTBOX_STATUSES = "'pending', 'publishing', 'published', 'failed'"


class OperationModel(Base):
    __tablename__ = "operations"
    __table_args__ = (
        CheckConstraint(f"status IN ({OPERATION_STATUSES})", name="status_valid"),
        CheckConstraint("progress_current >= 0", name="progress_current_nonnegative"),
        CheckConstraint(
            "progress_total IS NULL OR progress_total >= 0",
            name="progress_total_nonnegative",
        ),
        CheckConstraint("attempt >= 0", name="attempt_nonnegative"),
        CheckConstraint("max_attempts >= 1", name="max_attempts_positive"),
        CheckConstraint("warning_count >= 0", name="warning_count_nonnegative"),
        UniqueConstraint(
            "business_idempotency_key",
            name="operations_business_idempotency_key_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    task_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[UUID]
    target_revision: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="queued", server_default=text("'queued'")
    )
    stage_code: Mapped[str | None] = mapped_column(Text)
    stage_label: Mapped[str | None] = mapped_column(Text)
    progress_current: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    progress_total: Mapped[int | None] = mapped_column(Integer)
    progress_unit: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default=text("3")
    )
    celery_task_id: Mapped[str | None] = mapped_column(Text)
    business_idempotency_key: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    retry_of_operation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("operations.id", ondelete="RESTRICT")
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    result_summary: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    warning_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OperationItemModel(Base):
    __tablename__ = "operation_items"
    __table_args__ = (
        CheckConstraint(f"status IN ({OPERATION_STATUSES})", name="status_valid"),
        CheckConstraint("progress_current >= 0", name="progress_current_nonnegative"),
        CheckConstraint(
            "progress_total IS NULL OR progress_total >= 0",
            name="progress_total_nonnegative",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    operation_id: Mapped[UUID] = mapped_column(
        ForeignKey("operations.id", ondelete="RESTRICT"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(Text, nullable=False)
    item_id: Mapped[UUID]
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="queued", server_default=text("'queued'")
    )
    stage_code: Mapped[str | None] = mapped_column(Text)
    stage_label: Mapped[str | None] = mapped_column(Text)
    progress_current: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    progress_total: Mapped[int | None] = mapped_column(Integer)
    progress_unit: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    result_summary: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )


class TaskOutboxModel(Base):
    __tablename__ = "task_outbox"
    __table_args__ = (
        CheckConstraint(f"status IN ({OUTBOX_STATUSES})", name="status_valid"),
        CheckConstraint("publish_attempts >= 0", name="publish_attempts_nonnegative"),
        UniqueConstraint("operation_id", "event_type", name="task_outbox_operation_event_uq"),
        Index("task_outbox_status_next_attempt_idx", "status", "next_attempt_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    operation_id: Mapped[UUID] = mapped_column(
        ForeignKey("operations.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default=text("'pending'")
    )
    publish_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class AdminApiIdempotencyRecordModel(Base):
    __tablename__ = "api_idempotency_records"
    __table_args__ = (
        Index(
            "api_idempotency_admin_scope_uq",
            "administrator_id",
            "endpoint_code",
            "idempotency_key_hash",
            unique=True,
            postgresql_where=text("administrator_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    administrator_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrators.id", ondelete="RESTRICT"), nullable=False
    )
    endpoint_code: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    operation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("operations.id", ondelete="RESTRICT")
    )
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
