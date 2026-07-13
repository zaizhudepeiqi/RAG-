from collections.abc import Mapping
from typing import Final

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.ids import parse_or_create_trace_id, trace_id_context

SECURITY_HEADERS: Final[Mapping[str, str]] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
}


def response_headers(trace_id: str) -> dict[str, str]:
    return {"X-Trace-Id": trace_id, **SECURITY_HEADERS}


class TraceIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_headers = Headers(scope=scope)
        trace_id = parse_or_create_trace_id(request_headers.get("X-Trace-Id"))
        scope.setdefault("state", {})["trace_id"] = trace_id
        token = trace_id_context.set(trace_id)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Trace-Id"] = str(trace_id)
                for name, value in SECURITY_HEADERS.items():
                    if name not in headers:
                        headers[name] = value
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            trace_id_context.reset(token)
