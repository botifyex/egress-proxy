import asyncio

import httpx
import pytest

from egress_proxy.client import AsyncClient, AsyncTransport, Client, Refused
from tests.conftest import KEY
from tests.upstream import COMPRESSED


async def test_asynchronous_client_round_trip(egress: str, target: str) -> None:
    async with AsyncClient(egress, KEY, base_url=target) as client:
        response = await client.post("/echo", params={"page": 2}, json={"name": "value"})
    assert response.status_code == 200
    assert response.json()["query"] == "page=2"
    assert response.json()["body"] == '{"name":"value"}'


def test_synchronous_client_round_trip(egress: str, target: str) -> None:
    with Client(egress, KEY, base_url=target) as client:
        response = client.get("/echo", params={"page": 2})
    assert response.json()["query"] == "page=2"


async def test_plain_httpx_client_with_transport(egress: str, target: str) -> None:
    async with httpx.AsyncClient(transport=AsyncTransport(egress, KEY)) as client:
        response = await client.get(f"{target}/echo")
    assert response.status_code == 200


async def test_redirects_are_followed_through_proxy(egress: str, target: str) -> None:
    async with AsyncClient(egress, KEY, base_url=target, follow_redirects=True) as client:
        response = await client.get("/redirect")
    assert response.json()["query"] == "from=redirect"
    assert [step.status_code for step in response.history] == [307]


async def test_client_cookie_jar_works_through_proxy(egress: str, target: str) -> None:
    async with AsyncClient(egress, KEY, base_url=target) as client:
        await client.get("/cookies")
        response = await client.get("/echo")
    cookie = dict(response.json()["headers"])["cookie"]
    assert cookie in ("first=1; second=2", "second=2; first=1")


async def test_compressed_response_is_decoded(egress: str, target: str) -> None:
    async with AsyncClient(egress, KEY, base_url=target) as client:
        response = await client.get("/compressed")
    assert response.content == COMPRESSED


async def test_streaming_upload_and_download(egress: str, target: str) -> None:
    async def parts():
        for index in range(3):
            yield f"part-{index};".encode()

    async with AsyncClient(egress, KEY, base_url=target) as client:
        async with client.stream("PUT", "/echo", content=parts()) as response:
            body = await response.aread()
    assert b"part-0;part-1;part-2;" in body


async def test_concurrent_requests(egress: str, target: str) -> None:
    async with AsyncClient(egress, KEY, base_url=target) as client:
        responses = await asyncio.gather(*(client.get("/echo", params={"index": index}) for index in range(50)))
    assert sorted(response.json()["query"] for response in responses) == sorted(f"index={index}" for index in range(50))


async def test_raise_for_status_keeps_httpx_semantics(egress: str, target: str) -> None:
    async with AsyncClient(egress, KEY, base_url=target) as client:
        response = await client.get("/status/404")
    with pytest.raises(httpx.HTTPStatusError):
        response.raise_for_status()


async def test_wrong_key_raises_refused(egress: str, target: str) -> None:
    async with AsyncClient(egress, "wrong", base_url=target) as client:
        with pytest.raises(Refused, match="egress key"):
            await client.get("/echo")


def test_wrong_key_raises_refused_synchronously(egress: str, target: str) -> None:
    with Client(egress, "wrong", base_url=target) as client, pytest.raises(Refused):
        client.get("/echo")


async def test_upstream_timeout_raises_timeout(impatient: str, target: str) -> None:
    async with AsyncClient(impatient, KEY, base_url=target, timeout=10) as client:
        with pytest.raises(httpx.TimeoutException):
            await client.get("/slow")


async def test_unreachable_upstream_raises_connect_error(egress: str, unreachable: str) -> None:
    async with AsyncClient(egress, KEY) as client:
        with pytest.raises(httpx.ConnectError):
            await client.get(unreachable)


async def test_unreachable_egress_raises_connect_error(unreachable: str, target: str) -> None:
    async with AsyncClient(unreachable, KEY, base_url=target) as client:
        with pytest.raises(httpx.ConnectError):
            await client.get("/echo")


async def test_spoofed_failure_header_does_not_raise(egress: str, target: str) -> None:
    async with AsyncClient(egress, KEY, base_url=target) as client:
        response = await client.get("/spoof")
    assert response.text == "spoofed"
