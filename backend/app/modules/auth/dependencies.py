from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import Cookie, Depends, Header, Request

from app.core.errors import AppError
from app.core.security import csrf_matches
from app.modules.auth.domain import Administrator
from app.modules.auth.service import AuthenticationRequiredError, AuthService

ACCESS_COOKIE = "rag_admin_access"
CSRF_COOKIE = "rag_csrf"


def get_auth_service(request: Request) -> AuthService:
    return cast(AuthService, request.app.state.dependencies.auth_service)


def get_current_admin(
    service: Annotated[AuthService, Depends(get_auth_service)],
    access_token: Annotated[str | None, Cookie(alias=ACCESS_COOKIE)] = None,
) -> Administrator:
    if access_token is None:
        raise _unauthorized()
    try:
        return service.authenticate(access_token, datetime.now(UTC))
    except AuthenticationRequiredError as error:
        raise _unauthorized() from error


def require_admin(
    request: Request,
    administrator: Annotated[Administrator, Depends(get_current_admin)],
) -> Administrator:
    allowed_during_first_login = {
        "/api/v1/auth/change-password",
        "/api/v1/auth/logout",
    }
    if administrator.first_login_required and request.url.path not in allowed_during_first_login:
        raise AppError(
            code="AUTH_PASSWORD_CHANGE_REQUIRED",
            message="首次登录必须先修改密码",
            status_code=403,
        )
    return administrator


def require_csrf(
    csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE)] = None,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    if not csrf_matches(csrf_cookie, csrf_header):
        raise AppError(code="CSRF_INVALID", message="CSRF 校验失败", status_code=403)


def _unauthorized() -> AppError:
    return AppError(code="AUTH_UNAUTHORIZED", message="登录状态无效", status_code=401)
