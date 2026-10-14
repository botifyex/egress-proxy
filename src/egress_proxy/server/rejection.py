from egress_proxy.protocol import Failure, Header
from egress_proxy.server.asgi import Send

STATUSES: dict[Failure, int] = {
    Failure.UNAUTHORIZED: 401,
    Failure.INVALID: 400,
    Failure.TIMEOUT: 504,
    Failure.UNREACHABLE: 502,
}


class Rejection(Exception):
    def __init__(self, failure: Failure, message: str) -> None:
        super().__init__(message)
        self.failure = failure
        self.message = message

    def headers(self, body: bytes) -> list[tuple[bytes, bytes]]:
        return [
            (b"content-type", b"text/plain; charset=utf-8"),
            (b"content-length", str(len(body)).encode()),
            (Header.FAILURE.encode(), self.failure.encode()),
        ]

    async def send(self, send: Send) -> None:
        body = self.message.encode()
        await send({"type": "http.response.start", "status": STATUSES[self.failure], "headers": self.headers(body)})
        await send({"type": "http.response.body", "body": body})
