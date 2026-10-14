import aiohttp
from yarl import URL

from egress_proxy.protocol import Failure, Header


class Refused(aiohttp.ClientError):
    pass


ERRORS: dict[Failure, type[aiohttp.ClientError]] = {
    Failure.UNAUTHORIZED: Refused,
    Failure.INVALID: Refused,
    Failure.TIMEOUT: aiohttp.ServerTimeoutError,
    Failure.UNREACHABLE: aiohttp.ClientConnectionError,
}


class Middleware:
    def __init__(self, *, egress_url: str, egress_key: str) -> None:
        self.url = URL(egress_url)
        self.key = egress_key

    def rewrite(self, request: aiohttp.ClientRequest) -> None:
        if Header.TARGET in request.headers:
            return
        request.headers[Header.TARGET] = str(request.url)
        request.headers[Header.KEY] = self.key
        request.headers[aiohttp.hdrs.HOST] = self.url.host_port_subcomponent or ""
        request.url = self.url

    async def reject(self, response: aiohttp.ClientResponse) -> aiohttp.ClientError:
        failure = Failure(response.headers[Header.FAILURE])
        message = await response.text()
        response.release()
        return ERRORS[failure](message)

    async def __call__(
        self,
        request: aiohttp.ClientRequest,
        handler: aiohttp.ClientHandlerType,
    ) -> aiohttp.ClientResponse:
        self.rewrite(request)
        response = await handler(request)
        if Header.FAILURE in response.headers:
            raise await self.reject(response)
        return response
