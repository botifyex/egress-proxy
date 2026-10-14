import tomllib
from pathlib import Path
from typing import Any

import egress_proxy

PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"


def project() -> dict[str, Any]:
    with PYPROJECT.open("rb") as file:
        return tomllib.load(file)


def test_version_matches_project() -> None:
    assert egress_proxy.__version__ == project()["project"]["version"]


def test_bump_configuration_tracks_project_version() -> None:
    configuration = project()
    assert configuration["tool"]["bumpversion"]["current_version"] == configuration["project"]["version"]
