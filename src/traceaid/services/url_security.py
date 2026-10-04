"""SSRF protections for the opt-in live probe feature."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit


class UnsafeTargetError(ValueError):
    """Raised when a URL is not an eligible public HTTP target."""


Resolver = Callable[[str, int], Awaitable[Sequence[str]]]


@dataclass(frozen=True, slots=True)
class ValidatedTarget:
    url: str
    hostname: str
    port: int
    resolved_ips: tuple[str, ...]


_BLOCKED_HOST_SUFFIXES = (
    ".internal",
    ".intranet",
    ".lan",
    ".local",
    ".localhost",
    ".home.arpa",
)


def _validate_syntax(url: str) -> tuple[str, int]:
    if not url or len(url) > 4096:
        raise UnsafeTargetError("target URL is empty or too long")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeTargetError("target URL contains an invalid port") from exc

    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeTargetError("only http and https targets may be probed")
    if not parsed.hostname:
        raise UnsafeTargetError("target URL requires a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeTargetError("credentials in target URLs are not allowed")

    hostname = parsed.hostname.rstrip(".").casefold()
    if hostname == "localhost" or hostname.endswith(_BLOCKED_HOST_SUFFIXES):
        raise UnsafeTargetError("local and internal hostnames may not be probed")
    if any(character.isspace() or character in {"/", "\\", "\x00"} for character in hostname):
        raise UnsafeTargetError("target hostname is malformed")

    return hostname, port or (443 if parsed.scheme.lower() == "https" else 80)


def _ensure_public_ip(raw_address: str) -> str:
    try:
        address = ipaddress.ip_address(raw_address.split("%", 1)[0])
    except ValueError as exc:
        raise UnsafeTargetError("DNS returned a malformed address") from exc

    # is_global rejects loopback, RFC1918, link-local, multicast, unspecified,
    # documentation, benchmarking, carrier-grade NAT, and reserved ranges.
    if not address.is_global:
        raise UnsafeTargetError(f"target resolves to a non-public address ({address})")
    return address.compressed


async def _system_resolver(hostname: str, port: int) -> Sequence[str]:
    def resolve() -> list[str]:
        results = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        return [str(item[4][0]) for item in results]

    try:
        return await asyncio.to_thread(resolve)
    except socket.gaierror as exc:
        raise UnsafeTargetError("target hostname could not be resolved") from exc


async def validate_public_url(url: str, *, resolver: Resolver | None = None) -> ValidatedTarget:
    """Resolve *url* and reject it unless every address is globally routable.

    All returned DNS answers are checked.  The caller must invoke this directly
    before connecting and must not follow redirects without validating the new
    location. TraceAid's probe client disables redirects entirely.
    """

    hostname, port = _validate_syntax(url)
    addresses: Sequence[str]

    try:
        literal = ipaddress.ip_address(hostname.split("%", 1)[0])
    except ValueError:
        active_resolver = resolver or _system_resolver
        addresses = await active_resolver(hostname, port)
    else:
        addresses = [literal.compressed]

    if not addresses:
        raise UnsafeTargetError("target hostname did not resolve to an address")
    public_addresses = tuple(dict.fromkeys(_ensure_public_ip(address) for address in addresses))
    return ValidatedTarget(url=url, hostname=hostname, port=port, resolved_ips=public_addresses)


__all__ = ["Resolver", "UnsafeTargetError", "ValidatedTarget", "validate_public_url"]
