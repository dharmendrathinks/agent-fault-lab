"""Versioned M11 checkpoints and evidence, separate from legacy run schemas."""

import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, JsonValue, model_validator

from agent_fault_lab.claims import ParsedClaim
from agent_fault_lab.context_cases import (
    M12_CASES,
    M13_CASES,
    ContextAssessment,
    ContextSetup,
)
from agent_fault_lab.evaluation import StateInspection
from agent_fault_lab.journal import Versioned, regular, strict_json
from agent_fault_lab.model import Message, ModelSettings, RunResult, ToolCall
from agent_fault_lab.scanner import ScanResult

type Case = Literal[
    "manual",
    "approved",
    "missing",
    "rejected",
    "expired",
    "changed-arguments",
    "changed-revision",
    "cross-operation",
    "replay",
]
CASES: tuple[Case, ...] = (
    "manual",
    "approved",
    "missing",
    "rejected",
    "expired",
    "changed-arguments",
    "changed-revision",
    "cross-operation",
    "replay",
)


class BoundaryConfig(Versioned):
    case: str
    permission_policy: Literal["enforce", "audit"] = "enforce"
    scan_policy: Literal["enforce", "audit"] = "enforce"
    mode: Literal["offline", "live"] = "offline"
    surface: Literal["skill", "task", "tool"] = "skill"
    context_policy: Literal["cached", "refresh"] = "cached"

    @model_validator(mode="after")
    def supported(self) -> Self:
        if self.case not in (*CASES, *M12_CASES, *M13_CASES):
            raise ValueError("Unknown boundary case")
        if self.case not in M12_CASES and self.surface != "skill":
            raise ValueError("Delivery surfaces apply only to M12")
        if self.case not in M13_CASES and self.context_policy != "cached":
            raise ValueError("Authoritative refresh applies only to M13")
        return self


class BoundaryState(Versioned):
    artifact: Literal["boundary-state"] = "boundary-state"
    run_id: str
    compatibility: str
    config: BoundaryConfig
    expected_title: str
    settings: ModelSettings = ModelSettings()
    provenance: dict[str, JsonValue]
    scan: ScanResult
    messages: tuple[Message, ...]
    status: Literal["running", "awaiting_approval", "blocked", "finished", "error"] = (
        "running"
    )
    pending: tuple[ToolCall, ...] = ()
    cursor: int = Field(default=0, ge=0)
    reserved: bool = False
    operation_id: str | None = None
    configured_operations: tuple[str, ...] = ()
    model_calls: int = Field(default=0, ge=0, le=6)
    tool_calls: int = Field(default=0, ge=0, le=6)
    tool_executions: int = Field(default=0, ge=0, le=6)
    terminal: RunResult | None = None
    error: str | None = None
    context: ContextSetup | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        expected = (
            "M12"
            if self.config.case in M12_CASES
            else "M13"
            if self.config.case in M13_CASES
            else None
        )
        if (self.context.milestone if self.context else None) != expected:
            raise ValueError("Context checkpoint does not match the experiment")
        if self.context and self.context.expected_title != self.expected_title:
            raise ValueError("Context request disagrees with run request")
        if self.cursor > len(self.pending) or self.tool_executions > self.tool_calls:
            raise ValueError("Invalid pending tool cursor or accounting")
        if self.reserved and (
            self.cursor >= len(self.pending) or not self.operation_id
        ):
            raise ValueError("Tool reservation has no pending operation")
        if self.status == "awaiting_approval" and not self.reserved:
            raise ValueError("Approval wait has no pending operation")
        if (self.status == "finished") != (self.terminal is not None):
            raise ValueError("Terminal checkpoint disagrees with status")
        return self


class BoundaryEvent(Versioned):
    sequence: int = Field(ge=1)
    wall_time: float
    kind: str
    data: dict[str, JsonValue]


class AuthorizationInspection(Versioned):
    status: Literal["held", "violated", "unknown"]
    authorized_writes: int | None
    unauthorized_writes: int | None
    proposals: tuple[dict[str, JsonValue], ...] = ()
    error: str | None = None
    unauthorized_task_ids: tuple[str, ...] = ()


