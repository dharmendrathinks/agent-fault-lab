"""Standalone reduction of langchain-ai/langgraph#8834; no lab imports.

Protocol: print one JSON invocation record, then (in `both` mode) await `resume`
on stdin. The controller can independently inspect storage between invocations.
All diagnostics go to stderr; the timeline survives an interrupted invocation.
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import signal
import socket
import sqlite3
import sys
import time
import tomllib
from contextlib import ExitStack, closing
from pathlib import Path
from typing import TypedDict
from uuid import uuid4


# Block Python network access before importing the framework. Not an OS sandbox.
class OfflineSocket(socket.socket):
    def __init__(self, *args, **kwargs):
        raise OSError("Network disabled in the external reproduction")


socket.socket = OfflineSocket
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"


def identity():
    from packaging.markers import Marker

    result = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": {
            d.metadata["Name"].lower().replace("_", "-"): d.version
            for d in importlib.metadata.distributions()
        },
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    packages = {
        p["name"]: p
        for p in tomllib.loads(Path(__file__).with_name("uv.lock").read_text())[
            "package"
        ]
    }
    required = {}
    visited = set()

    def visit(name, extras=()):
        key = (name, tuple(extras))
        if key in visited:
            return
        visited.add(key)
        package = packages[name]
        if "registry" in package["source"]:
            required[name] = package["version"]
        dependencies = list(package.get("dependencies", []))
        for extra in extras:
            dependencies.extend(package.get("optional-dependencies", {}).get(extra, []))
        for dep in dependencies:
            if "marker" not in dep or Marker(dep["marker"]).evaluate():
                visit(dep["name"], dep.get("extra", ()))

    visit("langgraph-8834-reproduction")
    if result["dependencies"] != required:
        raise ValueError(
            "Installed dependencies differ from active locked dependencies"
        )
    return result


class State(TypedDict):
    value: int


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("doctor", "both", "initial", "resume"))
    parser.add_argument("--backend", choices=("memory", "sqlite"), default="memory")
    parser.add_argument(
        "--condition",
        choices=("healthy", "node-failure", "router-failure"),
        default="healthy",
    )
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--thread-id")
    args = parser.parse_args()
    signal.alarm(30)  # Also bounds a worker whose controller disappears.
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.graph import END, START, StateGraph

    if args.mode == "doctor":
        print(json.dumps(identity()), flush=True)
        return
    if args.directory is None or not args.thread_id:
        parser.error("execution requires --directory and --thread-id")
    directory = args.directory
    if args.mode != "resume":
        directory.mkdir(parents=True, exist_ok=False)
        with closing(sqlite3.connect(directory / "tasks.sqlite3")) as connection:
            with connection:
                connection.execute(
                    "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT)"
                )
    elif args.backend != "sqlite" or not (directory / "checkpoints.sqlite3").is_file():
        parser.error("resume requires an existing SQLite checkpoint")

    phase = "resume" if args.mode == "resume" else "initial"
    counts = {"work": 0, "router": 0, "sink": 0}
    fault_activated = False

    def event(kind):
        with (directory / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {
                        "phase": phase,
                        "event": kind,
                        "pid": os.getpid(),
                        "monotonic": time.monotonic(),
                    }
                )
                + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())

    def fail_at(condition):
        nonlocal fault_activated
        if phase == "initial" and not fault_activated and args.condition == condition:
            fault_activated = True
            event("fault-activated")
            raise RuntimeError("injected:" + condition)

    def work(state):
        counts["work"] += 1
        event("work")
        fail_at("node-failure")
        return {"value": 1}

    def route(state):
        counts["router"] += 1
        event("router")
        fail_at("router-failure")
        return "sink"

    def sink(state):
        counts["sink"] += 1
        event("sink")
        # No idempotency safeguard: repeated executions must remain visible.
        with closing(sqlite3.connect(directory / "tasks.sqlite3")) as connection:
            with connection:
                connection.execute(
                    "INSERT INTO tasks VALUES (?, ?)",
                    (str(uuid4()), "Review the invoice."),
                )
        event("sink-committed")
        return {"value": 2}

    with ExitStack() as stack:
        saver = (
            InMemorySaver()
            if args.backend == "memory"
            else stack.enter_context(
                SqliteSaver.from_conn_string(str(directory / "checkpoints.sqlite3"))
            )
        )
        builder = StateGraph(State)
        builder.add_node("work", work)
        builder.add_node("sink", sink)
        builder.add_edge(START, "work")
        builder.add_conditional_edges("work", route, {"sink": "sink"})
        builder.add_edge("sink", END)
        graph = builder.compile(checkpointer=saver)
        config = {"configurable": {"thread_id": args.thread_id}}

        def snapshot():
            state = graph.get_state(config)
            return {
                "values": state.values,
                "pending": list(state.next),
                "task_errors": [str(t.error) for t in state.tasks if t.error],
            }

        def invoke():
            started = time.monotonic()
            before = snapshot()
            event("invoke-start")
            error = None
            returned = None
            try:
                returned = graph.invoke(
                    {"value": 0} if phase == "initial" else None, config
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            after = snapshot()
            event("invoke-end")
            record = {
                "phase": phase,
                "pid": os.getpid(),
                "before": before,
                "after": after,
                "returned": returned,
                "error": error,
                "counts": dict(counts),
                "fault_activated": fault_activated,
                "elapsed_seconds": time.monotonic() - started,
            }
            target = directory / (phase + ".json")
            with target.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(record, indent=2) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            print(json.dumps(record), flush=True)

        invoke()
        if args.mode == "both":
            if sys.stdin.readline().strip() != "resume":
                raise ValueError("Expected an explicit resume command")
            phase = "resume"
            counts = {"work": 0, "router": 0, "sink": 0}
            fault_activated = False
            invoke()


if __name__ == "__main__":
    main()
