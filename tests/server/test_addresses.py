import ipaddress
import socket

import pytest
from aiohttp.abc import AbstractResolver, ResolveResult

from egress_proxy.server.addresses import Guard, Local, literal, public

LOCAL = (
    "127.0.0.1",
    "127.255.255.254",
    "10.0.0.1",
    "172.16.0.1",
    "172.31.255.254",
    "192.168.1.1",
    "169.254.169.254",
    "100.64.0.1",
    "198.18.0.1",
    "0.0.0.0",
    "255.255.255.255",
    "224.0.0.1",
    "239.255.255.250",
    "::1",
    "::",
    "fe80::1",
    "fc00::1",
    "fd12:3456::1",
    "ff02::1",
    "::ffff:127.0.0.1",
    "::ffff:10.0.0.1",
    "::ffff:169.254.169.254",
    "2002:7f00:1::1",
    "2001:0:4136:e378:8000:63bf:f5ff:fffe",
    "64:ff9b::7f00:1",
    "64:ff9b::a9fe:a9fe",
)

PUBLIC = ("8.8.8.8", "1.1.1.1", "93.184.215.14", "2606:4700:4700::1111", "::ffff:8.8.8.8", "64:ff9b::808:808")


@pytest.mark.parametrize("text", LOCAL)
def test_local_addresses_are_not_public(text: str) -> None:
    assert not public(ipaddress.ip_address(text))


@pytest.mark.parametrize("text", PUBLIC)
def test_global_addresses_are_public(text: str) -> None:
    assert public(ipaddress.ip_address(text))


@pytest.mark.parametrize(("host", "expected"), [("127.0.0.1", "127.0.0.1"), ("[::1]", "::1"), ("::1", "::1")])
def test_literal_addresses_are_recognised(host: str, expected: str) -> None:
    assert literal(host) == ipaddress.ip_address(expected)


@pytest.mark.parametrize("host", ["localhost", "example.com", "127.0.0.1.nip.io", ""])
def test_host_names_are_not_literal(host: str) -> None:
    assert literal(host) is None


class Fixed(AbstractResolver):
    def __init__(self, *addresses: str) -> None:
        self.addresses = addresses
        self.closed = False

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[ResolveResult]:
        return [
            ResolveResult(hostname=host, host=address, port=port, family=family, proto=0, flags=0)
            for address in self.addresses
        ]

    async def close(self) -> None:
        self.closed = True


async def test_guard_keeps_only_public_addresses() -> None:
    guard = Guard(Fixed("10.0.0.5", "93.184.215.14", "127.0.0.1"))
    results = await guard.resolve("rebinding.example", 80)
    assert [result["host"] for result in results] == ["93.184.215.14"]


async def test_guard_refuses_names_with_only_local_addresses() -> None:
    guard = Guard(Fixed("127.0.0.1", "::1"))
    with pytest.raises(Local, match="localhost resolves only to local addresses"):
        await guard.resolve("localhost", 80)


def test_local_is_an_os_error() -> None:
    assert issubclass(Local, OSError)


async def test_guard_closes_its_resolver() -> None:
    inner = Fixed()
    await Guard(inner).close()
    assert inner.closed
