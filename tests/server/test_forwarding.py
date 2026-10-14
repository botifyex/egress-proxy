import gzip
import hashlib
import json
from typing import Any

import httpx
import pytest

from egress_proxy.protocol import Failure, Header
from egress_proxy.server.application import application
from egress_proxy.server.settings import Proxy
from tests.support.identifying import ADDRESSES, LEGITIMATE, MARKERS
from tests.support.servers import KEY, Fleet
from tests.support.upstream import COMPRESSED


def headers(target: str, key: str = KEY) -> dict[str, str]:
    return {Header.KEY: key, Header.TARGET: target}


def received(response: httpx.Response) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for name, value in response.json()["headers"]:
        result.setdefault(name, []).append(value)
    return result


def request(method: str, url: str, **options: Any) -> httpx.Response:
    return httpx.request(method, url, verify=False, timeout=10, **options)


def send(egress: str, method: str, target: str, **options: Any) -> httpx.Response:
    extra = options.pop("headers", {})
    return request(method, egress, headers={**headers(target), **extra}, **options)


def test_missing_key_is_rejected(egress: str, target: str) -> None:
    response = request("GET", egress, headers={Header.TARGET: f"{target}/echo"})
    assert response.status_code == 401
    assert response.headers[Header.FAILURE] == Failure.UNAUTHORIZED


def test_wrong_key_is_rejected(egress: str, target: str) -> None:
    response = request("GET", egress, headers=headers(f"{target}/echo", key="wrong"))
    assert response.status_code == 401
    assert response.headers[Header.FAILURE] == Failure.UNAUTHORIZED


def test_missing_target_is_rejected(egress: str) -> None:
    response = request("GET", egress, headers={Header.KEY: KEY})
    assert response.status_code == 400
    assert response.headers[Header.FAILURE] == Failure.INVALID


@pytest.mark.parametrize("value", ["ftp://example.com/file", "/relative/path", "example.com", "http://", "http://[::1"])
def test_invalid_target_is_rejected(egress: str, value: str) -> None:
    response = request("GET", egress, headers=headers(value))
    assert response.status_code == 400
    assert response.headers[Header.FAILURE] == Failure.INVALID


def test_key_is_checked_before_target(egress: str) -> None:
    response = request("GET", egress, headers={Header.TARGET: "ftp://example.com"})
    assert response.status_code == 401


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_methods_are_forwarded(egress: str, target: str, method: str) -> None:
    response = send(egress, method, f"{target}/echo")
    assert response.status_code == 200
    assert response.json()["method"] == method


@pytest.mark.parametrize("method", ["TRACE", "PROPFIND"])
def test_unsupported_methods_are_rejected(egress: str, target: str, method: str) -> None:
    response = send(egress, method, f"{target}/echo")
    assert response.status_code == 400
    assert response.headers[Header.FAILURE] == Failure.INVALID


def test_head_is_forwarded(egress: str, target: str) -> None:
    response = send(egress, "HEAD", f"{target}/echo")
    assert response.status_code == 200
    assert response.content == b""


def test_egress_path_is_ignored(egress: str, target: str) -> None:
    response = request("GET", f"{egress}/anything/here", headers=headers(f"{target}/echo"))
    assert response.json()["path"] == "/echo"


def test_path_and_query_are_preserved_exactly(egress: str, target: str) -> None:
    response = send(egress, "GET", f"{target}/echo/a%2Fb/%D1%82%D0%B5%D1%81%D1%82?tag=x&tag=y&q=a%20b")
    assert response.json()["path"] == "/echo/a%2Fb/%D1%82%D0%B5%D1%81%D1%82"
    assert response.json()["query"] == "tag=x&tag=y&q=a%20b"


def test_host_header_matches_target(egress: str, target: str) -> None:
    response = send(egress, "GET", f"{target}/echo")
    assert received(response)["host"] == [target.removeprefix("http://")]


def test_custom_headers_are_forwarded(egress: str, target: str) -> None:
    response = send(egress, "GET", f"{target}/echo", headers={"authorization": "Bearer token", "x-custom": "1"})
    assert received(response)["authorization"] == ["Bearer token"]
    assert received(response)["x-custom"] == ["1"]


def test_private_headers_are_not_forwarded(egress: str, target: str) -> None:
    response = send(egress, "GET", f"{target}/echo")
    assert Header.KEY not in received(response)
    assert Header.TARGET not in received(response)


@pytest.mark.parametrize("name", ["x-forwarded-for", "x-real-ip", "forwarded", "via", "cf-connecting-ip"])
def test_identifying_headers_are_not_forwarded(egress: str, target: str, name: str) -> None:
    response = send(egress, "GET", f"{target}/echo", headers={name: "203.0.113.7"})
    assert name not in received(response)


def test_hop_by_hop_headers_are_not_forwarded(egress: str, target: str) -> None:
    response = send(egress, "GET", f"{target}/echo", headers={"proxy-authorization": "Basic secret", "te": "trailers"})
    assert "proxy-authorization" not in received(response)
    assert "te" not in received(response)


def test_body_is_forwarded_with_length(egress: str, target: str) -> None:
    response = send(egress, "POST", f"{target}/echo", json={"name": "value"})
    assert json.loads(response.json()["body"]) == {"name": "value"}
    assert received(response)["content-length"] == [str(response.json()["length"])]
    assert "transfer-encoding" not in received(response)


def test_request_without_body_is_not_chunked(egress: str, target: str) -> None:
    response = send(egress, "GET", f"{target}/echo")
    assert "transfer-encoding" not in received(response)
    assert response.json()["length"] == 0


