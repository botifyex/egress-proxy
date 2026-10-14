from collections.abc import Iterator

import pytest

from egress_proxy.server.application import application
from egress_proxy.server.settings import Proxy
from tests.support.servers import KEY, Fleet, bind
from tests.support.upstream import upstream


@pytest.fixture(scope="session")
def fleet() -> Iterator[Fleet]:
    fleet = Fleet()
    yield fleet
    fleet.stop()


@pytest.fixture(scope="session")
def target(fleet: Fleet) -> str:
    return fleet.start(upstream)


@pytest.fixture(scope="session")
def egress(fleet: Fleet) -> str:
    return fleet.start(application(Proxy(key=KEY, timeout=10, connect=10)))


@pytest.fixture(scope="session")
def impatient(fleet: Fleet) -> str:
    return fleet.start(application(Proxy(key=KEY, timeout=0.1, connect=0.1)))


@pytest.fixture
def unreachable() -> str:
    listener = bind()
    port = listener.getsockname()[1]
    listener.close()
    return f"http://127.0.0.1:{port}"
