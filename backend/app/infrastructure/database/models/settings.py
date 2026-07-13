from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Integer, func, text
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
