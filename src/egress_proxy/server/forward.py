import hmac
import ssl
from collections.abc import AsyncIterator
from typing import TypeAlias

import aiohttp
import certifi
from yarl import URL

from egress_proxy.protocol import Failure, Header
from egress_proxy.server.asgi import Receive, Scope, Send
from egress_proxy.server.rejection import Rejection
from egress_proxy.server.settings import Proxy

Pairs: TypeAlias = list[tuple[bytes, bytes]]
Headers: TypeAlias = dict[bytes, bytes]

SCHEMES = frozenset({"http", "https"})

METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})

AUTOMATIC = ("User-Agent", "Accept", "Accept-Encoding", "Content-Type")

HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)

IDENTIFYING = frozenset(
    {
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-port",
        "x-forwarded-proto",
        "x-forwarded-server",
        "x-real-ip",
        "x-original-forwarded-for",
        "forwarded",
        "via",
        "cf-connecting-ip",
        "cf-ipcountry",
        "true-client-ip",
        "x-cluster-client-ip",
    }
)

PRIVATE = frozenset(header.value for header in Header)

REQUEST_EXCLUDED = HOP | IDENTIFYING | PRIVATE | {"host"}

RESPONSE_EXCLUDED = HOP | PRIVATE

KEY = Header.KEY.encode()

TARGET = Header.TARGET.encode()


def filtered(pairs: Pairs, excluded: frozenset[str]) -> Pairs:
    return [(name, value) for name, value in pairs if name.decode("latin-1").lower() not in excluded]


def decoded(pairs: Pairs) -> list[tuple[str, str]]:
    return [(name.decode("latin-1"), value.decode("latin-1")) for name, value in pairs]


def session(proxy: Proxy) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(
            limit=0,
            ttl_dns_cache=300,
            ssl=ssl.create_default_context(cafile=certifi.where()),
        ),
        cookie_jar=aiohttp.DummyCookieJar(),
        auto_decompress=False,
        skip_auto_headers=AUTOMATIC,
        timeout=aiohttp.ClientTimeout(total=None, sock_connect=proxy.connect, sock_read=proxy.timeout),
    )


async def chunks(receive: Receive) -> AsyncIterator[bytes]:
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return
        if message.get("body"):
            yield message["body"]
        if not message.get("more_body", False):
            return


class Forward:
    def __init__(self, client: aiohttp.ClientSession, proxy: Proxy) -> None:
        self.client = client
        self.key = proxy.key.get_secret_value().encode()

    def authorize(self, headers: Headers) -> None:
        if not hmac.compare_digest(headers.get(KEY, b""), self.key):
            raise Rejection(Failure.UNAUTHORIZED, "egress key is missing or invalid")

    def method(self, scope: Scope) -> str:
        method: str = scope["method"]
        if method not in METHODS:
            raise Rejection(Failure.INVALID, f"method {method} is not supported")
        return method

    def target(self, headers: Headers) -> URL:
        value = headers.get(TARGET)
        if value is None:
            raise Rejection(Failure.INVALID, f"'{Header.TARGET}' header is required")
        text = value.decode("latin-1")
        try:
            url = URL(text, encoded=True)
        except ValueError as error:
            raise Rejection(Failure.INVALID, f"'{text}' is not a valid url") from error
        if url.scheme not in SCHEMES or not url.host:
            raise Rejection(Failure.INVALID, f"'{text}' must be an absolute http or https url")
        return url

    def body(self, headers: Headers, receive: Receive) -> AsyncIterator[bytes] | None:
        if b"content-length" in headers or b"transfer-encoding" in headers:
            return chunks(receive)
        return None

    async def request(self, scope: Scope, receive: Receive) -> aiohttp.ClientResponse:
        headers: Headers = dict(scope["headers"])
        self.authorize(headers)
        method = self.method(scope)
        url = self.target(headers)
        try:
            return await self.client.request(
                method,
                url,
                headers=decoded(filtered(scope["headers"], REQUEST_EXCLUDED)),
                data=self.body(headers, receive),
                allow_redirects=False,
            )
        except TimeoutError as error:
            raise Rejection(Failure.TIMEOUT, f"{url} timed out") from error
        except aiohttp.ClientError as error:
            raise Rejection(Failure.UNREACHABLE, f"{url} is unreachable") from error

    async def relay(self, upstream: aiohttp.ClientResponse, send: Send) -> None:
        headers = filtered(list(upstream.raw_headers), RESPONSE_EXCLUDED)
        await send({"type": "http.response.start", "status": upstream.status, "headers": headers})
        async for chunk in upstream.content.iter_any():
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b""})

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            upstream = await self.request(scope, receive)
        except Rejection as rejection:
            await rejection.send(send)
            return
        try:
            await self.relay(upstream, send)
        finally:
            upstream.release()
