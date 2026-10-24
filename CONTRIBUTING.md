# Contributing

## Development

```sh
uv sync
uv run pytest --cov
uv run pytest -n auto            # parallel, pays off once the suite grows beyond a few seconds
uv run ruff check src tests benchmarks
uv run ruff format src tests benchmarks
uv run egress-proxy
```

Every push and pull request runs CI: ruff, the test suite on Python 3.11–3.14 against both the
lowest and the latest allowed dependencies, and a wheel smoke test.

## Benchmarks

`benchmarks/run.sh` needs [wrk](https://github.com/wg/wrk). It starts a fast upstream on four
cores and the proxy on one core, then reports throughput and latency; extra arguments go to
`egress-proxy`:

```sh
./benchmarks/run.sh
./benchmarks/run.sh --workers 2
```

Reference results on one core, median of three runs:

| Load | First prototype | Current |
|---|---|---|
| 100 B, 1 connection | 1,225 req/s | 3,900–5,000 req/s |
| 100 B, 16 connections | 741 req/s, p99 86 ms | 10,000–13,700 req/s, p99 1.5 ms |
| 100 B, 64 connections | 646 req/s, p99 503 ms | 9,900–14,300 req/s, p99 5–7 ms |
| 1 MB, 16 connections | 450 req/s | 1,230–1,580 req/s |

`tests/integration/test_performance.py` pins the mechanisms behind these numbers: no import lookups per
request, keep-alive reuse of upstream connections, no extra tasks per request, the httptools
parser, and no delayed acknowledgement with several workers.

## Releases

Releases follow [Semantic Versioning](https://semver.org/) and are recorded in
[CHANGELOG.md](CHANGELOG.md).

1. Add entries under `## [Unreleased]` in `CHANGELOG.md` together with the changes.
2. Bump the version with a clean working tree: `bump-my-version bump patch|minor|major`.
   It updates `pyproject.toml`, `uv.lock` and `CHANGELOG.md`, commits and creates the `v<version>` tag.
3. Push with `git push --follow-tags`, then publish a GitHub release from that tag.

Publishing the release runs CI again and uploads the package to PyPI through Trusted Publishing,
so no token is stored.

One-time setup on PyPI → *Publishing* → *Add a new pending publisher*:
owner `botifyex`, repository `egress-proxy`, workflow `publish.yaml`, environment `pypi`.
