import os
import signal
import subprocess
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager

import httpx

from tests.support.servers import KEY, bind

RUN = "from egress_proxy.server.main import run; run()"


class Unstarted(RuntimeError):
    pass


def free() -> int:
    listener = bind()
    port = listener.getsockname()[1]
    listener.close()
    return port


def reachable(port: int) -> bool:
    try:
        httpx.get(f"http://127.0.0.1:{port}/", timeout=0.2)
    except httpx.TransportError:
        return False
    return True


def wait(process: subprocess.Popen[bytes], port: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while not reachable(port):
        if process.poll() is not None:
            raise Unstarted(f"egress-proxy exited with code {process.returncode} before listening")
        if time.monotonic() > deadline:
            raise Unstarted(f"egress-proxy did not listen on port {port} within {timeout} seconds")
        time.sleep(0.1)


def signal_group(process: subprocess.Popen[bytes], number: signal.Signals) -> None:
    try:
        os.killpg(process.pid, number)
    except ProcessLookupError:
        pass


def stop(process: subprocess.Popen[bytes]) -> None:
    signal_group(process, signal.SIGTERM)
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        signal_group(process, signal.SIGKILL)
        process.wait()


@contextmanager
def command(*arguments: str, timeout: float = 20) -> Generator[str, None, None]:
    port = free()
    process = subprocess.Popen(
        [sys.executable, "-c", RUN, "--port", str(port), *arguments],
        env={**os.environ, "PROXY__KEY": KEY, "PROXY__ALLOW_LOCAL": "true"},
        start_new_session=True,
    )
    try:
        wait(process, port, timeout)
        yield f"http://127.0.0.1:{port}"
    finally:
        stop(process)
