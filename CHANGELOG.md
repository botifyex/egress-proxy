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
- Proxy server that authenticates clients by key, streams request and response bodies,
  and strips identifying, hop-by-hop and protocol headers.
- Server configuration from `.env` and the `egress-proxy` command, which accepts every
  uvicorn option.
- Optional extras `client`, `server` and `all`.
- Support for Python 3.11 to 3.14.

[Unreleased]: https://github.com/botifyex/egress-proxy/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/botifyex/egress-proxy/releases/tag/v0.1.0
