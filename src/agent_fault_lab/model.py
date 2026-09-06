"""Project-owned messages: neither the task store nor the loop imports Ollama."""

from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ToolCall(Record):
    name: str
    arguments: JsonValue


class Message(Record):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    call_id: str | None = None
    tool_name: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ToolSpec(Record):
    name: str
    description: str
    parameters: dict[str, JsonValue]


class ModelSettings(Record):
    model: str = Field(default="qwen3:4b", min_length=1)
    temperature: float = Field(default=0.0, ge=0, le=2)
    context_tokens: int = Field(default=4096, gt=0)
    max_output_tokens: int = Field(default=512, gt=0)
    request_timeout_seconds: float = Field(default=60.0, gt=0, le=60)


class ModelTurn(Record):
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: dict[str, JsonValue] = Field(default_factory=dict)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    finish_reason: str | None = None


type ExecutionStatus = Literal[
    "finished", "model_limit", "tool_limit", "provider_error", "protocol_error"
]


class RunResult(Record):
    """Execution facts shared with the evaluator, without importing the loop."""

    status: ExecutionStatus
    final_content: str | None
    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    tool_executions: int = Field(ge=0)
    error: str | None = None


class ProviderError(Exception):
    """A failed model request, not a failed task or a tool result."""


class ModelClient(Protocol):
    @property
    def label(self) -> str: ...

    def complete(
        self,
        messages: Sequence[Message],
        tool_specs: Sequence[ToolSpec],
        settings: ModelSettings,
    ) -> ModelTurn: ...
