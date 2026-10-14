# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-14

### Added

- httpx integration in `egress_proxy.client.httpx`: `Transport` and `AsyncTransport` for any
  httpx client, plus drop-in `Client` and `AsyncClient` subclasses.
- aiohttp integration in `egress_proxy.client.aiohttp`: a `Middleware` for any
  `aiohttp.ClientSession` and a `session` factory; `response.url`, redirects and cookies keep
  referring to the target.
- Proxy failures surface as each library's own errors, with `Refused` for a rejected key or
  target.
- Proxy server built on uvicorn and aiohttp that authenticates clients by key and streams
  request and response bodies over pooled keep-alive connections.
- Targets on loopback, private, link-local (cloud metadata), shared, reserved and multicast
  addresses are refused unless `PROXY__ALLOW_LOCAL=true`, including host names that resolve to
  them and IPv6 forms that embed them; connections use only the checked addresses.
- Requests lose every header that reveals the client or a proxy: some 80 client address and
  proxy or CDN headers collected from OWASP, request-ip and CDN documentation, matched by name
  and fragment, case-insensitively and with `_` treated as `-`, plus headers named in
  `Connection` and the httpoxy `Proxy` header.
- Server configuration from `.env` and the `egress-proxy` command, which accepts every
  uvicorn option.
- Upstream proxies: the server can spread requests across HTTP, HTTPS, SOCKS4 and SOCKS5
  proxies listed in a file (`PROXY__UPSTREAMS_FILE` or `egress-proxy --upstreams-file`) or in
  `PROXY__UPSTREAMS`, moving on to the next proxy when one is unreachable and leaving it out for
  a cooldown.
- Optional extras `client-httpx`, `client-aiohttp`, `client` (both), `server` and `all`; importing
  a client integration or running `egress-proxy` without its extra raises
  `egress_proxy.extras.Missing` with the install command.
- Support for Python 3.11 to 3.14.

### Performance

- The server runs as a plain ASGI application on aiohttp and the httptools parser and has
  the access log off by default: 13 to 15 times the throughput of the first prototype
  under concurrency, with p99 latency down from about 500 ms to 7 ms.
- `sniffio` is installed with the client, so httpx no longer searches the filesystem for
  it on every request.
- `egress-proxy --workers N` disables Nagle's algorithm on its listening socket, removing
  a 40 ms delay per response in multi-process mode.

[Unreleased]: https://github.com/botifyex/egress-proxy/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/botifyex/egress-proxy/releases/tag/v0.1.0
