from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, utc_now


class RetentionSettingsModel(Base):
    __tablename__ = "retention_settings"
    __table_args__ = (
        CheckConstraint("chat_trace_days BETWEEN 7 AND 365", name="chat_trace_days_range"),
        CheckConstraint("conversation_days BETWEEN 1 AND 365", name="conversation_days_range"),
        CheckConstraint("operation_days BETWEEN 7 AND 365", name="operation_days_range"),
        CheckConstraint("audit_days BETWEEN 30 AND 3650", name="audit_days_range"),
        CheckConstraint(
            "temp_attachment_hours BETWEEN 1 AND 168",
            name="temp_attachment_hours_range",
        ),
        CheckConstraint("metric_days BETWEEN 30 AND 3650", name="metric_days_range"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    chat_trace_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default=text("30")
    )
    conversation_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default=text("30")
    )
    operation_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=90, server_default=text("90")
    )
    audit_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=180, server_default=text("180")
    )
    temp_attachment_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=24, server_default=text("24")
    )
    metric_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=365, server_default=text("365")
    )
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
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


class MinerUSettingsModel(Base):
    __tablename__ = "mineru_settings"
    __table_args__ = (
        CheckConstraint("token_revision >= 1", name="token_revision_positive"),
        CheckConstraint(
            "poll_timeout_seconds BETWEEN 300 AND 7200",
            name="poll_timeout_seconds_range",
        ),
        CheckConstraint("revision >= 1", name="revision_positive"),
        CheckConstraint(
            "(token_ciphertext IS NULL AND token_nonce IS NULL "
            "AND token_key_version IS NULL AND token_prefix IS NULL) "
            "OR (token_ciphertext IS NOT NULL AND token_nonce IS NOT NULL "
            "AND token_key_version IS NOT NULL)",
            name="token_encryption_complete",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    token_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    token_nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    token_key_version: Mapped[str | None] = mapped_column(Text)
    token_prefix: Mapped[str | None] = mapped_column(Text)
    token_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    default_parse_config: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    poll_timeout_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1800, server_default=text("1800")
    )
    cloud_processing_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cloud_processing_confirmed_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("administrators.id", ondelete="RESTRICT")
    )
    cloud_processing_terms_version: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
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
