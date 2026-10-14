from typing import Any

import httpx

from egress_proxy.client.transport import AsyncTransport, Transport


class Client(httpx.Client):
    def __init__(
        self,
        egress: str,
        key: str,
        transport: httpx.BaseTransport | None = None,
        **options: Any,
    ) -> None:
        super().__init__(transport=Transport(egress, key, transport), **options)


class AsyncClient(httpx.AsyncClient):
    def __init__(
        self,
        egress: str,
        key: str,
        transport: httpx.AsyncBaseTransport | None = None,
        **options: Any,
    ) -> None:
        super().__init__(transport=AsyncTransport(egress, key, transport), **options)
