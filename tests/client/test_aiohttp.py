import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from yarl import URL

from egress_proxy.client.aiohttp import Middleware, Refused, session
from egress_proxy.protocol import Failure, Header
from tests.support.servers import Fleet

METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


@dataclass
class Seen:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes


@dataclass
class Recorder:
    url: str = ""
    seen: list[Seen] = field(default_factory=list)

    @property
    def last(self) -> Seen:
        return self.seen[-1]


def answer(target: URL) -> Response:
    if target.path.startswith("/fail/"):
        failure = target.path.removeprefix("/fail/")
        return Response("details", status_code=502, headers={Header.FAILURE: failure})
    if target.path == "/broken":
        return Response("upstream broke", status_code=500)
    return Response(json.dumps({"target": str(target)}), media_type="application/json")


def recording(recorder: Recorder) -> Starlette:
    async def record(request: Request) -> Response:
        body = await request.body()
        recorder.seen.append(Seen(request.method, request.url.path, dict(request.headers), body))
        return answer(URL(request.headers.get(Header.TARGET, "")))

    return Starlette(routes=[Route("/{path:path}", record, methods=METHODS)])


@pytest.fixture(scope="session")
def shared(fleet: Fleet) -> Recorder:
    recorder = Recorder()
    recorder.url = fleet.start(recording(recorder))
    return recorder


@pytest.fixture
def recorder(shared: Recorder) -> Iterator[Recorder]:
    shared.seen.clear()
    yield shared


def client(recorder: Recorder, **options: Any) -> aiohttp.ClientSession:
    return session(egress_url=recorder.url, egress_key="key", **options)


async def test_request_is_sent_to_egress(recorder: Recorder) -> None:
    async with client(recorder) as http, http.get("https://api.example.com/items?page=2") as response:
        await response.read()
    assert recorder.last.path == "/"


async def test_target_header_carries_full_url(recorder: Recorder) -> None:
    params = [("page", "2"), ("tag", "x"), ("tag", "y")]
    async with client(recorder) as http, http.get("https://api.example.com/a%2Fb/items", params=params) as response:
        await response.read()
    assert recorder.last.headers[Header.TARGET] == "https://api.example.com/a%2Fb/items?page=2&tag=x&tag=y"


async def test_key_and_host_headers_point_to_egress(recorder: Recorder) -> None:
    async with client(recorder) as http, http.get("https://api.example.com/") as response:
        await response.read()
    assert recorder.last.headers[Header.KEY] == "key"
    assert recorder.last.headers["host"] == URL(recorder.url).host_port_subcomponent


async def test_method_headers_and_body_are_preserved(recorder: Recorder) -> None:
    async with (
        client(recorder) as http,
        http.put("https://api.example.com/", json={"name": "value"}, headers={"x-custom": "1"}) as response,
    ):
        await response.read()
    assert recorder.last.method == "PUT"
    assert recorder.last.headers["x-custom"] == "1"
    assert json.loads(recorder.last.body) == {"name": "value"}


async def test_response_url_is_the_target(recorder: Recorder) -> None:
    async with client(recorder) as http, http.get("https://api.example.com/items") as response:
        await response.read()
    assert response.url == URL("https://api.example.com/items")


async def test_base_url_is_resolved_before_rewrite(recorder: Recorder) -> None:
    async with client(recorder, base_url="https://api.example.com/v1/") as http, http.get("items") as response:
        await response.read()
    assert recorder.last.headers[Header.TARGET] == "https://api.example.com/v1/items"


async def test_upstream_error_status_is_not_a_failure(recorder: Recorder) -> None:
    async with client(recorder) as http, http.get("https://api.example.com/broken") as response:
        assert response.status == 500
        assert await response.text() == "upstream broke"


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        (Failure.UNAUTHORIZED, Refused),
        (Failure.INVALID, Refused),
        (Failure.TIMEOUT, aiohttp.ServerTimeoutError),
        (Failure.UNREACHABLE, aiohttp.ClientConnectionError),
    ],
)
async def test_failure_raises_aiohttp_error(
    recorder: Recorder,
    failure: Failure,
    error: type[aiohttp.ClientError],
) -> None:
    async with client(recorder) as http:
        with pytest.raises(error, match="details"):
            await http.get(f"https://api.example.com/fail/{failure}")


def test_refused_is_a_client_error() -> None:
    assert issubclass(Refused, aiohttp.ClientError)


async def test_timeout_is_a_timeout_error(recorder: Recorder) -> None:
    async with client(recorder) as http:
        with pytest.raises(TimeoutError):
            await http.get(f"https://api.example.com/fail/{Failure.TIMEOUT}")


async def test_middleware_plugs_into_existing_session(recorder: Recorder) -> None:
    egress = Middleware(egress_url=recorder.url, egress_key="key")
    async with aiohttp.ClientSession(middlewares=(egress,)) as http, http.get("https://api.example.com/") as response:
        await response.read()
    assert recorder.last.headers[Header.TARGET] == "https://api.example.com/"


async def test_own_middlewares_see_the_target(recorder: Recorder) -> None:
    observed: list[URL] = []

    async def spy(request: aiohttp.ClientRequest, handler: aiohttp.ClientHandlerType) -> aiohttp.ClientResponse:
        observed.append(request.url)
        return await handler(request)

    async with client(recorder, middlewares=(spy,)) as http, http.get("https://api.example.com/x") as response:
        await response.read()
    assert observed == [URL("https://api.example.com/x")]


async def test_repeated_handler_calls_keep_the_target(recorder: Recorder) -> None:
    egress = Middleware(egress_url=recorder.url, egress_key="key")

    async def twice(request: aiohttp.ClientRequest, handler: aiohttp.ClientHandlerType) -> aiohttp.ClientResponse:
        first = await handler(request)
        first.release()
        return await handler(request)

    async def inner(request: aiohttp.ClientRequest, handler: aiohttp.ClientHandlerType) -> aiohttp.ClientResponse:
        return await egress(request, handler)

    async with (
        aiohttp.ClientSession(middlewares=(twice, inner)) as http,
        http.get("https://api.example.com/again") as response,
    ):
        await response.read()
    assert [seen.headers[Header.TARGET] for seen in recorder.seen] == ["https://api.example.com/again"] * 2


@pytest.mark.parametrize("factory", [Middleware, session])
def test_egress_parameters_are_keyword_only(factory: Any) -> None:
    with pytest.raises(TypeError):
        factory("http://egress.local", "key")
