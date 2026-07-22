import hashlib
import json
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.tasks.domain import AdminIdempotencyRecord
from app.modules.tasks.errors import IdempotencyKeyReusedError
from app.modules.tasks.repository import AdminIdempotencyRepository


class AdminIdempotencyService:
    def __init__(self, repository: AdminIdempotencyRepository) -> None:
        self._repository = repository

    def reserve(
        self,
        session: Session,
        *,
        administrator_id: UUID,
        endpoint_code: str,
        idempotency_key: str,
        request_body: dict[str, object],
        operation_id: UUID | None,
        now: datetime,
    ) -> AdminIdempotencyRecord:
        key_hash, request_hash = self._hashes(idempotency_key, request_body)
        existing = self.find(
            session,
            administrator_id=administrator_id,
            endpoint_code=endpoint_code,
            idempotency_key=idempotency_key,
            request_body=request_body,
        )
        if existing is not None:
            return existing
        record = AdminIdempotencyRecord(
            id=uuid4(),
            administrator_id=administrator_id,
            endpoint_code=endpoint_code,
            idempotency_key_hash=key_hash,
            request_hash=request_hash,
            operation_id=operation_id,
            response_status=None,
            response_body=None,
            expires_at=now + timedelta(hours=24),
            created_at=now,
        )
        try:
            with session.begin_nested():
                self._repository.add(session, record)
                session.flush()
        except IntegrityError:
            concurrent = self._repository.find(
                session,
                administrator_id,
                endpoint_code,
                key_hash,
            )
            if concurrent is None:
                raise
            if concurrent.request_hash != request_hash:
                raise IdempotencyKeyReusedError from None
            return concurrent
        return record

    def find(
        self,
        session: Session,
        *,
        administrator_id: UUID,
        endpoint_code: str,
        idempotency_key: str,
        request_body: dict[str, object],
    ) -> AdminIdempotencyRecord | None:
        key_hash, request_hash = self._hashes(idempotency_key, request_body)
        existing = self._repository.find(session, administrator_id, endpoint_code, key_hash)
        if existing is not None and existing.request_hash != request_hash:
            raise IdempotencyKeyReusedError
        return existing

    @staticmethod
    def _hashes(
        idempotency_key: str,
        request_body: dict[str, object],
    ) -> tuple[str, str]:
        key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        canonical = json.dumps(
            request_body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        request_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return key_hash, request_hash
