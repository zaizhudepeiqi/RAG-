from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.core.logging import get_logger
from app.core.security import (
    AdminTokenClaims,
    InvalidAdminTokenError,
    decode_admin_token,
    generate_csrf_token,
    hash_password,
    issue_admin_token,
    validate_admin_password,
    verify_password,
)
from app.infrastructure.database.session import transaction
from app.modules.auth.domain import Administrator
from app.modules.auth.ports import AuditRepository, LoginRateLimiter
from app.modules.auth.repository import AdministratorRepository


class InvalidCredentialsError(Exception):
    pass


class AuthenticationRequiredError(Exception):
    pass


class LoginRateLimitedError(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("login rate limited")
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class AuthSession:
    administrator: Administrator
    access_token: str
    csrf_token: str
    expires_at: datetime


class AuthService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        administrators: AdministratorRepository,
        audits: AuditRepository,
        rate_limiter: LoginRateLimiter,
        initial_username: str,
        initial_secret: str,
        signing_key: bytes,
        access_token_expire_minutes: int,
    ) -> None:
        self._session_factory = session_factory
        self._administrators = administrators
        self._audits = audits
        self._rate_limiter = rate_limiter
        self._initial_username = initial_username
        self._initial_secret = initial_secret
        self._signing_key = signing_key
        self._access_token_expire_minutes = access_token_expire_minutes
        self._dummy_hash = hash_password("Timing-Equalization-Candidate-01!")

    def bootstrap_administrator(self) -> bool:
        validate_admin_password(
            username=self._initial_username,
            password=self._initial_secret,
        )
        with transaction(self._session_factory) as session:
            if self._administrators.count(session) > 0:
                get_logger().info("admin_bootstrap_exists")
                return False
            now = datetime.now(UTC)
            administrator = Administrator(
                id=uuid4(),
                username=self._initial_username,
                password_hash=hash_password(self._initial_secret),
                first_login_required=True,
                auth_version=1,
                revision=1,
                last_login_at=None,
                created_at=now,
                updated_at=now,
            )
            self._administrators.add(session, administrator)
        get_logger().info("admin_bootstrap_created")
        return True

    def login(
        self,
        *,
        username: str,
        candidate: str,
        source_ip: str,
        user_agent: str | None,
        trace_id: UUID | None,
        now: datetime,
    ) -> AuthSession:
        existing_limit = self._rate_limiter.check(username, source_ip, now)
        if existing_limit.limited:
            self._record_login_failure(
                administrator_id=None,
                source_ip=source_ip,
                user_agent=user_agent,
                trace_id=trace_id,
                now=now,
                error_code="AUTH_RATE_LIMITED",
            )
            raise LoginRateLimitedError(existing_limit.retry_after_seconds)

        with transaction(self._session_factory) as session:
            administrator = self._administrators.find_by_username(session, username)
            password_hash = (
                administrator.password_hash if administrator is not None else self._dummy_hash
            )
            valid = verify_password(password_hash, candidate)
            if valid and administrator is not None:
                administrator.record_login(now)
                self._administrators.save(session, administrator)
                self._audits.record(
                    session,
                    occurred_at=now,
                    actor_id=administrator.id,
                    event_code="auth.login_succeeded",
                    result_status="succeeded",
                    trace_id=trace_id,
                    source_ip=source_ip,
                    user_agent=user_agent,
                )

        if not valid or administrator is None:
            decision = self._rate_limiter.record_failure(username, source_ip, now)
            error_code = "AUTH_RATE_LIMITED" if decision.limited else "AUTH_INVALID_CREDENTIALS"
            self._record_login_failure(
                administrator_id=administrator.id if administrator is not None else None,
                source_ip=source_ip,
                user_agent=user_agent,
                trace_id=trace_id,
                now=now,
                error_code=error_code,
            )
            if decision.limited:
                raise LoginRateLimitedError(decision.retry_after_seconds)
            raise InvalidCredentialsError

        self._rate_limiter.clear(username, source_ip)
        return self._issue_session(administrator, now)

    def authenticate(self, access_token: str, now: datetime) -> Administrator:
        try:
            claims = decode_admin_token(access_token, self._signing_key, now)
        except InvalidAdminTokenError as error:
            raise AuthenticationRequiredError from error

        with transaction(self._session_factory) as session:
            administrator = self._administrators.get_by_id(session, claims.administrator_id)
        if administrator is None or administrator.auth_version != claims.auth_version:
            raise AuthenticationRequiredError
        return administrator

    def logout(
        self,
        administrator_id: UUID,
        *,
        source_ip: str,
        user_agent: str | None,
        trace_id: UUID | None,
        now: datetime,
    ) -> None:
        with transaction(self._session_factory) as session:
            administrator = self._required_administrator(session, administrator_id)
            administrator.invalidate_sessions(now)
            self._administrators.save(session, administrator)
            self._audits.record(
                session,
                occurred_at=now,
                actor_id=administrator.id,
                event_code="auth.logout",
                result_status="succeeded",
                trace_id=trace_id,
                source_ip=source_ip,
                user_agent=user_agent,
            )

    def change_password(
        self,
        administrator_id: UUID,
        *,
        old_secret: str,
        new_secret: str,
        source_ip: str,
        user_agent: str | None,
        trace_id: UUID | None,
        now: datetime,
    ) -> AuthSession:
        with transaction(self._session_factory) as session:
            administrator = self._required_administrator(session, administrator_id)
            if not verify_password(administrator.password_hash, old_secret):
                self._audits.record(
                    session,
                    occurred_at=now,
                    actor_id=administrator.id,
                    event_code="auth.password_change_failed",
                    result_status="failed",
                    trace_id=trace_id,
                    source_ip=source_ip,
                    user_agent=user_agent,
                    error_code="AUTH_INVALID_CREDENTIALS",
                )
                invalid_old_secret = True
            else:
                invalid_old_secret = False
                validate_admin_password(username=administrator.username, password=new_secret)
                administrator.change_password(hash_password(new_secret), now)
                self._administrators.save(session, administrator)
                self._audits.record(
                    session,
                    occurred_at=now,
                    actor_id=administrator.id,
                    event_code="auth.password_changed",
                    result_status="succeeded",
                    trace_id=trace_id,
                    source_ip=source_ip,
                    user_agent=user_agent,
                )

        if invalid_old_secret:
            raise InvalidCredentialsError
        return self._issue_session(administrator, now)

    def _issue_session(self, administrator: Administrator, now: datetime) -> AuthSession:
        expires_at = now + timedelta(minutes=self._access_token_expire_minutes)
        access_token = issue_admin_token(
            AdminTokenClaims(
                administrator_id=administrator.id,
                auth_version=administrator.auth_version,
                jti=uuid4(),
                issued_at=now,
                expires_at=expires_at,
            ),
            self._signing_key,
        )
        return AuthSession(
            administrator=administrator,
            access_token=access_token,
            csrf_token=generate_csrf_token(),
            expires_at=expires_at,
        )

    def _record_login_failure(
        self,
        *,
        administrator_id: UUID | None,
        source_ip: str,
        user_agent: str | None,
        trace_id: UUID | None,
        now: datetime,
        error_code: str,
    ) -> None:
        with transaction(self._session_factory) as session:
            self._audits.record(
                session,
                occurred_at=now,
                actor_id=administrator_id,
                event_code="auth.login_failed",
                result_status="denied",
                trace_id=trace_id,
                source_ip=source_ip,
                user_agent=user_agent,
                error_code=error_code,
            )

    def _required_administrator(
        self,
        session: Session,
        administrator_id: UUID,
    ) -> Administrator:
        administrator = self._administrators.get_by_id(session, administrator_id)
        if administrator is None:
            raise AuthenticationRequiredError
        return administrator
