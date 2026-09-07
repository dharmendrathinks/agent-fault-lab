"""The one-task experiment configuration and trace-derived accounting."""

from collections.abc import Sequence
from typing import Literal

from pydantic import Field

from agent_fault_lab.evaluation import Evaluation
from agent_fault_lab.faults import FaultMode
from agent_fault_lab.model import Record, RunResult
from agent_fault_lab.trace import Event

type Variant = Literal["baseline", "read-back"]

READ_BACK_INSTRUCTION = (
    " Before claiming completion, use get_task with the ID returned by create_task "
    "and check that the stored task has that exact ID and the exact requested title. "
    "If read-back does not confirm both, do not claim completion."
)


class ExperimentConfig(Record):
    variant: Variant = "baseline"
    fault: FaultMode = "none"


class Metrics(Record):
    model_calls: int
    tool_calls: int
    tool_executions: int
    injected_writes: int
    fault_exercised: bool
    read_back_calls: int
    elapsed_seconds: float
    # None means not reported for every requested model call, never zero tokens.
    prompt_tokens: int | None
    output_tokens: int | None
    model_load_seconds: float | None
    usage_calls_reported: int


class Observation(Record):
    schema_version: Literal[1] = 1
    config: ExperimentConfig
    evaluation: Evaluation
    metrics: Metrics


class RunSpec(Record):
    sequence: int = Field(ge=1)
    trial: int = Field(ge=1)
    config: ExperimentConfig

    @property
    def directory(self) -> str:
        return f"{self.sequence:03d}-{self.config.variant}-{self.config.fault}"


def schedule(trials: int) -> tuple[RunSpec, ...]:
    if type(trials) is not int or not 1 <= trials <= 5:
        raise ValueError("trials must be between 1 and 5 (four runs per trial)")
    specs: list[RunSpec] = []
    for trial in range(1, trials + 1):
        # Reverse both orders on successive repetitions; not randomization.
        variants: tuple[Variant, ...] = ("baseline", "read-back")
        faults: tuple[FaultMode, ...] = ("none", "dropped-write")
        if trial % 2 == 0:
            variants, faults = variants[::-1], faults[::-1]
        for fault in faults:
            for variant in variants:
                specs.append(
                    RunSpec(
                        sequence=len(specs) + 1,
                        trial=trial,
                        config=ExperimentConfig(variant=variant, fault=fault),
                    )
                )
    return tuple(specs)


def measure(events: Sequence[Event], result: RunResult) -> Metrics:
    returned = [event for event in events if event.kind == "model_returned"]

    def total(key: str) -> int | None:
        values: list[int] = []
        for event in returned:
            turn = event.data.get("turn")
            usage = turn.get("usage") if isinstance(turn, dict) else None
            value = usage.get(key) if isinstance(usage, dict) else None
            if type(value) is not int or value < 0:
                return None
            values.append(value)
        if len(values) != result.model_calls or not values:
            return None
        return sum(values)

    injected = sum(event.kind == "fault_injected" for event in events)
    reads = 0
    for event in events:
        call = event.data.get("call")
        if (
            event.kind == "tool_requested"
            and isinstance(call, dict)
            and call.get("name") == "get_task"
        ):
            reads += 1
    stopped = [event.elapsed_seconds for event in events if event.kind == "run_stopped"]
    if len(stopped) != 1:
        raise ValueError("Expected exactly one execution-stop event")
    load_ns = total("load_duration")
    usage_calls = 0
    for event in returned:
        turn = event.data.get("turn")
        if (
            isinstance(turn, dict)
            and isinstance(turn.get("usage"), dict)
            and turn["usage"]
        ):
            usage_calls += 1
    return Metrics(
        model_calls=result.model_calls,
        tool_calls=result.tool_calls,
        tool_executions=result.tool_executions,
        injected_writes=injected,
        fault_exercised=injected > 0,
        read_back_calls=reads,
        elapsed_seconds=stopped[0],
        prompt_tokens=total("prompt_eval_count"),
        output_tokens=total("eval_count"),
        model_load_seconds=None if load_ns is None else load_ns / 1_000_000_000,
        usage_calls_reported=usage_calls,
    )
