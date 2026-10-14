import socket
import threading
import time
from dataclasses import dataclass

import uvicorn
from starlette.types import ASGIApp

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
