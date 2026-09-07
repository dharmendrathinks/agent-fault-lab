"""M06 finite response-fault cases and policy-controlled tool delivery."""

import base64
import json
from collections.abc import Sequence
from typing import Literal

from pydantic import JsonValue

from agent_fault_lab.claims import TerminalClaim
from agent_fault_lab.contracts import ContractError, ErrorCode, error_response
from agent_fault_lab.contracts import validate_response as validate_response
from agent_fault_lab.faults import FaultInjector
from agent_fault_lab.model import Message, ModelTurn, Record, ToolCall
from agent_fault_lab.scripted import ScriptedClient
from agent_fault_lab.tasks import TaskStore
from agent_fault_lab.tools import ToolDelivery, execute_tool
from agent_fault_lab.trace import Recorder

type ResponseCase = Literal[
    "healthy",
    "malformed-json",
    "duplicate-keys",
    "non-finite",
    "missing-field",
    "extra-field",
    "wrong-type",
    "unsupported-version",
    "wrong-create-title",
    "wrong-get-id",
    "dropped-write",
]
type ResponsePolicy = Literal["pass-through", "validated"]

CASES: tuple[ResponseCase, ...] = (
    "healthy",
    "malformed-json",
    "duplicate-keys",
    "non-finite",
    "missing-field",
    "extra-field",
    "wrong-type",
    "unsupported-version",
    "wrong-create-title",
    "wrong-get-id",
    "dropped-write",
)
POLICIES: tuple[ResponsePolicy, ...] = ("pass-through", "validated")


class ReliabilityConfig(Record):
    case: ResponseCase
    policy: ResponsePolicy


class ResponseExecutor:
    """The policy changes delivery only; both paths validate all tool arguments."""

    def __init__(
        self, store: TaskStore, recorder: Recorder, config: ReliabilityConfig
    ) -> None:
        self.store = store
        self.recorder = recorder
        self.config = config

    def execute(self, call: ToolCall, call_id: str) -> ToolDelivery:
        injector = (
            FaultInjector("dropped-write", self.recorder)
            if self.config.case == "dropped-write"
            else None
        )
        result = execute_tool(self.store, call, injector=injector, call_id=call_id)
        if not result.ok:
            code: ErrorCode = (
                "storage_error"
                if result.executed
                else "unknown_tool"
                if call.name not in {"create_task", "get_task"}
                else "invalid_arguments"
            )
            raw = error_response(code, result.error or "Tool operation failed").encode()
        else:
            payload: dict[str, JsonValue] = {
                "schema_version": 1,
                "ok": True,
                "value": result.value,
                "error": None,
            }
            raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
            target = "get_task" if self.config.case == "wrong-get-id" else "create_task"
            if call.name == target and result.value is not None:
                raw = self._inject(raw, payload, call_id)
        self.recorder.emit(
            "response_captured",
            call_id=call_id,
            raw_base64=base64.b64encode(raw).decode("ascii"),
        )
        content = raw.decode("utf-8")
        if self.config.policy == "validated":
            try:
                validate_response(raw, call)
            except ContractError as exc:
                self.recorder.emit(
                    "contract_checked", call_id=call_id, status=exc.stage
                )
                content = error_response("invalid_result", str(exc))
            else:
                self.recorder.emit("contract_checked", call_id=call_id, status="valid")
        else:
            self.recorder.emit("contract_unchecked", call_id=call_id)
        return ToolDelivery(content=content, executed=result.executed)

    def _inject(self, raw: bytes, payload: dict[str, JsonValue], call_id: str) -> bytes:
        case = self.config.case
        if case == "healthy":
            return raw
        if case == "malformed-json":
            raw = raw[:-1]
        elif case == "duplicate-keys":
            raw = b'{"ok": false, ' + raw[1:]
        elif case == "non-finite":
            raw = raw.replace(b'"schema_version": 1', b'"schema_version": NaN', 1)
        elif case == "dropped-write":
            # The existing injector recorded the actual interception independently.
            return raw
        else:
            if case == "missing-field":
                del payload["error"]
            elif case == "extra-field":
                payload["unexpected"] = True
            elif case == "wrong-type":
                payload["ok"] = "true"
            elif case == "unsupported-version":
                payload["schema_version"] = 2
            else:
                value = payload["value"]
                if not isinstance(value, dict):
                    raise ValueError("Expected task-valued result for response fault")
                if case == "wrong-create-title":
                    value["title"] = str(value["title"]) + " (changed)"
                elif case == "wrong-get-id":
                    value["id"] = str(value["id"]) + "-changed"
            raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        self.recorder.emit("response_fault_injected", case=case, call_id=call_id)
        return raw


def scripted_response_client(title: str) -> ScriptedClient:
    """Same fixed create/read script for every case and policy; not AI evidence.

    This deliberately trusts success-shaped results without comparing request
    fields. It demonstrates what executor validation changes, not learned behavior.
    """

    def task_id(messages: Sequence[Message]) -> str | None:
        try:
            result = json.loads(messages[-1].content)
            if not isinstance(result, dict) or result.get("ok") is not True:
                return None
            value = result.get("value")
            if not isinstance(value, dict):
                return None
            identifier = value.get("id")
            return (
                identifier
                if isinstance(identifier, str) and identifier.strip()
                else None
            )
        except ValueError:
            return None

    def uncertain() -> ModelTurn:
        return ModelTurn(
            content=TerminalClaim(status="unknown", task_id=None).model_dump_json()
        )

    def lookup(messages: Sequence[Message]) -> ModelTurn:
        identifier = task_id(messages)
        if identifier is None:
            return uncertain()
        return ModelTurn(
            tool_calls=(ToolCall(name="get_task", arguments={"task_id": identifier}),)
        )

    def finish(messages: Sequence[Message]) -> ModelTurn:
        identifier = task_id(messages)
        if identifier is None:
            return uncertain()
        return ModelTurn(
            content=TerminalClaim(
                status="completed", task_id=identifier
            ).model_dump_json()
        )

    return ScriptedClient(
        [
            ModelTurn(
                tool_calls=(ToolCall(name="create_task", arguments={"title": title}),)
            ),
            lookup,
            finish,
        ]
    )
