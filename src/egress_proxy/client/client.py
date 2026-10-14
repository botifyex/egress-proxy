from typing import Any

import httpx

from egress_proxy.client.transport import AsyncTransport, Transport


class Client(httpx.Client):
    def __init__(
        self,
        *,
        egress_url: str,
        egress_key: str,
        egress_transport: httpx.BaseTransport | None = None,
        **options: Any,
    ) -> None:
        transport = Transport(egress_url=egress_url, egress_key=egress_key, egress_transport=egress_transport)
        super().__init__(transport=transport, **options)


class AsyncClient(httpx.AsyncClient):
    def __init__(
        self,
        *,
        egress_url: str,
        egress_key: str,
        egress_transport: httpx.AsyncBaseTransport | None = None,
        **options: Any,
    ) -> None:
        transport = AsyncTransport(egress_url=egress_url, egress_key=egress_key, egress_transport=egress_transport)
        super().__init__(transport=transport, **options)
