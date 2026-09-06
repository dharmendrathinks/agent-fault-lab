"""Basic JSONL evidence, flushed before and after each observable operation."""

import json
from time import monotonic
from typing import TextIO

from pydantic import JsonValue

from agent_fault_lab.model import Record


class Event(Record):
    sequence: int
    elapsed_seconds: float
    kind: str
    data: dict[str, JsonValue]


class Recorder:
    """Optional file sink; the caller owns its lifetime and opens it exclusively."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.events: list[Event] = []
        self._stream = stream
        self._started = monotonic()

    def emit(self, kind: str, **data: JsonValue) -> None:
        # Snapshot mutable dictionaries, so later edits cannot rewrite history.
        snapshot = json.loads(json.dumps(data, ensure_ascii=False, allow_nan=False))
        event = Event(
            sequence=len(self.events) + 1,
            elapsed_seconds=monotonic() - self._started,
            kind=kind,
            data=snapshot,
        )
        if self._stream is not None:
            self._stream.write(event.model_dump_json() + "\n")
            self._stream.flush()
        self.events.append(event)
