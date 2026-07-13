from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import TraceIdMiddleware


def create_app(settings: Settings) -> FastAPI:
    configure_logging()
    openapi_enabled = settings.app_env != "production" or settings.enable_production_openapi
    app = FastAPI(
        title="企业 RAG 知识库 API",
        version=settings.app_version,
        openapi_url="/api/v1/openapi.json" if openapi_enabled else None,
        docs_url="/docs" if openapi_enabled else None,
        redoc_url=None,
    )
    app.state.settings = settings
    register_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Content-Type",
            "Idempotency-Key",
            "X-CSRF-Token",
            "X-Trace-Id",
        ],
        expose_headers=["X-Trace-Id"],
    )
    app.add_middleware(TraceIdMiddleware)
    return app
