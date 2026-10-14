from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from starlette.applications import Starlette
from starlette.routing import Route

from egress_proxy.server.forward import Forward
from egress_proxy.server.settings import Proxy

METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def application(proxy: Proxy) -> Starlette:
    transport = httpx.AsyncHTTPTransport(http2=True)
    forward = Forward(transport, proxy)

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncGenerator[None]:
        async with transport:
            yield

    return Starlette(
        routes=[Route("/{path:path}", forward.handle, methods=METHODS)],
        lifespan=lifespan,
    )


def create() -> Starlette:
    return application(Proxy())
