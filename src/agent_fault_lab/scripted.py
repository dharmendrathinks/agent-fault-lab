"""Deterministic test machinery. No inference, learned behavior, or network."""

from collections.abc import Callable, Sequence

from agent_fault_lab.model import (
    Message,
    ModelSettings,
    ModelTurn,
    ProviderError,
    ToolSpec,
)

type Step = ModelTurn | ProviderError | Callable[[Sequence[Message]], ModelTurn]


class ScriptedClient:
    label = "scripted-test-client (NOT an AI model)"

    def __init__(self, steps: Sequence[Step]) -> None:
        self._steps = iter(steps)
        self.requests: list[tuple[Message, ...]] = []

    def complete(
        self,
        messages: Sequence[Message],
        tool_specs: Sequence[ToolSpec],
        settings: ModelSettings,
    ) -> ModelTurn:
        self.requests.append(
            tuple(message.model_copy(deep=True) for message in messages)
        )
        try:
            step = next(self._steps)
        except StopIteration as exc:
            raise ProviderError("Script exhausted; this is a test setup error") from exc
        if isinstance(step, ProviderError):
            raise step
        return step(messages) if callable(step) else step.model_copy(deep=True)
