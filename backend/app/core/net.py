"""Network destination validation for administrator-supplied API endpoints."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeProviderURL(ValueError):
    pass


def _public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return bool(address.is_global)


async def validate_provider_url(value: str, *, resolve: bool = True) -> str:
    url = value.strip().rstrip("/")
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise UnsafeProviderURL("Provider base URL must use HTTPS")
    if not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeProviderURL("Provider base URL must contain a public hostname and no credentials")
    if parsed.query or parsed.fragment:
        raise UnsafeProviderURL("Provider base URL cannot contain a query string or fragment")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal")):
        raise UnsafeProviderURL("Private provider hostnames are not allowed")
    try:
        is_public_address = _public_ip(host)
    except ValueError:
        is_public_address = None
    if is_public_address is not None:
        if not is_public_address:
            raise UnsafeProviderURL("Private or reserved provider addresses are not allowed")
        return url
    if resolve:
        try:
            infos = await asyncio.to_thread(
                socket.getaddrinfo,
                host,
                parsed.port or 443,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise UnsafeProviderURL("Provider hostname could not be resolved") from exc
        addresses = {item[4][0] for item in infos}
        if not addresses or any(not _public_ip(address) for address in addresses):
            raise UnsafeProviderURL("Provider hostname resolves to a private or reserved address")
    return url
