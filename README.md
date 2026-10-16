# egress-proxy

[![PyPI](https://img.shields.io/pypi/v/egress-proxy)](https://pypi.org/project/egress-proxy/)
[![Python](https://img.shields.io/pypi/pyversions/egress-proxy)](https://pypi.org/project/egress-proxy/)
[![CI](https://github.com/botifyex/egress-proxy/actions/workflows/ci.yml/badge.svg)](https://github.com/botifyex/egress-proxy/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/botifyex/egress-proxy/blob/master/LICENSE)

Send the HTTP requests of your Python project through your own server with a drop-in integration
for its HTTP client: they leave from the server's IP, or from upstream HTTP and SOCKS proxies it
rotates through, with identifying headers removed.

## Quick start

**1. Start the server** on the machine whose IP the requests should come from:

```sh
pip install "egress-proxy[server]"
python -c "import secrets; print('PROXY__KEY=' + secrets.token_urlsafe(32))" > .env
egress-proxy --host 0.0.0.0 --port 8000
```

The generated key is in `.env`; the client needs it.

**2. Use it in your project** with the HTTP client you already have:

```sh
pip install "egress-proxy[client-httpx]"     # httpx
pip install "egress-proxy[client-aiohttp]"   # aiohttp
pip install "egress-proxy[client]"           # both
```

```python
import asyncio

from egress_proxy.client.httpx import AsyncClient


async def main() -> None:
    async with AsyncClient(egress_url="http://SERVER_IP:8000", egress_key="PROXY_KEY") as client:
        response = await client.get("https://api.ipify.org?format=json")
        print(response.json())


asyncio.run(main())
```

It prints the server's IP. The `egress_*` parameters configure the proxy; everything else goes to
the HTTP client unchanged.

## httpx

**Replace the client class.** `Client` and `AsyncClient` are `httpx.Client` / `httpx.AsyncClient`
subclasses and accept all of their options:

```python
from egress_proxy.client.httpx import AsyncClient, Client

client = AsyncClient(
    egress_url="http://SERVER_IP:8000",
    egress_key="PROXY_KEY",
    base_url="https://api.example.com",
    timeout=10,
)
```

**Keep your own client** and only swap its transport (`Transport` for `httpx.Client`):

```python
import httpx
from egress_proxy.client.httpx import AsyncTransport

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

| Situation | Raised |
|---|---|
| Wrong key or invalid target URL | `egress_proxy.client.httpx.Refused` (a `httpx.TransportError`) |
| Target did not answer in time | `httpx.TimeoutException` |
| Target or proxy server unreachable | `httpx.ConnectError` |

## aiohttp

**Create a session.** `session` returns a regular `aiohttp.ClientSession` and accepts all of its
options:

```python
from egress_proxy.client.aiohttp import session

client = session(
    egress_url="http://SERVER_IP:8000",
    egress_key="PROXY_KEY",
    base_url="https://api.example.com/",
)
```

**Keep your own session** and add the middleware; put it last so your own middlewares see the
target URL:

```python
import aiohttp
from egress_proxy.client.aiohttp import Middleware

client = aiohttp.ClientSession(
    middlewares=[Middleware(egress_url="http://SERVER_IP:8000", egress_key="PROXY_KEY")],
)
```

`response.url`, redirects and cookies refer to the target, exactly as without the proxy.

| Situation | Raised |
|---|---|
| Wrong key or invalid target URL | `egress_proxy.client.aiohttp.Refused` (an `aiohttp.ClientError`) |
| Target did not answer in time | `aiohttp.ServerTimeoutError` (also a `TimeoutError`) |
| Target unreachable | `aiohttp.ClientConnectionError` |
| Proxy server unreachable | `aiohttp.ClientConnectorError` |

With either client, errors are the library's own exceptions, so existing `except` blocks keep
working, and responses with error statuses (404, 500, …) come back as normal responses.

## Server configuration

Settings are read from `.env` in the working directory or from environment variables, which take
precedence. Template: [`.env.example`](https://github.com/botifyex/egress-proxy/blob/master/.env.example).

| Variable | Default | Meaning |
|---|---|---|
| `PROXY__KEY` | required | Key every client must send |
| `PROXY__TIMEOUT` | `30` | Seconds to wait for the target |
| `PROXY__CONNECT` | `10` | Seconds to connect to the target |
| `PROXY__UPSTREAMS_FILE` | none | File with upstream proxies, see below; `--upstreams-file` overrides it |
| `PROXY__UPSTREAMS` | `[]` | Upstream proxies inline, as a JSON list |
| `PROXY__COOLDOWN` | `30` | Seconds an unreachable upstream proxy is left out |
| `PROXY__ATTEMPTS` | `3` | Upstream proxies tried per request before giving up |
| `PROXY__SHUFFLE` | `false` | Shuffle upstream proxies at startup, separately in every worker, see below |
| `PROXY__ALLOW_LOCAL` | `false` | Allow targets on local and private networks, see below |
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

## Local networks

By default the server refuses targets that are not publicly routable, so a client cannot use it to
reach services next to it: loopback, private networks (`10.0.0.0/8`, `172.16.0.0/12`,
`192.168.0.0/16`, `fc00::/7`), link-local addresses including cloud metadata at
`169.254.169.254`, shared and reserved ranges, multicast, and IPv6 forms that embed such an IPv4
address. Host names are checked after DNS resolution and the connection uses only the checked
addresses, so a name that points to a local address, or later starts to, is refused as well.
Refused requests get a 400 with `x-egress-failure: invalid`.

To proxy into local networks on purpose, set `PROXY__ALLOW_LOCAL=true`.

Through upstream proxies, local IP addresses in the target are still refused, but host names are
resolved by the proxy and reach whatever its network serves under that name.

## Upstream proxies

Without upstream proxies the server sends requests itself. List HTTP or SOCKS proxies and it spreads
requests across them in turn instead, so they leave from the proxies' IPs:

```sh
cat > proxies.txt <<'EOF'
socks5h://user:password@proxy-1.example.net:1080
http://user:password@proxy-2.example.net:3128
EOF
echo "PROXY__UPSTREAMS_FILE=proxies.txt" >> .env
```

One proxy URL per line; blank lines and `#` comments are ignored. Template:
[`proxies.example.txt`](https://github.com/botifyex/egress-proxy/blob/master/proxies.example.txt).

| Scheme | Proxy |
|---|---|
| `http://`, `https://` | HTTP proxy (CONNECT), `https` reaches the proxy over TLS |
| `socks5h://` | SOCKS5, host names resolved by the proxy |
| `socks5://` | SOCKS5, host names resolved by the egress server |
| `socks4://` | SOCKS4 |

The file can also be given on the command line, which overrides `.env`:

```sh
egress-proxy --upstreams-file proxies.txt --host 0.0.0.0
```

A few proxies can go straight into `.env` instead: `PROXY__UPSTREAMS=["socks5h://host:1080"]`.
Both sources can be combined; the file comes first.

If a proxy cannot be reached, the request moves on to the next one and the unreachable proxy is
left out for `PROXY__COOLDOWN` seconds. A proxy that refuses the tunnel, for example over a wrong
password or a target it cannot reach, is skipped for that request only. The client gets a 502 once
`PROXY__ATTEMPTS` proxies have failed. An invalid proxy URL stops the server at startup with its
file and line.

Every worker rotates through the proxies on its own, and each starts from the first one in the
list. With `--workers` above 1 and few requests, the first proxies therefore get a little more
traffic. `PROXY__SHUFFLE=true` shuffles the list when a worker starts, with a cryptographically
secure random generator, so each worker begins at a different proxy.

## How it works

The client sends each request to the server with the target URL and the key in headers. The
server checks the key, forwards the request over a pooled keep-alive connection and streams the
response back unchanged. Redirects and cookies are handled by your client, never stored on the
server.

Before forwarding, the server removes every header that could reveal the client or the proxy,
including those a load balancer or CDN in front of it adds:

- client addresses: `X-Forwarded-For`, `Forwarded`, `X-Real-IP`, `X-Client-IP`, `Client-IP`,
  `True-Client-IP`, `X-Originating-IP`, `X-Remote-Addr`, `CF-Connecting-IP`, `Fastly-Client-IP`,
  `CloudFront-Viewer-Address`, `X-Azure-ClientIP` and any other name containing `forwarded`,
  `client-ip`, `real-ip`, `remote-addr` or a similar fragment;
- proxy and CDN markers: `Via`, `CF-Ray`, `CDN-Loop`, `X-Amzn-Trace-Id`, `X-Envoy-*`,
  `CloudFront-Viewer-*` and similar;
- hop-by-hop headers, including every header named in `Connection` (RFC 9110), and `Proxy`
  (httpoxy).

Names are compared case-insensitively with `_` treated as `-`, since many servers map both to the
same variable. Credentials such as `Authorization`, `Cookie`, `CF-Access-Client-Id` or
`Fastly-Key` pass through untouched.

## Requirements

Python 3.11+. The clients need httpx 0.25.1+ or aiohttp 3.13+; the server runs on uvicorn and
aiohttp and handles about 13,000 requests per second on a single core.

## License

[Apache-2.0](https://github.com/botifyex/egress-proxy/blob/master/LICENSE): use, modify and
distribute it freely, including commercially. Keep the license and the
[NOTICE](https://github.com/botifyex/egress-proxy/blob/master/NOTICE) with every copy and mark the
files you change.

Contributing and releases:
[CONTRIBUTING.md](https://github.com/botifyex/egress-proxy/blob/master/CONTRIBUTING.md).
Security issues: [SECURITY.md](https://github.com/botifyex/egress-proxy/blob/master/SECURITY.md).
