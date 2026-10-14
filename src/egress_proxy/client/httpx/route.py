from dataclasses import dataclass

import httpx

from egress_proxy.protocol import Failure, Header


class Refused(httpx.TransportError):
    pass


ERRORS: dict[Failure, type[httpx.TransportError]] = {
    Failure.UNAUTHORIZED: Refused,
    Failure.INVALID: Refused,
    Failure.TIMEOUT: httpx.TimeoutException,
    Failure.UNREACHABLE: httpx.ConnectError,
}


@dataclass(frozen=True)
class Route:
    url: httpx.URL
    key: str

    def headers(self, request: httpx.Request) -> httpx.Headers:
        headers = request.headers.copy()
        headers["host"] = self.url.netloc.decode("ascii")
        headers[Header.KEY] = self.key
        headers[Header.TARGET] = str(request.url)
        return headers

    def rewrite(self, request: httpx.Request) -> httpx.Request:
        return httpx.Request(
            request.method,
            self.url,
            headers=self.headers(request),
            stream=request.stream,
            extensions=request.extensions,
        )

    def failed(self, response: httpx.Response) -> bool:
        return Header.FAILURE in response.headers

    def error(self, request: httpx.Request, response: httpx.Response) -> httpx.TransportError:
        failure = Failure(response.headers[Header.FAILURE])
        return ERRORS[failure](response.text, request=request)
