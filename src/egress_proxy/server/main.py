import sys

import uvicorn

from egress_proxy.server.settings import Server

FACTORY = "egress_proxy.server.application:create"


def defaults(server: Server) -> list[str]:
    return [
        FACTORY,
        "--factory",
        "--host",
        server.host,
        "--port",
        str(server.port),
        "--no-server-header",
        "--no-date-header",
    ]


def run() -> None:
    uvicorn.main.main(args=[*defaults(Server()), *sys.argv[1:]], prog_name="egress-proxy")
