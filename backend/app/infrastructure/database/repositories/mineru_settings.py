import ipaddress
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.infrastructure.database.models.auth import AuditLogModel
from app.infrastructure.database.models.settings import MinerUSettingsModel
from app.modules.parsing.settings_domain import MinerUSettings, ParseConfig


class SqlAlchemyMinerUSettingsRepository:
    def get_or_create(
        self,
        session: Session,
        default: MinerUSettings,
    ) -> MinerUSettings:
        session.execute(
            insert(MinerUSettingsModel)
            .values(**self._values(default))
            .on_conflict_do_nothing(index_elements=[MinerUSettingsModel.id])
        )
        model = session.get(MinerUSettingsModel, default.id)
        if model is None:
            raise RuntimeError("MinerU settings singleton was not created")
        return self._to_domain(model)

    def get_for_update(
        self,
        session: Session,
        settings_id: UUID,
    ) -> MinerUSettings | None:
        model = session.scalar(
            select(MinerUSettingsModel)
            .where(MinerUSettingsModel.id == settings_id)
            .with_for_update()
        )
        return self._to_domain(model) if model is not None else None

    def save(self, session: Session, settings: MinerUSettings) -> None:
        model = session.get(MinerUSettingsModel, settings.id)
        if model is None:
            raise RuntimeError("MinerU settings singleton does not exist")
        for field, value in self._values(settings).items():
            setattr(model, field, value)

    @staticmethod
    def _values(settings: MinerUSettings) -> dict[str, object]:
        config = settings.default_parse_config
        return {
            "id": settings.id,
            "base_url": settings.base_url,
            "token_ciphertext": settings.token_ciphertext,
            "token_nonce": settings.token_nonce,
            "token_key_version": settings.token_key_version,
            "token_prefix": settings.token_prefix,
            "token_revision": settings.token_revision,
            "default_parse_config": {
                "parserCode": config.parser_code,
                "modelVersion": config.model_version,
                "language": config.language,
                "ocrEnabled": config.ocr_enabled,
                "tableEnabled": config.table_enabled,
                "formulaEnabled": config.formula_enabled,
                "pageRanges": config.page_ranges,
                "extraFormats": list(config.extra_formats),
                "forceProviderRefresh": config.force_provider_refresh,
            },
            "poll_timeout_seconds": settings.poll_timeout_seconds,
            "cloud_processing_confirmed_at": settings.cloud_processing_confirmed_at,
            "cloud_processing_confirmed_by": settings.cloud_processing_confirmed_by,
            "cloud_processing_terms_version": settings.cloud_processing_terms_version,
            "revision": settings.revision,
            "created_at": settings.created_at,
            "updated_at": settings.updated_at,
        }

    @staticmethod
    def _to_domain(model: MinerUSettingsModel) -> MinerUSettings:
        config = model.default_parse_config
        raw_extra_formats = config["extraFormats"]
        if not isinstance(raw_extra_formats, list):
            raise ValueError("stored MinerU extraFormats must be an array")
        return MinerUSettings(
            id=model.id,
            base_url=model.base_url,
            token_ciphertext=model.token_ciphertext,
            token_nonce=model.token_nonce,
            token_key_version=model.token_key_version,
            token_prefix=model.token_prefix,
            token_revision=model.token_revision,
            default_parse_config=ParseConfig(
                parser_code=str(config["parserCode"]),
                model_version=str(config["modelVersion"]),
                language=str(config["language"]),
                ocr_enabled=bool(config["ocrEnabled"]),
                table_enabled=bool(config["tableEnabled"]),
                formula_enabled=bool(config["formulaEnabled"]),
                page_ranges=(
                    str(config["pageRanges"]) if config.get("pageRanges") is not None else None
                ),
                extra_formats=tuple(str(item) for item in raw_extra_formats),
                force_provider_refresh=bool(config["forceProviderRefresh"]),
            ),
            poll_timeout_seconds=model.poll_timeout_seconds,
            cloud_processing_confirmed_at=model.cloud_processing_confirmed_at,
            cloud_processing_confirmed_by=model.cloud_processing_confirmed_by,
            cloud_processing_terms_version=model.cloud_processing_terms_version,
            revision=model.revision,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class SqlAlchemyMinerUSettingsAuditRepository:
    def record(
        self,
        session: Session,
        *,
        occurred_at: datetime,
        actor_id: UUID,
        target_id: UUID,
        change_summary: Mapping[str, object],
        trace_id: UUID | None,
        source_ip: str | None,
        user_agent: str | None,
    ) -> None:
        session.add(
            AuditLogModel(
                id=uuid4(),
                occurred_at=occurred_at,
                actor_type="administrator",
                actor_id=actor_id,
                event_code="mineru.settings.updated",
                target_type="mineru_settings",
                target_id=target_id,
                target_name_snapshot="MinerU",
                trace_id=trace_id,
                source_ip=self._valid_ip(source_ip),
                user_agent=user_agent,
                change_summary=dict(change_summary),
                result_status="succeeded",
            )
        )

    @staticmethod
    def _valid_ip(source_ip: str | None) -> str | None:
        if source_ip is None:
            return None
        try:
            return ipaddress.ip_address(source_ip).compressed
        except ValueError:
            return None
