import hmac
from collections.abc import AsyncIterator

import httpx
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from egress_proxy.protocol import Failure, Header
from egress_proxy.server.rejection import Rejection
from egress_proxy.server.settings import Proxy

type Pairs = list[tuple[bytes, bytes]]

SCHEMES = frozenset({"http", "https"})

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


def filtered(pairs: Pairs, excluded: frozenset[str]) -> Pairs:
    return [(name, value) for name, value in pairs if name.decode("latin-1").lower() not in excluded]


class Forward:
    def __init__(self, transport: httpx.AsyncBaseTransport, proxy: Proxy) -> None:
        self.transport = transport
        self.proxy = proxy

    def authorize(self, request: Request) -> None:
        given = request.headers.get(Header.KEY, "").encode()
        expected = self.proxy.key.get_secret_value().encode()
        if not hmac.compare_digest(given, expected):
            raise Rejection(Failure.UNAUTHORIZED, "egress key is missing or invalid")

    def target(self, request: Request) -> httpx.URL:
        value = request.headers.get(Header.TARGET)
        if value is None:
            raise Rejection(Failure.INVALID, f"'{Header.TARGET}' header is required")
        try:
            url = httpx.URL(value)
        except httpx.InvalidURL as error:
            raise Rejection(Failure.INVALID, f"'{value}' is not a valid url") from error
        if url.scheme not in SCHEMES or not url.host:
            raise Rejection(Failure.INVALID, f"'{value}' must be an absolute http or https url")
        return url

    def body(self, request: Request) -> AsyncIterator[bytes] | None:
        if "content-length" in request.headers or "transfer-encoding" in request.headers:
            return request.stream()
        return None

    def timeout(self) -> httpx.Timeout:
        return httpx.Timeout(self.proxy.timeout, connect=self.proxy.connect)

    def build(self, request: Request) -> httpx.Request:
        return httpx.Request(
            request.method,
            self.target(request),
            headers=filtered(request.headers.raw, REQUEST_EXCLUDED),
            content=self.body(request),
            extensions={"timeout": self.timeout().as_dict()},
        )

    async def send(self, upstream: httpx.Request) -> httpx.Response:
        try:
            return await self.transport.handle_async_request(upstream)
        except httpx.TimeoutException as error:
            raise Rejection(Failure.TIMEOUT, f"{upstream.url} timed out") from error
        except httpx.TransportError as error:
            raise Rejection(Failure.UNREACHABLE, f"{upstream.url} is unreachable") from error

    def relay(self, upstream: httpx.Response) -> Response:
        response = StreamingResponse(
            upstream.aiter_raw(),
            status_code=upstream.status_code,
            background=BackgroundTask(upstream.aclose),
        )
        response.raw_headers = filtered(upstream.headers.raw, RESPONSE_EXCLUDED)
        return response

    async def handle(self, request: Request) -> Response:
        try:
            self.authorize(request)
            return self.relay(await self.send(self.build(request)))
        except Rejection as rejection:
            return rejection.response()
