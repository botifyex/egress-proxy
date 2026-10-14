from starlette.responses import PlainTextResponse, Response

from egress_proxy.protocol import Failure, Header

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

    def response(self) -> Response:
        return PlainTextResponse(
            self.message,
            status_code=STATUSES[self.failure],
            headers={Header.FAILURE: self.failure},
        )
