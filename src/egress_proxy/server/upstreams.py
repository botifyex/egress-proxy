from dataclasses import dataclass
from pathlib import Path

from aiohttp_socks import ProxyType
from yarl import URL

from egress_proxy.server.settings import Proxy


class Malformed(ValueError):
    pass


@dataclass(frozen=True)
class Scheme:
    kind: ProxyType
    remote: bool
    secure: bool
    port: bool


SCHEMES: dict[str, Scheme] = {
    "http": Scheme(ProxyType.HTTP, remote=True, secure=False, port=False),
    "https": Scheme(ProxyType.HTTP, remote=True, secure=True, port=False),
    "socks4": Scheme(ProxyType.SOCKS4, remote=False, secure=False, port=True),
    "socks5": Scheme(ProxyType.SOCKS5, remote=False, secure=False, port=True),
    "socks5h": Scheme(ProxyType.SOCKS5, remote=True, secure=False, port=True),
}


@dataclass(frozen=True)
class Upstream:
    url: URL
    scheme: Scheme

    @property
    def name(self) -> str:
        return str(self.url.with_user(None))


def parse(text: str, origin: str) -> Upstream:
    try:
        url = URL(text.strip())
    except ValueError as error:
        raise Malformed(f"{origin}: not a valid proxy url") from error
    scheme = SCHEMES.get(url.scheme)
    if scheme is None:
        raise Malformed(f"{origin}: unsupported proxy scheme '{url.scheme}', use one of {', '.join(SCHEMES)}")
    if not url.host:
        raise Malformed(f"{origin}: proxy url has no host")
    if scheme.port and url.explicit_port is None:
        raise Malformed(f"{origin}: {url.scheme} proxy url needs a port")
    return Upstream(url, scheme)


def entries(path: Path) -> list[tuple[str, str]]:
    try:
        lines = path.read_text().splitlines()
    except OSError as error:
        raise Malformed(f"{path}: cannot read upstream proxies file ({error.strerror})") from error
    return [
        (f"{path}:{number}", line.strip())
        for number, line in enumerate(lines, start=1)
        if line.strip() and not line.strip().startswith("#")
    ]


def configured(proxy: Proxy) -> list[Upstream]:
    listed = entries(proxy.upstreams_file) if proxy.upstreams_file else []
    inline = [(f"PROXY__UPSTREAMS[{index}]", text) for index, text in enumerate(proxy.upstreams)]
    return [parse(text, origin) for origin, text in [*listed, *inline]]
