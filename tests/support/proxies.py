import asyncio
import base64
import ipaddress
import socket
import threading
from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["socks5", "http"]

SUCCESS = b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00"

REFUSED = b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00"


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while chunk := await reader.read(65536):
            writer.write(chunk)
            await writer.drain()
    except ConnectionError:
        pass
    finally:
        writer.close()


async def address(reader: asyncio.StreamReader, kind: int) -> str:
    if kind == 1:
        return str(ipaddress.IPv4Address(await reader.readexactly(4)))
    if kind == 4:
        return str(ipaddress.IPv6Address(await reader.readexactly(16)))
    length = (await reader.readexactly(1))[0]
    return (await reader.readexactly(length)).decode()


@dataclass
class Proxy:
    kind: Kind
    user: str | None = None
    password: str | None = None
    port: int = 0
    strict: bool = False
    early: int = 0
    tunnels: int = 0
    targets: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        credentials = f"{self.user}:{self.password}@" if self.user else ""
        return f"{self.kind}://{credentials}127.0.0.1:{self.port}"

    def authorized(self, user: str, password: str) -> bool:
        return self.user is None or (user, password) == (self.user, self.password)

    async def greeted(self, reader: asyncio.StreamReader) -> bool:
        if not self.strict:
            _, count = await reader.readexactly(2)
            await reader.readexactly(count)
            return True
        first = await reader.read(65536)
        if len(first) > 2 + first[1]:
            self.early += 1
            return False
        return True

    async def socks(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> tuple[str, int] | None:
        if not await self.greeted(reader):
            return None
        if self.user is None:
            writer.write(b"\x05\x00")
        else:
            writer.write(b"\x05\x02")
            _, length = await reader.readexactly(2)
            user = (await reader.readexactly(length)).decode()
            length = (await reader.readexactly(1))[0]
            password = (await reader.readexactly(length)).decode()
            if not self.authorized(user, password):
                writer.write(b"\x01\x01")
                return None
            writer.write(b"\x01\x00")
        _, _, _, kind = await reader.readexactly(4)
        host = await address(reader, kind)
        port = int.from_bytes(await reader.readexactly(2), "big")
        return host, port

    async def connect(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> tuple[str, int] | None:
        head = (await reader.readuntil(b"\r\n\r\n")).decode("latin-1").split("\r\n")
        host, port = head[0].split()[1].rsplit(":", 1)
        given = next((line.split(" ", 2)[2] for line in head if line.lower().startswith("proxy-authorization:")), "")
        user, _, password = base64.b64decode(given or b"").decode().partition(":")
        if not self.authorized(user, password):
            writer.write(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
            return None
        return host.strip("[]"), int(port)

    def accepted(self, writer: asyncio.StreamWriter) -> None:
        writer.write(SUCCESS if self.kind == "socks5" else b"HTTP/1.1 200 Connection established\r\n\r\n")

    def failed(self, writer: asyncio.StreamWriter) -> None:
        writer.write(REFUSED if self.kind == "socks5" else b"HTTP/1.1 502 Bad Gateway\r\n\r\n")

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        negotiate = self.socks if self.kind == "socks5" else self.connect
        destination = await negotiate(reader, writer)
        if destination is None:
            await writer.drain()
            writer.close()
            return
        self.targets.append(f"{destination[0]}:{destination[1]}")
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(*destination)
        except OSError:
            self.failed(writer)
            await writer.drain()
            writer.close()
            return
        self.tunnels += 1
        self.accepted(writer)
        await writer.drain()
        await asyncio.gather(pipe(reader, upstream_writer), pipe(upstream_reader, writer))


@dataclass
class Running:
    proxy: Proxy
    loop: asyncio.AbstractEventLoop
    thread: threading.Thread
    server: asyncio.Server

    async def shutdown(self) -> None:
        self.server.close()
        tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.server.wait_closed()

    def stop(self) -> None:
        asyncio.run_coroutine_threadsafe(self.shutdown(), self.loop).result(timeout=10)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=10)
        self.loop.close()


def serve(proxy: Proxy) -> Running:
    loop = asyncio.new_event_loop()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
    listener.bind(("127.0.0.1", 0))
    proxy.port = listener.getsockname()[1]
    servers: list[asyncio.Server] = []
    ready = threading.Event()

    def run() -> None:
        asyncio.set_event_loop(loop)
        servers.append(loop.run_until_complete(asyncio.start_server(proxy.handle, sock=listener)))
        ready.set()
        loop.run_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    ready.wait(timeout=10)
    return Running(proxy, loop, thread, servers[0])
