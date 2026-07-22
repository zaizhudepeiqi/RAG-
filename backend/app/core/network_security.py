import ipaddress
import socket
from collections.abc import Callable, Iterable
from typing import Literal
from urllib.parse import urlsplit, urlunsplit


class OutboundUrlPolicyError(ValueError):
    code = "PROVIDER_BASE_URL_FORBIDDEN"


AddressResolver = Callable[[str], Iterable[str]]


def resolve_host_addresses(host: str) -> tuple[str, ...]:
    addresses: set[str] = set()
    for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM):
        if item[4] and isinstance(item[4][0], str):
            addresses.add(item[4][0])
    return tuple(sorted(addresses))


def validate_outbound_base_url(
    value: str,
    *,
    app_env: Literal["development", "test", "production"],
    allow_local_http: bool,
    resolver: AddressResolver = resolve_host_addresses,
) -> str:
    try:
        parsed = urlsplit(value.strip())
        host = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise OutboundUrlPolicyError("provider base URL is not allowed") from error

    if (
        parsed.scheme not in {"http", "https"}
        or host is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise OutboundUrlPolicyError("provider base URL is not allowed")

    normalized_host = host.rstrip(".").lower()
    if not normalized_host:
        raise OutboundUrlPolicyError("provider base URL is not allowed")

    addresses = _resolve_addresses(normalized_host, resolver)
    local_http = app_env == "development" and allow_local_http and parsed.scheme == "http"
    if parsed.scheme == "http" and not local_http:
        raise OutboundUrlPolicyError("provider base URL is not allowed")
    if local_http:
        if not all(address.is_loopback for address in addresses):
            raise OutboundUrlPolicyError("provider base URL is not allowed")
    elif not all(address.is_global for address in addresses):
        raise OutboundUrlPolicyError("provider base URL is not allowed")

    rendered_host = f"[{normalized_host}]" if ":" in normalized_host else normalized_host
    netloc = f"{rendered_host}:{port}" if port is not None else rendered_host
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, netloc, path, "", ""))


def _resolve_addresses(
    host: str, resolver: AddressResolver
) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    raw_addresses: tuple[str, ...]
    try:
        direct = ipaddress.ip_address(host)
        raw_addresses = (str(direct),)
    except ValueError:
        try:
            raw_addresses = tuple(resolver(host))
        except (OSError, ValueError) as error:
            raise OutboundUrlPolicyError("provider base URL is not allowed") from error

    if not raw_addresses:
        raise OutboundUrlPolicyError("provider base URL is not allowed")
    try:
        return tuple(ipaddress.ip_address(address) for address in raw_addresses)
    except ValueError as error:
        raise OutboundUrlPolicyError("provider base URL is not allowed") from error
