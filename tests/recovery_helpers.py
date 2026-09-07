"""Parent-owned crash controller: explicit barriers, never timed kill guesses."""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep

from agent_fault_lab.execution_types import PausePoint
from agent_fault_lab.journal import run_lock


def wait_barrier(directory: Path, process: subprocess.Popen[str]) -> dict[str, object]:
    deadline = monotonic() + 20
    while monotonic() < deadline:
        ready = directory / "barrier-ready.json"
        if ready.exists():
            result: dict[str, object] = json.loads(ready.read_text())
            return result
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(f"Runner exited before barrier: {stdout}\n{stderr}")
        sleep(0.01)
    raise AssertionError("Explicit barrier was not reached")


def paused_run(directory: Path, point: PausePoint) -> tuple[subprocess.Popen[str], int]:
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "agent_fault_lab.cli",
            "reliability",
            "run",
            "restart-healthy",
            "--policy",
            "bounded-retry",
            "--offline",
            "--output",
            str(directory),
            "--pause-at",
            point,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        barrier = wait_barrier(directory, process)
        assert barrier["point"] == point
        pid = barrier["pid"]
        assert type(pid) is int
        return process, pid
    except BaseException:
        process.kill()
        process.communicate()
        raise


def crash(process: subprocess.Popen[str], worker_pid: int) -> None:
    process.kill()
    process.communicate()
    if worker_pid != process.pid:
        try:
            os.kill(worker_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def await_unowned(directory: Path) -> None:
    deadline = monotonic() + 5
    while monotonic() < deadline:
        try:
            with run_lock(directory):
                return
        except ValueError:
            sleep(0.01)
    raise AssertionError("Killed owner did not release the run lock")
