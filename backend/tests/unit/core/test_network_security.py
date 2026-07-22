from importlib import import_module
from importlib.util import find_spec
from types import ModuleType

import pytest


def load_network_security() -> ModuleType:
    assert find_spec("app.core.network_security") is not None, (
        "app.core.network_security must define outbound URL validation"
    )
    return import_module("app.core.network_security")


def public_resolver(_host: str) -> tuple[str, ...]:
    return ("8.8.8.8",)


def private_resolver(_host: str) -> tuple[str, ...]:
    return ("10.0.0.5",)


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "https://127.0.0.1/v1",
        "https://[::1]/v1",
        "https://user:password@example.com/v1",
        "file:///etc/passwd",
        "https://example.com/v1?credential=value",
        "https://example.com/v1#fragment",
    ],
)
def test_outbound_provider_url_rejects_unsafe_targets(url: str) -> None:
    module = load_network_security()

    with pytest.raises(module.OutboundUrlPolicyError) as raised:
        module.validate_outbound_base_url(
            url,
            app_env="production",
            allow_local_http=False,
            resolver=public_resolver,
        )

    assert raised.value.code == "PROVIDER_BASE_URL_FORBIDDEN"
    assert url not in str(raised.value)


def test_outbound_provider_url_rejects_dns_resolution_to_private_address() -> None:
    module = load_network_security()

    with pytest.raises(module.OutboundUrlPolicyError):
        module.validate_outbound_base_url(
            "https://models.example.com/v1",
            app_env="production",
            allow_local_http=False,
            resolver=private_resolver,
        )


def test_outbound_provider_url_normalizes_public_https_url() -> None:
    module = load_network_security()

    normalized = module.validate_outbound_base_url(
        "https://models.example.com/v1/",
        app_env="production",
        allow_local_http=False,
        resolver=public_resolver,
    )

    assert normalized == "https://models.example.com/v1"


def test_local_http_requires_explicit_development_switch() -> None:
    module = load_network_security()

    assert (
        module.validate_outbound_base_url(
            "http://127.0.0.1:11434/v1/",
            app_env="development",
            allow_local_http=True,
            resolver=lambda _host: ("127.0.0.1",),
        )
        == "http://127.0.0.1:11434/v1"
    )
    with pytest.raises(module.OutboundUrlPolicyError):
        module.validate_outbound_base_url(
            "http://127.0.0.1:11434/v1",
            app_env="development",
            allow_local_http=False,
            resolver=lambda _host: ("127.0.0.1",),
        )


def test_test_environment_rejects_public_http_provider() -> None:
    module = load_network_security()

    with pytest.raises(module.OutboundUrlPolicyError):
        module.validate_outbound_base_url(
            "http://models.example.com/v1",
            app_env="test",
            allow_local_http=True,
            resolver=public_resolver,
        )
