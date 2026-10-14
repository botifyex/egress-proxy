import httpx

from egress_proxy.client.route import Route


class Transport(httpx.BaseTransport):
    def __init__(self, egress: str, key: str, inner: httpx.BaseTransport | None = None) -> None:
        self.route = Route(httpx.URL(egress), key)
        self.inner = inner or httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.inner.handle_request(self.route.rewrite(request))
        if self.route.failed(response):
            response.read()
            raise self.route.error(request, response)
        return response

    def close(self) -> None:
        self.inner.close()


class AsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self, egress: str, key: str, inner: httpx.AsyncBaseTransport | None = None) -> None:
        self.route = Route(httpx.URL(egress), key)
        self.inner = inner or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self.inner.handle_async_request(self.route.rewrite(request))
        if self.route.failed(response):
            await response.aread()
            raise self.route.error(request, response)
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()
