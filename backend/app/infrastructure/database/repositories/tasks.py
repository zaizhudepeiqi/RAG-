import re
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Select, asc, desc, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from app.infrastructure.database.base import utc_now
from app.infrastructure.database.models.tasks import (
    AdminApiIdempotencyRecordModel,
    OperationModel,
    TaskOutboxModel,
)
from app.infrastructure.database.session import transaction
from app.modules.tasks.domain import (
    AdminIdempotencyRecord,
    Operation,
    OperationEvent,
    OperationStatus,
    OutboxEvent,
    transition_operation,
)
from app.modules.tasks.errors import InvalidStateTransitionError
from app.modules.tasks.ports import ClaimedOutboxEvent, ClaimKind, OperationClaim
from app.modules.tasks.repository import OperationListQuery, Page


class SqlAlchemyOperationRepository:
    def add(self, session: Session, operation: Operation) -> None:
        session.add(self._to_model(operation))

    def get(
        self,
        session: Session,
        operation_id: UUID,
        *,
        for_update: bool = False,
    ) -> Operation | None:
        statement = select(OperationModel).where(OperationModel.id == operation_id)
        if for_update:
            statement = statement.with_for_update()
        model = session.scalar(statement)
        return self._to_domain(model) if model is not None else None

    def find_by_business_key(self, session: Session, key: str) -> Operation | None:
        model = session.scalar(
            select(OperationModel).where(OperationModel.business_idempotency_key == key)
        )
        return self._to_domain(model) if model is not None else None

    def list(self, session: Session, query: OperationListQuery) -> Page[Operation]:
        conditions: list[ColumnElement[bool]] = []
        if query.status:
            conditions.append(OperationModel.status.in_(query.status))
        if query.task_type is not None:
            conditions.append(OperationModel.task_type == query.task_type)
        if query.target_type is not None:
            conditions.append(OperationModel.target_type == query.target_type)
        if query.target_id is not None:
            conditions.append(OperationModel.target_id == query.target_id)
        ordering = {
            "queued_at": asc(OperationModel.queued_at),
            "-queued_at": desc(OperationModel.queued_at),
            "created_at": asc(OperationModel.created_at),
            "-created_at": desc(OperationModel.created_at),
        }
        if query.sort not in ordering:
            raise ValueError("unsupported operation sort")
        statement: Select[tuple[OperationModel]] = (
            select(OperationModel)
            .where(*conditions)
            .order_by(ordering[query.sort], OperationModel.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
        models = session.scalars(statement).all()
        total = (
            session.scalar(select(func.count()).select_from(OperationModel).where(*conditions)) or 0
        )
        return Page(
            items=[self._to_domain(model) for model in models],
            total=total,
            page=query.page,
            page_size=query.page_size,
        )

    def save(self, session: Session, operation: Operation) -> None:
        previous_status = {
            OperationStatus.RUNNING: OperationStatus.QUEUED,
            OperationStatus.CANCELLED: OperationStatus.QUEUED,
            OperationStatus.SUCCEEDED: OperationStatus.RUNNING,
            OperationStatus.PARTIAL_SUCCEEDED: OperationStatus.RUNNING,
            OperationStatus.FAILED: OperationStatus.RUNNING,
        }.get(operation.status)
        values = self._values(operation)
        statement = update(OperationModel).where(OperationModel.id == operation.id)
        if previous_status is not None:
            statement = statement.where(OperationModel.status == previous_status.value)
        result = cast(
            CursorResult[Any],
            session.execute(
                statement.values(**values).execution_options(synchronize_session=False)
            ),
        )
        if result.rowcount != 1:
            raise InvalidStateTransitionError(
                "INVALID_STATE_TRANSITION",
                {"current": "changed_concurrently", "event": "save", "allowedEvents": []},
            )

    @staticmethod
    def _values(operation: Operation) -> dict[str, object]:
        return {
            "status": operation.status.value,
            "stage_code": operation.stage_code,
            "stage_label": operation.stage_label,
            "progress_current": operation.progress_current,
            "progress_total": operation.progress_total,
            "progress_unit": operation.progress_unit,
            "attempt": operation.attempt,
            "celery_task_id": operation.celery_task_id,
            "heartbeat_at": operation.heartbeat_at,
            "started_at": operation.started_at,
            "finished_at": operation.finished_at,
            "error_code": operation.error_code,
            "error_message": _sanitize_error(operation.error_message),
            "retryable": operation.retryable,
            "result_summary": operation.result_summary,
            "warning_count": operation.warning_count,
        }

    @classmethod
    def _to_model(cls, operation: Operation) -> OperationModel:
        return OperationModel(
            id=operation.id,
            task_type=operation.task_type,
            target_type=operation.target_type,
            target_id=operation.target_id,
            target_revision=operation.target_revision,
            business_idempotency_key=operation.business_idempotency_key,
            retry_of_operation_id=operation.retry_of_operation_id,
            queued_at=operation.queued_at,
            max_attempts=operation.max_attempts,
            created_at=operation.created_at,
            expires_at=operation.expires_at,
            **cls._values(operation),
        )

    @staticmethod
    def _to_domain(model: OperationModel) -> Operation:
        return Operation(
            id=model.id,
            task_type=model.task_type,
            target_type=model.target_type,
            target_id=model.target_id,
            target_revision=model.target_revision,
            status=OperationStatus(model.status),
            stage_code=model.stage_code,
            stage_label=model.stage_label,
            progress_current=model.progress_current,
            progress_total=model.progress_total,
            progress_unit=model.progress_unit,
            attempt=model.attempt,
            max_attempts=model.max_attempts,
            celery_task_id=model.celery_task_id,
            business_idempotency_key=model.business_idempotency_key.strip(),
            retry_of_operation_id=model.retry_of_operation_id,
            heartbeat_at=model.heartbeat_at,
            queued_at=model.queued_at,
            started_at=model.started_at,
            finished_at=model.finished_at,
            error_code=model.error_code,
            error_message=model.error_message,
            retryable=model.retryable,
            result_summary=model.result_summary,
            warning_count=model.warning_count,
            created_at=model.created_at,
            expires_at=model.expires_at,
        )


class SqlAlchemyOutboxRepository:
    def add(self, session: Session, event: OutboxEvent) -> None:
        session.add(
            TaskOutboxModel(
                id=event.id,
                operation_id=event.operation_id,
                event_type=event.event_type,
                schema_version=event.schema_version,
                payload=event.payload,
                created_at=event.created_at,
                next_attempt_at=event.created_at,
            )
        )


class SqlAlchemyAdminIdempotencyRepository:
    def find(
        self,
        session: Session,
        administrator_id: UUID,
        endpoint_code: str,
        key_hash: str,
    ) -> AdminIdempotencyRecord | None:
        model = session.scalar(
            select(AdminApiIdempotencyRecordModel).where(
                AdminApiIdempotencyRecordModel.administrator_id == administrator_id,
                AdminApiIdempotencyRecordModel.endpoint_code == endpoint_code,
                AdminApiIdempotencyRecordModel.idempotency_key_hash == key_hash,
            )
        )
        if model is None:
            return None
        return AdminIdempotencyRecord(
            id=model.id,
            administrator_id=model.administrator_id,
            endpoint_code=model.endpoint_code,
            idempotency_key_hash=model.idempotency_key_hash.strip(),
            request_hash=model.request_hash.strip(),
            operation_id=model.operation_id,
            response_status=model.response_status,
            response_body=model.response_body,
            expires_at=model.expires_at,
            created_at=model.created_at,
        )

    def add(self, session: Session, record: AdminIdempotencyRecord) -> None:
        session.add(
            AdminApiIdempotencyRecordModel(
                id=record.id,
                administrator_id=record.administrator_id,
                endpoint_code=record.endpoint_code,
                idempotency_key_hash=record.idempotency_key_hash,
                request_hash=record.request_hash,
                operation_id=record.operation_id,
                response_status=record.response_status,
                response_body=record.response_body,
                expires_at=record.expires_at,
                created_at=record.created_at,
            )
        )


def _sanitize_error(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"[\r\n]+", " ", value).strip()[:1000]


class SqlAlchemyOutboxDispatchStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def claim_batch(self, now: datetime, limit: int) -> list[ClaimedOutboxEvent]:
        with transaction(self._session_factory) as session:
            models = session.scalars(
                select(TaskOutboxModel)
                .where(
                    TaskOutboxModel.status.in_(("pending", "failed")),
                    TaskOutboxModel.next_attempt_at <= now,
                )
                .order_by(TaskOutboxModel.created_at)
                .with_for_update(skip_locked=True)
                .limit(limit)
            ).all()
            claimed = []
            for model in models:
                model.status = "publishing"
                model.publish_attempts += 1
                claimed.append(
                    ClaimedOutboxEvent(
                        id=model.id,
                        operation_id=model.operation_id,
                        event_type=model.event_type,
                        schema_version=model.schema_version,
                        publish_attempts=model.publish_attempts,
                    )
                )
            return claimed

    def mark_published(self, event_id: UUID, now: datetime) -> None:
        with transaction(self._session_factory) as session:
            model = session.get(TaskOutboxModel, event_id)
            if model is not None:
                model.status = "published"
                model.published_at = now
                model.last_error = None

    def mark_retry(
        self,
        event_id: UUID,
        delay_seconds: int,
        error: str,
        now: datetime,
    ) -> None:
        with transaction(self._session_factory) as session:
            model = session.get(TaskOutboxModel, event_id)
            if model is not None:
                model.status = "pending"
                model.next_attempt_at = now + timedelta(seconds=delay_seconds)
                model.last_error = error[:255]

    def mark_schema_failed(self, event: ClaimedOutboxEvent, now: datetime) -> None:
        with transaction(self._session_factory) as session:
            outbox = session.get(TaskOutboxModel, event.id)
            operation = session.get(OperationModel, event.operation_id)
            if outbox is not None:
                outbox.status = "failed"
                outbox.next_attempt_at = datetime.max.replace(tzinfo=UTC)
                outbox.last_error = "TASK_SCHEMA_UNSUPPORTED"
            if operation is not None and operation.status == "queued":
                operation.status = "failed"
                operation.error_code = "TASK_SCHEMA_UNSUPPORTED"
                operation.retryable = False
                operation.finished_at = now

    def reconcile(self, now: datetime) -> int:
        cutoff = now - timedelta(minutes=1)
        with transaction(self._session_factory) as session:
            operation_ids = select(OperationModel.id).where(
                OperationModel.status == "queued",
                OperationModel.queued_at <= cutoff,
            )
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(TaskOutboxModel)
                    .where(
                        TaskOutboxModel.operation_id.in_(operation_ids),
                        TaskOutboxModel.status != "published",
                    )
                    .values(status="pending", next_attempt_at=now)
                    .execution_options(synchronize_session=False)
                ),
            )
            return result.rowcount


class SqlAlchemyOperationExecutionStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._repository = SqlAlchemyOperationRepository()

    def claim(self, operation_id: UUID, expected_task_type: str) -> OperationClaim:
        with transaction(self._session_factory) as session:
            operation = self._repository.get(session, operation_id, for_update=True)
            if operation is None or operation.task_type != expected_task_type:
                return OperationClaim(ClaimKind.TERMINAL, operation_id)
            if operation.status is OperationStatus.RUNNING:
                return OperationClaim(ClaimKind.ALREADY_RUNNING, operation_id)
            if operation.status is not OperationStatus.QUEUED:
                return OperationClaim(ClaimKind.TERMINAL, operation_id)
            claimed = transition_operation(operation, OperationEvent.WORKER_CLAIM, utc_now())
            self._repository.save(session, claimed)
            return OperationClaim(ClaimKind.CLAIMED, operation_id)

    def complete(self, operation_id: UUID, result: dict[str, object]) -> None:
        with transaction(self._session_factory) as session:
            operation = self._repository.get(session, operation_id, for_update=True)
            if operation is None or operation.status is not OperationStatus.RUNNING:
                return
            operation.result_summary = result
            completed = transition_operation(operation, OperationEvent.COMPLETE, utc_now())
            self._repository.save(session, completed)

    def fail(self, operation_id: UUID, code: str, *, retryable: bool) -> None:
        with transaction(self._session_factory) as session:
            operation = self._repository.get(session, operation_id, for_update=True)
            if operation is None or operation.status is not OperationStatus.RUNNING:
                return
            operation.error_code = code
            operation.retryable = retryable
            failed = transition_operation(operation, OperationEvent.FAIL, utc_now())
            self._repository.save(session, failed)
