from collections.abc import Mapping
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.ids import new_uuid, trace_id_context
from app.core.logging import get_logger
from app.core.middleware import response_headers
from app.core.schemas import ApiModel


class ApiError(ApiModel):
    code: str
    message: str
    trace_id: UUID
    details: dict[str, Any] | None = None


class AppError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        details: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = dict(details) if details is not None else None
        self.headers = dict(headers) if headers is not None else None


def _request_trace_id(request: Request) -> UUID:
    state_trace_id = getattr(request.state, "trace_id", None)
    if isinstance(state_trace_id, UUID):
        return state_trace_id
    return trace_id_context.get() or new_uuid()


def _error_response(
    *,
    trace_id: UUID,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    payload = ApiError(code=code, message=message, trace_id=trace_id, details=details)
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json", exclude_none=True),
        headers=response_headers(str(trace_id)),
    )


async def app_error_handler(request: Request, error: AppError) -> JSONResponse:
    response = _error_response(
        trace_id=_request_trace_id(request),
        status_code=error.status_code,
        code=error.code,
        message=error.message,
        details=error.details,
    )
    if error.headers is not None:
        response.headers.update(error.headers)
    return response


async def validation_error_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    field_errors = [
        {
            "field": ".".join(str(part) for part in item["loc"]),
            "message": item["msg"],
            "type": item["type"],
        }
        for item in error.errors()
    ]
    return _error_response(
        trace_id=_request_trace_id(request),
        status_code=422,
        code="VALIDATION_ERROR",
        message="请求参数校验失败",
        details={"fieldErrors": field_errors},
    )


async def unhandled_error_handler(request: Request, error: Exception) -> JSONResponse:
    trace_id = _request_trace_id(request)
    get_logger().exception(
        "unhandled_request_error",
        trace_id=str(trace_id),
        error_type=type(error).__name__,
    )
    return _error_response(
        trace_id=trace_id,
        status_code=500,
        code="INTERNAL_ERROR",
        message="系统内部错误",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_error_handler)