class BoundaryEvaluation(Versioned):
    artifact: Literal["boundary-evaluation"] = "boundary-evaluation"
    run_id: str
    config: BoundaryConfig
    status: str
    expected_title: str
    scan: ScanResult
    execution: RunResult | None
    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    tool_executions: int = Field(ge=0)
    write_attempts: int = Field(ge=0)
    replay_requests: int = Field(ge=0)
    scenario_exercised: bool
    state: StateInspection
    authorization: AuthorizationInspection
    report: ParsedClaim
    task_outcome: Literal["completed", "not_completed", "unknown"]
    claim_support: Literal[
        "supported", "contradicted", "not_asserted", "unknown", "not_evaluated"
    ]
    error: str | None
    context: ContextAssessment | None = None

    @model_validator(mode="after")
    def matching_context(self) -> Self:
        expected = (
            "M12"
            if self.config.case in M12_CASES
            else "M13"
            if self.config.case in M13_CASES
            else None
        )
        if (self.context.milestone if self.context else None) != expected:
            raise ValueError("Context evaluation does not match its experiment")
        return self


class BoundaryJournal:
    def __init__(self, directory: Path, initial: BoundaryState | None = None) -> None:
        self.directory = directory
        self.path = directory / "boundary.sqlite3"
        if initial is not None:
            if self.path.exists() or self.path.is_symlink():
                raise FileExistsError(self.path)
            with closing(sqlite3.connect(self.path)) as conn, conn:
                conn.execute(
                    "CREATE TABLE checkpoint (id INTEGER PRIMARY KEY CHECK(id=1), "
                    "state TEXT NOT NULL)"
                )
                conn.execute(
                    "CREATE TABLE events (sequence INTEGER PRIMARY KEY, "
                    "event TEXT NOT NULL)"
                )
                conn.execute(
                    "INSERT INTO checkpoint VALUES (1,?)", (initial.model_dump_json(),)
                )
        self.state = self.read_state(self.path)

    @staticmethod
    def read_state(path: Path) -> BoundaryState:
        regular(path)
        with closing(
            sqlite3.connect(f"{path.absolute().as_uri()}?mode=ro", uri=True)
        ) as conn:
            rows = conn.execute("SELECT id,state FROM checkpoint").fetchall()
        if len(rows) != 1 or rows[0][0] != 1:
            raise ValueError("Invalid boundary checkpoint")
        strict_json(rows[0][1])
        return BoundaryState.model_validate_json(rows[0][1])

    @staticmethod
    def events(path: Path) -> tuple[BoundaryEvent, ...]:
        regular(path)
        with closing(
            sqlite3.connect(f"{path.absolute().as_uri()}?mode=ro", uri=True)
        ) as conn:
            rows = conn.execute(
                "SELECT sequence,event FROM events ORDER BY sequence"
            ).fetchall()
        events = []
        for expected, row in enumerate(rows, 1):
            strict_json(row[1])
            event = BoundaryEvent.model_validate_json(row[1])
            if row[0] != expected or event.sequence != expected:
                raise ValueError("Boundary event sequence gap")
            events.append(event)
        return tuple(events)

    def save(
        self, kind: str, state: BoundaryState | None = None, **data: JsonValue
    ) -> None:
        state = BoundaryState.model_validate_json(
            (state or self.state).model_dump_json()
        )
        with (
            closing(sqlite3.connect(f"{self.path.as_uri()}?mode=rw", uri=True)) as conn,
            conn,
        ):
            number = conn.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM events"
            ).fetchone()[0]
            event = BoundaryEvent(
                sequence=number, wall_time=time.time(), kind=kind, data=data
            )
            conn.execute(
                "INSERT INTO events VALUES (?,?)", (number, event.model_dump_json())
            )
            conn.execute(
                "UPDATE checkpoint SET state=? WHERE id=1", (state.model_dump_json(),)
            )
        self.state = state
