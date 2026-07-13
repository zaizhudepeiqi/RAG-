from datetime import UTC, datetime
from uuid import uuid4

from app.modules.observability.ports import DependencyStatus
from app.modules.observability.service import HealthService


class FakeProbe:
    def __init__(self, code: str, status: str, *, required: bool) -> None:
        self.code = code
        self.required_for_readiness = required
        self.status = status
        self.calls = 0

    def check(self) -> DependencyStatus:
        self.calls += 1
        return DependencyStatus(code=self.code, status=self.status, message="test")


def test_liveness_never_calls_dependency_checks() -> None:
    probe = FakeProbe("postgresql", "unhealthy", required=True)
    service = HealthService(version="0.1.0", probes=[probe])

    response = service.liveness(trace_id=uuid4(), now=datetime.now(UTC))

    assert response.status == "healthy"
    assert probe.calls == 0


def test_ready_is_unhealthy_when_database_or_storage_is_unhealthy() -> None:
    service = HealthService(
        version="0.1.0",
        probes=[
            FakeProbe("postgresql", "healthy", required=True),
            FakeProbe("storage", "unhealthy", required=True),
            FakeProbe("redis", "healthy", required=False),
        ],
    )

    response = service.readiness(trace_id=uuid4(), now=datetime.now(UTC))

    assert response.status == "unhealthy"


def test_dependencies_preserve_not_configured_for_mineru_and_models() -> None:
    service = HealthService(
        version="0.1.0",
        probes=[
            FakeProbe("mineru", "not_configured", required=False),
            FakeProbe("models", "not_configured", required=False),
        ],
    )

    response = service.dependencies(trace_id=uuid4(), now=datetime.now(UTC))

    assert response.status == "degraded"
    assert [item.status for item in response.dependencies] == ["not_configured", "not_configured"]


def test_optional_provider_degraded_does_not_fail_liveness() -> None:
    service = HealthService(
        version="0.1.0",
        probes=[FakeProbe("celery", "degraded", required=False)],
    )

    response = service.dependencies(trace_id=uuid4(), now=datetime.now(UTC))

    assert response.status == "degraded"
