from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from redis import Redis
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.infrastructure.database.repositories.audit import SqlAlchemyAuditRepository
from app.infrastructure.database.repositories.auth import SqlAlchemyAdministratorRepository
from app.infrastructure.database.repositories.generation_builds import (
    SqlAlchemyGenerationBuildStore,
)
from app.infrastructure.database.repositories.generation_items import (
    SqlAlchemyGenerationItemStore,
)
from app.infrastructure.database.repositories.knowledge_bases import (
    SqlAlchemyKnowledgeBaseRepository,
)
from app.infrastructure.database.repositories.mineru_settings import (
    SqlAlchemyMinerUSettingsAuditRepository,
    SqlAlchemyMinerUSettingsRepository,
)
from app.infrastructure.database.repositories.models import (
    SqlAlchemyModelAuditRepository,
    SqlAlchemyModelProviderRepository,
    SqlAlchemyModelRepository,
    SqlAlchemyModelVerificationTaskStore,
    SqlAlchemyProviderTaskStore,
)
from app.infrastructure.database.repositories.parsing import (
    SqlAlchemyDataSourceAuditRepository,
    SqlAlchemyDataSourceRepository,
    SqlAlchemyMinerUTestTaskStore,
    SqlAlchemyParseTaskStore,
    SqlAlchemyParsingCleanupTaskStore,
    SqlAlchemyParsingReferenceQuery,
)
from app.infrastructure.database.repositories.tasks import (
    SqlAlchemyAdminIdempotencyRepository,
    SqlAlchemyOperationExecutionStore,
    SqlAlchemyOperationRepository,
    SqlAlchemyOutboxDispatchStore,
    SqlAlchemyOutboxRepository,
)
from app.infrastructure.database.session import create_engine_from_settings, create_session_factory
from app.infrastructure.health.celery import CeleryHealthProbe
from app.infrastructure.health.chroma import ChromaHealthProbe
from app.infrastructure.health.postgresql import PostgreSQLHealthProbe
from app.infrastructure.health.redis import RedisHealthProbe
from app.infrastructure.health.storage import StorageHealthProbe
from app.infrastructure.model_providers.embedding import ConfiguredDocumentEmbedder
from app.infrastructure.model_providers.registry import (
    ModelProviderAdapterRegistry,
    build_model_provider_adapter_registry,
)
from app.infrastructure.parsers.builtin_text import BuiltinTextParser
from app.infrastructure.parsers.mineru_precision import MinerUPrecisionAdapter
from app.infrastructure.parsers.registry import ParserRegistry
from app.infrastructure.redis.client import create_redis_client
from app.infrastructure.redis.login_rate_limit import RedisLoginRateLimiter
from app.infrastructure.storage.local import LocalStorageAdapter
from app.infrastructure.vector.chroma import ChromaAdapter, ChromaVectorStoreAdapter
from app.modules.auth.service import AuthService
from app.modules.capabilities.registry import build_capability_registry
from app.modules.capabilities.service import CapabilityService
from app.modules.knowledge_bases.generation_items import DefaultGenerationItemExecutor
from app.modules.knowledge_bases.service import (
    KnowledgeBaseService,
    RegistryKnowledgeModelSelector,
)
from app.modules.knowledge_bases.tasks import GenerationBuildHandler
from app.modules.models.service import (
    ModelConfigService,
    ModelProviderService,
    ModelSelectionService,
)
from app.modules.models.tasks import (
    ModelVerificationHandler,
    ProviderDiscoveryHandler,
    ProviderTestHandler,
)
from app.modules.observability.service import HealthService, NotConfiguredProbe
from app.modules.parsing.service import DataSourceService
from app.modules.parsing.settings_service import MinerUSettingsService
from app.modules.parsing.tasks import (
    MinerUConnectionTestHandler,
    ParsingCleanupHandler,
    SourceParseHandler,
)
from app.modules.tasks.idempotency import AdminIdempotencyService
from app.modules.tasks.ports import TaskDispatchDefinition, TaskDispatchRegistry
from app.modules.tasks.service import TaskService

