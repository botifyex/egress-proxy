from pathlib import Path

import pytest
from aiohttp_socks import ProxyType

from egress_proxy.server.settings import Proxy
from egress_proxy.server.upstreams import Malformed, configured, entries, parse


@pytest.mark.parametrize(
    ("text", "kind", "remote", "secure"),
    [
        ("http://proxy.example.net:3128", ProxyType.HTTP, True, False),
        ("https://proxy.example.net:8443", ProxyType.HTTP, True, True),
        ("socks4://proxy.example.net:1080", ProxyType.SOCKS4, False, False),
        ("socks5://proxy.example.net:1080", ProxyType.SOCKS5, False, False),
        ("socks5h://proxy.example.net:1080", ProxyType.SOCKS5, True, False),
    ],
)
def test_scheme_selects_proxy_type(text: str, kind: ProxyType, remote: bool, secure: bool) -> None:
    scheme = parse(text, "test").scheme
    assert (scheme.kind, scheme.remote, scheme.secure) == (kind, remote, secure)


def test_credentials_are_kept_but_hidden_from_name() -> None:
    upstream = parse("socks5h://user:secret@proxy.example.net:1080", "test")
    assert (upstream.url.user, upstream.url.password) == ("user", "secret")
    assert upstream.name == "socks5h://proxy.example.net:1080"


def test_http_proxy_port_defaults_to_scheme_port() -> None:
    assert parse("http://proxy.example.net", "test").url.port == 80


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("ftp://proxy.example.net:21", "unsupported proxy scheme 'ftp'"),
        ("proxy.example.net:1080", "unsupported proxy scheme"),
        ("http://", "proxy url has no host"),
        ("socks5://proxy.example.net", "socks5 proxy url needs a port"),
        ("http://[::1", "not a valid proxy url"),
    ],
)
def test_malformed_urls_are_rejected(text: str, message: str) -> None:
    with pytest.raises(Malformed, match=message):
        parse(text, "origin")


def test_errors_name_the_origin_but_not_the_password() -> None:
    with pytest.raises(Malformed) as raised:
        parse("ftp://user:secret@proxy.example.net:21", "proxies.txt:7")
    assert str(raised.value).startswith("proxies.txt:7:")
    assert "secret" not in str(raised.value)


def test_file_skips_comments_and_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "proxies.txt"
    path.write_text("# header\n\n  socks5://a.example.net:1080  \n# note\nhttp://b.example.net:3128\n")
    assert entries(path) == [
        (f"{path}:3", "socks5://a.example.net:1080"),
        (f"{path}:5", "http://b.example.net:3128"),
    ]


def test_unreadable_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(Malformed, match="cannot read upstream proxies file"):
        entries(tmp_path / "missing.txt")


def test_file_line_is_named_in_errors(tmp_path: Path) -> None:
    path = tmp_path / "proxies.txt"
    path.write_text("socks5://a.example.net:1080\nftp://b.example.net:21\n")
    with pytest.raises(Malformed, match=rf"^{path}:2: unsupported"):
        configured(Proxy(key="key", upstreams_file=path))


def test_file_and_inline_upstreams_are_combined_in_order(tmp_path: Path) -> None:
    path = tmp_path / "proxies.txt"
    path.write_text("socks5://from-file.example.net:1080\n")
    proxy = Proxy(key="key", upstreams_file=path, upstreams=["http://inline.example.net:3128"])
    assert [upstream.name for upstream in configured(proxy)] == [
        "socks5://from-file.example.net:1080",
        "http://inline.example.net:3128",
    ]


def test_inline_errors_name_the_setting() -> None:
    with pytest.raises(Malformed, match=r"^PROXY__UPSTREAMS\[1\]:"):
        configured(Proxy(key="key", upstreams=["http://ok.example.net:3128", "ftp://bad.example.net:21"]))


def test_no_upstreams_means_direct() -> None:
    assert configured(Proxy(key="key")) == []


def test_settings_read_upstreams_from_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROXY__KEY", "key")
    monkeypatch.setenv("PROXY__UPSTREAMS", '["socks5://a.example.net:1080"]')
    monkeypatch.setenv("PROXY__UPSTREAMS_FILE", "proxies.txt")
    monkeypatch.setenv("PROXY__COOLDOWN", "5")
    monkeypatch.setenv("PROXY__ATTEMPTS", "2")
    proxy = Proxy()
    assert (proxy.upstreams, proxy.upstreams_file) == (["socks5://a.example.net:1080"], Path("proxies.txt"))
    assert (proxy.cooldown, proxy.attempts) == (5, 2)


def test_empty_file_setting_means_no_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROXY__UPSTREAMS_FILE", "")
    assert Proxy(key="key").upstreams_file is None


@pytest.mark.parametrize(("name", "value"), [("attempts", 0), ("cooldown", -1)])
def test_retry_settings_are_validated(name: str, value: int) -> None:
    with pytest.raises(ValueError):
        Proxy(key="key", **{name: value})
