import hmac
from collections.abc import AsyncIterator
from typing import TypeAlias

import aiohttp
from aiohttp_socks import ProxyConnectionError, ProxyError, ProxyTimeoutError
from yarl import URL

from egress_proxy.protocol import Failure, Header
from egress_proxy.server.asgi import Receive, Scope, Send
from egress_proxy.server.headers import REQUEST, RESPONSE, Pairs, filtered
from egress_proxy.server.rejection import Rejection
from egress_proxy.server.routes import Balancer, Route
from egress_proxy.server.settings import Proxy

Headers: TypeAlias = dict[bytes, bytes]

SCHEMES = frozenset({"http", "https"})

METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})

KEY = Header.KEY.encode()

TARGET = Header.TARGET.encode()

UNREACHABLE = (ProxyConnectionError, ProxyTimeoutError)

REFUSED = (*UNREACHABLE, ProxyError)


def decoded(pairs: Pairs) -> list[tuple[str, str]]:
    return [(name.decode("latin-1"), value.decode("latin-1")) for name, value in pairs]


async def chunks(receive: Receive) -> AsyncIterator[bytes]:
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return
        if message.get("body"):
            yield message["body"]
        if not message.get("more_body", False):
            return


class Stream:
    def __init__(self, receive: Receive, present: bool) -> None:
        self.receive = receive
        self.present = present
        self.started = False

    async def chunks(self) -> AsyncIterator[bytes]:
        self.started = True
        async for chunk in chunks(self.receive):
            yield chunk

    def body(self) -> AsyncIterator[bytes] | None:
        return self.chunks() if self.present else None


class Forward:
    def __init__(self, balancer: Balancer, proxy: Proxy) -> None:
        self.balancer = balancer
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

    def stream(self, headers: Headers, receive: Receive) -> Stream:
        return Stream(receive, b"content-length" in headers or b"transfer-encoding" in headers)

    async def send(
        self,
        route: Route,
        method: str,
        url: URL,
        headers: list[tuple[str, str]],
        stream: Stream,
    ) -> aiohttp.ClientResponse:
        try:
            return await route.client.request(method, url, headers=headers, data=stream.body(), allow_redirects=False)
        except TimeoutError as error:
            raise Rejection(Failure.TIMEOUT, f"{url} timed out") from error
        except aiohttp.ClientError as error:
            raise Rejection(Failure.UNREACHABLE, f"{url} is unreachable") from error

    def failed(self, route: Route, url: URL, error: Exception) -> Rejection:
        if isinstance(error, UNREACHABLE):
            self.balancer.rest(route)
            return Rejection(Failure.UNREACHABLE, f"upstream proxy {route.name} is unreachable")
        return Rejection(Failure.UNREACHABLE, f"{url} is unreachable through upstream proxy {route.name}")

    async def request(self, scope: Scope, receive: Receive) -> aiohttp.ClientResponse:
        headers: Headers = dict(scope["headers"])
        self.authorize(headers)
        method = self.method(scope)
        url = self.target(headers)
        forwarded = decoded(filtered(scope["headers"], REQUEST))
        stream = self.stream(headers, receive)
        failure = Rejection(Failure.UNREACHABLE, f"{url} is unreachable")
        for route in self.balancer.candidates():
            try:
                return await self.send(route, method, url, forwarded, stream)
            except REFUSED as error:
                failure = self.failed(route, url, error)
            if stream.started:
                break
        raise failure

    async def relay(self, upstream: aiohttp.ClientResponse, send: Send) -> None:
        headers = filtered(list(upstream.raw_headers), RESPONSE)
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
