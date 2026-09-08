"""Standard-library bootstrap for the separately installed, pinned scanner."""

import json
import os
import resource
import signal
import socket
import ssl  # Load SSL's socket subclass before blocking socket construction.
import sys
from importlib.metadata import distribution
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PIN = "704bc9544260c2f41222dc0f92982521709496ab"
VERSION = "2.11.1"


class OfflineSocket(socket.socket):
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise PermissionError("AFLAB scanner network access is disabled")


def deny_network(*args: object, **kwargs: object) -> object:
    raise PermissionError("AFLAB scanner network access is disabled")


def gateway_network(port: int) -> None:
    """Permit only the owned numeric loopback endpoint and local socket pairs."""
    resolve = socket.getaddrinfo

    def check(address: object) -> None:
        if address != ("127.0.0.1", port):
            raise PermissionError("Semantic scanner may connect only to its gateway")

    class GatewaySocket(socket.socket):
        def __init__(
            self,
            family: int = socket.AF_INET,
            type: int = socket.SOCK_STREAM,
            proto: int = 0,
            fileno: int | None = None,
        ) -> None:
            if (
                family not in (socket.AF_INET, socket.AF_UNIX)
                or type != socket.SOCK_STREAM
            ):
                raise PermissionError("Only stream gateway sockets are permitted")
            super().__init__(family, type, proto, fileno)

        def connect(self, address: Any) -> None:
            check(address)
            super().connect(address)

        def connect_ex(self, address: Any) -> int:
            check(address)
            return super().connect_ex(address)

        def sendto(self, *args: Any) -> int:
            raise PermissionError("Datagram network access is disabled")

        def sendmsg(self, *args: Any, **kwargs: Any) -> int:
            raise PermissionError("Addressed message access is disabled")

        def bind(self, address: Any) -> None:
            raise PermissionError("Scanner listeners are disabled")

        def listen(self, backlog: int = 0) -> None:
            raise PermissionError("Scanner listeners are disabled")

    def gateway_resolve(host: Any, service: Any, *args: Any, **kwargs: Any) -> Any:
        check((host, int(service)))
        return resolve(host, service, *args, **kwargs)

    socket.socket = GatewaySocket  # type: ignore[misc]
    socket.getaddrinfo = gateway_resolve  # type: ignore[assignment]


def main() -> None:
    # This is a Python socket boundary, not an operating-system sandbox.
    _ = ssl.SSLSocket
    semantic = len(sys.argv) == 6
    if semantic:
        endpoint = urlparse(sys.argv[3])
        if (
            endpoint.scheme != "http"
            or endpoint.hostname != "127.0.0.1"
            or endpoint.port is None
        ):
            raise ValueError("Invalid semantic gateway URL")
        gateway_network(endpoint.port)
        os.environ.update(
            {
                "SKILLSPECTOR_PROVIDER": "ollama",
                "SKILLSPECTOR_MODEL": sys.argv[4],
                "OLLAMA_BASE_URL": sys.argv[3],
                "SKILLSPECTOR_MODEL_REGISTRY": sys.argv[5],
                "SKILLSPECTOR_MAX_LLM_CONCURRENCY": "1",
                "SKILLSPECTOR_TEMPERATURE": "0",
                "SKILLSPECTOR_STRICT_MODEL_VALIDATION": "true",
            }
        )
        # Registry override is project-owned data, never an edit to upstream code.
        if not Path(sys.argv[5]).is_file():
            raise ValueError("Missing explicit model token registry")
    else:
        socket.socket = OfflineSocket  # type: ignore[misc]
    resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 * 1024, 4 * 1024 * 1024))
    if not semantic:
        socket.create_connection = deny_network  # type: ignore[assignment]
        socket.getaddrinfo = deny_network  # type: ignore[assignment]
    installed = distribution("skillspector")
    provenance = json.loads(installed.read_text("direct_url.json") or "{}")
    commit = provenance.get("vcs_info", {}).get("commit_id")
    if installed.version != VERSION or commit != PIN:
        raise ValueError("Scanner installation does not match the approved Git pin")
    if sys.argv[1:] == ["doctor"]:
        print(json.dumps({"version": installed.version, "commit": commit}))
        return
    if len(sys.argv) != 3 and not semantic:
        raise ValueError("Expected an input snapshot and an output report path")
    # This fallback also bounds a scanner whose controller was killed abruptly.
    signal.setitimer(signal.ITIMER_REAL, 180 if semantic else 60)
    # Import only after network blocking and installation identity verification.
    from skillspector.cli import app  # type: ignore[import-not-found]

    app(
        args=[
            "scan",
            sys.argv[1],
            *([] if semantic else ["--no-llm"]),
            "--format",
            "json",
            "--fail-on-incomplete",
            "--output",
            sys.argv[2],
        ],
        prog_name="skillspector",
    )


if __name__ == "__main__":
    main()
