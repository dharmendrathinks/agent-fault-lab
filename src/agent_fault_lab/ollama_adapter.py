"""Local-only Ollama boundary. No pulls, retries, redirects, or cloud fallback."""

from collections.abc import Sequence

import httpx
from ollama import Client, ResponseError
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agent_fault_lab.model import (
    DEFAULT_MODEL,
    Message,
    ModelSettings,
    ModelTurn,
    ProviderError,
    Record,
    ToolCall,
    ToolSpec,
)

LOCAL_HOST = "http://127.0.0.1:11434"
EXPECTED_CHECKPOINT: dict[str, JsonValue] = {
    "general.architecture": "qwen3",
    "general.basename": "Qwen3",
    "general.finetune": "Instruct",
    "general.version": "2507",
    "general.size_label": "4B",
}


class DoctorResult(Record):
    model: str
    host: str = LOCAL_HOST
    ollama_version: str | None = None
    model_digest: str | None = None
    cloud_disabled: bool | None = None
    tools_supported: bool | None = None
    checkpoint: dict[str, JsonValue] = Field(default_factory=dict)
    problems: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.problems


class _Boundary(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")


class _Version(_Boundary):
    version: str


class _Cloud(_Boundary):
    disabled: bool


class _Status(_Boundary):
    cloud: _Cloud


class _InstalledModel(_Boundary):
    name: str
    digest: str


class _Tags(_Boundary):
    models: list[_InstalledModel]


class _Show(_Boundary):
    capabilities: list[str]
    model_info: dict[str, JsonValue] = Field(default_factory=dict)
    remote_host: str | None = None
    remote_model: str | None = None


def _wire_message(message: Message) -> dict[str, JsonValue]:
    wire: dict[str, JsonValue] = {"role": message.role, "content": message.content}
    if message.role == "assistant":
        if "thinking" in message.metadata:
            wire["thinking"] = message.metadata["thinking"]
        if message.tool_calls:
            calls: list[JsonValue] = []
            for call in message.tool_calls:
                calls.append(
                    {
                        "function": {
                            "name": call.name,
                            "arguments": call.arguments,
                        }
                    }
                )
            wire["tool_calls"] = calls
    if message.role == "tool":
        wire["tool_name"] = message.tool_name
        # Ollama SDK 0.6.2 associates results by tool name and message order.
        # A local m1-t1 ID belongs to our trace, not to Ollama's wire protocol.
    return wire


class OllamaClient:
    label = "ollama-local"

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        # Injection is for socket-free HTTP contract tests, not provider selection.
        self._transport = transport

    def inspect(self, model: str = DEFAULT_MODEL) -> DoctorResult:
        """Read metadata only. Missing/unknown local-only status fails closed."""
        version = digest = None
        disabled = supported = None
        checkpoint: dict[str, JsonValue] = {}
        problems: list[str] = []
        try:
            with httpx.Client(
                base_url=LOCAL_HOST,
                timeout=5.0,
                follow_redirects=False,
                trust_env=False,
                transport=self._transport,
            ) as client:
                response = client.get("/api/version")
                response.raise_for_status()
                version = _Version.model_validate(response.json()).version
                response = client.get("/api/status")
                response.raise_for_status()
                disabled = _Status.model_validate(response.json()).cloud.disabled
                if not disabled:
                    problems.append("Ollama cloud is enabled; enable local-only mode.")
                response = client.get("/api/tags")
                response.raise_for_status()
                installed = _Tags.model_validate(response.json()).models
                match = next((item for item in installed if item.name == model), None)
                if match is None:
                    problems.append(
                        f"Model {model!r} is not installed; no download made."
                    )
                else:
                    digest = match.digest
                    if not digest:
                        problems.append("Installed model has no digest.")
                    response = client.post("/api/show", json={"model": model})
                    response.raise_for_status()
                    details = _Show.model_validate(response.json())
                    supported = "tools" in details.capabilities
                    if not supported:
                        problems.append("Model does not advertise tool support.")
                    if details.remote_host or details.remote_model or "cloud" in model:
                        problems.append("Remote/cloud models are not allowed in M02.")
                    checkpoint = {
                        key: details.model_info[key]
                        for key in EXPECTED_CHECKPOINT
                        if key in details.model_info
                    }
                    # Family-level "thinking" flags cannot distinguish the two
                    # 2507 checkpoints. Verify the approved non-thinking baseline.
                    if checkpoint != EXPECTED_CHECKPOINT:
                        problems.append(
                            "Checkpoint metadata does not match the approved "
                            "Qwen3-4B-Instruct-2507 baseline; review model selection."
                        )
        except (httpx.HTTPError, ValueError) as exc:
            problems.append(
                f"Cannot verify local prerequisites: {type(exc).__name__}: {exc}"
            )
        return DoctorResult(
            model=model,
            ollama_version=version,
            model_digest=digest,
            cloud_disabled=disabled,
            tools_supported=supported,
            checkpoint=checkpoint,
            problems=tuple(problems),
        )

    def complete(
        self,
        messages: Sequence[Message],
        tool_specs: Sequence[ToolSpec],
        settings: ModelSettings,
    ) -> ModelTurn:
        info = self.inspect(settings.model)
        if not info.ready:
            raise ProviderError("; ".join(info.problems))
        try:
            # Explicit host and transport settings ignore cloud/proxy environment
            # defaults. A non-secret header prevents SDK env API-key injection.
            with Client(
                host=LOCAL_HOST,
                timeout=settings.request_timeout_seconds,
                trust_env=False,
                follow_redirects=False,
                headers={"Authorization": "Bearer local-only-no-credentials"},
                transport=self._transport,
            ) as client:
                response = client.chat(
                    model=settings.model,
                    messages=[_wire_message(message) for message in messages],
                    tools=[
                        {"type": "function", "function": spec.model_dump(mode="json")}
                        for spec in tool_specs
                    ],
                    stream=False,
                    think=False,
                    options={
                        "temperature": settings.temperature,
                        "num_ctx": settings.context_tokens,
                        "num_predict": settings.max_output_tokens,
                    },
                )
            if response.done is not True or response.message.role != "assistant":
                raise ProviderError("Incomplete or non-assistant Ollama response")
            calls = tuple(
                ToolCall(
                    name=call.function.name,
                    arguments=dict(call.function.arguments),
                )
                for call in response.message.tool_calls or ()
            )
            usage = {
                key: value
                for key, value in response.model_dump(mode="json").items()
                if value is not None
                and key
                in {
                    "prompt_eval_count",
                    "eval_count",
                    "total_duration",
                    "load_duration",
                    "prompt_eval_duration",
                    "eval_duration",
                }
            }
            return ModelTurn(
                content=response.message.content or "",
                tool_calls=calls,
                usage=usage,
                metadata={
                    "thinking": response.message.thinking,
                    "model": response.model,
                    "model_digest": info.model_digest,
                    "checkpoint": info.checkpoint,
                    "ollama_version": info.ollama_version,
                    "cloud_disabled": info.cloud_disabled,
                },
                finish_reason=response.done_reason,
            )
        except (ResponseError, ConnectionError, httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"{type(exc).__name__}: {exc}") from exc