BACKEND_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class ApplicationDependencies:
    engine: Engine
    session_factory: sessionmaker[Session]
    redis_client: Redis
    auth_service: AuthService
    health_service: HealthService
    task_service: TaskService
    admin_idempotency_service: AdminIdempotencyService
    outbox_dispatch_store: SqlAlchemyOutboxDispatchStore
    operation_execution_store: SqlAlchemyOperationExecutionStore
    task_dispatch_registry: TaskDispatchRegistry
    capability_service: CapabilityService
    model_provider_service: ModelProviderService
    model_provider_adapter_registry: ModelProviderAdapterRegistry
    provider_test_handler: ProviderTestHandler
    provider_discovery_handler: ProviderDiscoveryHandler
    model_config_service: ModelConfigService
    model_selection_service: ModelSelectionService
    model_verification_handler: ModelVerificationHandler
    mineru_settings_service: MinerUSettingsService
    data_source_service: DataSourceService
    knowledge_base_service: KnowledgeBaseService
    generation_build_handler: GenerationBuildHandler
    source_storage: LocalStorageAdapter
    source_parse_handler: SourceParseHandler
    mineru_connection_test_handler: MinerUConnectionTestHandler
    parsing_cleanup_handler: ParsingCleanupHandler

    def assert_database_at_head(self) -> None:
        config = Config(BACKEND_ROOT / "alembic.ini")
        expected = ScriptDirectory.from_config(config).get_current_head()
        with self.engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
        if current != expected:
            raise RuntimeError(
                f"database migration mismatch: expected {expected!r}, found {current!r}"
            )

    def close(self) -> None:
        self.redis_client.close()
        self.engine.dispose()


