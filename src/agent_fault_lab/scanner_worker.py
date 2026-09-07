"""Standard-library bootstrap for the separately installed, pinned scanner."""

import json
import resource
import socket
import ssl  # Load SSL's socket subclass before blocking socket construction.
import sys
from importlib.metadata import distribution

PIN = "704bc9544260c2f41222dc0f92982521709496ab"
VERSION = "2.11.1"


class OfflineSocket(socket.socket):
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise PermissionError("AFLAB scanner network access is disabled")


def deny_network(*args: object, **kwargs: object) -> object:
    raise PermissionError("AFLAB scanner network access is disabled")


def main() -> None:
    # This is a Python socket boundary, not an operating-system sandbox.
    _ = ssl.SSLSocket
    socket.socket = OfflineSocket  # type: ignore[misc]
    resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 * 1024, 4 * 1024 * 1024))
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
    if len(sys.argv) != 3:
        raise ValueError("Expected an input snapshot and an output report path")
    # Import only after network blocking and installation identity verification.
    from skillspector.cli import app  # type: ignore[import-not-found]

    app(
        args=[
            "scan",
            sys.argv[1],
            "--no-llm",
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
