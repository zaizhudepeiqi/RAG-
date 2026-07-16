from typing import Annotated, Protocol, cast

from fastapi import APIRouter, Depends, Query, Request

from app.core.errors import AppError
from app.modules.auth.dependencies import require_admin
from app.modules.capabilities.errors import CapabilityNotFoundError
from app.modules.capabilities.schemas import CapabilityOptionResponse, capability_response
from app.modules.capabilities.service import CapabilityService


class CapabilityDependencies(Protocol):
    capability_service: CapabilityService


router = APIRouter(
    prefix="/api/v1/capabilities",
    tags=["能力目录"],
    dependencies=[Depends(require_admin)],
)


def get_capability_dependencies(request: Request) -> CapabilityDependencies:
    return cast(CapabilityDependencies, request.app.state.dependencies)


@router.get("", response_model=list[CapabilityOptionResponse], operation_id="capabilitiesList")
def list_capabilities(
    dependencies: Annotated[CapabilityDependencies, Depends(get_capability_dependencies)],
    category: str | None = None,
    include_disabled: Annotated[bool, Query(alias="includeDisabled")] = False,
) -> list[CapabilityOptionResponse]:
    options = dependencies.capability_service.list(
        category=category,
        include_disabled=include_disabled,
    )
    return [capability_response(option) for option in options]


@router.get(
    "/{code}/versions/{version}",
    response_model=CapabilityOptionResponse,
    operation_id="capabilitiesGetVersion",
)
def get_capability(
    code: str,
    version: str,
    dependencies: Annotated[CapabilityDependencies, Depends(get_capability_dependencies)],
) -> CapabilityOptionResponse:
    try:
        option = dependencies.capability_service.get(code, version)
    except CapabilityNotFoundError as error:
        raise AppError(
            code="CAPABILITY_NOT_FOUND",
            message="能力或版本不存在",
            status_code=404,
        ) from error
    return capability_response(option)
