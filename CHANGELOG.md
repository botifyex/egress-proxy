# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-14

### Added

- httpx integration: `Transport` and `AsyncTransport` for any httpx client, plus drop-in
  `Client` and `AsyncClient` subclasses that route every request through the proxy.
- Proxy failures surface as regular httpx errors: `httpx.TimeoutException`,
  `httpx.ConnectError`, and `egress_proxy.client.Refused` for a rejected key or target.
- Proxy server built on uvicorn and aiohttp that authenticates clients by key, streams
  request and response bodies over pooled keep-alive connections, and strips identifying,
  hop-by-hop and protocol headers.
- Server configuration from `.env` and the `egress-proxy` command, which accepts every
  uvicorn option.
- Optional extras `client`, `server` and `all`.
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
