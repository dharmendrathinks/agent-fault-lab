"""Explicit opt-in crash-test barriers, controlled by another process."""

import json
import os
from pathlib import Path
from time import sleep

from agent_fault_lab.execution_types import PausePoint


def pause(directory: Path, selected: PausePoint | None, point: PausePoint) -> None:
    if selected != point or (directory / "barrier-used").exists():
        return
    # Exclusive marker makes the injection once-only across restart sessions.
    with (directory / "barrier-used").open("x") as marker:
        marker.write(point)
        marker.flush()
        os.fsync(marker.fileno())
    temporary = directory / "barrier-ready.tmp"
    with temporary.open("x") as stream:
        json.dump({"point": point, "pid": os.getpid()}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(directory / "barrier-ready.json")
    while not (directory / "barrier-release").exists():
        sleep(0.01)
