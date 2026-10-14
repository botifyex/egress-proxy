import importlib
import sys

import pytest

from egress_proxy.extras import Missing, require


def hidden(monkeypatch: pytest.MonkeyPatch, library: str, package: str) -> None:
    monkeypatch.setitem(sys.modules, library, None)
    for name in [name for name in sys.modules if name.startswith(package)]:
        monkeypatch.delitem(sys.modules, name)


def test_installed_libraries_pass() -> None:
    require("client-json", "json", "sys")


def test_missing_library_names_the_extra() -> None:
    with pytest.raises(Missing, match=r"pip install 'egress-proxy\[client-absent\]'"):
        require("client-absent", "absent_library_for_tests")


def test_first_missing_library_is_reported() -> None:
    with pytest.raises(Missing, match="^absent_library_for_tests is not installed"):
        require("server", "json", "absent_library_for_tests", "other_absent_library")


def test_missing_is_a_module_not_found_error() -> None:
    assert issubclass(Missing, ModuleNotFoundError)


@pytest.mark.parametrize(
    ("library", "package", "extra"),
    [
        ("httpx", "egress_proxy.client.httpx", "client-httpx"),
        ("aiohttp", "egress_proxy.client.aiohttp", "client-aiohttp"),
        ("uvicorn", "egress_proxy.server", "server"),
        ("httptools", "egress_proxy.server", "server"),
    ],
)
def test_package_without_its_library_explains_the_extra(
    monkeypatch: pytest.MonkeyPatch,
    library: str,
    package: str,
    extra: str,
) -> None:
    hidden(monkeypatch, library, package)
    with pytest.raises(Missing, match=rf"egress-proxy\[{extra}\]"):
        importlib.import_module(package)
