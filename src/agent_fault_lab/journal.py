"""M09 control-state transactions and M10 authoritative event ordering."""

import fcntl
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Literal, Self
from uuid import uuid4

from pydantic import Field, JsonValue, field_validator, model_validator

from agent_fault_lab.agent import Limits
from agent_fault_lab.evaluation import Evaluation
from agent_fault_lab.execution_types import (
    ExecutionLimits,
    ExecutionState,
    ProcessConfig,
)
from agent_fault_lab.model import (
    Message,
    ModelSettings,
    ModelTurn,
    Record,
    RunResult,
    ToolCall,
)
from agent_fault_lab.trace import Event, Recorder


class Versioned(Record):
    schema_version: Literal[1] = 1

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("Unsupported execution schema version")
        return value


class RunState(Versioned):
    run_id: str
    compatibility: str
    config: ProcessConfig
    mode: Literal["offline", "live"]
    client: str
    provenance: dict[str, JsonValue]
    settings: ModelSettings
    limits: Limits = Limits()
    execution_limits: ExecutionLimits = ExecutionLimits()
    request: str
    expected_title: str
    script: Literal["create-read-report-v1", "batch-two-v1"] = "create-read-report-v1"
    script_cursor: int = Field(default=0, ge=0, le=6)
    messages: tuple[Message, ...]
    last_turn: ModelTurn | None = None
    phase: Literal["model", "tools", "terminal"] = "model"
    pending: tuple[ToolCall, ...] = ()
    tool_cursor: int = Field(default=0, ge=0)
    tool_reserved: bool = False
    model_calls: int = Field(default=0, ge=0, le=6)
    tool_calls: int = Field(default=0, ge=0, le=6)
    tool_executions: int = Field(default=0, ge=0, le=6)
    execution: ExecutionState = ExecutionState()
    terminal: RunResult | None = None
    evaluation: Evaluation | None = None
    finalized: bool = False

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.tool_cursor > len(self.pending):
            raise ValueError("Tool cursor exceeds pending calls")
        if self.phase == "tools" and (
            self.last_turn is None or self.pending != self.last_turn.tool_calls
        ):
            raise ValueError("Pending calls disagree with saved assistant response")
        if self.tool_reserved and (
            self.phase != "tools"
            or self.tool_cursor >= len(self.pending)
            or self.tool_calls == 0
        ):
            raise ValueError("Reserved tool has no pending request")
        if self.tool_executions > self.tool_calls:
            raise ValueError("Execution count exceeds accepted calls")
        if (
            self.model_calls > self.limits.max_model_calls
            or self.tool_calls > self.limits.max_tool_calls
        ):
            raise ValueError("Saved agent budgets exceed limits")
        if self.execution.total_attempts > self.execution_limits.total_attempts:
            raise ValueError("Saved attempt budget exceeds limit")
        op = self.execution.active
        if op and (
            op.attempts > self.execution_limits.max_attempts
            or op.attempts > self.execution.total_attempts
            or op.reserved_seconds > op.remaining_seconds
            or op.remaining_seconds > self.execution_limits.operation_seconds
        ):
            raise ValueError("Invalid saved operation budget")
        if (self.phase == "terminal") != (self.terminal is not None):
            raise ValueError("Terminal checkpoint and phase disagree")
        if self.finalized and (self.terminal is None or self.evaluation is None):
            raise ValueError("Finalized run lacks evaluation")
        if self.terminal and (
            self.terminal.model_calls,
            self.terminal.tool_calls,
            self.terminal.tool_executions,
        ) != (self.model_calls, self.tool_calls, self.tool_executions):
            raise ValueError("Terminal counts disagree with journal")
        if self.evaluation and self.evaluation.execution != self.terminal:
            raise ValueError("Evaluation disagrees with terminal checkpoint")
        return self


