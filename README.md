# egress-proxy

Authenticated egress proxy server with a drop-in httpx client.

```sh
pip install "egress-proxy[client]"   # httpx integration
pip install "egress-proxy[server]"   # proxy server
```

Supports Python 3.11+, httpx 0.25.1+, Starlette 0.27+ (works alongside FastAPI 0.100+).

## Server

```env
SERVER__HOST=0.0.0.0
SERVER__PORT=8000
PROXY__KEY=change-me
PROXY__TIMEOUT=30
PROXY__CONNECT=10
```

`egress-proxy` accepts every uvicorn option; `SERVER__HOST` and `SERVER__PORT` are only defaults:

```sh
egress-proxy
egress-proxy --host 0.0.0.0 --port 9000 --workers 4 --log-level warning
```

Or run the application factory with uvicorn directly:

```sh
uvicorn egress_proxy.server.application:create --factory --host 0.0.0.0 --port 9000
```

## Client

Drop-in replacement for `httpx.AsyncClient` / `httpx.Client`:

```python
from egress_proxy.client import AsyncClient

async with AsyncClient("http://proxy:8000", "change-me", base_url="https://api.example.com") as client:
    response = await client.get("/items", params={"page": 1})
```

Subclass it like any httpx client:

```python
class Example(AsyncClient):
    def __init__(self) -> None:
        super().__init__("http://proxy:8000", "change-me", base_url="https://api.example.com")
```

Or plug the transport into an existing httpx client:

```python
import httpx
from egress_proxy.client import AsyncTransport

client = httpx.AsyncClient(transport=AsyncTransport("http://proxy:8000", "change-me"))
```

Pass `transport=` (or `inner=` for `AsyncTransport`) to customise the connection to the proxy,
for example `httpx.AsyncHTTPTransport(http2=True, retries=2)`.

Proxy failures surface as regular httpx errors: `httpx.TimeoutException`, `httpx.ConnectError`,
and `egress_proxy.client.Refused` (a `httpx.TransportError`) for a wrong key or target.

## Development

```sh
uv sync
uv run pytest --cov
uv run pytest -n auto            # parallel, pays off once the suite grows beyond a few seconds
uv run ruff check src tests
uv run egress-proxy
```

## Publishing

Every push and pull request runs CI: ruff, the test suite on Python 3.11–3.14 against both the
lowest and the latest allowed dependencies, and a wheel smoke test.

Publishing a GitHub release tagged `v<version>` (matching `version` in `pyproject.toml`) runs CI
again and uploads the package to PyPI through Trusted Publishing, so no token is stored.

One-time setup on PyPI → *Publishing* → *Add a new pending publisher*:
owner `botifyex`, repository `egress-proxy`, workflow `publish.yml`, environment `pypi`.

## License

[MIT-0](LICENSE) — use it for anything, no attribution required.
