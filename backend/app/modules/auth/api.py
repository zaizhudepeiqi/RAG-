from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.core.errors import AppError
from app.core.security import PasswordPolicyError
from app.modules.auth.dependencies import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    get_auth_service,
    require_admin,
    require_csrf,
)
from app.modules.auth.domain import Administrator
from app.modules.auth.schemas import (
    AdminProfile,
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    SuccessResponse,
)
from app.modules.auth.service import (
    AuthenticationRequiredError,
    AuthService,
    AuthSession,
    InvalidCredentialsError,
    LoginRateLimitedError,
)

router = APIRouter(prefix="/api/v1/auth", tags=["管理员认证"])


@router.post("/login", response_model=LoginResponse, operation_id="authLogin")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> LoginResponse:
    try:
        auth_session = service.login(
            username=payload.username,
            candidate=payload.password,
            source_ip=_source_ip(request),
            user_agent=request.headers.get("User-Agent"),
            trace_id=_trace_id(request),
            now=datetime.now(UTC),
        )
    except InvalidCredentialsError as error:
        raise AppError(
            code="AUTH_INVALID_CREDENTIALS",
            message="账号或密码错误",
            status_code=401,
        ) from error
    except LoginRateLimitedError as error:
        raise AppError(
            code="AUTH_RATE_LIMITED",
            message="登录失败次数过多, 请稍后重试",
            status_code=429,
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error

    _set_session_cookies(response, request, auth_session)
    return LoginResponse(
        admin=_profile(auth_session.administrator),
        csrf_token=auth_session.csrf_token,
        first_login_required=auth_session.administrator.first_login_required,
    )


@router.post(
    "/logout",
    response_model=SuccessResponse,
    operation_id="authLogout",
    dependencies=[Depends(require_csrf)],
)
def logout(
    request: Request,
    response: Response,
    administrator: Annotated[Administrator, Depends(require_admin)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> SuccessResponse:
    try:
        service.logout(
            administrator.id,
            source_ip=_source_ip(request),
            user_agent=request.headers.get("User-Agent"),
            trace_id=_trace_id(request),
            now=datetime.now(UTC),
        )
    except AuthenticationRequiredError as error:
        raise AppError(code="AUTH_UNAUTHORIZED", message="登录状态无效", status_code=401) from error
    _clear_session_cookies(response, request)
    return SuccessResponse()


@router.get("/me", response_model=AdminProfile, operation_id="authMe")
def me(
    administrator: Annotated[Administrator, Depends(require_admin)],
) -> AdminProfile:
    return _profile(administrator)


@router.post(
    "/change-password",
    response_model=SuccessResponse,
    operation_id="authChangePassword",
    dependencies=[Depends(require_csrf)],
)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    administrator: Annotated[Administrator, Depends(require_admin)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> SuccessResponse:
    try:
        auth_session = service.change_password(
            administrator.id,
            old_secret=payload.old_password,
            new_secret=payload.new_password,
            source_ip=_source_ip(request),
            user_agent=request.headers.get("User-Agent"),
            trace_id=_trace_id(request),
            now=datetime.now(UTC),
        )
    except InvalidCredentialsError as error:
        raise AppError(
            code="AUTH_INVALID_CREDENTIALS",
            message="账号或密码错误",
            status_code=401,
        ) from error
    except PasswordPolicyError as error:
        raise AppError(
            code="AUTH_PASSWORD_POLICY_INVALID",
            message="新密码不符合安全策略",
            status_code=422,
        ) from error
    _set_session_cookies(response, request, auth_session)
    return SuccessResponse()


def _set_session_cookies(response: Response, request: Request, auth_session: AuthSession) -> None:
    settings = request.app.state.settings
    secure = settings.app_env == "production"
    max_age = settings.access_token_expire_minutes * 60
    response.set_cookie(
        ACCESS_COOKIE,
        auth_session.access_token,
        max_age=max_age,
        path="/",
        secure=secure,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        CSRF_COOKIE,
        auth_session.csrf_token,
        max_age=max_age,
        path="/",
        secure=secure,
        httponly=False,
        samesite="lax",
    )


def _clear_session_cookies(response: Response, request: Request) -> None:
    secure = request.app.state.settings.app_env == "production"
    response.delete_cookie(ACCESS_COOKIE, path="/", secure=secure, httponly=True, samesite="lax")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=secure, httponly=False, samesite="lax")


def _profile(administrator: Administrator) -> AdminProfile:
    return AdminProfile(
        id=administrator.id,
        username=administrator.username,
        first_login_required=administrator.first_login_required,
    )


def _source_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _trace_id(request: Request) -> UUID | None:
    trace_id = getattr(request.state, "trace_id", None)
    return trace_id if isinstance(trace_id, UUID) else None


__all__ = ["ACCESS_COOKIE", "CSRF_COOKIE", "router"]
