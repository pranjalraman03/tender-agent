import httpx
import pytest

from core.net import safe_fetch
from core.net.safe_fetch import FetchError, UnsafeURL, resolve_public, safe_get, validate_url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/",
        "http://localhost/",
        "http://foo.localhost/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://user:pass@example.com/",
        "http://example.com:8080/",
        "gopher://example.com/",
    ],
)
def test_validate_url_rejects(url: str) -> None:
    with pytest.raises(UnsafeURL):
        validate_url(url)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "::1",
        "fe80::1",
        "fd00:ec2::254",
        "::ffff:127.0.0.1",
        "224.0.0.1",
    ],
)
async def test_resolve_public_rejects_internal_literals(ip: str) -> None:
    with pytest.raises(UnsafeURL):
        await resolve_public(ip, 80)


async def test_resolve_public_accepts_public_literal() -> None:
    assert await resolve_public("93.184.216.34", 443) == "93.184.216.34"


DNS = {"site.test": "93.184.216.34", "evil.test": "10.0.0.5"}


@pytest.fixture
def fake_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(host: str, port: int) -> str:
        ip = DNS.get(host, host)  # literal IPs pass through
        return await resolve_public(ip, port)  # applies the real IP checks

    monkeypatch.setattr(safe_fetch, "resolve_public", resolve)


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, follow_redirects=False)


async def test_connects_to_checked_ip_with_host_header(fake_dns: None) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>hi</p>")

    result = await safe_get("https://site.test/about", client=_client(httpx.MockTransport(handler)))
    assert result.body == b"<p>hi</p>" and result.url == "https://site.test/about"
    assert seen[0].url.host == "93.184.216.34"
    assert seen[0].headers["host"] == "site.test"
    assert seen[0].extensions["sni_hostname"] == "site.test"


async def test_redirect_to_internal_host_is_blocked(fake_dns: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://evil.test/admin"})

    with pytest.raises(UnsafeURL):
        await safe_get("https://site.test/", client=_client(httpx.MockTransport(handler)))


async def test_redirect_to_metadata_ip_is_blocked(fake_dns: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(301, headers={"location": "http://169.254.169.254/latest/"})

    with pytest.raises(UnsafeURL):
        await safe_get("https://site.test/", client=_client(httpx.MockTransport(handler)))


async def test_response_size_cap(fake_dns: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"x" * 5000)

    with pytest.raises(FetchError):
        await safe_get(
            "https://site.test/", client=_client(httpx.MockTransport(handler)), max_bytes=1000
        )


async def test_redirect_loop_is_capped(fake_dns: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/again"})

    with pytest.raises(FetchError):
        await safe_get("https://site.test/", client=_client(httpx.MockTransport(handler)))
