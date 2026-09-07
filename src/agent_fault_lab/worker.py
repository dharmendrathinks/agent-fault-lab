"""Allowlisted offline tool worker. stdout is only the model-facing envelope."""

import os
import signal
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from time import sleep
from unittest.mock import patch

from agent_fault_lab.barriers import pause
from agent_fault_lab.contracts import ResponseEnvelope, TaskValue, error_response
from agent_fault_lab.execution_types import WorkerRequest
from agent_fault_lab.tasks import OperationConflict, Task, TaskStore
from agent_fault_lab.tools import CreateArguments, GetArguments
from agent_fault_lab.trace import Recorder


def perform(request: WorkerRequest, recorder: Recorder) -> str:
    directory = Path(request.run_directory)

    class BarrierStore(TaskStore):
        @contextmanager
        def _connection(
            self, *, create: bool = False, immediate: bool = False
        ) -> Iterator[sqlite3.Connection]:
            with super()._connection(create=create, immediate=immediate) as conn:
                yield conn
                if immediate:
                    pause(directory, request.pause_at, "transaction")

    call = request.call
    if call.name not in {"create_task", "get_task"}:
        return error_response("unknown_tool", "Unknown tool")
    args = (
        CreateArguments.model_validate(call.arguments)
        if call.name == "create_task"
        else GetArguments.model_validate(call.arguments)
    )
    # An attempt may open only the existing experiment file; no silent recreation.
    if not Path(request.database).is_file():
        return error_response("storage_error", "Task database is missing")
    if request.fault != "none":
        recorder.emit("fault_activated", fault=request.fault)
    if request.fault == "transient":
        return error_response("transient_error", "Tool temporarily unavailable")
    if request.fault == "permanent":
        return error_response("storage_error", "Permanent tool failure")
    if request.fault == "ignore-termination":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        recorder.emit("termination_ignored")
    if request.fault in {"delay-before", "ignore-termination"}:
        recorder.emit("delay_started", position="before_write")
        sleep(request.delay_seconds)
    recorder.emit("storage_entered")
    task: Task | None
    try:
        store = BarrierStore(Path(request.database))
        if isinstance(args, CreateArguments):
            receipt = store.create_task_idempotent(args.title, request.operation_id)
            task = receipt.task
            recorder.emit(
                "storage_committed", task_id=task.id, replayed=receipt.replayed
            )
            pause(directory, request.pause_at, "after-commit")
        else:
            task = store.get_task(args.task_id)
            recorder.emit("storage_read", task_id=task.id if task else None)
    except OperationConflict as exc:
        return error_response("operation_conflict", str(exc))
    except sqlite3.Error as exc:
        return error_response("storage_error", f"{type(exc).__name__}: {exc}")
    if request.fault == "delay-after":
        recorder.emit("delay_started", position="after_commit")
        sleep(request.delay_seconds)
    if request.fault == "exit":
        os._exit(7)
    if request.fault == "malformed":
        return "{invalid"
    return ResponseEnvelope(
        schema_version=1,
        ok=True,
        value=TaskValue(id=task.id, title=task.title) if task else None,
        error=None,
    ).model_dump_json()


def main() -> int:
    request = WorkerRequest.model_validate_json(sys.stdin.buffer.read())
    with Path(request.evidence).open("x", encoding="utf-8") as stream:
        recorder = Recorder(stream)
        recorder.emit("worker_started", pid=os.getpid())
        # pytest's socket guard does not cross exec; every tool worker blocks its
        # own sockets, including workers dispatched by a live model conversation.
        with patch("socket.socket", side_effect=AssertionError("Worker is offline")):
            content = perform(request, recorder)
        recorder.emit("worker_completed")
        sys.stdout.write(content)
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
