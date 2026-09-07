"""One controlled fault at the validated create boundary, never in the evaluator."""

from typing import Literal
from uuid import uuid4

from agent_fault_lab.tasks import Task, TaskStore
from agent_fault_lab.trace import Recorder

type FaultMode = Literal["none", "dropped-write"]


class FaultInjector:
    def __init__(self, mode: FaultMode, recorder: Recorder) -> None:
        if mode not in ("none", "dropped-write"):
            raise ValueError("Unknown fault mode")
        self.mode = mode
        self.recorder = recorder

    def create_task(self, store: TaskStore, title: str, call_id: str) -> Task:
        # Called only after the normal tool argument validation has passed.
        if self.mode == "none":
            return store.create_task(title)
        task = Task(id=str(uuid4()), title=title)
        self.recorder.emit(
            "fault_injected",
            fault=self.mode,
            call_id=call_id,
            fabricated_id=task.id,
            title=title,
            write_performed=False,
        )
        return task
