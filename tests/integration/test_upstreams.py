import socket
import time
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TypeAlias, TypedDict, Unpack

import httpx
import pytest
from pydantic import SecretStr

from egress_proxy.protocol import Failure, Header
from egress_proxy.server import probes
from egress_proxy.server.application import Application, application
from egress_proxy.server.settings import Proxy
from tests.support.commands import Unstarted, command
from tests.support.proxies import Kind, Running, serve
from tests.support.proxies import Proxy as Tunnel
from tests.support.servers import KEY, Fleet, bind

Start: TypeAlias = Callable[..., Tunnel]


@pytest.fixture
def tunnels() -> Iterator[Start]:
    running: list[Running] = []

    def start(
        kind: Kind = "socks5",
        user: str | None = None,
        password: str | None = None,
        strict: bool = False,
    ) -> Tunnel:
        running.append(serve(Tunnel(kind, user, password, strict=strict)))
        return running[-1].proxy

    yield start
    for item in running:
        item.stop()


@pytest.fixture(scope="module")
def local() -> Iterator[Fleet]:
    fleet = Fleet()
    yield fleet
    fleet.stop()


@pytest.fixture
def dead(unreachable: str) -> str:
    return unreachable.replace("http://", "socks5://")


@pytest.fixture
def silent() -> Iterator[str]:
    listener = bind()
    listener.listen()
    yield f"socks5://127.0.0.1:{listener.getsockname()[1]}"
    listener.close()


@pytest.fixture
def probed(monkeypatch: pytest.MonkeyPatch, target: str) -> None:
    host, port = target.removeprefix("http://").split(":")
    monkeypatch.setattr(probes, "DESTINATION", (host, int(port)))


class Tuning(TypedDict, total=False):
    cooldown: float
    attempts: int
    timeout: float
    connect: float
    probe: float


class Egress:
    def __init__(self, fleet: Fleet, upstreams: list[str], local: bool = True, **options: Unpack[Tuning]) -> None:
        options.setdefault("probe", 0)
        proxy = Proxy(key=SecretStr(KEY), upstreams=upstreams, allow_local=local, **options)
        self.application: Application = application(proxy)
        self.url = fleet.start(self.application)

    def get(self, target: str) -> httpx.Response:
        headers: dict[str, str] = {Header.KEY: KEY, Header.TARGET: target}
        return httpx.get(self.url, headers=headers, timeout=10)

    def post(self, target: str, content: bytes) -> httpx.Response:
        headers: dict[str, str] = {Header.KEY: KEY, Header.TARGET: target}
        return httpx.post(self.url, headers=headers, content=content, timeout=10)

    def resting(self) -> list[str]:
        forward = self.application.forward
        assert forward is not None
        return [route.name for route in forward.balancer.routes if route.resting > forward.balancer.clock()]

    def settled(self, expected: list[str]) -> list[str]:
        deadline = time.monotonic() + 5
        while self.resting() != expected and time.monotonic() < deadline:
            time.sleep(0.01)
        return self.resting()


@pytest.mark.parametrize("kind", ["socks5", "http"])
def test_requests_go_through_the_upstream_proxy(local: Fleet, target: str, tunnels: Start, kind: Kind) -> None:
    proxy = tunnels(kind)
    response = Egress(local, [proxy.url]).get(f"{target}/echo?via={kind}")
    assert response.status_code == 200
    assert response.json()["query"] == f"via={kind}"
    assert proxy.tunnels == 1


@pytest.mark.parametrize("kind", ["socks5", "http"])
def test_proxy_credentials_are_used(local: Fleet, target: str, tunnels: Start, kind: Kind) -> None:
    proxy = tunnels(kind, "user", "secret")
    assert Egress(local, [proxy.url]).get(f"{target}/echo").status_code == 200


def test_socks5h_lets_the_proxy_resolve_host_names(local: Fleet, target: str, tunnels: Start) -> None:
    proxy = tunnels("socks5")
    named = target.replace("127.0.0.1", "localhost")
    Egress(local, [proxy.url.replace("socks5://", "socks5h://")]).get(f"{named}/echo")
    assert proxy.targets[-1].startswith("localhost:")


def test_socks5_resolves_host_names_on_the_egress_server(local: Fleet, target: str, tunnels: Start) -> None:
    proxy = tunnels("socks5")
    named = target.replace("127.0.0.1", "localhost")
    Egress(local, [proxy.url]).get(f"{named}/echo")
    assert not proxy.targets[-1].startswith("localhost:")