def strict_json(raw: str) -> JsonValue:
    def unique(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject(value: str) -> JsonValue:
        raise ValueError(f"Non-finite JSON number: {value}")

    value: JsonValue = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    return value


class JournalEvent(Versioned):
    run_id: str
    session_id: str
    sequence: int = Field(ge=1)
    wall_time: str
    elapsed_seconds: float = Field(ge=0)
    kind: str
    call_id: str | None = None
    operation_id: str | None = None
    attempt_id: str | None = None
    data: dict[str, JsonValue]


@contextmanager
def run_lock(directory: Path, *, create: bool = False) -> Iterator[int]:
    path = directory / "run.lock"
    if path.is_symlink():
        raise ValueError("Run lock must not be a symlink")
    with path.open("x+b" if create else "r+b") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Run is still owned by a runner or tool worker") from exc
        try:
            yield stream.fileno()
        finally:
            # Closing (without LOCK_UN) retains the inherited lock if a worker
            # outlives the runner. flock's ownership follows the open description.
            pass


def regular(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Expected an existing regular file: {path.name}")


class Journal:
    def __init__(self, directory: Path, *, initial: RunState | None = None) -> None:
        self.directory = directory
        self.path = directory / "journal.sqlite3"
        if initial is None:
            regular(self.path)
        elif self.path.exists():
            raise FileExistsError(self.path)
        mode = "rwc" if initial else "rw"
        with closing(
            sqlite3.connect(
                f"{self.path.as_uri()}?mode={mode}", uri=True, autocommit=False
            )
        ) as conn:
            with conn:
                if initial:
                    conn.execute(
                        "CREATE TABLE checkpoint (id INTEGER PRIMARY KEY CHECK(id=1), "
                        "state TEXT NOT NULL)"
                    )
                    conn.execute(
                        "CREATE TABLE events (sequence INTEGER PRIMARY KEY, "
                        "event TEXT NOT NULL)"
                    )
                    conn.execute(
                        "INSERT INTO checkpoint VALUES (1, ?)",
                        (initial.model_dump_json(),),
                    )
        self.state = self.read_state(self.path)

    @staticmethod
    def read_state(path: Path) -> RunState:
        regular(path)
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as conn:
            rows = conn.execute("SELECT id, state FROM checkpoint").fetchall()
        if len(rows) != 1 or rows[0][0] != 1:
            raise ValueError("Missing or ambiguous journal checkpoint")
        strict_json(rows[0][1])
        return RunState.model_validate_json(rows[0][1])

    @staticmethod
    def read_events(path: Path) -> tuple[JournalEvent, ...]:
        regular(path)
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as conn:
            rows = conn.execute(
                "SELECT sequence, event FROM events ORDER BY sequence"
            ).fetchall()
        for row in rows:
            strict_json(row[1])
        events = tuple(JournalEvent.model_validate_json(row[1]) for row in rows)
        if any(
            row[0] != event.sequence or event.sequence != index
            for index, (row, event) in enumerate(zip(rows, events, strict=True), 1)
        ):
            raise ValueError("Journal event sequence is incomplete or inconsistent")
        return events

    def commit(self, event: JournalEvent, state: RunState | None = None) -> None:
        # Revalidate copies: model_copy is intentionally not a validation boundary.
        if state is not None:
            state = RunState.model_validate_json(state.model_dump_json())
        with closing(
            sqlite3.connect(f"{self.path.as_uri()}?mode=rw", uri=True, autocommit=False)
        ) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO events VALUES (?, ?)",
                    (event.sequence, event.model_dump_json()),
                )
                if state is not None:
                    conn.execute(
                        "UPDATE checkpoint SET state = ? WHERE id=1",
                        (state.model_dump_json(),),
                    )
        if state is not None:
            self.state = state


class JournalRecorder(Recorder):
    """Commit first; append JSONL as an explicitly fallible readable projection."""

    def __init__(self, journal: Journal) -> None:
        super().__init__()
        self.journal = journal
        self.session_id = str(uuid4())
        self.started = monotonic()
        self.records = list(Journal.read_events(journal.path))
        if any(e.run_id != journal.state.run_id for e in self.records):
            raise ValueError("Journal events belong to a different run")
        self.events = [
            Event(
                sequence=e.sequence,
                elapsed_seconds=e.elapsed_seconds,
                kind=e.kind,
                data=e.data,
            )
            for e in self.records
        ]

    def transition(self, state: RunState | None, kind: str, **data: JsonValue) -> None:
        identifiers = {
            key: data.pop(key, None)
            for key in ("call_id", "operation_id", "attempt_id")
        }
        event = JournalEvent(
            run_id=self.journal.state.run_id,
            session_id=self.session_id,
            sequence=len(self.records) + 1,
            wall_time=datetime.now(UTC).isoformat(),
            elapsed_seconds=monotonic() - self.started,
            kind=kind,
            data=data,
            **identifiers,  # type: ignore[arg-type]
        )
        self.journal.commit(event, state)
        self.records.append(event)
        self.events.append(
            Event(
                sequence=event.sequence,
                elapsed_seconds=event.elapsed_seconds,
                kind=kind,
                data=data,
            )
        )
        projection = self.journal.directory / "trace.jsonl"
        if projection.is_symlink():
            raise ValueError("Trace projection must not be a symlink")
        with projection.open("a", encoding="utf-8") as stream:
            stream.write(event.model_dump_json() + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def emit(self, kind: str, **data: JsonValue) -> None:
        self.transition(None, kind, **data)


def atomic_json(path: Path, value: JsonValue) -> None:
    if path.is_symlink():
        raise ValueError(f"Refusing symlink output: {path.name}")
    temporary = path.with_name(f".{path.name}.{uuid4()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
