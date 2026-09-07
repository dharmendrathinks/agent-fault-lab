"""M06 response contracts: shape and request consistency, never storage proof."""

import json
from typing import Literal, Self

from pydantic import ValidationError, field_validator, model_validator

from agent_fault_lab.model import Record, ToolCall
from agent_fault_lab.tools import CreateArguments, GetArguments


class TaskValue(Record):
    id: str
    title: str

    @field_validator("id", "title")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Task fields must not be blank")
        return value


type ErrorCode = Literal[
    "invalid_arguments",
    "unknown_tool",
    "storage_error",
    "invalid_result",
    "delivery_error",
    "operation_conflict",
    "transient_error",
    "deadline_exceeded",
    "execution_limit",
]


class ToolError(Record):
    code: ErrorCode
    message: str

    @field_validator("message")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Error message must not be blank")
        return value


class ResponseEnvelope(Record):
    # All fields are required on the wire, including explicit nulls.
    schema_version: Literal[1]
    ok: bool
    value: TaskValue | None
    error: ToolError | None

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("Unsupported response schema version")
        return value

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.ok and self.error is not None:
            raise ValueError("Success cannot include an error")
        if not self.ok and (self.error is None or self.value is not None):
            raise ValueError("Failure requires an error and a null value")
        return self


type ContractStage = Literal["syntax", "schema", "request"]


class ContractError(ValueError):
    def __init__(self, stage: ContractStage) -> None:
        self.stage = stage
        # Do not expose rejected payloads, fault names, or storage assumptions.
        super().__init__(f"Tool response failed {stage} validation")


def validate_response(raw: bytes, call: ToolCall) -> ResponseEnvelope:
    """Validate the entire UTF-8 JSON response; never repair or query storage."""

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate key")
            result[key] = value
        return result

    def finite(value: str) -> object:
        raise ValueError("Non-finite value")

    try:
        decoded = json.loads(
            raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=finite
        )
    except (ValueError, UnicodeError) as exc:
        raise ContractError("syntax") from exc
    try:
        response = ResponseEnvelope.model_validate(decoded)
    except ValidationError as exc:
        raise ContractError("schema") from exc
    if response.ok:
        try:
            if call.name == "create_task":
                arguments = CreateArguments.model_validate(call.arguments)
                if response.value is None or response.value.title != arguments.title:
                    raise ValueError("Create response does not match the request")
            elif call.name == "get_task":
                lookup = GetArguments.model_validate(call.arguments)
                if response.value is not None and response.value.id != lookup.task_id:
                    raise ValueError("Lookup response does not match the request")
            else:
                raise ValueError("Unknown tool cannot report success")
        except ValueError as exc:
            raise ContractError("request") from exc
    return response


def error_response(code: ErrorCode, message: str) -> str:
    return ResponseEnvelope(
        schema_version=1,
        ok=False,
        value=None,
        error=ToolError(code=code, message=message),
    ).model_dump_json()