def test_requests_are_spread_evenly_across_upstreams(local: Fleet, target: str, tunnels: Start) -> None:
    proxies = [tunnels("socks5"), tunnels("http"), tunnels("socks5")]
    egress = Egress(local, [proxy.url for proxy in proxies])
    ports = Counter(egress.get(f"{target}/connection").text for _ in range(30))
    assert sorted(ports.values()) == [10, 10, 10]
    assert [proxy.tunnels for proxy in proxies] == [1, 1, 1]


def test_unreachable_upstream_is_skipped_and_rested(local: Fleet, target: str, tunnels: Start, dead: str) -> None:
    alive = tunnels("socks5")
    egress = Egress(local, [dead, alive.url])
    statuses = [egress.get(f"{target}/echo").status_code for _ in range(6)]
    assert statuses == [200] * 6
    assert egress.resting() == [dead]


def test_request_body_survives_a_failover(local: Fleet, target: str, tunnels: Start, dead: str) -> None:
    alive = tunnels("http")
    payload = bytes(range(256)) * 400
    response = Egress(local, [dead, alive.url]).post(f"{target}/echo", payload)
    assert response.json()["length"] == len(payload)


def test_rested_upstream_returns_after_cooldown(local: Fleet, target: str, tunnels: Start, dead: str) -> None:
    alive = tunnels("socks5")
    egress = Egress(local, [dead, alive.url], cooldown=0)
    egress.get(f"{target}/echo")
    assert egress.resting() == []


def test_all_upstreams_unreachable_is_reported(local: Fleet, target: str, dead: str) -> None:
    egress = Egress(local, [dead, dead.replace("socks5://", "http://")])
    response = egress.get(f"{target}/echo")
    assert response.status_code == 502
    assert response.headers[Header.FAILURE] == Failure.UNREACHABLE
    assert "is unreachable" in response.text
    assert len(egress.resting()) == 2


def test_attempts_limit_the_failover(local: Fleet, target: str, tunnels: Start, dead: str) -> None:
    alive = tunnels("socks5")
    egress = Egress(local, [dead, dead, alive.url], attempts=2)
    response = egress.get(f"{target}/echo")
    assert response.status_code == 502
    assert alive.tunnels == 0


def test_wrong_proxy_credentials_fail_over_without_resting(local: Fleet, target: str, tunnels: Start) -> None:
    locked = tunnels("socks5", "user", "secret")
    alive = tunnels("http")
    egress = Egress(local, [locked.url.replace("secret", "wrong"), alive.url])
    assert egress.get(f"{target}/echo").status_code == 200
    assert egress.resting() == []


def test_target_unreachable_through_proxies_rests_nothing(
    local: Fleet,
    tunnels: Start,
    unreachable: str,
) -> None:
    proxies = [tunnels("socks5"), tunnels("http")]
    egress = Egress(local, [proxy.url for proxy in proxies])
    response = egress.get(f"{unreachable}/")
    assert response.status_code == 502
    assert "through upstream proxy" in response.text
    assert egress.resting() == []


def test_upstream_errors_do_not_leak_proxy_passwords(local: Fleet, target: str, unreachable: str) -> None:
    egress = Egress(local, [unreachable.replace("http://", "socks5://user:secret@")])
    response = egress.get(f"{target}/echo")
    assert response.status_code == 502
    assert "secret" not in response.text


def test_timeout_after_tunnel_is_not_retried(local: Fleet, target: str, tunnels: Start) -> None:
    proxies = [tunnels("socks5"), tunnels("socks5")]
    egress = Egress(local, [proxy.url for proxy in proxies], timeout=0.1)
    response = egress.get(f"{target}/slow")
    assert response.status_code == 504
    assert sum(proxy.tunnels for proxy in proxies) == 1


@pytest.mark.parametrize("credentials", [(None, None), ("user", "secret")])
def test_socks5_handshake_is_sent_in_one_write(
    local: Fleet,
    target: str,
    tunnels: Start,
    credentials: tuple[str | None, str | None],
) -> None:
    proxy = tunnels("socks5", *credentials, strict=True)
    response = Egress(local, [proxy.url]).get(f"{target}/echo")
    assert response.status_code == 200
    assert proxy.early == 1


def test_proxy_refusing_early_data_gets_stepwise_handshakes_from_then_on(
    local: Fleet,
    target: str,
    tunnels: Start,
) -> None:
    proxy = tunnels("socks5", "user", "secret", strict=True)
    egress = Egress(local, [proxy.url])
    named = target.replace("127.0.0.1", "localhost")
    statuses = [egress.get(f"{origin}/echo").status_code for origin in (target, named)]
    assert statuses == [200, 200]
    assert proxy.tunnels == 2
    assert proxy.early == 1


