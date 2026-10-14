from egress_proxy.server.asgi import Receive, Scope, Send

SMALL = b"x" * 100

LARGE = b"y" * 1_048_576


async def lifespan(receive: Receive, send: Send) -> None:
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
            continue
        await send({"type": "lifespan.shutdown.complete"})
        return


async def drain(receive: Receive) -> None:
    while (await receive()).get("more_body", False):
        pass


async def app(scope: Scope, receive: Receive, send: Send) -> None:
    if scope["type"] == "lifespan":
        await lifespan(receive, send)
        return
    await drain(receive)
    body = LARGE if scope["path"] == "/large" else SMALL
    headers = [(b"content-length", str(len(body)).encode())]
    await send({"type": "http.response.start", "status": 200, "headers": headers})
    await send({"type": "http.response.body", "body": body})
