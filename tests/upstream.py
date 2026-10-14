import asyncio
import gzip
import hashlib
import json
from collections.abc import AsyncIterator

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Route

from egress_proxy.protocol import Failure, Header

METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]

COMPRESSED = b"compressed " * 1000


async def echo(request: Request) -> Response:
    body = await request.body()
    return JSONResponse(
        {
            "method": request.method,
            "path": request.scope["raw_path"].decode(),
            "query": request.scope["query_string"].decode(),
            "headers": [[name.decode(), value.decode()] for name, value in request.headers.raw],
            "length": len(body),
            "digest": hashlib.sha256(body).hexdigest(),
            "body": body.decode(errors="replace")[:1000],
        }
    )


async def compressed(_: Request) -> Response:
    return Response(gzip.compress(COMPRESSED), headers={"content-encoding": "gzip"})


async def redirect(_: Request) -> Response:
    return RedirectResponse("/echo?from=redirect", status_code=307)


EMPTY = frozenset({204, 304})


async def status(request: Request) -> Response:
    code = int(request.path_params["code"])
    content = None if code in EMPTY else json.dumps({"status": "custom"})
    return Response(content, status_code=code)


async def cookies(_: Request) -> Response:
    response = Response("cookies")
    response.raw_headers.append((b"set-cookie", b"first=1; Path=/"))
    response.raw_headers.append((b"set-cookie", b"second=2; Path=/"))
    return response


async def slow(_: Request) -> Response:
    await asyncio.sleep(3)
    return Response("late")


async def spoof(_: Request) -> Response:
    return Response("spoofed", headers={Header.FAILURE: Failure.UNAUTHORIZED})


async def chunks() -> AsyncIterator[bytes]:
    for index in range(5):
        yield f"chunk-{index};".encode()


async def stream(_: Request) -> Response:
    return StreamingResponse(chunks())


upstream = Starlette(
    routes=[
        Route("/echo", echo, methods=METHODS),
        Route("/echo/{rest:path}", echo, methods=METHODS),
        Route("/compressed", compressed),
        Route("/redirect", redirect),
        Route("/status/{code:int}", status, methods=METHODS),
        Route("/cookies", cookies),
        Route("/slow", slow),
        Route("/spoof", spoof),
        Route("/stream", stream),
    ]
)
