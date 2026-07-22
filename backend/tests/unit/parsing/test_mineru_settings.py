from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.modules.parsing.settings_domain import (
    CLOUD_PROCESSING_TERMS_VERSION,
    DEFAULT_PARSE_CONFIG,
    MinerUSettings,
    default_mineru_settings,
)
from app.modules.parsing.settings_service import (
    MinerUCloudConsentRequiredError,
    MinerUSettingsRevisionConflictError,
    MinerUSettingsService,
)


class InMemorySettingsRepository:
    def __init__(self) -> None:
        self.settings: MinerUSettings | None = None

    def get_or_create(self, _session: object, default: MinerUSettings) -> MinerUSettings:
        if self.settings is None:
            self.settings = default
        return self.settings

    def get_for_update(self, _session: object, settings_id: UUID) -> MinerUSettings | None:
        if self.settings is not None and self.settings.id == settings_id:
            return self.settings
        return None

    def save(self, _session: object, settings: MinerUSettings) -> None:
        self.settings = settings


class RecordingAuditRepository:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def record(self, _session: object, **values: object) -> None:
        self.records.append(values)


NOW = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)
KEY = b"m" * 32


def build_service() -> tuple[
    MinerUSettingsService,
    InMemorySettingsRepository,
    RecordingAuditRepository,
]:
    repository = InMemorySettingsRepository()
    audits = RecordingAuditRepository()
    return MinerUSettingsService(repository, audits, KEY), repository, audits


def update_settings(
    service: MinerUSettingsService,
    *,
    expected_revision: int,
    credential: str | None,
    consent_accepted: bool = False,
) -> MinerUSettings:
    return service.update(
        object(),
        expected_revision=expected_revision,
        base_url="https://8.8.8.8/api/v4",
        replacement_credential=credential,
        default_parse_config=DEFAULT_PARSE_CONFIG,
        poll_timeout_seconds=1800,
        consent_terms_version=(CLOUD_PROCESSING_TERMS_VERSION if consent_accepted else None),
        administrator_id=uuid4(),
        now=NOW,
        trace_id=uuid4(),
        source_ip="127.0.0.1",
        user_agent="pytest",
    )


def test_default_settings_use_fixed_singleton_and_locked_parse_config() -> None:
    first = default_mineru_settings(NOW)
    second = default_mineru_settings(NOW)

    assert first.id == second.id
    assert first.base_url == "https://mineru.net"
    assert first.default_parse_config == DEFAULT_PARSE_CONFIG
    assert first.poll_timeout_seconds == 1800
    assert first.token_ciphertext is None
    assert first.revision == 1


def test_first_token_requires_cloud_processing_consent() -> None:
    service, _repository, _audits = build_service()
    service.get(object(), now=NOW)

    with pytest.raises(MinerUCloudConsentRequiredError):
        update_settings(service, expected_revision=1, credential="mineru-secret-token")


def test_empty_token_preserves_encrypted_material_and_token_revision() -> None:
    service, repository, _audits = build_service()
    service.get(object(), now=NOW)
    configured = update_settings(
        service,
        expected_revision=1,
        credential="mineru-secret-token",
        consent_accepted=True,
    )

    unchanged = update_settings(service, expected_revision=2, credential="")

    assert unchanged.token_ciphertext == configured.token_ciphertext
    assert unchanged.token_nonce == configured.token_nonce
    assert unchanged.token_key_version == configured.token_key_version
    assert unchanged.token_revision == 1
    assert repository.settings is unchanged


def test_token_rotation_changes_ciphertext_and_increments_token_revision() -> None:
    service, _repository, audits = build_service()
    service.get(object(), now=NOW)
    configured = update_settings(
        service,
        expected_revision=1,
        credential="mineru-secret-token",
        consent_accepted=True,
    )

    rotated = update_settings(
        service,
        expected_revision=2,
        credential="mineru-rotated-token",
    )

    assert rotated.token_ciphertext != configured.token_ciphertext
    assert rotated.token_nonce != configured.token_nonce
    assert rotated.token_revision == 2
    assert rotated.cloud_processing_terms_version == CLOUD_PROCESSING_TERMS_VERSION
    assert "mineru-secret-token" not in repr(audits.records)
    assert "mineru-rotated-token" not in repr(audits.records)


def test_update_rejects_stale_revision() -> None:
    service, _repository, _audits = build_service()
    service.get(object(), now=NOW)

    with pytest.raises(MinerUSettingsRevisionConflictError):
        update_settings(service, expected_revision=2, credential=None)
