from egress_proxy.server.asgi import Receive, Scope, Send
from egress_proxy.server.forward import Forward, session
from egress_proxy.server.settings import Proxy


class Unstarted(RuntimeError):
    pass


class Application:
    def __init__(self, proxy: Proxy) -> None:
        self.proxy = proxy
        self.forward: Forward | None = None

    async def startup(self) -> None:
        self.forward = Forward(session(self.proxy), self.proxy)

    async def shutdown(self) -> None:
        if self.forward is not None:
            await self.forward.client.close()
            self.forward = None

    async def lifespan(self, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await self.startup()
                await send({"type": "lifespan.startup.complete"})
                continue
            await self.shutdown()
            await send({"type": "lifespan.shutdown.complete"})
            return

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.lifespan(receive, send)
            return
        if scope["type"] != "http":
            return
        if self.forward is None:
            raise Unstarted("application must complete lifespan startup before serving requests")
        await self.forward.handle(scope, receive, send)


def application(proxy: Proxy) -> Application:
    return Application(proxy)


def create() -> Application:
    return application(Proxy())