def test_silent_upstream_is_rested_once_the_connect_timeout_passes(
    local: Fleet,
    target: str,
    tunnels: Start,
    silent: str,
) -> None:
    alive = tunnels("socks5")
    egress = Egress(local, [silent, alive.url], connect=0.2)
    assert egress.get(f"{target}/echo").status_code == 200
    assert egress.resting() == [silent]


def test_failed_tls_through_a_tunnel_is_reported_as_unreachable(local: Fleet, target: str, tunnels: Start) -> None:
    proxy = tunnels("socks5")
    response = Egress(local, [proxy.url]).get(f"{target.replace('http://', 'https://')}/echo")
    assert response.status_code == 502
    assert response.headers[Header.FAILURE] == Failure.UNREACHABLE


@pytest.mark.usefixtures("probed")
def test_probe_rests_a_silent_upstream_before_any_request(local: Fleet, tunnels: Start, silent: str) -> None:
    alive = tunnels("socks5")
    egress = Egress(local, [silent, alive.url], connect=0.5, probe=0.05)
    assert egress.settled([silent]) == [silent]


@pytest.mark.usefixtures("probed")
def test_requests_do_not_wait_for_a_probed_silent_upstream(
    local: Fleet,
    target: str,
    tunnels: Start,
    silent: str,
) -> None:
    alive = tunnels("socks5")
    egress = Egress(local, [silent, alive.url], connect=2, probe=0.05)
    egress.settled([silent])
    started = time.monotonic()
    statuses = [egress.get(f"{target}/echo").status_code for _ in range(4)]
    assert statuses == [200] * 4
    assert time.monotonic() - started < 1


@pytest.mark.usefixtures("probed")
def test_probe_restores_a_rested_upstream_that_answers(local: Fleet, tunnels: Start) -> None:
    alive = tunnels("socks5")
    egress = Egress(local, [alive.url], cooldown=60, probe=0.05)
    forward = egress.application.forward
    assert forward is not None
    forward.balancer.rest(forward.balancer.routes[0])
    assert egress.settled([]) == []


@pytest.mark.usefixtures("probed")
def test_probe_keeps_an_upstream_that_refuses_the_tunnel(local: Fleet, tunnels: Start) -> None:
    locked = tunnels("socks5", "user", "secret")
    egress = Egress(local, [locked.url.replace("secret", "wrong")], probe=0.05)
    time.sleep(0.3)
    assert egress.resting() == []


def test_probe_is_off_at_zero(local: Fleet, silent: str) -> None:
    egress = Egress(local, [silent], probe=0)
    assert egress.application.prober is not None
    assert egress.application.prober.task is None


def test_command_option_routes_workers_through_the_file(target: str, tunnels: Start, tmp_path: Path) -> None:
    proxy = tunnels("socks5")
    path = tmp_path / "proxies.txt"
    path.write_text(f"# test proxy\n{proxy.url}\n")
    with command("--upstreams-file", str(path), "--workers", "2") as egress:
        responses = [httpx.get(egress, headers={Header.KEY: KEY, Header.TARGET: f"{target}/echo"}) for _ in range(6)]
    assert [response.status_code for response in responses] == [200] * 6
    assert proxy.tunnels >= 1


def test_command_helper_stops_a_server_that_never_listens(tmp_path: Path) -> None:
    socket_path = tmp_path / "egress.sock"
    with pytest.raises(Unstarted, match="did not listen"):
        with command("--uds", str(socket_path), timeout=2):
            pass
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe, pytest.raises(OSError):
        probe.connect(str(socket_path))


def test_command_helper_reports_a_server_that_exits(tmp_path: Path) -> None:
    with pytest.raises(Unstarted, match="exited with code 1"):
        with command("--upstreams-file", str(tmp_path / "missing.txt")):
            pass


def test_local_address_is_refused_through_upstream_proxies(local: Fleet, target: str, tunnels: Start) -> None:
    proxy = tunnels("socks5")
    response = Egress(local, [proxy.url], local=False).get(f"{target}/echo")
    assert response.status_code == 400
    assert "points to a local address" in response.text
    assert proxy.tunnels == 0


def test_host_names_are_resolved_by_the_upstream_proxy(local: Fleet, target: str, tunnels: Start) -> None:
    proxy = tunnels("socks5")
    named = target.replace("127.0.0.1", "localhost")
    response = Egress(local, [proxy.url.replace("socks5://", "socks5h://")], local=False).get(f"{named}/echo")
    assert response.status_code == 200
    assert proxy.targets[-1].startswith("localhost:")
