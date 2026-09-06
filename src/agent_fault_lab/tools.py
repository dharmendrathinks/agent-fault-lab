"""The two allowed tools, with strict model-facing argument validation."""

import sqlite3
from dataclasses import asdict

from pydantic import JsonValue, ValidationError, field_validator

from agent_fault_lab.model import Record, ToolCall, ToolSpec
from agent_fault_lab.tasks import Task, TaskStore


class CreateArguments(Record):
    title: str

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be empty or whitespace-only")
        return value


class GetArguments(Record):
    task_id: str

    @field_validator("task_id")
    @classmethod
    def nonblank_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("task_id must not be empty or whitespace-only")
        return value


TOOL_SPECS = (
    ToolSpec(
        name="create_task",
        description="Save a task with the exact title. Returns id and title.",
        parameters=CreateArguments.model_json_schema(),
    ),
    ToolSpec(
        name="get_task",
        description="Read a task by ID. Returns the task, or null if it is not found.",
        parameters=GetArguments.model_json_schema(),
    ),
)


class ToolResult(Record):
    ok: bool
    value: JsonValue = None
    error: str | None = None
    # True means the Python function was entered, not that a write committed.
    executed: bool = False


def execute_tool(store: TaskStore, call: ToolCall) -> ToolResult:
    if call.name not in {"create_task", "get_task"}:
        return ToolResult(ok=False, error=f"Unknown tool: {call.name}")
    task: Task | None
    try:
        if call.name == "create_task":
            arguments = CreateArguments.model_validate(call.arguments)
            task = store.create_task(arguments.title)
        else:
            lookup = GetArguments.model_validate(call.arguments)
            task = store.get_task(lookup.task_id)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'arguments'}: "
            f"{error['msg']}"
            for error in exc.errors(include_url=False, include_input=False)
        )
        return ToolResult(ok=False, error=f"Invalid arguments: {details}")
    except sqlite3.Error as exc:
        # No retry: a later milestone studies ambiguous and duplicate writes.
        return ToolResult(
            ok=False, error=f"Storage error: {type(exc).__name__}: {exc}", executed=True
        )
    return ToolResult(ok=True, value=asdict(task) if task else None, executed=True)
