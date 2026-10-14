import logging
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass

import aiohttp
import certifi
from aiohttp_socks import ProxyConnector

from egress_proxy.server.settings import Proxy
from egress_proxy.server.upstreams import Upstream, configured

AUTOMATIC = ("User-Agent", "Accept", "Accept-Encoding", "Content-Type")

DIRECT = "direct"

log = logging.getLogger("egress_proxy")


def trusted() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())


def direct(context: ssl.SSLContext) -> aiohttp.BaseConnector:
    return aiohttp.TCPConnector(limit=0, ttl_dns_cache=300, ssl=context)


def tunnel(upstream: Upstream, context: ssl.SSLContext) -> aiohttp.BaseConnector:
    return ProxyConnector(
        host=upstream.url.host or "",
        port=upstream.url.port or 0,
        proxy_type=upstream.scheme.kind,
        username=upstream.url.user,
        password=upstream.url.password,
        rdns=upstream.scheme.remote,
        proxy_ssl=context if upstream.scheme.secure else None,
        limit=0,
        ttl_dns_cache=300,
        ssl=context,
    )


def client(proxy: Proxy, connector: aiohttp.BaseConnector) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        connector=connector,
        cookie_jar=aiohttp.DummyCookieJar(),
        auto_decompress=False,
        skip_auto_headers=AUTOMATIC,
        timeout=aiohttp.ClientTimeout(total=None, sock_connect=proxy.connect, sock_read=proxy.timeout),
    )


@dataclass
class Route:
    name: str
    client: aiohttp.ClientSession
    resting: float = 0.0


class Balancer:
    def __init__(
        self,
        routes: list[Route],
        cooldown: float,
        attempts: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.routes = routes
        self.cooldown = cooldown
        self.attempts = attempts
        self.clock = clock
        self.position = 0

    def rotated(self) -> list[Route]:
        start = self.position % len(self.routes)
        self.position += 1
        return [*self.routes[start:], *self.routes[:start]]

    def ranked(self, ordered: list[Route], now: float) -> list[Route]:
        ready = [route for route in ordered if route.resting <= now]
        resting = sorted((route for route in ordered if route.resting > now), key=lambda route: route.resting)
        return [*ready, *resting]

    def candidates(self) -> list[Route]:
        if len(self.routes) == 1:
            return self.routes
        ordered = self.rotated()
        now = self.clock()
        if all(route.resting <= now for route in ordered):
            return ordered[: self.attempts]
        return self.ranked(ordered, now)[: self.attempts]

    def rest(self, route: Route) -> None:
        route.resting = self.clock() + self.cooldown
        log.warning("upstream proxy %s is unreachable, resting it for %g seconds", route.name, self.cooldown)

    async def close(self) -> None:
        for route in self.routes:
            await route.client.close()


def routes(proxy: Proxy, upstreams: list[Upstream]) -> list[Route]:
    context = trusted()
    if not upstreams:
        return [Route(DIRECT, client(proxy, direct(context)))]
    return [Route(upstream.name, client(proxy, tunnel(upstream, context))) for upstream in upstreams]


def balancer(proxy: Proxy, upstreams: list[Upstream] | None = None) -> Balancer:
    chosen = configured(proxy) if upstreams is None else upstreams
    return Balancer(routes(proxy, chosen), proxy.cooldown, proxy.attempts)
