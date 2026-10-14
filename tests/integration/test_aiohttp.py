import asyncio
import json

import aiohttp
import pytest
from yarl import URL

from egress_proxy.client.aiohttp import Refused, session
from tests.support.servers import KEY
from tests.support.upstream import COMPRESSED


def client(egress: str, target: str = "", key: str = KEY) -> aiohttp.ClientSession:
    return session(egress_url=egress, egress_key=key, base_url=f"{target}/" if target else None)


async def test_round_trip(egress: str, target: str) -> None:
    async with (
        client(egress, target) as http,
        http.post("echo", params={"page": 2}, json={"name": "value"}) as response,
    ):
        echoed = await response.json()
    assert response.status == 200
    assert echoed["query"] == "page=2"
    assert json.loads(echoed["body"]) == {"name": "value"}


async def test_redirects_are_followed_through_proxy(egress: str, target: str) -> None:
    async with client(egress, target) as http, http.get("redirect") as response:
        echoed = await response.json()
    assert echoed["query"] == "from=redirect"
    assert [step.status for step in response.history] == [307]
    assert response.url == URL(f"{target}/echo?from=redirect")


async def test_cookies_are_stored_for_the_target(egress: str, target: str) -> None:
    named = target.replace("127.0.0.1", "localhost")
    jar = aiohttp.CookieJar(unsafe=True)
    async with session(egress_url=egress, egress_key=KEY, cookie_jar=jar) as http:
        async with http.get(f"{named}/cookies") as response:
            await response.read()
        async with http.get(f"{named}/echo") as response:
            echoed = await response.json()
    assert set(jar.filter_cookies(URL(named))) == {"first", "second"}
    assert set(jar.filter_cookies(URL(egress))) == set()
    assert dict(echoed["headers"])["cookie"] in ("first=1; second=2", "second=2; first=1")


async def test_compressed_response_is_decoded(egress: str, target: str) -> None:
    async with client(egress, target) as http, http.get("compressed") as response:
        assert await response.read() == COMPRESSED


async def test_streaming_upload_and_download(egress: str, target: str) -> None:
    async def parts():
        for index in range(3):
            yield f"part-{index};".encode()

    async with client(egress, target) as http, http.put("echo", data=parts()) as response:
        echoed = await response.json()
    assert echoed["body"] == "part-0;part-1;part-2;"


async def test_streamed_response_is_relayed(egress: str, target: str) -> None:
    async with client(egress, target) as http, http.get("stream") as response:
        chunks = [chunk async for chunk in response.content.iter_any()]
    assert b"".join(chunks) == b"chunk-0;chunk-1;chunk-2;chunk-3;chunk-4;"


async def test_concurrent_requests(egress: str, target: str) -> None:
    async with client(egress, target) as http:

        async def query(index: int) -> str:
            async with http.get("echo", params={"index": index}) as response:
                return (await response.json())["query"]

        queries = await asyncio.gather(*(query(index) for index in range(50)))
    assert sorted(queries) == sorted(f"index={index}" for index in range(50))


async def test_raise_for_status_keeps_aiohttp_semantics(egress: str, target: str) -> None:
    async with client(egress, target) as http, http.get("status/404") as response:
        with pytest.raises(aiohttp.ClientResponseError):
            response.raise_for_status()


async def test_wrong_key_raises_refused(egress: str, target: str) -> None:
    async with client(egress, target, key="wrong") as http:
        with pytest.raises(Refused, match="egress key"):
            await http.get("echo")


async def test_upstream_timeout_raises_timeout(impatient: str, target: str) -> None:
    async with client(impatient, target) as http:
        with pytest.raises(aiohttp.ServerTimeoutError):
            await http.get("slow")


async def test_unreachable_upstream_raises_connection_error(egress: str, unreachable: str) -> None:
    async with client(egress) as http:
        with pytest.raises(aiohttp.ClientConnectionError):
            await http.get(unreachable)


async def test_unreachable_egress_raises_connection_error(unreachable: str, target: str) -> None:
    async with client(unreachable, target) as http:
        with pytest.raises(aiohttp.ClientConnectorError):
            await http.get("echo")


async def test_spoofed_failure_header_does_not_raise(egress: str, target: str) -> None:
    async with client(egress, target) as http, http.get("spoof") as response:
        assert await response.text() == "spoofed"
