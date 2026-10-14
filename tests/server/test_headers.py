import pytest

from egress_proxy.server.headers import REQUEST, RESPONSE, Policy, declared, filtered, normalized
from tests.support.identifying import ADDRESSES, LEGITIMATE, MARKERS

IDENTIFYING = (*ADDRESSES, *MARKERS)


def spellings(name: str) -> tuple[str, ...]:
    title = "-".join(part.capitalize() for part in name.split("-"))
    return name, name.replace("-", "_"), title, title.replace("-", "_"), name.upper()


@pytest.mark.parametrize("name", [spelling for name in IDENTIFYING for spelling in spellings(name)])
def test_identifying_header_is_removed_from_requests(name: str) -> None:
    assert REQUEST.excluded(normalized(name.encode()))


@pytest.mark.parametrize("name", [spelling for name in LEGITIMATE for spelling in spellings(name)])
def test_legitimate_header_is_kept(name: str) -> None:
    assert not REQUEST.excluded(normalized(name.encode()))


def test_host_is_removed_from_requests_only() -> None:
    assert REQUEST.excluded("host")
    assert not RESPONSE.excluded("host")


@pytest.mark.parametrize("name", ["set-cookie", "content-encoding", "x-forwarded-for", "via", "cf-ray"])
def test_responses_keep_everything_but_hop_by_hop(name: str) -> None:
    assert not RESPONSE.excluded(name)


@pytest.mark.parametrize("name", ["connection", "keep-alive", "transfer-encoding", "x-egress-failure"])
def test_responses_drop_hop_by_hop_and_protocol_headers(name: str) -> None:
    assert RESPONSE.excluded(name)


def test_names_are_normalized() -> None:
    assert normalized(b"X_Forwarded_For") == "x-forwarded-for"


def test_policy_matches_exact_names_prefixes_and_fragments() -> None:
    policy = Policy(exact=frozenset({"exact"}), fragments=("inside",), prefixes=("start-",))
    matched = {name for name in ("exact", "start-here", "x-inside-y", "other") if policy.excluded(name)}
    assert matched == {"exact", "start-here", "x-inside-y"}


def test_connection_tokens_are_collected_from_every_connection_header() -> None:
    pairs = [(b"Connection", b"keep-alive, X-Hop"), (b"connection", b" x_other "), (b"x-hop", b"1")]
    assert declared(pairs) == {"keep-alive", "x-hop", "x-other"}


@pytest.mark.parametrize("policy", [REQUEST, RESPONSE])
def test_headers_named_by_connection_are_removed(policy: Policy) -> None:
    pairs = [(b"connection", b"close, X-Secret-Hop"), (b"x-secret-hop", b"1"), (b"x-kept", b"2")]
    assert filtered(pairs, policy) == [(b"x-kept", b"2")]


def test_filtering_keeps_order_and_duplicates() -> None:
    pairs = [(b"set-cookie", b"a=1"), (b"via", b"1.1 proxy"), (b"set-cookie", b"b=2")]
    assert filtered(pairs, RESPONSE) == pairs
    assert filtered(pairs, REQUEST) == [(b"set-cookie", b"a=1"), (b"set-cookie", b"b=2")]
