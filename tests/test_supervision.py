"""Real subprocess effects plus fake-time admission and exhaustion checks."""

import json
from collections.abc import Callable
from pathlib import Path
from time import monotonic, sleep
from unittest.mock import patch

import pytest

from agent_fault_lab.contracts import ResponseEnvelope
from agent_fault_lab.evaluation import inspect_state
from agent_fault_lab.execution_types import (
    ExecutionLimits,
    ProcessCase,
    ProcessConfig,
    ProcessPolicy,
)
from agent_fault_lab.model import ToolCall
from agent_fault_lab.supervision import Supervisor
from agent_fault_lab.tasks import TaskStore
from agent_fault_lab.trace import Recorder

CREATE = ToolCall(name="create_task", arguments={"title": "Review the invoice"})


def supervisor(
    tmp_path: Path,
    case: ProcessCase,
    policy: ProcessPolicy = "bounded-retry",
    *,
    limits: ExecutionLimits | None = None,
    clock: Callable[[], float] = monotonic,
    sleeper: Callable[[float], None] = sleep,
) -> Supervisor:
    TaskStore(tmp_path / "tasks.sqlite3")
    return Supervisor(
        tmp_path,
        Recorder(),
        ProcessConfig(case=case, policy=policy),
        limits=limits,
        clock=clock,
        sleeper=sleeper,
    )


@pytest.mark.parametrize(
    "case,attempts,rows,ok",
    [
        ("process-healthy", 1, 1, True),
        ("transient-once", 2, 1, True),
        ("transient-twice", 3, 1, True),
        ("transient-always", 3, 0, False),
        ("permanent-error", 1, 0, False),
        ("exit-before-reply", 2, 1, True),
        ("malformed-worker", 1, 1, False),
    ],
)
def test_worker_cases(
    tmp_path: Path, case: ProcessCase, attempts: int, rows: int, ok: bool
) -> None:
    runner = supervisor(tmp_path, case)
    response = ResponseEnvelope.model_validate_json(
        runner.execute(CREATE, "c1").content
    )
    assert response.ok == ok and runner.state.total_attempts == attempts
    state = inspect_state(tmp_path / "tasks.sqlite3")
    assert state.rows is not None and len(state.rows) == rows
    assert runner.worker is None
    exits = [e for e in runner.recorder.events if e.kind == "worker_exit_confirmed"]
    assert len(exits) == attempts
    assert all(e.data["returncode"] is not None for e in exits)


@pytest.mark.parametrize("case", ["delay-before-write", "delay-after-commit"])
@pytest.mark.parametrize("policy", ["observe", "terminate"])
def test_deadline_is_distinct_from_cancellation_and_commit(
    tmp_path: Path, case: ProcessCase, policy: ProcessPolicy
) -> None:
    runner = supervisor(
        tmp_path,
        case,
        policy,
        limits=ExecutionLimits(
            attempt_seconds=1.0, delay_seconds=1.5, grace_seconds=0.1
        ),
    )
    response = ResponseEnvelope.model_validate_json(
        runner.execute(CREATE, "c1").content
    )
    assert response.ok == (policy == "observe")
    state = inspect_state(tmp_path / "tasks.sqlite3")
    assert state.rows is not None
    assert len(state.rows) == (policy == "observe" or case == "delay-after-commit")
    kinds = [e.kind for e in runner.recorder.events]
    assert "deadline_expired" in kinds and "worker_exit_confirmed" in kinds
    assert ("late_response" in kinds) == (policy == "observe")
    assert ("cancellation_requested" in kinds) == (policy == "terminate")
    assert runner.worker is None


def test_ignored_termination_requires_kill(tmp_path: Path) -> None:
    runner = supervisor(
        tmp_path,
        "ignore-termination",
        "terminate",
        limits=ExecutionLimits(
            attempt_seconds=1.0, delay_seconds=2.0, grace_seconds=0.1
        ),
    )
    runner.execute(CREATE, "c1")
    assert "kill_requested" in [e.kind for e in runner.recorder.events]
    assert inspect_state(tmp_path / "tasks.sqlite3").rows == ()
    assert runner.worker is None


