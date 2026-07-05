from fastapi import HTTPException, Request, Response

from src.client.base import Body, Client, Headers, Method, Upstream, UpstreamTimeout

HOP_BY_HOP_HEADERS = frozenset(
    {
        "host",
        "content-length",
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

PROXY_IDENTIFYING_HEADERS = frozenset(
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

RESPONSE_STRIPPED_HEADERS = frozenset(
    {
        "content-encoding",
        "content-length",
        "transfer-encoding",
        "connection",
        "keep-alive",
    }
)


class UpstreamFailure(HTTPException):
    def __init__(self, error: Upstream) -> None:
        super().__init__(status_code=self.status(error), detail=str(error))

    @staticmethod
    def status(error: Upstream) -> int:
        if isinstance(error, UpstreamTimeout):
            return 504
        return 502


class Forward:
    def __init__(self, request: Request, header: str) -> None:
        self._request = request
        self._header = header.lower()

    def method(self) -> Method:
        return Method(self._request.method)

    def params(self) -> dict[str, str]:
        return dict(self._request.query_params)

    def excluded(self, name: str) -> bool:
        name = name.lower()
        return (
            name in HOP_BY_HOP_HEADERS
            or name in PROXY_IDENTIFYING_HEADERS
            or name == self._header
        )

    def headers(self) -> Headers:
        return {
            name: value
            for name, value in self._request.headers.items()
            if not self.excluded(name)
        }

    async def body(self) -> Body | None:
        raw = await self._request.body()
        if not raw:
            return None
        return await self._request.json()

    def upstream_response_headers(self, upstream: Headers) -> Headers:
        return {
            name: value
            for name, value in upstream.items()
            if name.lower() not in RESPONSE_STRIPPED_HEADERS
        }

    async def to(self, client: Client, path: str) -> Response:
        try:
            response = await client.attempt(
                self.method(),
                path,
                params=self.params(),
                body=await self.body(),
                headers=self.headers(),
            )
        except Upstream as error:
            raise UpstreamFailure(error) from error

        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=self.upstream_response_headers(dict(response.headers)),
        )
