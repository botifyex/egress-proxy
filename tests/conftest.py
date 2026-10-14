import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
import uvicorn
from starlette.types import ASGIApp

from egress_proxy.server.application import application
from egress_proxy.server.settings import Proxy
from tests.upstream import upstream

KEY = "secret"


@dataclass(frozen=True)
class Running:
    url: str
    server: uvicorn.Server
    thread: threading.Thread


def bind() -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    return listener


def wait(server: uvicorn.Server) -> None:
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise TimeoutError("server did not start within 10 seconds")
        time.sleep(0.01)


def start(app: ASGIApp) -> Running:
    listener = bind()
    port = listener.getsockname()[1]
    config = uvicorn.Config(
        app,
        log_level="warning",
        server_header=False,
        date_header=False,
        timeout_graceful_shutdown=0,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    wait(server)
    return Running(f"http://127.0.0.1:{port}", server, thread)


class Fleet:
    def __init__(self) -> None:
        self.running: list[Running] = []

    def start(self, app: ASGIApp) -> str:
        running = start(app)
        self.running.append(running)
        return running.url

    def stop(self) -> None:
        for running in self.running:
            running.server.should_exit = True
        for running in self.running:
            running.thread.join(timeout=10)


@pytest.fixture(scope="session")
def fleet() -> Iterator[Fleet]:
    fleet = Fleet()
    yield fleet
    fleet.stop()


@pytest.fixture(scope="session")
def target(fleet: Fleet) -> str:
    return fleet.start(upstream)


@pytest.fixture(scope="session")
def egress(fleet: Fleet) -> str:
    return fleet.start(application(Proxy(key=KEY, timeout=10, connect=10)))


@pytest.fixture(scope="session")
def impatient(fleet: Fleet) -> str:
    return fleet.start(application(Proxy(key=KEY, timeout=0.1, connect=0.1)))


@pytest.fixture
def unreachable() -> str:
    listener = bind()
    port = listener.getsockname()[1]
    listener.close()
    return f"http://127.0.0.1:{port}"
