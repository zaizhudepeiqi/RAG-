from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from app.modules.models.domain import (
    ModelConfig,
    ModelProvider,
    ModelReference,
    ModelType,
    ModelVerificationSnapshot,
    VerificationStatus,
)
from app.modules.models.service import (
    ModelConfigService,
    ModelInUseError,
    ModelNotSelectableError,
    ModelSelectionService,
)
from sqlalchemy.orm import Session


def provider() -> ModelProvider:
    now = datetime.now(UTC)
    return ModelProvider(
        id=uuid4(),
        provider_type="openai",
        display_name="Selection Provider",
        base_url="https://8.8.8.8/v1",
        supported_model_types=(ModelType.LLM, ModelType.EMBEDDING, ModelType.VISION),
        credential_ciphertext=b"encrypted",
        credential_nonce=b"123456789012",
        credential_key_version="v1",
        credential_prefix="sk-t...1234",
        credential_revision=3,
        enabled=True,
        revision=4,
        created_at=now,
        updated_at=now,
        deleted_at=None,
        model_count=1,
    )


def model(provider_id: UUID) -> ModelConfig:
    now = datetime.now(UTC)
    return ModelConfig(
        id=uuid4(),
        provider_id=provider_id,
        model_name="gpt-model-v1",
        display_name="GPT Model",
        model_type=ModelType.LLM,
        enabled=True,
        verification_status=VerificationStatus.PASSED,
        context_window=8192,
        max_output_tokens=2048,
        embedding_dimension=None,
        capability_version="1",
        default_params={"temperature": 0.2},
        config_schema={"type": "object"},
        revision=7,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )


def verification(model_id: UUID) -> ModelVerificationSnapshot:
    return ModelVerificationSnapshot(
        model_id=model_id,
        tested_model_revision=7,
        tested_provider_revision=4,
        tested_credential_revision=3,
        status="succeeded",
        latency_ms=12,
        error_code=None,
        tested_at=datetime.now(UTC),
    )


class Models:
    def __init__(
        self,
        value: ModelConfig,
        latest: ModelVerificationSnapshot | None,
        references: tuple[ModelReference, ...] = (),
    ) -> None:
        self.value = value
        self.latest = latest
        self.reference_values = references
        self.saved = 0

    def get(
        self, session: Session, model_id: UUID, *, for_update: bool = False
    ) -> ModelConfig | None:
        return self.value if model_id == self.value.id else None

    def latest_verification(
        self,
        session: Session,
        model_id: UUID,
    ) -> ModelVerificationSnapshot | None:
        return self.latest

    def references(self, session: Session, model_id: UUID) -> tuple[ModelReference, ...]:
        return self.reference_values

    def save(self, session: Session, value: ModelConfig) -> None:
        self.value = value
        self.saved += 1


class Providers:
    def __init__(self, value: ModelProvider) -> None:
        self.value = value

    def get(
        self,
        session: Session,
        provider_id: UUID,
        *,
        for_update: bool = False,
    ) -> ModelProvider | None:
        return self.value if provider_id == self.value.id else None


def session() -> Session:
    return cast(Session, object())


def test_selector_returns_only_current_enabled_passed_expected_type() -> None:
    provider_value = provider()
    model_value = model(provider_value.id)
    models = Models(model_value, verification(model_value.id))
    selector = ModelSelectionService(models, Providers(provider_value))

    selected = selector.require_selectable(session(), model_value.id, ModelType.LLM)

    assert selected.model == model_value
    assert selected.provider == provider_value
    assert selected.verification == models.latest


@pytest.mark.parametrize(
    ("model_change", "provider_change", "verification_change", "expected_type", "code"),
    [
        ({"enabled": False}, {}, {}, ModelType.LLM, "MODEL_VERIFICATION_REQUIRED"),
        (
            {"verification_status": VerificationStatus.FAILED},
            {},
            {},
            ModelType.LLM,
            "MODEL_VERIFICATION_REQUIRED",
        ),
        ({"revision": 8}, {}, {}, ModelType.LLM, "MODEL_VERIFICATION_REQUIRED"),
        ({}, {"revision": 5}, {}, ModelType.LLM, "MODEL_VERIFICATION_REQUIRED"),
        ({}, {"credential_revision": 4}, {}, ModelType.LLM, "MODEL_VERIFICATION_REQUIRED"),
        ({}, {"enabled": False}, {}, ModelType.LLM, "MODEL_VERIFICATION_REQUIRED"),
        ({}, {}, {"status": "failed"}, ModelType.LLM, "MODEL_VERIFICATION_REQUIRED"),
        ({}, {}, {}, ModelType.EMBEDDING, "MODEL_TYPE_MISMATCH"),
    ],
)
def test_selector_rejects_every_nonselectable_state(
    model_change: dict[str, object],
    provider_change: dict[str, object],
    verification_change: dict[str, object],
    expected_type: ModelType,
    code: str,
) -> None:
    provider_value = replace(provider(), **provider_change)
    model_value = replace(model(provider_value.id), **model_change)
    latest = replace(verification(model_value.id), **verification_change)
    selector = ModelSelectionService(Models(model_value, latest), Providers(provider_value))

    with pytest.raises(ModelNotSelectableError) as captured:
        selector.require_selectable(session(), model_value.id, expected_type)

    assert captured.value.code == code


def test_identity_update_disable_and_delete_reject_real_references() -> None:
    provider_value = provider()
    model_value = model(provider_value.id)
    reference = ModelReference(
        resource_type="knowledge_base",
        resource_id=uuid4(),
        display_name="Support Knowledge Base",
        state="active",
    )
    models = Models(model_value, verification(model_value.id), (reference,))
    service = ModelConfigService(models, Providers(provider_value), capabilities=None)

    with pytest.raises(ModelInUseError) as update_error:
        service.update(
            session(),
            model_value.id,
            expected_revision=7,
            model_name="changed-model",
            display_name=None,
            model_type=None,
            context_window=None,
            max_output_tokens=None,
            embedding_dimension=None,
            capability_version=None,
            default_params=None,
            config_schema=None,
        )
    with pytest.raises(ModelInUseError):
        service.disable(session(), model_value.id, expected_revision=7)
    with pytest.raises(ModelInUseError):
        service.delete(session(), model_value.id, expected_revision=7)

    assert update_error.value.references == (reference,)
