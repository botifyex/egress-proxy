import socket
import sys
from collections.abc import Callable
from typing import TypeAlias

import uvicorn

from egress_proxy.server.settings import Server

FACTORY = "egress_proxy.server.application:create"

NETWORK = frozenset({socket.AF_INET, socket.AF_INET6})

Binder: TypeAlias = Callable[[uvicorn.Config], socket.socket]


def nodelay(listener: socket.socket) -> socket.socket:
    if listener.family in NETWORK:
        listener.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return listener


def immediate(bind: Binder) -> Binder:
    def bound(config: uvicorn.Config) -> socket.socket:
        return nodelay(bind(config))

    return bound


def defaults(server: Server) -> list[str]:
    return [
        FACTORY,
        "--factory",
        "--http",
        "httptools",
        "--host",
        server.host,
        "--port",
        str(server.port),
        "--no-server-header",
        "--no-date-header",
        "--no-access-log",
    ]


def run() -> None:
    uvicorn.Config.bind_socket = immediate(uvicorn.Config.bind_socket)
    uvicorn.main.main(args=[*defaults(Server()), *sys.argv[1:]], prog_name="egress-proxy")
