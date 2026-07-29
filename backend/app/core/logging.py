import logging
from collections.abc import MutableMapping
from typing import Any, cast

import structlog
from structlog.typing import FilteringBoundLogger

_SENSITIVE_PARTS = ("password", "secret", "token", "authorization", "credential", "api_key")


def redact_sensitive_values(
    _logger: FilteringBoundLogger,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    for key in tuple(event_dict):
        normalized = key.casefold()
        if any(part in normalized for part in _SENSITIVE_PARTS):
            event_dict[key] = "***"
    return event_dict


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            redact_sensitive_values,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger() -> FilteringBoundLogger:
    return cast(FilteringBoundLogger, structlog.get_logger())
