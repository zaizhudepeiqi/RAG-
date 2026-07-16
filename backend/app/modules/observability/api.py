from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Request, Response

from app.modules.observability.schemas import DependencyHealthResponse, HealthResponse

router = APIRouter(prefix="/api/v1/health", tags=["系统健康"])


@router.get("/live", response_model=HealthResponse, operation_id="healthLive")
def live(request: Request) -> HealthResponse:
    return request.app.state.dependencies.health_service.liveness(
        trace_id=_trace_id(request),
        now=datetime.now(UTC),
    )


@router.get("/ready", response_model=DependencyHealthResponse, operation_id="healthReady")
def ready(request: Request, response: Response) -> DependencyHealthResponse:
    result = request.app.state.dependencies.health_service.readiness(
        trace_id=_trace_id(request),
        now=datetime.now(UTC),
    )
    if result.status == "unhealthy":
        response.status_code = 503
    return result


@router.get(
    "/dependencies",
    response_model=DependencyHealthResponse,
    operation_id="healthDependencies",
)
def dependencies(request: Request, response: Response) -> DependencyHealthResponse:
    result = request.app.state.dependencies.health_service.dependencies(
        trace_id=_trace_id(request),
        now=datetime.now(UTC),
    )
    if result.status == "unhealthy":
        response.status_code = 503
    return result


def _trace_id(request: Request) -> UUID:
    value = request.state.trace_id
    if not isinstance(value, UUID):
        raise RuntimeError("trace middleware did not provide a UUID")
    return value
