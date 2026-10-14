import json

import httpx
import pytest

from egress_proxy.client import AsyncClient, AsyncTransport, Client, Refused, Transport
from egress_proxy.protocol import Failure, Header

EGRESS = "http://egress.local:8000"


class Recorder:
    def __init__(self, response: httpx.Response | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.response = response or httpx.Response(200, text="ok")

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        return self.response

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]


def failing(failure: Failure) -> Recorder:
    return Recorder(httpx.Response(502, text="details", headers={Header.FAILURE: failure}))


def synchronous(recorder: Recorder) -> httpx.Client:
    return httpx.Client(transport=Transport(EGRESS, "key", httpx.MockTransport(recorder)))


def asynchronous(recorder: Recorder) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=AsyncTransport(EGRESS, "key", httpx.MockTransport(recorder)))


def test_request_is_sent_to_egress() -> None:
    recorder = Recorder()
    with synchronous(recorder) as client:
        client.get("https://api.example.com/items?page=2")
    assert recorder.last.url == httpx.URL(EGRESS)


def test_target_header_carries_full_url() -> None:
    recorder = Recorder()
    with synchronous(recorder) as client:
        client.get("https://api.example.com/a%2Fb/items", params={"page": 2, "tag": ["x", "y"]})
    assert recorder.last.headers[Header.TARGET] == "https://api.example.com/a%2Fb/items?page=2&tag=x&tag=y"


def test_key_header_is_added() -> None:
    recorder = Recorder()
    with synchronous(recorder) as client:
        client.get("https://api.example.com/")
    assert recorder.last.headers[Header.KEY] == "key"


def test_host_header_points_to_egress() -> None:
    recorder = Recorder()
    with synchronous(recorder) as client:
        client.get("https://api.example.com/")
    assert recorder.last.headers["host"] == "egress.local:8000"


def test_method_headers_and_body_are_preserved() -> None:
    recorder = Recorder()
    with synchronous(recorder) as client:
        client.put("https://api.example.com/", json={"name": "value"}, headers={"x-custom": "1"})
    assert recorder.last.method == "PUT"
    assert recorder.last.headers["x-custom"] == "1"
    assert recorder.last.headers["content-type"] == "application/json"
    assert json.loads(recorder.last.content) == {"name": "value"}


def test_timeout_extension_is_preserved() -> None:
    recorder = Recorder()
    with synchronous(recorder) as client:
        client.get("https://api.example.com/", timeout=3.5)
    assert recorder.last.extensions["timeout"]["read"] == 3.5


def test_base_url_is_resolved_before_rewrite() -> None:
    recorder = Recorder()
    transport = Transport(EGRESS, "key", httpx.MockTransport(recorder))
    with httpx.Client(base_url="https://api.example.com/v1", transport=transport) as client:
        client.get("/items")
    assert recorder.last.headers[Header.TARGET] == "https://api.example.com/v1/items"


def test_upstream_error_status_is_not_a_failure() -> None:
    recorder = Recorder(httpx.Response(500, text="upstream broke"))
    with synchronous(recorder) as client:
        response = client.get("https://api.example.com/")
    assert response.status_code == 500
    assert response.text == "upstream broke"


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        (Failure.UNAUTHORIZED, Refused),
        (Failure.INVALID, Refused),
        (Failure.TIMEOUT, httpx.TimeoutException),
        (Failure.UNREACHABLE, httpx.ConnectError),
    ],
)
def test_failure_raises_httpx_error(failure: Failure, error: type[httpx.TransportError]) -> None:
    with synchronous(failing(failure)) as client, pytest.raises(error, match="details") as raised:
        client.get("https://api.example.com/")
    assert raised.value.request.url == httpx.URL("https://api.example.com/")


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        (Failure.UNAUTHORIZED, Refused),
        (Failure.TIMEOUT, httpx.TimeoutException),
        (Failure.UNREACHABLE, httpx.ConnectError),
    ],
)
async def test_failure_raises_httpx_error_asynchronously(failure: Failure, error: type[httpx.TransportError]) -> None:
    async with asynchronous(failing(failure)) as client:
        with pytest.raises(error, match="details"):
            await client.get("https://api.example.com/")


def test_refused_is_a_transport_error() -> None:
    assert issubclass(Refused, httpx.TransportError)


async def test_asynchronous_transport_rewrites_request() -> None:
    recorder = Recorder()
    async with asynchronous(recorder) as client:
        await client.post("https://api.example.com/path", content=b"payload")
    assert recorder.last.url == httpx.URL(EGRESS)
    assert recorder.last.headers[Header.TARGET] == "https://api.example.com/path"
    assert recorder.last.content == b"payload"


def test_client_uses_given_inner_transport() -> None:
    recorder = Recorder()
    with Client(EGRESS, "key", transport=httpx.MockTransport(recorder), base_url="https://api.example.com") as client:
        client.get("/items")
    assert recorder.last.headers[Header.TARGET] == "https://api.example.com/items"


async def test_asynchronous_client_uses_given_inner_transport() -> None:
    recorder = Recorder()
    async with AsyncClient(EGRESS, "key", transport=httpx.MockTransport(recorder)) as client:
        await client.get("https://api.example.com/items")
    assert recorder.last.headers[Header.KEY] == "key"


def test_client_can_be_subclassed() -> None:
    recorder = Recorder()

    class Example(Client):
        def __init__(self) -> None:
            super().__init__(EGRESS, "key", transport=httpx.MockTransport(recorder), base_url="https://example.com")

        def items(self) -> httpx.Response:
            return self.get("/items")

    with Example() as client:
        client.items()
    assert recorder.last.headers[Header.TARGET] == "https://example.com/items"


def test_environment_proxies_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://other-proxy:3128")
    monkeypatch.setenv("HTTP_PROXY", "http://other-proxy:3128")
    recorder = Recorder()
    with Client(EGRESS, "key", transport=httpx.MockTransport(recorder)) as client:
        client.get("https://api.example.com/")
    assert recorder.last.url == httpx.URL(EGRESS)


def test_closing_client_closes_inner_transport() -> None:
    closed: list[bool] = []

    class Inner(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        def close(self) -> None:
            closed.append(True)

    client = Client(EGRESS, "key", transport=Inner())
    client.close()
    assert closed == [True]


async def test_closing_asynchronous_client_closes_inner_transport() -> None:
    closed: list[bool] = []

    class Inner(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        async def aclose(self) -> None:
            closed.append(True)

    client = AsyncClient(EGRESS, "key", transport=Inner())
    await client.aclose()
    assert closed == [True]
