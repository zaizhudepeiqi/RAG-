from datetime import UTC, datetime
from typing import Annotated, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.infrastructure.database.session import transaction
from app.modules.auth.dependencies import require_admin, require_csrf
from app.modules.auth.domain import Administrator
from app.modules.parsing.settings_schemas import (
    MinerUSettingsView,
    UpdateMinerUSettingsRequest,
    mineru_settings_view,
    parse_config_domain,
)
from app.modules.parsing.settings_service import (
    MinerUCloudConsentRequiredError,
    MinerUSettingsRevisionConflictError,
    MinerUSettingsService,
)


class MinerUSettingsDependencies(Protocol):
    session_factory: sessionmaker[Session]
    mineru_settings_service: MinerUSettingsService


router = APIRouter(
    prefix="/api/v1/settings/mineru",
    tags=["MinerU 设置"],
    dependencies=[Depends(require_admin)],
)


def get_dependencies(request: Request) -> MinerUSettingsDependencies:
    return cast(MinerUSettingsDependencies, request.app.state.dependencies)


@router.get("", response_model=MinerUSettingsView, operation_id="mineruSettingsGet")
def get_mineru_settings(
    dependencies: Annotated[MinerUSettingsDependencies, Depends(get_dependencies)],
) -> MinerUSettingsView:
    with transaction(dependencies.session_factory) as session:
        settings = dependencies.mineru_settings_service.get(session, now=datetime.now(UTC))
    return mineru_settings_view(settings)


@router.patch(
    "",
    response_model=MinerUSettingsView,
    operation_id="mineruSettingsUpdate",
    dependencies=[Depends(require_csrf)],
)
def update_mineru_settings(
    payload: UpdateMinerUSettingsRequest,
    request: Request,
    administrator: Annotated[Administrator, Depends(require_admin)],
    dependencies: Annotated[MinerUSettingsDependencies, Depends(get_dependencies)],
) -> MinerUSettingsView:
    consent = payload.cloud_processing_consent
    replacement_credential = payload.token.get_secret_value() if payload.token is not None else None
    try:
        with transaction(dependencies.session_factory) as session:
            settings = dependencies.mineru_settings_service.update(
                session,
                expected_revision=payload.expected_revision,
                base_url=str(payload.base_url).rstrip("/"),
                replacement_credential=replacement_credential,
                default_parse_config=parse_config_domain(payload.default_parse_config),
                poll_timeout_seconds=payload.poll_timeout_seconds,
                consent_terms_version=consent.terms_version if consent is not None else None,
                administrator_id=administrator.id,
                now=datetime.now(UTC),
                trace_id=_trace_id(request),
                source_ip=request.client.host if request.client is not None else None,
                user_agent=request.headers.get("User-Agent"),
            )
    except MinerUCloudConsentRequiredError as error:
        raise AppError(
            code="MINERU_CLOUD_CONSENT_REQUIRED",
            message="首次配置 MinerU Token 必须确认云处理条款",
            status_code=422,
        ) from error
    except MinerUSettingsRevisionConflictError as error:
        raise AppError(
            code="REVISION_CONFLICT",
            message="MinerU 设置已被其他请求修改",
            status_code=409,
        ) from error
    return mineru_settings_view(settings)


def _trace_id(request: Request) -> UUID | None:
    trace_id = getattr(request.state, "trace_id", None)
    return trace_id if isinstance(trace_id, UUID) else None
