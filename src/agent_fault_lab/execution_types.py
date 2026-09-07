"""Finite process experiments and durable execution records for M08–M10."""

from typing import Literal, Self

from pydantic import Field, model_validator

from agent_fault_lab.model import Record, ToolCall
from agent_fault_lab.tools import ToolDelivery

type ProcessCase = Literal[
    "process-healthy",
    "transient-once",
    "transient-twice",
    "transient-always",
    "permanent-error",
    "delay-before-write",
    "delay-after-commit",
    "ignore-termination",
    "exit-before-reply",
    "malformed-worker",
    "restart-healthy",
]
type ProcessPolicy = Literal["process-single", "bounded-retry", "observe", "terminate"]
PROCESS_CASES: tuple[ProcessCase, ...] = (
    "process-healthy",
    "transient-once",
    "transient-twice",
    "transient-always",
    "permanent-error",
    "delay-before-write",
    "delay-after-commit",
    "ignore-termination",
    "exit-before-reply",
    "malformed-worker",
    "restart-healthy",
)
PROCESS_POLICIES: tuple[ProcessPolicy, ...] = (
    "process-single",
    "bounded-retry",
    "observe",
    "terminate",
)


def policies_for(case: ProcessCase) -> tuple[ProcessPolicy, ...]:
    if case in {"delay-before-write", "delay-after-commit", "ignore-termination"}:
        return ("observe", "terminate")
    return ("process-single", "bounded-retry")


class ProcessConfig(Record):
    case: ProcessCase
    policy: ProcessPolicy

    @model_validator(mode="after")
    def supported(self) -> Self:
        if self.policy not in policies_for(self.case):
            raise ValueError("Unsupported process case/policy combination")
        return self


class ExecutionLimits(Record):
    attempt_seconds: float = Field(default=2.0, gt=0, le=2)
    operation_seconds: float = Field(default=8.0, gt=0, le=8)
    max_attempts: int = Field(default=3, ge=1, le=3)
    backoff: tuple[float, float] = (0.1, 0.2)
    grace_seconds: float = Field(default=0.5, gt=0, le=0.5)
    total_attempts: int = Field(default=18, ge=1, le=18)
    delay_seconds: float = Field(default=3.0, gt=0, le=3)

    @model_validator(mode="after")
    def valid_backoff(self) -> Self:
        if any(not 0 <= value <= 0.2 for value in self.backoff):
            raise ValueError("Invalid backoff")
        return self


class Operation(Record):
    operation_id: str
    call_id: str
    call: ToolCall
    attempts: int = Field(default=0, ge=0, le=3)
    remaining_seconds: float = Field(default=8.0, ge=0, le=8)
    reserved_seconds: float = Field(default=0.0, ge=0, le=8)
    result: ToolDelivery | None = None


class ExecutionState(Record):
    total_attempts: int = Field(default=0, ge=0, le=18)
    fault_cursor: int = Field(default=0, ge=0, le=18)
    active: Operation | None = None


type WorkerFault = Literal[
    "none",
    "transient",
    "permanent",
    "delay-before",
    "delay-after",
    "ignore-termination",
    "exit",
    "malformed",
]
type PausePoint = Literal[
    "assistant-checkpoint",
    "attempt-checkpoint",
    "transaction",
    "after-commit",
    "tool-checkpoint",
    "terminal-checkpoint",
]
PAUSE_POINTS: tuple[PausePoint, ...] = (
    "assistant-checkpoint",
    "attempt-checkpoint",
    "transaction",
    "after-commit",
    "tool-checkpoint",
    "terminal-checkpoint",
)


class WorkerRequest(Record):
    database: str
    evidence: str
    operation_id: str
    attempt_id: str
    call: ToolCall
    fault: WorkerFault
    delay_seconds: float = Field(gt=0, le=3)
    pause_at: PausePoint | None = None
    run_directory: str
