import asyncio
import statistics
import sys
import time
from collections.abc import AsyncIterator, Coroutine, Generator, Iterator, Sequence
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec
from types import ModuleType
from typing import Any, TypeAlias, TypeVar

import httpx
import pytest
from pydantic import SecretStr

from egress_proxy.client.httpx import AsyncClient
from egress_proxy.server import main
from egress_proxy.server.application import Application, application
from egress_proxy.server.settings import Proxy, Server
from tests.support.commands import command
from tests.support.servers import KEY, Fleet


class Spy(MetaPathFinder):
    def __init__(self) -> None:
        self.names: list[str] = []

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        self.names.append(fullname)
        return None


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Iterator[Spy]:
    finder = Spy()
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])
    yield finder


@pytest.fixture
async def started() -> AsyncIterator[Application]:
    instance = application(Proxy(key=SecretStr(KEY), allow_local=True))
    await instance.startup()
    yield instance
    await instance.shutdown()


T = TypeVar("T")

if sys.version_info >= (3, 12):
    Routine: TypeAlias = Coroutine[Any, Any, T]
else:
    Routine: TypeAlias = Generator[Any, None, T] | Coroutine[Any, Any, T]


def counting(created: list[str]) -> None:
    loop = asyncio.get_running_loop()

    def factory(loop: asyncio.AbstractEventLoop, coroutine: Routine[T], **options: Any) -> asyncio.Task[T]:
        created.append(getattr(coroutine, "__qualname__", repr(coroutine)))
        return asyncio.Task(coroutine, loop=loop, **options)

    loop.set_task_factory(factory)


@pytest.fixture
def fresh(fleet: Fleet) -> str:
    return fleet.start(application(Proxy(key=SecretStr(KEY), allow_local=True)))


async def sequential(client: AsyncClient, count: int) -> set[str]:
    return {(await client.get("/connection")).text for _ in range(count)}


async def concurrent(client: AsyncClient, count: int) -> set[str]:
    responses = await asyncio.gather(*(client.get("/connection") for _ in range(count)))
    return {response.text for response in responses}


async def test_requests_do_not_search_for_modules(egress: str, target: str, spy: Spy) -> None:
    async with AsyncClient(egress_url=egress, egress_key=KEY, base_url=target) as client:
        await client.get("/echo")
        spy.names.clear()
        for _ in range(20):
            await client.get("/echo")
    assert spy.names == []


async def test_sequential_requests_share_one_upstream_connection(fresh: str, target: str) -> None:
    async with AsyncClient(egress_url=fresh, egress_key=KEY, base_url=target) as client:
        seen = await sequential(client, 50)
    assert len(seen) == 1


async def test_open_upstream_connections_are_reused(fresh: str, target: str) -> None:
    async with AsyncClient(egress_url=fresh, egress_key=KEY, base_url=target) as client:
        opened = await concurrent(client, 20)
        reused = await sequential(client, 50)
    assert reused <= opened


async def test_server_creates_no_tasks_per_request(started: Application, target: str) -> None:
    transport = httpx.ASGITransport(app=started)
    headers = {"x-egress-key": KEY, "x-egress-target": f"{target}/stream"}
    async with httpx.AsyncClient(transport=transport, base_url="http://egress") as client:
        await client.get("/", headers=headers)
        created: list[str] = []
        counting(created)
        for _ in range(20):
            response = await client.get("/", headers=headers)
            assert response.text == "chunk-0;chunk-1;chunk-2;chunk-3;chunk-4;"
    assert created == []


def test_command_uses_httptools_parser() -> None:
    arguments = main.defaults(Server())
    assert arguments[arguments.index("--http") + 1] == "httptools"
    __import__("httptools")


@pytest.fixture
def workers() -> Iterator[str]:
    with command("--workers", "2", "--loop", "asyncio", "--log-level", "warning") as url:
        yield url


def test_worker_processes_answer_without_delayed_acknowledgement(workers: str, target: str) -> None:
    headers = {"x-egress-key": KEY, "x-egress-target": f"{target}/connection"}
    durations: list[float] = []
    with httpx.Client(base_url=workers, headers=headers) as client:
        client.get("/")
        for _ in range(20):
            start = time.perf_counter()
            client.get("/").raise_for_status()
            durations.append(time.perf_counter() - start)
    assert statistics.median(durations) < 0.01
