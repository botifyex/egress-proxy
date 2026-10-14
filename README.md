# egress-proxy

Send the HTTP requests of any httpx-based Python project through your own server: they leave from
the server's IP, with identifying headers removed.

## Quick start

**1. Start the server** on the machine whose IP the requests should come from:

```sh
pip install "egress-proxy[server]"
python -c "import secrets; print('PROXY__KEY=' + secrets.token_urlsafe(32))" > .env
egress-proxy --host 0.0.0.0 --port 8000
```

The generated key is in `.env`; the client needs it.

**2. Use it in your project:**

```sh
pip install "egress-proxy[client]"
```

```python
import asyncio

from egress_proxy.client import AsyncClient


async def main() -> None:
    async with AsyncClient(egress_url="http://SERVER_IP:8000", egress_key="PROXY_KEY") as client:
        response = await client.get("https://api.ipify.org?format=json")
        print(response.json())


asyncio.run(main())
```

It prints the server's IP. `AsyncClient` is a regular `httpx.AsyncClient`: the `egress_*`
parameters configure the proxy, everything else is passed to httpx unchanged.

## Add to an existing project

**Replace the client class.** `Client` and `AsyncClient` accept every `httpx.Client` /
`httpx.AsyncClient` option:

```python
from egress_proxy.client import AsyncClient, Client

client = AsyncClient(
    egress_url="http://SERVER_IP:8000",
    egress_key="PROXY_KEY",
    base_url="https://api.example.com",
    timeout=10,
)
```

**Keep your own httpx client** and only swap its transport (`Transport` for `httpx.Client`):

```python
import httpx
from egress_proxy.client import AsyncTransport

client = httpx.AsyncClient(
    transport=AsyncTransport(egress_url="http://SERVER_IP:8000", egress_key="PROXY_KEY"),
)
```

**Subclass it** like any httpx client:

```python
class Api(AsyncClient):
    def __init__(self) -> None:
        super().__init__(
            egress_url="http://SERVER_IP:8000",
            egress_key="PROXY_KEY",
            base_url="https://api.example.com",
        )
```

To tune the connection to the proxy server, pass `egress_transport`, for example
`egress_transport=httpx.AsyncHTTPTransport(http2=True, retries=2)`.

Errors are standard httpx exceptions, so existing `except` blocks keep working:

| Situation | Raised |
|---|---|
| Wrong key or invalid target URL | `egress_proxy.client.Refused` (a `httpx.TransportError`) |
| Target did not answer in time | `httpx.TimeoutException` |
| Target or proxy server unreachable | `httpx.ConnectError` |

Responses with error statuses (404, 500, …) come back as normal responses, exactly as without the proxy.

## Server configuration

Settings are read from `.env` in the working directory or from environment variables, which take
precedence. Template: [`.env.example`](https://github.com/botifyex/egress-proxy/blob/master/.env.example).

| Variable | Default | Meaning |
|---|---|---|
| `PROXY__KEY` | required | Key every client must send |
| `PROXY__TIMEOUT` | `30` | Seconds to wait for the target |
| `PROXY__CONNECT` | `10` | Seconds to connect to the target |
| `SERVER__HOST` | `127.0.0.1` | Address to listen on |
| `SERVER__PORT` | `8000` | Port to listen on |

The client's own timeout still applies (httpx defaults to 5 seconds), so raise it as well for slow
targets: `AsyncClient(..., timeout=60)`.

`egress-proxy` accepts every [uvicorn option](https://uvicorn.dev/settings/), and command-line
values override `.env`:

```sh
egress-proxy --host 0.0.0.0 --port 8000 --workers 4 --log-level warning
```

The access log is off by default, since every line would read `GET / 200`; enable it with
`--access-log`.

**Use HTTPS over the internet.** The key travels in a request header, so encrypt the connection,
either directly or behind a TLS-terminating reverse proxy, and use `https://` in the client:

```sh
egress-proxy --host 0.0.0.0 --port 443 --ssl-keyfile key.pem --ssl-certfile cert.pem
```

## How it works

The client sends each request to the server with the target URL and the key in headers. The
server checks the key, removes headers that reveal the original client (`X-Forwarded-*`,
`Forwarded`, `Via`, `X-Real-IP`, `CF-Connecting-IP`, `True-Client-IP` and similar) and hop-by-hop
headers, forwards the request over a pooled keep-alive connection and streams the response back
unchanged. Redirects and cookies are
handled by your client, never stored on the server.

## Requirements

Python 3.11+. The client needs httpx 0.25.1+; the server runs on uvicorn and aiohttp and handles
about 13,000 requests per second on a single core.

## License

[MIT-0](https://github.com/botifyex/egress-proxy/blob/master/LICENSE): use it for anything, no
attribution required. Contributing and releases:
[CONTRIBUTING.md](https://github.com/botifyex/egress-proxy/blob/master/CONTRIBUTING.md).
