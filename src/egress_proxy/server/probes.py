import asyncio

from python_socks import ProxyConnectionError, ProxyError, ProxyTimeoutError
from python_socks.async_.asyncio.v2 import Proxy as Tunnel

from egress_proxy.server.routes import Balancer, Route, endpoint, trusted
from egress_proxy.server.upstreams import Upstream

DESTINATION = ("1.1.1.1", 443)

UNREACHABLE = (ProxyConnectionError, ProxyTimeoutError, OSError)


class Prober:
    def __init__(self, balancer: Balancer, interval: float, timeout: float) -> None:
        self.balancer = balancer
        self.interval = interval
        self.timeout = timeout
        self.context = trusted()
        self.task: asyncio.Task[None] | None = None

    async def reachable(self, upstream: Upstream) -> bool:
        try:
            stream = await Tunnel(**endpoint(upstream, self.context)).connect(*DESTINATION, timeout=self.timeout)
        except UNREACHABLE:
            return False
        except ProxyError:
            return True
        await stream.close()
        return True

    async def check(self, route: Route, upstream: Upstream) -> None:
        if await self.reachable(upstream):
            self.balancer.restore(route)
        else:
            self.balancer.rest(route)

    async def sweep(self) -> None:
        await asyncio.gather(
            *(self.check(route, route.upstream) for route in self.balancer.routes if route.upstream is not None)
        )

    async def run(self) -> None:
        while True:
            await self.sweep()
            await asyncio.sleep(self.interval)

    def start(self) -> None:
        if self.interval > 0 and any(route.upstream is not None for route in self.balancer.routes):
            self.task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self.task is None:
            return
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass
        self.task = None
