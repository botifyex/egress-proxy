import ipaddress
import socket
from typing import TypeAlias

from aiohttp.abc import AbstractResolver, ResolveResult
from aiohttp.resolver import DefaultResolver

Address: TypeAlias = ipaddress.IPv4Address | ipaddress.IPv6Address

NAT64 = ipaddress.ip_network("64:ff9b::/96")


class Local(OSError):
    pass


def unwrapped(address: ipaddress.IPv6Address) -> list[Address]:
    inner: list[Address | None] = [address.ipv4_mapped, address.sixtofour, *(address.teredo or ())]
    if address in NAT64:
        inner.append(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
    return [item for item in inner if item is not None]


def embedded(address: Address) -> list[Address]:
    if isinstance(address, ipaddress.IPv4Address):
        return [address]
    return [address, *unwrapped(address)]


def public(address: Address) -> bool:
    return all(item.is_global and not item.is_multicast for item in embedded(address))


def literal(host: str) -> Address | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


class Guard(AbstractResolver):
    def __init__(self, inner: AbstractResolver | None = None) -> None:
        self.inner = inner or DefaultResolver()

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[ResolveResult]:
        results = await self.inner.resolve(host, port, family)
        allowed = [result for result in results if public(ipaddress.ip_address(result["host"]))]
        if not allowed:
            raise Local(f"{host} resolves only to local addresses")
        return allowed

    async def close(self) -> None:
        await self.inner.close()
