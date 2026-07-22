from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from anyio import to_thread
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.bootstrap.dependencies import build_application_dependencies
from app.core.config import Settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import TraceIdMiddleware
from app.modules.auth.api import router as auth_router
from app.modules.capabilities.api import router as capabilities_router
from app.modules.models.api import models_router
from app.modules.models.api import router as model_providers_router
from app.modules.observability.api import router as health_router
from app.modules.parsing.settings_api import router as mineru_settings_router
from app.modules.tasks.api import router as tasks_router


def create_app(settings: Settings) -> FastAPI:
    configure_logging()
    dependencies = build_application_dependencies(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            await to_thread.run_sync(dependencies.assert_database_at_head)
            await to_thread.run_sync(dependencies.auth_service.bootstrap_administrator)
            yield
        finally:
            dependencies.close()

    openapi_enabled = settings.app_env != "production" or settings.enable_production_openapi
    app = FastAPI(
        title="企业 RAG 知识库 API",
        version=settings.app_version,
        openapi_url="/api/v1/openapi.json" if openapi_enabled else None,
        docs_url="/docs" if openapi_enabled else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.dependencies = dependencies
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
    app.include_router(auth_router)
    app.include_router(capabilities_router)
    app.include_router(health_router)
    app.include_router(model_providers_router)
    app.include_router(models_router)
    app.include_router(mineru_settings_router)
    app.include_router(tasks_router)
    return app
