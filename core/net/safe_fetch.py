"""SSRF-safe HTTP fetch for user-supplied URLs (CLAUDE.md rule 8).

For every request, including each redirect hop:
- only http/https on the default ports;
- DNS is resolved here and every resolved address must be public (no private, loopback,
  link-local, multicast, reserved, CGNAT or cloud-metadata ranges);
- the connection goes to the IP that was checked (Host header and TLS SNI keep the original
  hostname), so a second DNS answer can't swap in an internal address (DNS rebinding);
- response size and total time are capped. Page caps are the caller's job (fetch_site).
"""

import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from core.config import get_settings

MAX_REDIRECTS = 5
ALLOWED_PORTS = {"http": 80, "https": 443}
ALLOWED_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
METADATA_HOSTS = {"metadata.google.internal", "metadata", "instance-data"}


class UnsafeURL(Exception):
    pass


class FetchError(Exception):
    pass


@dataclass(frozen=True)
class FetchResult:
    url: str  # final URL after redirects
    status: int
    content_type: str
    body: bytes


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        not (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
            or (
                isinstance(ip, ipaddress.IPv4Address)
                and ip in ipaddress.ip_network("100.64.0.0/10")
            )  # CGNAT
        )
        and ip.is_global
    )


def validate_url(url: str) -> tuple[str, str, int]:
    """Return (scheme, host, port) or raise UnsafeURL. No network access."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_PORTS:
        raise UnsafeURL("only http and https URLs are allowed")
    if parts.username or parts.password:
        raise UnsafeURL("credentials in URLs are not allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeURL("URL has no host")
    if (
        host in METADATA_HOSTS
        or host == "localhost"
        or host.endswith(".localhost")
        or host.endswith(".internal")
        or host.endswith(".local")
    ):
        raise UnsafeURL("internal host names are not allowed")
    port = parts.port or ALLOWED_PORTS[scheme]
    if port != ALLOWED_PORTS[scheme]:
        raise UnsafeURL("non-standard ports are not allowed")
    return scheme, host, port


async def resolve_public(host: str, port: int) -> str:
    """Resolve and return one public IP for host; raise if any answer is not public."""
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _is_public(literal):
            raise UnsafeURL("address is not public")
        return str(literal)
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError(f"cannot resolve {host}") from exc
    addresses = {str(info[4][0]) for info in infos}
    if not addresses:
        raise FetchError(f"cannot resolve {host}")
    for addr in addresses:
        if not _is_public(ipaddress.ip_address(addr.split("%")[0])):
            # One bad answer is enough to refuse: an attacker controls the whole record set.
            raise UnsafeURL("host resolves to a non-public address")
    return sorted(addresses)[0]


async def safe_get(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    max_bytes: int | None = None,
    timeout_s: float | None = None,
) -> FetchResult:
    settings = get_settings()
    max_bytes = max_bytes or settings.fetch_max_bytes
    timeout_s = timeout_s or settings.fetch_timeout_s
    deadline = time.monotonic() + timeout_s
    own_client = client is None
    client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s),
        follow_redirects=False,
        headers={"User-Agent": settings.crawler_user_agent},
    )
    try:
        current = url
        for _hop in range(MAX_REDIRECTS + 1):
            scheme, host, port = validate_url(current)
            ip = await resolve_public(host, port)
            parts = urlsplit(current)
            ip_host = f"[{ip}]" if ":" in ip else ip
            target = urlunsplit((scheme, ip_host, parts.path or "/", parts.query, ""))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FetchError("timed out")
            request = client.build_request(
                "GET",
                target,
                headers={"Host": host},
                timeout=remaining,
                extensions={"sni_hostname": host},
            )
            response = await client.send(request, stream=True)
            try:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise FetchError("redirect without location")
                    current = urljoin(current, location)
                    continue
                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise FetchError("response too large")
                    if time.monotonic() > deadline:
                        raise FetchError("timed out")
                return FetchResult(current, response.status_code, content_type, bytes(body))
            finally:
                await response.aclose()
        raise FetchError("too many redirects")
    except httpx.HTTPError as exc:
        raise FetchError(f"fetch failed: {exc.__class__.__name__}") from exc
    finally:
        if own_client:
            await client.aclose()
