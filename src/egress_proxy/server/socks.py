import asyncio
import ipaddress
import socket
import ssl
import struct
from typing import Any

from aiohttp.client_proto import ResponseHandler
from aiohttp_socks import ProxyConnectionError, ProxyConnector, ProxyError, ProxyTimeoutError

VERSION = 5

ANONYMOUS = 0

PASSWORD = 2

CONNECT = 1

GRANTED = 0

IPV4 = 1

DOMAIN = 3

IPV6 = 4

LENGTHS = {IPV4: 4, IPV6: 16}


class Violation(Exception):
    pass


class Handler(ResponseHandler):
    def __init__(self, loop: asyncio.AbstractEventLoop, writer: asyncio.StreamWriter) -> None:
        super().__init__(loop)
        self.writer = writer


def text(value: str) -> bytes:
    encoded = value.encode()
    return bytes([len(encoded)]) + encoded


def greeting(username: str | None, password: str | None) -> bytes:
    if username is None:
        return bytes([VERSION, 1, ANONYMOUS])
    return bytes([VERSION, 1, PASSWORD, 1]) + text(username) + text(password or "")


def address(host: str) -> bytes:
    try:
        parsed = ipaddress.ip_address(host)
    except ValueError:
        return bytes([DOMAIN]) + text(host)
    return bytes([IPV4 if parsed.version == 4 else IPV6]) + parsed.packed


def request(host: str, port: int) -> bytes:
    return bytes([VERSION, CONNECT, 0]) + address(host) + struct.pack(">H", port)


async def exactly(reader: asyncio.StreamReader, size: int) -> bytes:
    try:
        return await reader.readexactly(size)
    except asyncio.IncompleteReadError as error:
        raise Violation("proxy closed the connection during the handshake") from error


async def chosen(reader: asyncio.StreamReader, expected: int) -> None:
    version, method = await exactly(reader, 2)
    if version != VERSION or method != expected:
        raise Violation(f"proxy chose authentication method {method}")


async def authenticated(reader: asyncio.StreamReader) -> None:
    _, status = await exactly(reader, 2)
    if status != GRANTED:
        raise ProxyError("proxy rejected the credentials")


async def connected(reader: asyncio.StreamReader) -> None:
    version, reply, _, kind = await exactly(reader, 4)
    if version != VERSION:
        raise Violation(f"proxy answered with version {version}")
    if reply != GRANTED:
        raise ProxyError(f"proxy refused the tunnel with reply {reply}", error_code=reply)
    length = LENGTHS.get(kind) or (await exactly(reader, 1))[0]
    await exactly(reader, length + 2)


class Pipelined(ProxyConnector):
    def __init__(self, **options: Any) -> None:
        super().__init__(**options)
        self.pipelining = True

    async def destination(self, host: str, port: int) -> str:
        if self._rdns:
            return host
        found = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        return str(found[0][4][0])

    async def opened(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        try:
            return await asyncio.open_connection(self._proxy_host, self._proxy_port)
        except OSError as error:
            raise ProxyConnectionError(f"couldn't connect to proxy {self._proxy_host}:{self._proxy_port}") from error

    async def handshake(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, host: str, port: int) -> None:
        writer.write(greeting(self._proxy_username, self._proxy_password) + request(host, port))
        if self._proxy_username is None:
            await chosen(reader, ANONYMOUS)
        else:
            await chosen(reader, PASSWORD)
            await authenticated(reader)
        await connected(reader)

    async def tunnel(
        self, host: str, port: int, context: ssl.SSLContext | None
    ) -> tuple[asyncio.Transport, ResponseHandler]:
        reader, writer = await self.opened()
        try:
            await self.handshake(reader, writer, await self.destination(host, port), port)
            if context is not None:
                await writer.start_tls(context, server_hostname=host)
        except BaseException:
            writer.close()
            raise
        transport = writer.transport
        protocol = Handler(asyncio.get_running_loop(), writer)
        transport.set_protocol(protocol)
        protocol.connection_made(transport)
        return transport, protocol  # pyright: ignore[reportReturnType]

    async def pipelined(
        self, host: str, port: int, context: ssl.SSLContext | None, timeout: float | None
    ) -> tuple[asyncio.Transport, ResponseHandler]:
        try:
            async with asyncio.timeout(timeout):
                return await self.tunnel(host, port, context)
        except TimeoutError as error:
            raise ProxyTimeoutError(f"proxy connection timed out: {timeout}") from error

    async def _connect_via_proxy(
        self,
        host: str,
        port: int,
        ssl: ssl.SSLContext | None = None,
        timeout: float | None = None,
    ) -> tuple[asyncio.Transport, ResponseHandler]:
        if not self.pipelining:
            return await super()._connect_via_proxy(host, port, ssl, timeout)
        try:
            return await self.pipelined(host, port, ssl, timeout)
        except Violation:
            self.pipelining = False
            return await super()._connect_via_proxy(host, port, ssl, timeout)
