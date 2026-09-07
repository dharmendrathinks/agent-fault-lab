"""M07 bounded retries: one operation identity, multiple delivery attempts."""

import base64
import sqlite3
from dataclasses import asdict
from typing import Literal
from uuid import uuid4

from pydantic import ValidationError

from agent_fault_lab.contracts import (
    ContractError,
    ErrorCode,
    ResponseEnvelope,
    TaskValue,
    error_response,
    validate_response,
)
from agent_fault_lab.model import Record, ToolCall
from agent_fault_lab.tasks import CreateReceipt, OperationConflict, Task, TaskStore
from agent_fault_lab.tools import CreateArguments, GetArguments, ToolDelivery
from agent_fault_lab.trace import Recorder

type RetryCase = Literal["retry-healthy", "before-write-once", "lost-reply-once"]
type RetryPolicy = Literal["single-attempt", "retry-unprotected", "retry-idempotent"]
RETRY_CASES: tuple[RetryCase, ...] = (
    "retry-healthy",
    "before-write-once",
    "lost-reply-once",
)
RETRY_POLICIES: tuple[RetryPolicy, ...] = (
    "single-attempt",
    "retry-unprotected",
    "retry-idempotent",
)
RETRY_PAIR: tuple[RetryPolicy, ...] = ("retry-unprotected", "retry-idempotent")


class RetryConfig(Record):
    case: RetryCase
    policy: RetryPolicy


class DeliveryUnavailable(Exception):
    """A missing reply says nothing about whether its write committed."""


class RetryFaultInjector:
    """A single failure on the first eligible create in a run, shared by policies."""

    def __init__(self, case: RetryCase, recorder: Recorder) -> None:
        self.case = case
        self.recorder = recorder
        self.consumed = False

    def create(
        self,
        store: TaskStore,
        title: str,
        operation_id: str,
        attempt_id: str,
        *,
        protected: bool,
    ) -> CreateReceipt:
        if self.case == "before-write-once" and not self.consumed:
            self._fail(operation_id, attempt_id, committed=False)
        self.recorder.emit(
            "storage_entered", operation_id=operation_id, attempt_id=attempt_id
        )
        receipt = (
            store.create_task_idempotent(title, operation_id)
            if protected
            else CreateReceipt(store.create_task(title), replayed=False)
        )
        self.recorder.emit(
            "storage_returned",
            operation_id=operation_id,
            attempt_id=attempt_id,
            replayed=receipt.replayed,
            task=asdict(receipt.task),
        )
        if self.case == "lost-reply-once" and not self.consumed:
            self._fail(operation_id, attempt_id, committed=True)
        return receipt

    def _fail(self, operation_id: str, attempt_id: str, *, committed: bool) -> None:
        self.consumed = True
        self.recorder.emit(
            "retry_fault_injected",
            case=self.case,
            operation_id=operation_id,
            attempt_id=attempt_id,
            write_committed=committed,
        )
        raise DeliveryUnavailable("Tool reply unavailable; storage outcome is unknown")


class RetryExecutor:
    """At most two attempts. Only delivery failures qualify for an M07 retry."""

    def __init__(
        self, store: TaskStore, recorder: Recorder, config: RetryConfig
    ) -> None:
        self.store = store
        self.recorder = recorder
        self.config = config
        self.injector = RetryFaultInjector(config.case, recorder)

    def execute(self, call: ToolCall, call_id: str) -> ToolDelivery:
        if call.name not in {"create_task", "get_task"}:
            return self._error(
                "unknown_tool", f"Unknown tool: {call.name}", call_id, False
            )
        try:
            arguments = (
                CreateArguments.model_validate(call.arguments)
                if call.name == "create_task"
                else GetArguments.model_validate(call.arguments)
            )
        except ValidationError:
            return self._error(
                "invalid_arguments", "Invalid tool arguments", call_id, False
            )
        operation_id = str(uuid4())
        self.recorder.emit(
            "operation_started",
            call_id=call_id,
            operation_id=operation_id,
            call=call.model_dump(mode="json"),
        )
        limit = 1 if self.config.policy == "single-attempt" else 2
        for number in range(1, limit + 1):
            attempt_id = f"{operation_id}:{number}"
            self.recorder.emit(
                "attempt_started",
                call_id=call_id,
                operation_id=operation_id,
                attempt_id=attempt_id,
                number=number,
            )
            try:
                raw = self._attempt(arguments, operation_id, attempt_id)
                self.recorder.emit(
                    "response_captured",
                    call_id=call_id,
                    operation_id=operation_id,
                    attempt_id=attempt_id,
                    raw_base64=base64.b64encode(raw).decode("ascii"),
                )
                validate_response(raw, call)
            except DeliveryUnavailable:
                self.recorder.emit(
                    "attempt_failed",
                    operation_id=operation_id,
                    attempt_id=attempt_id,
                    reason="delivery_error",
                )
                if number < limit:
                    self.recorder.emit(
                        "retry_scheduled",
                        operation_id=operation_id,
                        after_attempt=attempt_id,
                        reason="delivery_error",
                    )
                    continue
                return self._error(
                    "delivery_error",
                    "Tool reply unavailable; storage outcome is unknown",
                    call_id,
                    True,
                )
            except OperationConflict as exc:
                code: ErrorCode = "operation_conflict"
                message = str(exc)
            except sqlite3.Error as exc:
                code = "storage_error"
                message = f"Storage error: {type(exc).__name__}: {exc}"
            except ContractError as exc:
                code = "invalid_result"
                message = str(exc)
            else:
                self.recorder.emit(
                    "attempt_succeeded",
                    operation_id=operation_id,
                    attempt_id=attempt_id,
                )
                return ToolDelivery(content=raw.decode("utf-8"), executed=True)
            self.recorder.emit(
                "attempt_failed",
                operation_id=operation_id,
                attempt_id=attempt_id,
                reason=code,
            )
            return self._error(code, message, call_id, True)
        raise AssertionError("Attempt loop must return or raise")

    def _attempt(
        self,
        arguments: CreateArguments | GetArguments,
        operation_id: str,
        attempt_id: str,
    ) -> bytes:
        task: Task | None
        if isinstance(arguments, CreateArguments):
            task = self.injector.create(
                self.store,
                arguments.title,
                operation_id,
                attempt_id,
                protected=self.config.policy == "retry-idempotent",
            ).task
        else:
            self.recorder.emit(
                "storage_entered", operation_id=operation_id, attempt_id=attempt_id
            )
            task = self.store.get_task(arguments.task_id)
            self.recorder.emit(
                "storage_returned",
                operation_id=operation_id,
                attempt_id=attempt_id,
                replayed=False,
                task=asdict(task) if task else None,
            )
        return (
            ResponseEnvelope(
                schema_version=1,
                ok=True,
                value=TaskValue(id=task.id, title=task.title) if task else None,
                error=None,
            )
            .model_dump_json()
            .encode("utf-8")
        )

    def _error(
        self, code: ErrorCode, message: str, call_id: str, executed: bool
    ) -> ToolDelivery:
        content = error_response(code, message)
        self.recorder.emit("operation_error", call_id=call_id, code=code)
        return ToolDelivery(content=content, executed=executed)