def build_application_dependencies(settings: Settings) -> ApplicationDependencies:
    engine = create_engine_from_settings(settings)
    session_factory = create_session_factory(engine)
    redis_client = create_redis_client(settings.redis_url)
    auth_service = AuthService(
        session_factory=session_factory,
        administrators=SqlAlchemyAdministratorRepository(),
        audits=SqlAlchemyAuditRepository(),
        rate_limiter=RedisLoginRateLimiter(redis_client),
        initial_username=settings.initial_admin_username,
        initial_secret=settings.initial_admin_password.get_secret_value(),
        signing_key=settings.jwt_signing_key_bytes,
        access_token_expire_minutes=settings.access_token_expire_minutes,
    )
    source_storage = LocalStorageAdapter(settings.storage_root)
    health_service = HealthService(
        version=settings.app_version,
        probes=[
            PostgreSQLHealthProbe(engine, BACKEND_ROOT / "alembic.ini"),
            RedisHealthProbe(redis_client),
            ChromaHealthProbe(ChromaAdapter(settings.chroma_host, settings.chroma_port)),
            StorageHealthProbe(source_storage),
            CeleryHealthProbe(redis_client),
            NotConfiguredProbe("mineru"),
            NotConfiguredProbe("models"),
        ],
    )
    task_service = TaskService(SqlAlchemyOperationRepository(), SqlAlchemyOutboxRepository())
    admin_idempotency_service = AdminIdempotencyService(SqlAlchemyAdminIdempotencyRepository())
    outbox_dispatch_store = SqlAlchemyOutboxDispatchStore(session_factory)
    operation_execution_store = SqlAlchemyOperationExecutionStore(session_factory)
    capability_service = CapabilityService(build_capability_registry())
    model_provider_adapter_registry = build_model_provider_adapter_registry()
    provider_task_store = SqlAlchemyProviderTaskStore(session_factory)
    provider_test_handler = ProviderTestHandler(
        provider_task_store,
        model_provider_adapter_registry,
        settings.credential_encryption_key_bytes,
    )
    provider_discovery_handler = ProviderDiscoveryHandler(
        provider_task_store,
        model_provider_adapter_registry,
        settings.credential_encryption_key_bytes,
    )
    model_verification_handler = ModelVerificationHandler(
        SqlAlchemyModelVerificationTaskStore(session_factory),
        model_provider_adapter_registry,
        settings.credential_encryption_key_bytes,
    )
    model_provider_service = ModelProviderService(
        providers=SqlAlchemyModelProviderRepository(),
        audits=SqlAlchemyModelAuditRepository(),
        capabilities=capability_service,
        encryption_key=settings.credential_encryption_key_bytes,
        app_env=settings.app_env,
        allow_local_http=settings.allow_local_provider_http,
        tasks=task_service,
        idempotency=admin_idempotency_service,
        operation_retention_days=settings.operation_retention_days,
    )
    model_repository = SqlAlchemyModelRepository()
    provider_repository = SqlAlchemyModelProviderRepository()
    model_config_service = ModelConfigService(
        model_repository,
        provider_repository,
        capability_service,
        tasks=task_service,
        idempotency=admin_idempotency_service,
        operation_retention_days=settings.operation_retention_days,
    )
    model_selection_service = ModelSelectionService(model_repository, provider_repository)
    knowledge_base_service = KnowledgeBaseService(
        SqlAlchemyKnowledgeBaseRepository(),
        RegistryKnowledgeModelSelector(model_selection_service),
        build_capability_registry(),
        task_service,
        operation_retention_days=settings.operation_retention_days,
        idempotency=admin_idempotency_service,
    )
    vector_store = ChromaVectorStoreAdapter(settings.chroma_host, settings.chroma_port)
    document_embedder = ConfiguredDocumentEmbedder(
        session_factory,
        model_selection_service,
        model_provider_adapter_registry,
        settings.credential_encryption_key_bytes,
    )
    generation_item_executor = DefaultGenerationItemExecutor(
        SqlAlchemyGenerationItemStore(session_factory),
        document_embedder,
        vector_store,
    )
    generation_build_handler = GenerationBuildHandler(
        SqlAlchemyGenerationBuildStore(session_factory),
        generation_item_executor,
        vector_store,
    )
    mineru_settings_service = MinerUSettingsService(
        SqlAlchemyMinerUSettingsRepository(),
        SqlAlchemyMinerUSettingsAuditRepository(),
        settings.credential_encryption_key_bytes,
        tasks=task_service,
        idempotency=admin_idempotency_service,
        operation_retention_days=settings.operation_retention_days,
    )
    data_source_service = DataSourceService(
        SqlAlchemyDataSourceRepository(),
        SqlAlchemyDataSourceAuditRepository(),
        tasks=task_service,
        mineru_settings=mineru_settings_service,
        references=SqlAlchemyParsingReferenceQuery(),
        operation_retention_days=settings.operation_retention_days,
    )
    parser_registry = ParserRegistry()
    parser_registry.register(BuiltinTextParser())
    source_parse_handler = SourceParseHandler(
        SqlAlchemyParseTaskStore(session_factory),
        parser_registry,
        source_storage,
        mineru_adapter_factory=MinerUPrecisionAdapter,
        credential_encryption_key=settings.credential_encryption_key_bytes,
    )
    mineru_connection_test_handler = MinerUConnectionTestHandler(
        SqlAlchemyMinerUTestTaskStore(session_factory),
        mineru_adapter_factory=MinerUPrecisionAdapter,
        credential_encryption_key=settings.credential_encryption_key_bytes,
    )
    parsing_cleanup_handler = ParsingCleanupHandler(
        SqlAlchemyParsingCleanupTaskStore(session_factory),
        source_storage,
    )
    task_dispatch_registry = TaskDispatchRegistry()
    task_dispatch_registry.register(
        TaskDispatchDefinition(
            event_type="knowledge_base.generation.requested",
            schema_version="1",
            celery_task_name="app.tasks.indexing.build_generation",
            queue="indexing",
        )
    )
    task_dispatch_registry.register(
        TaskDispatchDefinition(
            event_type="model.provider.test.requested",
            schema_version="1",
            celery_task_name="app.tasks.maintenance.test_model_provider",
            queue="maintenance",
        )
    )
    task_dispatch_registry.register(
        TaskDispatchDefinition(
            event_type="parsing.cleanup.requested",
            schema_version="1",
            celery_task_name="app.tasks.maintenance.cleanup_parsing",
            queue="maintenance",
        )
    )
    task_dispatch_registry.register(
        TaskDispatchDefinition(
            event_type="model.verification.requested",
            schema_version="1",
            celery_task_name="app.tasks.maintenance.verify_model",
            queue="maintenance",
        )
    )
    task_dispatch_registry.register(
        TaskDispatchDefinition(
            event_type="model.provider.discovery.requested",
            schema_version="1",
            celery_task_name="app.tasks.maintenance.discover_provider_models",
            queue="maintenance",
        )
    )
    task_dispatch_registry.register(
        TaskDispatchDefinition(
            event_type="parsing.source.requested",
            schema_version="1",
            celery_task_name="app.tasks.parsing.parse_source",
            queue="parsing",
        )
    )
    task_dispatch_registry.register(
        TaskDispatchDefinition(
            event_type="parsing.mineru.test.requested",
            schema_version="1",
            celery_task_name="app.tasks.maintenance.test_mineru",
            queue="maintenance",
        )
    )
    return ApplicationDependencies(
        engine=engine,
        session_factory=session_factory,
        redis_client=redis_client,
        auth_service=auth_service,
        health_service=health_service,
        task_service=task_service,
        admin_idempotency_service=admin_idempotency_service,
        outbox_dispatch_store=outbox_dispatch_store,
        operation_execution_store=operation_execution_store,
        task_dispatch_registry=task_dispatch_registry,
        capability_service=capability_service,
        model_provider_service=model_provider_service,
        model_provider_adapter_registry=model_provider_adapter_registry,
        provider_test_handler=provider_test_handler,
        provider_discovery_handler=provider_discovery_handler,
        model_config_service=model_config_service,
        model_selection_service=model_selection_service,
        model_verification_handler=model_verification_handler,
        mineru_settings_service=mineru_settings_service,
        data_source_service=data_source_service,
        knowledge_base_service=knowledge_base_service,
        generation_build_handler=generation_build_handler,
        source_storage=source_storage,
        source_parse_handler=source_parse_handler,
        mineru_connection_test_handler=mineru_connection_test_handler,
        parsing_cleanup_handler=parsing_cleanup_handler,
    )
