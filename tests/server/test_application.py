from collections.abc import Awaitable, Callable

import pytest

from egress_proxy.server.application import Unstarted, application
from egress_proxy.server.asgi import Message
from egress_proxy.server.forward import chunks
from egress_proxy.server.settings import Proxy
from tests.support.servers import KEY


def receiver(*messages: Message) -> Callable[[], Awaitable[Message]]:
    queue = list(messages)

    async def receive() -> Message:
        return queue.pop(0)

    return receive


class Recorder:
    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def __call__(self, message: Message) -> None:
        self.messages.append(message)


async def test_lifespan_opens_and_closes_the_upstream_session() -> None:
    instance = application(Proxy(key=KEY))
    recorder = Recorder()
    await instance(
        {"type": "lifespan"}, receiver({"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}), recorder
    )
    assert [message["type"] for message in recorder.messages] == [
        "lifespan.startup.complete",
        "lifespan.shutdown.complete",
    ]
    assert instance.forward is None


async def test_requests_before_startup_are_refused() -> None:
    with pytest.raises(Unstarted):
        await application(Proxy(key=KEY))({"type": "http"}, receiver(), Recorder())


async def test_shutdown_without_startup_is_harmless() -> None:
    instance = application(Proxy(key=KEY))
    await instance.shutdown()
    assert instance.forward is None


async def test_websocket_connections_are_ignored() -> None:
    recorder = Recorder()
    await application(Proxy(key=KEY))({"type": "websocket"}, receiver(), recorder)
    assert recorder.messages == []


async def test_body_stops_when_client_disconnects() -> None:
    receive = receiver(
        {"type": "http.request", "body": b"first", "more_body": True},
        {"type": "http.disconnect"},
    )
    assert [chunk async for chunk in chunks(receive)] == [b"first"]


async def test_body_skips_empty_messages() -> None:
    receive = receiver(
        {"type": "http.request", "body": b"", "more_body": True},
        {"type": "http.request", "body": b"last", "more_body": False},
    )
    assert [chunk async for chunk in chunks(receive)] == [b"last"]
