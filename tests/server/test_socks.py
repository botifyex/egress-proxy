import asyncio

import pytest
from aiohttp_socks import ProxyError

from egress_proxy.server.socks import Violation, address, authenticated, chosen, connected, greeting, request


def fed(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


@pytest.mark.parametrize(
    ("host", "encoded"),
    [
        ("93.184.216.34", b"\x01\x5d\xb8\xd8\x22"),
        ("::1", b"\x04" + b"\x00" * 15 + b"\x01"),
        ("example.com", b"\x03\x0bexample.com"),
    ],
)
def test_addresses_use_their_socks5_type(host: str, encoded: bytes) -> None:
    assert address(host) == encoded


def test_request_ends_with_the_port_in_network_order() -> None:
    assert request("example.com", 443) == b"\x05\x01\x00\x03\x0bexample.com\x01\xbb"


def test_anonymous_greeting_offers_only_no_authentication() -> None:
    assert greeting(None, None) == b"\x05\x01\x00"


def test_credential_greeting_offers_only_passwords_and_carries_them() -> None:
    assert greeting("user", "secret") == b"\x05\x01\x02\x01\x04user\x06secret"


def test_missing_password_is_sent_empty() -> None:
    assert greeting("user", None) == b"\x05\x01\x02\x01\x04user\x00"


@pytest.mark.parametrize(
    "reply",
    [
        b"\x05\x00\x00\x01" + b"\x00" * 6,
        b"\x05\x00\x00\x04" + b"\x00" * 18,
        b"\x05\x00\x00\x03\x07example" + b"\x00" * 2,
    ],
)
async def test_granted_replies_are_read_to_their_end(reply: bytes) -> None:
    reader = fed(reply + b"rest")
    await connected(reader)
    assert await reader.read() == b"rest"


async def test_refused_tunnel_carries_the_reply_code() -> None:
    with pytest.raises(ProxyError, match="reply 5"):
        await connected(fed(b"\x05\x05\x00\x01" + b"\x00" * 6))


@pytest.mark.parametrize(
    ("expected", "data"),
    [(2, b"\x05\xff"), (2, b"\x05\x00"), (2, b"\x04\x02"), (0, b"\x05")],
)
async def test_unexpected_method_choice_is_a_violation(expected: int, data: bytes) -> None:
    with pytest.raises(Violation):
        await chosen(fed(data), expected)


async def test_reply_from_another_protocol_is_a_violation() -> None:
    with pytest.raises(Violation):
        await connected(fed(b"HTTP/1.1 400 Bad Request\r\n"))


async def test_rejected_credentials_are_a_refusal() -> None:
    with pytest.raises(ProxyError, match="credentials"):
        await authenticated(fed(b"\x01\x01"))