def test_large_body_is_forwarded_intact(egress: str, target: str) -> None:
    payload = bytes(range(256)) * 40_000
    response = send(egress, "PUT", f"{target}/echo", content=payload)
    assert response.json()["length"] == len(payload)
    assert response.json()["digest"] == hashlib.sha256(payload).hexdigest()


def test_chunked_body_is_forwarded(egress: str, target: str) -> None:
    def parts() -> Any:
        yield b"first-"
        yield b"second"

    response = send(egress, "POST", f"{target}/echo", content=parts())
    assert response.json()["body"] == "first-second"


def test_upstream_status_is_passed_through(egress: str, target: str) -> None:
    for code in (201, 404, 418, 500, 503):
        response = send(egress, "GET", f"{target}/status/{code}")
        assert response.status_code == code
        assert Header.FAILURE not in response.headers


def test_empty_response_status_is_passed_through(egress: str, target: str) -> None:
    response = send(egress, "DELETE", f"{target}/status/204")
    assert response.status_code == 204
    assert response.content == b""


def test_compressed_response_is_relayed_raw(egress: str, target: str) -> None:
    with httpx.stream("GET", egress, headers=headers(f"{target}/compressed"), verify=False) as response:
        raw = b"".join(response.iter_raw())
    assert response.headers["content-encoding"] == "gzip"
    assert gzip.decompress(raw) == COMPRESSED


def test_compressed_response_is_decoded_by_httpx(egress: str, target: str) -> None:
    response = send(egress, "GET", f"{target}/compressed")
    assert response.content == COMPRESSED


def test_streamed_response_is_relayed(egress: str, target: str) -> None:
    response = send(egress, "GET", f"{target}/stream")
    assert response.text == "chunk-0;chunk-1;chunk-2;chunk-3;chunk-4;"


def test_redirect_is_not_followed_by_server(egress: str, target: str) -> None:
    response = send(egress, "GET", f"{target}/redirect")
    assert response.status_code == 307
    assert response.headers["location"] == "/echo?from=redirect"


def test_repeated_response_headers_are_preserved(egress: str, target: str) -> None:
    response = send(egress, "GET", f"{target}/cookies")
    assert response.headers.get_list("set-cookie") == ["first=1; Path=/", "second=2; Path=/"]


def test_cookies_are_not_shared_between_clients(egress: str, target: str) -> None:
    send(egress, "GET", f"{target}/cookies")
    response = send(egress, "GET", f"{target}/echo")
    assert "cookie" not in received(response)


def test_upstream_cannot_spoof_failure_header(egress: str, target: str) -> None:
    response = send(egress, "GET", f"{target}/spoof")
    assert response.status_code == 200
    assert Header.FAILURE not in response.headers


def test_upstream_timeout_is_reported(impatient: str, target: str) -> None:
    response = send(impatient, "GET", f"{target}/slow")
    assert response.status_code == 504
    assert response.headers[Header.FAILURE] == Failure.TIMEOUT


def test_unreachable_upstream_is_reported(egress: str, unreachable: str) -> None:
    response = send(egress, "GET", f"{unreachable}/")
    assert response.status_code == 502
    assert response.headers[Header.FAILURE] == Failure.UNREACHABLE


def test_server_does_not_add_identifying_headers(egress: str, target: str) -> None:
    response = send(egress, "GET", f"{target}/echo")
    assert "server" not in response.headers


@pytest.mark.parametrize("form", ["dash", "underscore"])
@pytest.mark.parametrize("names", [ADDRESSES, MARKERS], ids=["addresses", "markers"])
def test_no_identifying_header_reaches_the_target(egress: str, target: str, names: tuple[str, ...], form: str) -> None:
    sent = {name if form == "dash" else name.replace("-", "_"): "203.0.113.7" for name in names}
    response = send(egress, "GET", f"{target}/echo", headers=sent)
    assert set(received(response)) & set(sent) == set()


def test_legitimate_headers_reach_the_target(egress: str, target: str) -> None:
    sent = {name: "value" for name in LEGITIMATE}
    response = send(egress, "GET", f"{target}/echo", headers=sent)
    assert set(sent) <= set(received(response))


def test_headers_named_by_connection_do_not_reach_the_target(egress: str, target: str) -> None:
    headers = {"connection": "keep-alive, x-secret-hop", "x-secret-hop": "203.0.113.7", "x-kept": "1"}
    response = send(egress, "GET", f"{target}/echo", headers=headers)
    assert "x-secret-hop" not in received(response)
    assert received(response)["x-kept"] == ["1"]


@pytest.fixture(scope="module")
def strict(fleet: Fleet) -> str:
    return fleet.start(application(Proxy(key=KEY)))


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "[::1]", "[::ffff:127.0.0.1]", "[64:ff9b::7f00:1]", "169.254.169.254", "10.0.0.1", "0.0.0.0"],
)
def test_local_addresses_are_refused_by_default(strict: str, target: str, host: str) -> None:
    port = target.rsplit(":", 1)[1]
    response = send(strict, "GET", f"http://{host}:{port}/echo")
    assert response.status_code == 400
    assert response.headers[Header.FAILURE] == Failure.INVALID
    assert "points to a local address" in response.text


def test_names_resolving_to_local_addresses_are_refused_by_default(strict: str, target: str) -> None:
    response = send(strict, "GET", f"{target.replace('127.0.0.1', 'localhost')}/echo")
    assert response.status_code == 400
    assert response.headers[Header.FAILURE] == Failure.INVALID
    assert "resolves only to local addresses" in response.text


def test_local_addresses_are_allowed_when_enabled(egress: str, target: str) -> None:
    assert send(egress, "GET", f"{target.replace('127.0.0.1', 'localhost')}/echo").status_code == 200
