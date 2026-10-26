from dataclasses import dataclass
from functools import lru_cache
from typing import TypeAlias

from egress_proxy.protocol import Header

Pairs: TypeAlias = list[tuple[bytes, bytes]]

HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "xonnection",
        "xroxy-connection",
    }
)

UNSAFE = frozenset({"proxy"})

ADDRESSES = (
    "forwarded",
    "forward-for",
    "client-ip",
    "clientip",
    "real-ip",
    "remote-addr",
    "remote-ip",
    "connecting-ip",
    "user-ip",
    "originating-ip",
    "original-ip",
    "socketip",
)

ADDRESSED = frozenset(
    {
        "x-ip",
        "x-from-ip",
        "source-ip",
        "coming-from",
        "x-coming-from",
        "connect-via-ip",
        "x-delegate-remote-host",
        "x-imforwards",
        "x-proxymesh-ip",
        "cf-pseudo-ipv4",
    }
)

MARKERS = frozenset(
    {
        "via",
        "x-bluecoat-via",
        "x-proxy-id",
        "cdn-loop",
        "cf-ew-via",
        "cf-ipcountry",
        "cf-ray",
        "cf-visitor",
        "fastly-ff",
        "akamai-origin-hop",
        "x-akamai-edgescape",
        "x-azure-fdid",
        "x-azure-ref",
        "x-amzn-trace-id",
        "x-cloud-trace-context",
        "x-request-id",
        "request-id",
        "x-correlation-id",
        "correlation-id",
        "x-host",
        "x-original-host",
        "x-backend-host",
        "x-gateway-host",
        "x-url-scheme",
        "front-end-https",
    }
)

EDGES = ("x-envoy-", "cloudfront-viewer-")

PRIVATE = frozenset(header.value for header in Header)


@dataclass(frozen=True)
class Policy:
    exact: frozenset[str]
    fragments: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()

    def excluded(self, name: str) -> bool:
        if name in self.exact or name.startswith(self.prefixes):
            return True
        return any(fragment in name for fragment in self.fragments)


REQUEST = Policy(
    exact=HOP | UNSAFE | ADDRESSED | MARKERS | PRIVATE | {"host"},
    fragments=ADDRESSES,
    prefixes=EDGES,
)

RESPONSE = Policy(exact=HOP | PRIVATE)


def canonical(text: str) -> str:
    return text.strip().lower().replace("_", "-")


@lru_cache(maxsize=4096)
def normalized(name: bytes) -> str:
    return canonical(name.decode("latin-1"))


@lru_cache(maxsize=4096)
def blocked(policy: Policy, name: bytes) -> bool:
    return policy.excluded(normalized(name))


def declared(pairs: Pairs) -> frozenset[str]:
    values = (value.decode("latin-1") for name, value in pairs if normalized(name) == "connection")
    return frozenset(canonical(token) for value in values for token in value.split(","))


def kept(name: bytes, policy: Policy, hop: frozenset[str]) -> bool:
    return not blocked(policy, name) and normalized(name) not in hop


def filtered(pairs: Pairs, policy: Policy) -> Pairs:
    hop = declared(pairs)
    return [(name, value) for name, value in pairs if kept(name, policy, hop)]
