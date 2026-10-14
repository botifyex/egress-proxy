import importlib
import sys

import pytest
import uvicorn

from egress_proxy.server import main
from egress_proxy.server.settings import Server


def run(monkeypatch: pytest.MonkeyPatch, *arguments: str) -> list[str]:
    captured: list[str] = []

    def fake(args: list[str], prog_name: str) -> None:
        captured.extend(args)

    monkeypatch.setattr(uvicorn.main, "main", fake)
    monkeypatch.setattr(sys, "argv", ["egress-proxy", *arguments])
    monkeypatch.setattr(main, "Server", lambda: Server(host="10.0.0.1", port=7000))
    main.run()
    return captured


def value(arguments: list[str], option: str) -> str:
    positions = [index for index, argument in enumerate(arguments) if argument == option]
    return arguments[positions[-1] + 1]


def test_factory_is_passed_to_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    arguments = run(monkeypatch)
    assert arguments[0] == main.FACTORY
    assert "--factory" in arguments


def test_settings_are_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    arguments = run(monkeypatch)
    assert value(arguments, "--host") == "10.0.0.1"
    assert value(arguments, "--port") == "7000"


def test_command_line_overrides_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    arguments = run(monkeypatch, "--host", "0.0.0.0", "--port", "9000", "--workers", "4")
    assert value(arguments, "--host") == "0.0.0.0"
    assert value(arguments, "--port") == "9000"
    assert value(arguments, "--workers") == "4"


def test_identifying_headers_are_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    arguments = run(monkeypatch)
    assert "--no-server-header" in arguments
    assert "--no-date-header" in arguments


def test_factory_resolves_to_application(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROXY__KEY", "key")
    module, name = main.FACTORY.split(":")
    factory = getattr(importlib.import_module(module), name)
    assert callable(factory())
