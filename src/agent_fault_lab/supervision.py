"""M08 sequential subprocess ownership, deadlines and bounded protected retry."""

import base64
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

from pydantic import ValidationError

from agent_fault_lab.barriers import pause
from agent_fault_lab.contracts import (
    ContractError,
    ErrorCode,
    error_response,
    validate_response,
)
from agent_fault_lab.execution_types import (
    ExecutionLimits,
    ExecutionState,
    Operation,
    PausePoint,
    ProcessConfig,
    WorkerFault,
    WorkerRequest,
)
from agent_fault_lab.model import ToolCall
from agent_fault_lab.tools import CreateArguments, GetArguments, ToolDelivery
from agent_fault_lab.trace import Event, Recorder


class Supervisor:
    def __init__(
        self,
        directory: Path,
        recorder: Recorder,
        config: ProcessConfig,
        *,
        limits: ExecutionLimits | None = None,
        state: ExecutionState | None = None,
        checkpoint: Callable[[ExecutionState], None] | None = None,
        clock: Callable[[], float] = monotonic,
        sleeper: Callable[[float], None] = sleep,
        lock_fd: int | None = None,
        pause_at: PausePoint | None = None,
    ) -> None:
        self.directory = directory.resolve()
        self.recorder = recorder
        self.config = config
        self.limits = limits or ExecutionLimits()
        self.state = state or ExecutionState()
        self.checkpoint = checkpoint or (lambda state: None)
        self.clock, self.sleeper = clock, sleeper
        self.lock_fd, self.pause_at = lock_fd, pause_at
        self.worker: subprocess.Popen[bytes] | None = None

    def save(self, state: ExecutionState) -> None:
        self.state = state
        self.checkpoint(state)

    def save_operation(self, operation: Operation) -> None:
        self.save(self.state.model_copy(update={"active": operation}))

    def emit(self, kind: str, **data: str | int | float | bool | None) -> None:
        op = self.state.active
        self.recorder.emit(
            kind,
            call_id=op.call_id if op else None,
            operation_id=op.operation_id if op else None,
            attempt_id=f"{op.operation_id}:{op.attempts}"
            if op and op.attempts
            else None,
            **data,
        )

    def finish(self, code: ErrorCode, message: str) -> ToolDelivery:
        result = ToolDelivery(content=error_response(code, message), executed=True)
        assert self.state.active is not None
        self.save_operation(self.state.active.model_copy(update={"result": result}))
        self.emit("operation_failed", code=code)
        return result

    def execute(self, call: ToolCall, call_id: str) -> ToolDelivery:
        if call.name not in {"create_task", "get_task"}:
            return ToolDelivery(
                content=error_response("unknown_tool", "Unknown tool"), executed=False
            )
        try:
            if call.name == "create_task":
                CreateArguments.model_validate(call.arguments)
            else:
                GetArguments.model_validate(call.arguments)
        except ValidationError:
            return ToolDelivery(
                content=error_response("invalid_arguments", "Invalid tool arguments"),
                executed=False,
            )
        op = self.state.active
        if op is None or op.call_id != call_id:
            if op is not None and op.result is None:
                raise ValueError("Cannot replace an unfinished operation")
            op = Operation(
                operation_id=str(uuid4()),
                call_id=call_id,
                call=call,
                remaining_seconds=self.limits.operation_seconds,
            )
            self.save_operation(op)
            self.emit("operation_started")
        elif op.call != call:
            raise ValueError("Checkpointed operation arguments changed")
        if op.result is not None:
            return op.result
        if op.reserved_seconds:
            # No elapsed clock survives a crash. Charge the full reservation.
            self.emit("interrupted_reservation_charged", seconds=op.reserved_seconds)
            op = op.model_copy(
                update={
                    "remaining_seconds": max(
                        0.0, op.remaining_seconds - op.reserved_seconds
                    ),
                    "reserved_seconds": 0.0,
                }
            )
            self.save_operation(op)
        maximum = (
            self.limits.max_attempts if self.config.policy == "bounded-retry" else 1
        )
        while (
            op.attempts < maximum
            and self.state.total_attempts < self.limits.total_attempts
        ):
            if op.attempts:
                wait = self.limits.backoff[min(op.attempts - 1, 1)]
                if op.remaining_seconds <= wait + self.limits.grace_seconds:
                    return self.finish(
                        "execution_limit", "Operation budget exhausted during backoff"
                    )
                self.save_operation(op.model_copy(update={"reserved_seconds": wait}))
                self.emit("backoff_started", seconds=wait)
                start = self.clock()
                self.sleeper(wait)
                op = op.model_copy(
                    update={
                        "remaining_seconds": max(
                            0.0, op.remaining_seconds - max(wait, self.clock() - start)
                        )
                    }
                )
                self.save_operation(op)
            if op.remaining_seconds <= self.limits.grace_seconds:
                return self.finish("execution_limit", "Operation time budget exhausted")
            timeout = min(
                self.limits.attempt_seconds,
                op.remaining_seconds - self.limits.grace_seconds,
            )
            reservation = (
                op.remaining_seconds
                if self.config.policy == "observe"
                else min(op.remaining_seconds, timeout + self.limits.grace_seconds)
            )
            fault = self.fault_for(call)
            op = op.model_copy(
                update={"attempts": op.attempts + 1, "reserved_seconds": reservation}
            )
            self.save(
                self.state.model_copy(
                    update={
                        "active": op,
                        "total_attempts": self.state.total_attempts + 1,
                        "fault_cursor": self.state.fault_cursor
                        + int(call.name == "create_task"),
                    }
                )
            )
            self.emit(
                "attempt_started", reserved_seconds=reservation, configured_fault=fault
            )
            pause(self.directory, self.pause_at, "attempt-checkpoint")
            started = self.clock()
            raw, failure = self.dispatch(call, fault, timeout, op.remaining_seconds)
            op = op.model_copy(
                update={
                    "remaining_seconds": max(
                        0.0, op.remaining_seconds - (self.clock() - started)
                    ),
                    "reserved_seconds": 0.0,
                }
            )
            self.save_operation(op)
            response = None
            if raw is not None:
                self.emit(
                    "response_captured",
                    raw_base64=base64.b64encode(raw).decode("ascii"),
                )
                try:
                    response = validate_response(raw, call)
                except ContractError as exc:
                    self.emit("contract_rejected", stage=exc.stage)
                    return self.finish("invalid_result", str(exc))
                if response.ok:
                    result = ToolDelivery(content=raw.decode("utf-8"), executed=True)
                    self.save_operation(op.model_copy(update={"result": result}))
                    self.emit("attempt_succeeded")
                    return result
                assert response.error is not None
                failure = response.error.code
            assert failure is not None
            self.emit("attempt_failed", reason=failure)
            if failure not in {
                "transient_error",
                "delivery_error",
                "deadline_exceeded",
            }:
                assert response is not None and response.error is not None
                return self.finish(response.error.code, response.error.message)
            if op.attempts >= maximum:
                return self.finish(
                    failure, "Tool execution stopped; storage outcome is unknown"
                )
            self.emit("retry_scheduled", reason=failure)
        return self.finish(
            "execution_limit", "Attempt budget exhausted; storage outcome is unknown"
        )

    def fault_for(self, call: ToolCall) -> WorkerFault:
        if call.name != "create_task":
            return "none"
        case, cursor = self.config.case, self.state.fault_cursor
        if (
            case == "transient-always"
            or (case == "transient-once" and cursor < 1)
            or (case == "transient-twice" and cursor < 2)
        ):
            return "transient"
        if cursor:
            return "none"
        return {
            "permanent-error": "permanent",
            "delay-before-write": "delay-before",
            "delay-after-commit": "delay-after",
            "ignore-termination": "ignore-termination",
            "exit-before-reply": "exit",
            "malformed-worker": "malformed",
        }.get(case, "none")  # type: ignore[return-value]

    def stop_worker(self) -> None:
        worker = self.worker
        if worker is None:
            return
        if worker.poll() is None:
            self.emit("cancellation_requested", pid=worker.pid)
            worker.terminate()
            try:
                worker.communicate(timeout=self.limits.grace_seconds)
            except subprocess.TimeoutExpired:
                self.emit("kill_requested", pid=worker.pid)
                worker.kill()
                worker.communicate()
        else:
            worker.communicate()
        self.emit("worker_exit_confirmed", pid=worker.pid, returncode=worker.returncode)
        self.worker = None

    def dispatch(
        self, call: ToolCall, fault: WorkerFault, timeout: float, remaining: float
    ) -> tuple[bytes | None, ErrorCode | None]:
        op = self.state.active
        assert op is not None
        evidence = self.directory / f"worker-{op.operation_id}-{op.attempts}.jsonl"
        request = WorkerRequest(
            database=str(self.directory / "tasks.sqlite3"),
            evidence=str(evidence),
            operation_id=op.operation_id,
            attempt_id=f"{op.operation_id}:{op.attempts}",
            call=call,
            fault=fault,
            delay_seconds=self.limits.delay_seconds,
            run_directory=str(self.directory),
            pause_at=self.pause_at,
        )
        started = self.clock()
        self.worker = subprocess.Popen(
            [sys.executable, "-m", "agent_fault_lab.worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=() if self.lock_fd is None else (self.lock_fd,),
        )
        worker = self.worker
        self.emit("worker_dispatched", pid=worker.pid, evidence=evidence.name)
        try:
            try:
                raw, stderr = worker.communicate(
                    request.model_dump_json().encode(), timeout=timeout
                )
            except subprocess.TimeoutExpired:
                self.emit("deadline_expired", seconds=timeout)
                if self.config.policy == "observe":
                    self.emit("observation_wait_started", pid=worker.pid)
                    available = max(
                        0.0,
                        remaining
                        - (self.clock() - started)
                        - self.limits.grace_seconds,
                    )
                    try:
                        raw, stderr = worker.communicate(timeout=available)
                        self.emit("late_response", bytes=len(raw))
                    except subprocess.TimeoutExpired:
                        return None, "deadline_exceeded"
                else:
                    return None, "deadline_exceeded"
            if worker.returncode != 0 or not raw:
                self.emit(
                    "worker_reply_missing",
                    returncode=worker.returncode,
                    stderr=stderr.decode("utf-8", errors="replace"),
                )
                return None, "delivery_error"
            return raw, None
        finally:
            # Includes KeyboardInterrupt. Never evaluate or dispatch again until
            # wait/communicate has confirmed this owned process exited.
            self.stop_worker()
            if evidence.exists():
                for line in evidence.read_text(encoding="utf-8").splitlines():
                    try:
                        event = Event.model_validate_json(line)
                    except ValueError:
                        self.emit("worker_evidence_gap", evidence=evidence.name)
                        break
                    self.recorder.emit(
                        "worker_evidence",
                        operation_id=op.operation_id,
                        call_id=op.call_id,
                        attempt_id=f"{op.operation_id}:{op.attempts}",
                        evidence=evidence.name,
                        event=event.model_dump(mode="json"),
                    )
