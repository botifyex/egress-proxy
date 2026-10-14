import importlib
import socket
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
    monkeypatch.setattr(uvicorn.Config, "bind_socket", uvicorn.Config.bind_socket)
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


def test_access_log_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "--no-access-log" in run(monkeypatch)


def test_access_log_can_be_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    arguments = run(monkeypatch, "--access-log")
    assert arguments.index("--access-log") > arguments.index("--no-access-log")


def test_listening_socket_disables_nagle() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        main.nodelay(listener)
        assert listener.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) != 0


def test_unix_socket_is_left_untouched() -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        assert main.nodelay(listener) is listener


def test_bound_sockets_disable_nagle(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[socket.socket] = []

    def bind(config: uvicorn.Config) -> socket.socket:
        created.append(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
        return created[-1]

    listener = main.immediate(bind)(uvicorn.Config(app=main.FACTORY))
    assert listener.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) != 0
    listener.close()


def test_run_installs_nagle_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    original = uvicorn.Config.bind_socket
    run(monkeypatch)
    assert uvicorn.Config.bind_socket is not original
