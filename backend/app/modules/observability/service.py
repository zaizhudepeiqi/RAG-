from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from app.modules.observability.ports import DependencyCode, DependencyProbe, DependencyStatus
from app.modules.observability.schemas import (
    DependencyHealthItem,
    DependencyHealthResponse,
    HealthResponse,
)


class NotConfiguredProbe:
    required_for_readiness = False

    def __init__(self, code: DependencyCode) -> None:
        self.code = code

    def check(self) -> DependencyStatus:
        return DependencyStatus(self.code, "not_configured", "not configured")


class HealthService:
    def __init__(self, *, version: str, probes: list[DependencyProbe]) -> None:
        self._version = version
        self._probes = probes

    def liveness(
        self,
        *,
        trace_id: UUID | None = None,
        now: datetime | None = None,
    ) -> HealthResponse:
        return HealthResponse(
            status="healthy",
            version=self._version,
            timestamp=now or datetime.now(UTC),
            trace_id=trace_id or uuid4(),
        )

    def readiness(
        self,
        *,
        trace_id: UUID | None = None,
        now: datetime | None = None,
    ) -> DependencyHealthResponse:
        return self._aggregate(trace_id=trace_id, now=now, readiness_only=True)

    def dependencies(
        self,
        *,
        trace_id: UUID | None = None,
        now: datetime | None = None,
    ) -> DependencyHealthResponse:
        return self._aggregate(trace_id=trace_id, now=now, readiness_only=False)

    def _aggregate(
        self,
        *,
        trace_id: UUID | None,
        now: datetime | None,
        readiness_only: bool,
    ) -> DependencyHealthResponse:
        selected = (
            [probe for probe in self._probes if probe.required_for_readiness]
            if readiness_only
            else self._probes
        )
        statuses = [(probe, probe.check()) for probe in selected]
        unhealthy = any(
            status.status == "unhealthy" and probe.required_for_readiness
            for probe, status in statuses
        )
        degraded = any(status.status != "healthy" for _, status in statuses)
        overall: Literal["healthy", "degraded", "unhealthy"] = (
            "unhealthy" if unhealthy else "degraded" if degraded else "healthy"
        )
        return DependencyHealthResponse(
            status=overall,
            version=self._version,
            timestamp=now or datetime.now(UTC),
            trace_id=trace_id or uuid4(),
            dependencies=[
                DependencyHealthItem(code=status.code, status=status.status, message=status.message)
                for _, status in statuses
            ],
        )
