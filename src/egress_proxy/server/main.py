import argparse
import os
import socket
import sys
from collections.abc import Callable
from typing import TypeAlias

import uvicorn

from egress_proxy.server.settings import Server

FACTORY = "egress_proxy.server.application:create"

NETWORK = frozenset({socket.AF_INET, socket.AF_INET6})

Binder: TypeAlias = Callable[[uvicorn.Config], socket.socket]

UPSTREAMS = "PROXY__UPSTREAMS_FILE"

EPILOG = """\b
egress-proxy options:
  --upstreams-file PATH  File with upstream proxies, one URL per line.
                         Overrides PROXY__UPSTREAMS_FILE."""


def nodelay(listener: socket.socket) -> socket.socket:
    if listener.family in NETWORK:
        listener.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return listener


def immediate(bind: Binder) -> Binder:
    def bound(config: uvicorn.Config) -> socket.socket:
        return nodelay(bind(config))

    return bound


def options() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="egress-proxy", add_help=False, allow_abbrev=False)
    parser.add_argument("--upstreams-file", dest="upstreams")
    return parser


def separated(arguments: list[str]) -> list[str]:
    own, rest = options().parse_known_args(arguments)
    if own.upstreams is not None:
        os.environ[UPSTREAMS] = own.upstreams
    return rest


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
    rest = separated(sys.argv[1:])
    uvicorn.Config.bind_socket = immediate(uvicorn.Config.bind_socket)
    uvicorn.main.epilog = EPILOG
    uvicorn.main.main(args=[*defaults(Server()), *rest], prog_name="egress-proxy")
