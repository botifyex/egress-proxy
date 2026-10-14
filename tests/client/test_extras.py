import importlib
import sys

import pytest

from egress_proxy.client import Missing, require


def hidden(monkeypatch: pytest.MonkeyPatch, library: str) -> None:
    monkeypatch.setitem(sys.modules, library, None)
    for name in [name for name in sys.modules if name.startswith(f"egress_proxy.client.{library}")]:
        monkeypatch.delitem(sys.modules, name)


def test_installed_library_passes() -> None:
    require("json", "client-json")


def test_missing_library_names_the_extra() -> None:
    with pytest.raises(Missing, match=r"pip install 'egress-proxy\[client-absent\]'"):
        require("absent_library_for_tests", "client-absent")


def test_missing_is_a_module_not_found_error() -> None:
    assert issubclass(Missing, ModuleNotFoundError)


@pytest.mark.parametrize("library", ["httpx", "aiohttp"])
def test_integration_without_its_library_explains_the_extra(monkeypatch: pytest.MonkeyPatch, library: str) -> None:
    hidden(monkeypatch, library)
    with pytest.raises(Missing, match=f"client-{library}"):
        importlib.import_module(f"egress_proxy.client.{library}")
