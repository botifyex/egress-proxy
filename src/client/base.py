from enum import StrEnum
from typing import Any, ClassVar, Self

import httpx

type Params = dict[str, Any]
type Headers = dict[str, str]
type Body = dict[str, Any]


class Method(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class HttpError(Exception):
    pass


class NotOpened(HttpError):  # noqa: N818
    def __init__(self) -> None:
        super().__init__("client must be used as an async context manager")


class RequestFailed(HttpError):  # noqa: N818
    def __init__(self, method: Method, path: str, response: httpx.Response) -> None:
        self.method = method
        self.path = path
        self.status = response.status_code
        self.response = response
        super().__init__(f"{method} {path} failed with status {self.status}")


class ClientFault(RequestFailed):
    pass


class ServerFault(RequestFailed):
    pass


class Upstream(HttpError):  # noqa: N818
    def __init__(self, method: Method, path: str, cause: Exception) -> None:
        self.method = method
        self.path = path
        self.cause = cause
        super().__init__(f"{method} {path} could not reach the upstream")


class UpstreamTimeout(Upstream):
    pass


class UpstreamUnavailable(Upstream):
    pass


class Faults:
    @staticmethod
    def of(response: httpx.Response) -> type[RequestFailed]:
        if response.is_server_error:
            return ServerFault
        if response.is_client_error:
            return ClientFault
        return RequestFailed

    @staticmethod
    def upstream(error: httpx.TransportError) -> type[Upstream]:
        if isinstance(error, httpx.TimeoutException):
            return UpstreamTimeout
        return UpstreamUnavailable


class Client:
    base: ClassVar[str] = ""
    timeout: ClassVar[float] = 30.0
    connect: ClassVar[float] = 10.0
    http2: ClassVar[bool] = True
    redirects: ClassVar[bool] = True

    headers: ClassVar[Headers] = {
        "accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "accept-language": "en-US,en;q=0.9",
        "sec-ch-ua": (
            '"Chromium";v="147", "Google Chrome";v="147", "Not=A?Brand";v="24"'
        ),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "upgrade-insecure-requests": "1",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
    }

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owns = client is None

    async def __aenter__(self) -> Self:
        if self._client is None:
            self._client = self._build()
        return self

    async def __aexit__(self, *error: object) -> None:
        await self.aclose()

    def _build(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base,
            headers=self.headers,
            http2=self.http2,
            timeout=httpx.Timeout(self.timeout, connect=self.connect),
            follow_redirects=self.redirects,
        )

    async def aclose(self) -> None:
        if self._owns and self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def session(self) -> httpx.AsyncClient:
        if self._client is None:
            raise NotOpened()
        return self._client

    def _check(
        self, method: Method, path: str, response: httpx.Response
    ) -> httpx.Response:
        if response.is_error:
            raise Faults.of(response)(method, path, response)
        return response

    def payload(self, response: httpx.Response) -> Any:
        if not response.content:
            return None
        return response.json()

    async def attempt(
        self,
        method: Method,
        path: str,
        *,
        params: Params | None = None,
        body: Body | None = None,
        headers: Headers | None = None,
    ) -> httpx.Response:
        try:
            return await self.session.request(
                method,
                path,
                params=params,
                json=body,
                headers=headers,
            )
        except httpx.TransportError as error:
            raise Faults.upstream(error)(method, path, error) from error

    async def request(
        self,
        method: Method,
        path: str,
        *,
        params: Params | None = None,
        body: Body | None = None,
        headers: Headers | None = None,
    ) -> httpx.Response:
        response = await self.attempt(
            method, path, params=params, body=body, headers=headers
        )
        return self._check(method, path, response)

    async def get(
        self,
        path: str,
        *,
        params: Params | None = None,
        headers: Headers | None = None,
    ) -> Any:
        response = await self.request(Method.GET, path, params=params, headers=headers)
        return self.payload(response)

    async def post(
        self,
        path: str,
        *,
        body: Body | None = None,
        params: Params | None = None,
        headers: Headers | None = None,
    ) -> Any:
        response = await self.request(
            Method.POST, path, body=body, params=params, headers=headers
        )
        return self.payload(response)

    async def put(
        self,
        path: str,
        *,
        body: Body | None = None,
        params: Params | None = None,
        headers: Headers | None = None,
    ) -> Any:
        response = await self.request(
            Method.PUT, path, body=body, params=params, headers=headers
        )
        return self.payload(response)

    async def patch(
        self,
        path: str,
        *,
        body: Body | None = None,
        params: Params | None = None,
        headers: Headers | None = None,
    ) -> Any:
        response = await self.request(
            Method.PATCH, path, body=body, params=params, headers=headers
        )
        return self.payload(response)

    async def delete(
        self,
        path: str,
        *,
        params: Params | None = None,
        headers: Headers | None = None,
    ) -> Any:
        response = await self.request(
            Method.DELETE, path, params=params, headers=headers
        )
        return self.payload(response)
