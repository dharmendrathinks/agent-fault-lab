"""Explicit four-run restart smoke: two controls and two barrier-driven crashes."""

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep

from pydantic import JsonValue

from agent_fault_lab.journal import atomic_json, run_lock


def check_restart(output: Path, *, live: bool) -> None:
    output = output.resolve()
    output.mkdir()
    mode = "--live" if live else "--offline"
    commands = [sys.executable, "-m", "agent_fault_lab.cli"]
    entries: list[dict[str, JsonValue]] = []
    error = None
    try:
        for index, point in enumerate(("assistant-checkpoint", "after-commit"), 1):
            baseline = output / f"{index}-uninterrupted-{point}"
            resumed = output / f"{index}-resumed-{point}"
            run = [
                *commands,
                "reliability",
                "run",
                "restart-healthy",
                "--policy",
                "bounded-retry",
                mode,
                "--output",
            ]
            subprocess.run([*run, str(baseline)], check=True)
            entries.append({"directory": baseline.name, "kind": "uninterrupted"})
            process = subprocess.Popen(
                [*run, str(resumed), "--pause-at", point],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            worker_pid = None
            try:
                deadline = monotonic() + 60
                while monotonic() < deadline:
                    ready = resumed / "barrier-ready.json"
                    if ready.exists():
                        barrier = json.loads(ready.read_text())
                        if barrier["point"] != point or type(barrier["pid"]) is not int:
                            raise ValueError("Unexpected crash barrier")
                        worker_pid = barrier["pid"]
                        break
                    if process.poll() is not None:
                        stdout, stderr = process.communicate()
                        raise RuntimeError(f"Barrier not reached: {stdout}\n{stderr}")
                    sleep(0.01)
                else:
                    raise RuntimeError(
                        "Timed out waiting for an explicit crash barrier"
                    )
                process.kill()
                stdout, stderr = process.communicate()
                (resumed / "controller-stdout.txt").write_text(stdout)
                (resumed / "controller-stderr.txt").write_text(stderr)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
                if worker_pid is not None and worker_pid != process.pid:
                    try:
                        os.kill(worker_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            deadline = monotonic() + 5
            while True:
                try:
                    with run_lock(resumed):
                        break
                except ValueError:
                    if monotonic() >= deadline:
                        raise
                    sleep(0.01)
            atomic_json(
                resumed / "controller.json",
                {
                    "schema_version": 1,
                    "artifact": "crash-controller",
                    "point": point,
                    "signal": "SIGKILL",
                    "runner_pid": process.pid,
                    "worker_pid": worker_pid,
                    "runner_returncode": process.returncode,
                    "ownership_released": True,
                },
            )
            subprocess.run([*commands, "resume", str(resumed), mode], check=True)
            entries.append(
                {"directory": resumed.name, "kind": "crash-resume", "point": point}
            )
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        atomic_json(
            output / "controller.json",
            {
                "schema_version": 1,
                "artifact": "restart-smoke-controller",
                "mode": mode,
                "planned_runs": 4,
                "completed": [entry for entry in entries],
                "error": error,
            },
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--offline", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    check_restart(args.output, live=args.live)
