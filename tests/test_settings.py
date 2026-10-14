from pathlib import Path

import pytest
from pydantic import ValidationError

from egress_proxy.server.settings import Proxy, Server

EXAMPLE = Path(__file__).parent.parent / ".env.example"


def names(path: Path) -> set[str]:
    lines = (line.strip() for line in path.read_text().splitlines())
    return {line.split("=", 1)[0] for line in lines if line and not line.startswith("#")}


def fields() -> set[str]:
    server = {f"SERVER__{name.upper()}" for name in Server.model_fields}
    proxy = {f"PROXY__{name.upper()}" for name in Proxy.model_fields}
    return server | proxy


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for variable in fields():
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_server_defaults() -> None:
    server = Server()
    assert (server.host, server.port) == ("127.0.0.1", 8000)


def test_proxy_requires_key() -> None:
    with pytest.raises(ValidationError):
        Proxy()


def test_values_are_read_from_dotenv(isolated: Path) -> None:
    (isolated / ".env").write_text("SERVER__HOST=0.0.0.0\nSERVER__PORT=9000\nPROXY__KEY=from-file\nPROXY__TIMEOUT=5\n")
    assert (Server().host, Server().port) == ("0.0.0.0", 9000)
    assert Proxy().key.get_secret_value() == "from-file"
    assert Proxy().timeout == 5


def test_environment_overrides_dotenv(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (isolated / ".env").write_text("PROXY__KEY=from-file\n")
    monkeypatch.setenv("PROXY__KEY", "from-environment")
    assert Proxy().key.get_secret_value() == "from-environment"


def test_unrelated_variables_are_ignored(isolated: Path) -> None:
    (isolated / ".env").write_text("PROXY__KEY=key\nDATABASE_URL=postgres://\n")
    assert Proxy().key.get_secret_value() == "key"


def test_key_is_hidden_in_representation() -> None:
    assert "hidden" not in repr(Proxy(key="hidden"))


def test_example_lists_every_setting() -> None:
    assert names(EXAMPLE) == fields()


def test_example_is_loadable(isolated: Path) -> None:
    (isolated / ".env").write_text(EXAMPLE.read_text())
    assert (Server().host, Server().port) == (Server.model_fields["host"].default, Server.model_fields["port"].default)
    assert Proxy().key.get_secret_value() == "change-me"
    assert (Proxy().timeout, Proxy().connect) == (30, 10)
