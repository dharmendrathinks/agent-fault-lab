"""Pinned runtime worker with explicit network boundaries and a physical timer."""

import json
import platform
import resource
import signal
import socket
import ssl
import sys
import time
from importlib.metadata import distributions, version
from pathlib import Path
from types import FrameType
from typing import Literal, cast

from agent_fault_lab.boundaries import run_boundary
from agent_fault_lab.boundary_records import BoundaryJournal
from agent_fault_lab.journal import atomic_json
from agent_fault_lab.runtime_records import (
    RuntimeResult,
    render_runtime,
    runtime_config,
)


def main() -> None:
    _ = ssl.SSLSocket
    if sys.argv[1] == "doctor":
        import langgraph.graph  # type: ignore[import-not-found]  # noqa: F401

        from agent_fault_lab.study_records import fingerprint

        print(
            json.dumps(
                {
                    "langgraph": version("langgraph"),
                    "source_sha256": fingerprint()["source_sha256"],
                    "python": ".".join(platform.python_version_tuple()[:2]),
                    "dependencies": {
                        d.metadata["Name"]: d.version for d in distributions()
                    },
                }
            )
        )
        return
    runtime, case, mode, output, raw_identity, raw_deadline = sys.argv[2:]
    if runtime not in ("native", "langgraph") or mode not in ("offline", "live"):
        raise ValueError("Unsupported runtime or mode")
    if mode == "live":
        from agent_fault_lab.scanner_worker import gateway_network

        gateway_network(11434)
    else:
        from agent_fault_lab.scanner_worker import OfflineSocket

        socket.socket = OfflineSocket  # type: ignore[misc]

    def expire(signum: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt("Runtime worker deadline or termination")

    signal.signal(signal.SIGALRM, expire)
    signal.signal(signal.SIGTERM, expire)
    deadline = float(raw_deadline)
    if not 0 < deadline <= 450.0:
        raise ValueError("Runtime deadline must be positive and at most 450 seconds")
    signal.setitimer(signal.ITIMER_REAL, deadline)
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
    from agent_fault_lab.langgraph_runtime import run_graph

    started = time.monotonic()
    directory = Path(output)
    identity = json.loads(raw_identity)
    evaluation = run_boundary(
        directory,
        runtime_config(case, cast(Literal["offline", "live"], mode)),
        driver=run_graph if runtime == "langgraph" else None,
        runtime_identity={**identity, "runtime": runtime},
    )
    nodes = tuple(
        str(event.data["node"])
        for event in BoundaryJournal.events(directory / "boundary.sqlite3")
        if event.kind == "runtime_node"
    )
    result = RuntimeResult(
        runtime=cast(Literal["native", "langgraph"], runtime),
        identity=identity,
        evaluation=evaluation,
        elapsed_seconds=time.monotonic() - started,
        nodes=nodes,
    )
    atomic_json(directory / "runtime.json", result.model_dump(mode="json"))
    (directory / "report.md").write_text(render_runtime(result), encoding="utf-8")


if __name__ == "__main__":
    main()
