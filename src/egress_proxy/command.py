from importlib import import_module
from types import ModuleType

from egress_proxy.extras import Missing

SERVER = "egress_proxy.server.main"


def server() -> ModuleType:
    try:
        return import_module(SERVER)
    except Missing as error:
        raise SystemExit(f"egress-proxy: {error}") from None


def run() -> None:
    server().run()
