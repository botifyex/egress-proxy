# Contributing

## Development

```sh
uv sync
uv run pytest --cov
uv run pytest -n auto            # parallel, pays off once the suite grows beyond a few seconds
uv run ruff check src tests
uv run ruff format src tests
uv run egress-proxy
```

Every push and pull request runs CI: ruff, the test suite on Python 3.11–3.14 against both the
lowest and the latest allowed dependencies, and a wheel smoke test.

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
owner `botifyex`, repository `egress-proxy`, workflow `publish.yml`, environment `pypi`.
