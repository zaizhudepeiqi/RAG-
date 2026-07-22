from dataclasses import replace
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.security import encrypt_secret
from app.modules.parsing.settings_domain import (
    CLOUD_PROCESSING_TERMS_VERSION,
    MINERU_SETTINGS_ID,
    MinerUSettings,
    ParseConfig,
    default_mineru_settings,
    mask_token,
    mineru_token_aad,
)
from app.modules.parsing.settings_ports import MinerUSettingsAuditRepository
from app.modules.parsing.settings_repository import MinerUSettingsRepository


class MinerUCloudConsentRequiredError(ValueError):
    pass


class MinerUSettingsRevisionConflictError(ValueError):
    pass


class MinerUSettingsService:
    def __init__(
        self,
        repository: MinerUSettingsRepository,
        audits: MinerUSettingsAuditRepository,
        encryption_key: bytes,
    ) -> None:
        self._repository = repository
        self._audits = audits
        self._encryption_key = encryption_key

    def get(self, session: Session, *, now: datetime) -> MinerUSettings:
        return self._repository.get_or_create(session, default_mineru_settings(now))

    def update(
        self,
        session: Session,
        *,
        expected_revision: int,
        base_url: str,
        replacement_credential: str | None,
        default_parse_config: ParseConfig,
        poll_timeout_seconds: int,
        consent_terms_version: str | None,
        administrator_id: UUID,
        now: datetime,
        trace_id: UUID | None,
        source_ip: str | None,
        user_agent: str | None,
    ) -> MinerUSettings:
        self._repository.get_or_create(session, default_mineru_settings(now))
        current = self._repository.get_for_update(session, MINERU_SETTINGS_ID)
        if current is None:
            raise RuntimeError("MinerU settings singleton was not created")
        if current.revision != expected_revision:
            raise MinerUSettingsRevisionConflictError

        credential_value = (
            replacement_credential.strip() if replacement_credential is not None else ""
        )
        token_changed = bool(credential_value)
        confirmed = current.cloud_processing_confirmed_at is not None
        if token_changed and not confirmed and consent_terms_version is None:
            raise MinerUCloudConsentRequiredError

        confirmed_at = current.cloud_processing_confirmed_at
        confirmed_by = current.cloud_processing_confirmed_by
        terms_version = current.cloud_processing_terms_version
        if consent_terms_version is not None:
            if consent_terms_version != CLOUD_PROCESSING_TERMS_VERSION:
                raise MinerUCloudConsentRequiredError
            confirmed_at = now
            confirmed_by = administrator_id
            terms_version = consent_terms_version

        updated = replace(
            current,
            base_url=base_url,
            default_parse_config=default_parse_config,
            poll_timeout_seconds=poll_timeout_seconds,
            cloud_processing_confirmed_at=confirmed_at,
            cloud_processing_confirmed_by=confirmed_by,
            cloud_processing_terms_version=terms_version,
            revision=current.revision + 1,
            updated_at=now,
        )
        if token_changed:
            encrypted = encrypt_secret(
                credential_value.encode("utf-8"),
                self._encryption_key,
                associated_data=mineru_token_aad(current.id),
                key_version="v1",
            )
            updated.token_ciphertext = encrypted.ciphertext
            updated.token_nonce = encrypted.nonce
            updated.token_key_version = encrypted.key_version
            updated.token_prefix = mask_token(credential_value)
            updated.token_revision = current.token_revision + int(
                current.token_ciphertext is not None
            )

        self._repository.save(session, updated)
        self._audits.record(
            session,
            occurred_at=now,
            actor_id=administrator_id,
            target_id=updated.id,
            change_summary={
                "baseUrl": updated.base_url,
                "tokenChanged": token_changed,
                "tokenRevision": updated.token_revision,
                "pollTimeoutSeconds": updated.poll_timeout_seconds,
                "cloudProcessingTermsVersion": updated.cloud_processing_terms_version,
            },
            trace_id=trace_id,
            source_ip=source_ip,
            user_agent=user_agent,
        )
        return updated
