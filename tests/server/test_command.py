import importlib
import os
import socket
import sys
from pathlib import Path

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
    monkeypatch.setattr(uvicorn.main, "epilog", uvicorn.main.epilog)
    monkeypatch.setenv(main.UPSTREAMS, os.environ.get(main.UPSTREAMS, ""))
    monkeypatch.setenv("PROXY__KEY", os.environ.get("PROXY__KEY", "key"))
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


@pytest.fixture
def files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("proxies.txt", "from-environment.txt", "from-command.txt"):
        (tmp_path / name).write_text("socks5://proxy.example.net:1080\n")


@pytest.mark.usefixtures("files")
@pytest.mark.parametrize("arguments", [("--upstreams-file", "proxies.txt"), ("--upstreams-file=proxies.txt",)])
def test_upstreams_file_option_sets_the_setting(monkeypatch: pytest.MonkeyPatch, arguments: tuple[str, ...]) -> None:
    passed = run(monkeypatch, "--port", "9000", *arguments)
    assert os.environ[main.UPSTREAMS] == "proxies.txt"
    assert not any(argument.startswith("--upstreams-file") for argument in passed)
    assert value(passed, "--port") == "9000"


@pytest.mark.usefixtures("files")
def test_upstreams_file_option_overrides_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(main.UPSTREAMS, "from-environment.txt")
    run(monkeypatch, "--upstreams-file", "from-command.txt")
    assert os.environ[main.UPSTREAMS] == "from-command.txt"


@pytest.mark.usefixtures("files")
def test_without_option_environment_is_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(main.UPSTREAMS, "from-environment.txt")
    run(monkeypatch)
    assert os.environ[main.UPSTREAMS] == "from-environment.txt"


def test_option_needs_a_path(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        run(monkeypatch, "--upstreams-file")
    assert "--upstreams-file: expected one argument" in capsys.readouterr().err


def test_option_is_not_matched_by_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "--upstreams" in run(monkeypatch, "--upstreams", "x")


def test_help_describes_the_option(monkeypatch: pytest.MonkeyPatch) -> None:
    run(monkeypatch, "--help")
    assert "--upstreams-file PATH" in uvicorn.main.epilog


def test_invalid_upstreams_stop_before_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit, match="^egress-proxy: missing.txt: cannot read upstream proxies file"):
        run(monkeypatch, "--upstreams-file", "missing.txt")


def test_empty_key_stops_before_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROXY__KEY", "")
    with pytest.raises(SystemExit, match=r"(?s)^egress-proxy: .*\bkey\b"):
        run(monkeypatch)


@pytest.mark.parametrize("flag", ["--help", "--version"])
def test_informational_flags_skip_validation(monkeypatch: pytest.MonkeyPatch, flag: str) -> None:
    monkeypatch.setenv("PROXY__KEY", "")
    monkeypatch.delenv("PROXY__KEY")
    assert flag in run(monkeypatch, flag, "--upstreams-file", "missing.txt")
