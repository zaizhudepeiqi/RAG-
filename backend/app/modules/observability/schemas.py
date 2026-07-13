from datetime import datetime
from typing import Literal
from uuid import UUID

from app.core.schemas import ApiModel
from app.modules.observability.ports import DependencyCode, DependencyState


class HealthResponse(ApiModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    timestamp: datetime
    trace_id: UUID


class DependencyHealthItem(ApiModel):
    code: DependencyCode
    status: DependencyState
    message: str


class DependencyHealthResponse(HealthResponse):
    dependencies: list[DependencyHealthItem]
