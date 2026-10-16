from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import cast

import aiohttp
import pytest
from aiohttp_socks import ProxyConnector, ProxyError

from egress_proxy.server.forward import Forward
from egress_proxy.server.rejection import Rejection
from egress_proxy.server.routes import DIRECT, Balancer, Route, balancer, shuffled
from egress_proxy.server.settings import Proxy
from egress_proxy.server.upstreams import Upstream, parse


@dataclass
class Clock:
    now: float = 100.0

    def __call__(self) -> float:
        return self.now


class Closable:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def routes(*names: str) -> list[Route]:
    return [Route(name, cast(aiohttp.ClientSession, Closable())) for name in names]


def names(chosen: list[Route]) -> list[str]:
    return [route.name for route in chosen]


def test_requests_rotate_through_routes() -> None:
    subject = Balancer(routes("a", "b", "c"), cooldown=30, attempts=1)
    assert [names(subject.candidates()) for _ in range(4)] == [["a"], ["b"], ["c"], ["a"]]


def test_candidates_continue_after_the_first_choice() -> None:
    subject = Balancer(routes("a", "b", "c"), cooldown=30, attempts=3)
    subject.candidates()
    assert names(subject.candidates()) == ["b", "c", "a"]


def test_attempts_limit_the_candidates() -> None:
    subject = Balancer(routes("a", "b", "c", "d"), cooldown=30, attempts=2)
    assert names(subject.candidates()) == ["a", "b"]


def test_resting_route_is_skipped_until_cooldown_ends() -> None:
    clock = Clock()
    pool = routes("a", "b")
    subject = Balancer(pool, cooldown=30, attempts=1, clock=clock)
    subject.rest(pool[0])
    assert [names(subject.candidates()) for _ in range(3)] == [["b"], ["b"], ["b"]]
    clock.now += 30
    assert names(subject.candidates()) == ["b"]
    assert names(subject.candidates()) == ["a"]


def test_resting_routes_are_tried_last_soonest_first() -> None:
    clock = Clock()
    pool = routes("a", "b", "c")
    subject = Balancer(pool, cooldown=30, attempts=3, clock=clock)
    subject.rest(pool[1])
    clock.now += 1
    subject.rest(pool[0])
    assert names(subject.candidates()) == ["c", "b", "a"]


def test_resting_logs_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    pool = routes("socks5://a.example.net:1080")
    Balancer(pool, cooldown=30, attempts=1).rest(pool[0])
    assert "upstream proxy socks5://a.example.net:1080 is unreachable, resting it for 30 seconds" in caplog.text


async def test_close_closes_every_route() -> None:
    pool = routes("a", "b")
    await Balancer(pool, cooldown=30, attempts=1).close()
    assert [cast(Closable, route.client).closed for route in pool] == [True, True]


async def test_no_upstreams_gives_one_direct_route() -> None:
    subject = balancer(Proxy(key="key"), [])
    assert names(subject.routes) == [DIRECT]
    assert not isinstance(subject.routes[0].client.connector, ProxyConnector)
    await subject.close()


async def test_each_upstream_gets_its_own_tunnelled_session() -> None:
    upstreams = [parse("socks5h://user:secret@a.example.net:1080", "a"), parse("http://b.example.net:3128", "b")]
    subject = balancer(Proxy(key="key", cooldown=5, attempts=2), upstreams)
    assert names(subject.routes) == ["socks5h://a.example.net:1080", "http://b.example.net:3128"]
    assert all(isinstance(route.client.connector, ProxyConnector) for route in subject.routes)
    assert (subject.cooldown, subject.attempts) == (5, 2)
    await subject.close()


class Consuming:
    def __init__(self) -> None:
        self.calls = 0

    async def request(self, *arguments: object, data: AsyncIterator[bytes], **options: object) -> None:
        self.calls += 1
        async for _ in data:
            pass
        raise ProxyError("refused after reading the body")

    async def close(self) -> None:
        pass


async def test_started_body_is_never_replayed() -> None:
    clients = [Consuming(), Consuming()]
    pool = [Route(name, cast(aiohttp.ClientSession, item)) for name, item in zip("ab", clients, strict=True)]
    forward = Forward(Balancer(pool, cooldown=30, attempts=2), Proxy(key="key"))
    messages = [{"type": "http.request", "body": b"payload", "more_body": False}]

    async def receive() -> dict[str, object]:
        return messages.pop(0)

    scope = {
        "method": "POST",
        "headers": [(b"x-egress-key", b"key"), (b"x-egress-target", b"http://example.net/"), (b"content-length", b"7")],
    }
    with pytest.raises(Rejection, match="through upstream proxy a"):
        await forward.request(scope, receive)
    assert [item.calls for item in clients] == [1, 0]


def upstreams(*hosts: str) -> list[Upstream]:
    return [parse(f"socks5h://{host}.example.net:1080", host) for host in hosts]


def hosts(chosen: list[Upstream]) -> list[str]:
    return [str(upstream.url.host).split(".")[0] for upstream in chosen]


def route_hosts(subject: Balancer) -> list[str]:
    return [name.removeprefix("socks5h://").split(".")[0] for name in names(subject.routes)]


class Reversing:
    def shuffle(self, items: list[Upstream]) -> None:
        items.reverse()


async def test_upstreams_keep_their_order_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("egress_proxy.server.routes.secrets.SystemRandom", Reversing)
    subject = balancer(Proxy(key="key"), upstreams("a", "b", "c"))
    assert route_hosts(subject) == ["a", "b", "c"]
    await subject.close()


async def test_shuffle_uses_the_secure_generator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("egress_proxy.server.routes.secrets.SystemRandom", Reversing)
    subject = balancer(Proxy(key="key", shuffle=True), upstreams("a", "b", "c"))
    assert route_hosts(subject) == ["c", "b", "a"]
    await subject.close()


def test_shuffled_keeps_every_upstream_and_the_original_list() -> None:
    original = upstreams("a", "b", "c", "d")
    mixed = shuffled(original)
    assert sorted(hosts(mixed)) == ["a", "b", "c", "d"]
    assert hosts(original) == ["a", "b", "c", "d"]


def test_shuffled_can_start_with_any_upstream() -> None:
    original = upstreams("a", "b", "c")
    assert {hosts(shuffled(original))[0] for _ in range(300)} == {"a", "b", "c"}
