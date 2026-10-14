from collections.abc import Sequence
from typing import Any

import aiohttp

from egress_proxy.client.aiohttp.middleware import Middleware


def session(
    *,
    egress_url: str,
    egress_key: str,
    middlewares: Sequence[aiohttp.ClientMiddlewareType] = (),
    **options: Any,
) -> aiohttp.ClientSession:
    egress = Middleware(egress_url=egress_url, egress_key=egress_key)
    return aiohttp.ClientSession(middlewares=(*middlewares, egress), **options)
