from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, utc_now

MODEL_TYPES = "'llm', 'embedding', 'rerank', 'vision'"
PROVIDER_TYPES = "'openai', 'openai_compatible', 'deepseek', 'qwen'"
VERIFICATION_STATUSES = "'untested', 'passed', 'failed', 'stale'"
VERIFICATION_RESULT_STATUSES = "'succeeded', 'failed', 'timeout'"
DISCOVERY_PROVIDER_STATUSES = "'available', 'unavailable', 'unknown'"
MODEL_TYPES_JSON = '\'["llm", "embedding", "rerank", "vision"]\'::jsonb'


class ModelProviderModel(Base):
    __tablename__ = "model_providers"
    __table_args__ = (
        CheckConstraint(f"provider_type IN ({PROVIDER_TYPES})", name="provider_type_valid"),
        CheckConstraint(
            "jsonb_typeof(supported_model_types) = 'array' "
            f"AND supported_model_types <@ {MODEL_TYPES_JSON}",
            name="supported_model_types_valid",
        ),
        CheckConstraint("credential_revision >= 1", name="credential_revision_positive"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        Index(
            "model_providers_lower_display_name_uq",
            text("lower(display_name)"),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider_type: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    supported_model_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    credential_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    credential_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    credential_key_version: Mapped[str] = mapped_column(Text, nullable=False)
    credential_prefix: Mapped[str | None] = mapped_column(Text)
    credential_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
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
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModelConfigModel(Base):
    __tablename__ = "model_configs"
    __table_args__ = (
        CheckConstraint(f"model_type IN ({MODEL_TYPES})", name="model_type_valid"),
        CheckConstraint(
            f"verification_status IN ({VERIFICATION_STATUSES})",
            name="verification_status_valid",
        ),
        CheckConstraint(
            "context_window IS NULL OR context_window > 0",
            name="context_window_positive",
        ),
        CheckConstraint(
            "max_output_tokens IS NULL OR max_output_tokens > 0",
            name="max_output_tokens_positive",
        ),
        CheckConstraint(
            "embedding_dimension IS NULL OR embedding_dimension > 0",
            name="embedding_dimension_positive",
        ),
        CheckConstraint("revision >= 1", name="revision_positive"),
        Index("model_configs_provider_id_idx", "provider_id"),
        Index(
            "model_configs_provider_identity_uq",
            "provider_id",
            "model_name",
            "model_type",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("model_providers.id", ondelete="RESTRICT"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    model_type: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    verification_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="untested", server_default=text("'untested'")
    )
    context_window: Mapped[int | None] = mapped_column(Integer)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer)
    capability_version: Mapped[str] = mapped_column(Text, nullable=False)
    default_params: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    config_schema: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
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
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModelVerificationModel(Base):
    __tablename__ = "model_verifications"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({VERIFICATION_RESULT_STATUSES})",
            name="status_valid",
        ),
        CheckConstraint("tested_model_revision >= 1", name="tested_model_revision_positive"),
        CheckConstraint("tested_provider_revision >= 1", name="tested_provider_revision_positive"),
        CheckConstraint(
            "tested_credential_revision >= 1", name="tested_credential_revision_positive"
        ),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="latency_nonnegative"),
        Index("model_verifications_model_tested_idx", "model_id", text("tested_at DESC")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    model_id: Mapped[UUID] = mapped_column(
        ForeignKey("model_configs.id", ondelete="RESTRICT"), nullable=False
    )
    operation_id: Mapped[UUID] = mapped_column(
        ForeignKey("operations.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    tested_model_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    tested_provider_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    tested_credential_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    provider_request_id: Mapped[str | None] = mapped_column(Text)
    response_summary: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    tested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class ModelDiscoveredCandidateModel(Base):
    __tablename__ = "model_discovered_candidates"
    __table_args__ = (
        CheckConstraint(
            f"jsonb_typeof(suggested_types) = 'array' AND suggested_types <@ {MODEL_TYPES_JSON}",
            name="suggested_types_valid",
        ),
        CheckConstraint(
            f"provider_status IN ({DISCOVERY_PROVIDER_STATUSES})",
            name="provider_status_valid",
        ),
        UniqueConstraint(
            "provider_id",
            "discovery_operation_id",
            "model_name",
            name="model_discovered_candidates_operation_model_uq",
        ),
        Index(
            "model_discovered_candidates_provider_discovered_idx", "provider_id", "discovered_at"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider_id: Mapped[UUID] = mapped_column(
        ForeignKey("model_providers.id", ondelete="RESTRICT"), nullable=False
    )
    discovery_operation_id: Mapped[UUID] = mapped_column(
        ForeignKey("operations.id", ondelete="RESTRICT"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    provider_status: Mapped[str] = mapped_column(Text, nullable=False)
    raw_metadata_summary: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
