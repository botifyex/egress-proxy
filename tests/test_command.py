import sys

import pytest

from egress_proxy import command


def hidden(monkeypatch: pytest.MonkeyPatch, library: str) -> None:
    monkeypatch.setitem(sys.modules, library, None)
    for name in [name for name in sys.modules if name.startswith("egress_proxy.server")]:
        monkeypatch.delitem(sys.modules, name)


def test_command_without_server_extra_prints_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    hidden(monkeypatch, "uvicorn")
    with pytest.raises(SystemExit) as raised:
        command.run()
    assert raised.value.code == "egress-proxy: uvicorn is not installed: pip install 'egress-proxy[server]'"
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__


def test_command_starts_the_server(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[bool] = []
    monkeypatch.setattr(command.server(), "run", lambda: started.append(True))
    command.run()
    assert started == [True]