def test_invalid_arguments_never_dispatch(tmp_path: Path) -> None:
    runner = supervisor(tmp_path, "transient-once")
    with patch.object(runner, "dispatch", side_effect=AssertionError("forbidden")):
        result = runner.execute(
            ToolCall(name="create_task", arguments={"title": " "}), "c1"
        )
    assert not result.executed and runner.state.total_attempts == 0
    assert runner.state.fault_cursor == 0


def test_backoff_charges_elapsed_time_and_stops_before_dispatch(tmp_path: Path) -> None:
    now = [0.0]

    def slow_sleep(seconds: float) -> None:
        now[0] += 9.0

    runner = supervisor(
        tmp_path, "transient-always", clock=lambda: now[0], sleeper=slow_sleep
    )
    with patch.object(
        runner, "dispatch", return_value=(None, "delivery_error")
    ) as dispatch:
        result = runner.execute(CREATE, "c1")
    assert dispatch.call_count == 1
    assert json.loads(result.content)["error"]["code"] == "execution_limit"


def test_interrupt_reaps_the_worker(tmp_path: Path) -> None:
    runner = supervisor(tmp_path, "process-healthy")
    import subprocess

    real = subprocess.Popen.communicate
    calls = 0

    def interrupt_once(
        process: subprocess.Popen[bytes], *args: object, **kwargs: object
    ) -> tuple[bytes, bytes]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise KeyboardInterrupt
        return real(process, *args, **kwargs)  # type: ignore[arg-type,return-value]

    with patch.object(subprocess.Popen, "communicate", interrupt_once):
        with pytest.raises(KeyboardInterrupt):
            runner.execute(CREATE, "c1")
    assert runner.worker is None
    assert any(e.kind == "worker_exit_confirmed" for e in runner.recorder.events)


def test_worker_blocks_its_own_sockets(tmp_path: Path) -> None:
    import subprocess
    import sys

    # Invoke the real entry point, replacing only its task function in the child.
    script = """
import socket
from agent_fault_lab import worker
def probe(request, recorder):
    try:
        socket.socket()
    except AssertionError:
        return 'blocked'
    raise AssertionError('socket was allowed')
worker.perform = probe
worker.main()
"""
    request = {
        "database": str(tmp_path / "unused"),
        "evidence": str(tmp_path / "worker.jsonl"),
        "operation_id": "o",
        "attempt_id": "a",
        "call": CREATE.model_dump(),
        "fault": "none",
        "delay_seconds": 1.0,
        "run_directory": str(tmp_path),
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout == "blocked"


def test_commit_racing_cancellation_preserves_atomic_effect(tmp_path: Path) -> None:
    TaskStore(tmp_path / "tasks.sqlite3")
    runner = Supervisor(
        tmp_path,
        Recorder(),
        ProcessConfig(case="process-healthy", policy="process-single"),
        limits=ExecutionLimits(attempt_seconds=1.0, grace_seconds=0.1),
        pause_at="transaction",
    )
    emit = runner.emit

    def release_at_deadline(kind: str, **data: str | int | float | bool | None) -> None:
        emit(kind, **data)
        if kind == "deadline_expired":
            assert (tmp_path / "barrier-ready.json").exists()
            (tmp_path / "barrier-release").touch()

    with patch.object(runner, "emit", side_effect=release_at_deadline):
        response = runner.execute(CREATE, "race")
    assert json.loads(response.content)["error"]["code"] == "deadline_exceeded"
    # Either signal delivery or commit may win; assert atomicity, not invented
    # ordering. No evaluator snapshot is taken until the worker was reaped.
    rows = inspect_state(tmp_path / "tasks.sqlite3").rows
    assert rows is not None and len(rows) in {0, 1}
    assert runner.worker is None
    if rows:
        assert runner.state.active is not None
        receipt = TaskStore(tmp_path / "tasks.sqlite3").create_task_idempotent(
            "Review the invoice", runner.state.active.operation_id
        )
        assert receipt.replayed and receipt.task.id == rows[0].id
