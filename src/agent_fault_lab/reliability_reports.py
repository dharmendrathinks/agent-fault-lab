"""Versioned M06 evidence and pure reporting, preserving independent grades."""

from collections import Counter
from collections.abc import Sequence
from typing import Literal, Self

from pydantic import Field, JsonValue, field_validator, model_validator

from agent_fault_lab.evaluation import Evaluation
from agent_fault_lab.experiments import Metrics
from agent_fault_lab.model import Record
from agent_fault_lab.reliability import POLICIES, ReliabilityConfig, ResponseCase
from agent_fault_lab.reporting import json_block, render_report
from agent_fault_lab.trace import Event


class ContractCounts(Record):
    valid: int = Field(ge=0)
    syntax_errors: int = Field(ge=0)
    schema_errors: int = Field(ge=0)
    request_errors: int = Field(ge=0)
    unchecked: int = Field(ge=0)
    fault_activations: int = Field(ge=0)


def count_contracts(events: Sequence[Event]) -> ContractCounts:
    checked = Counter(
        event.data["status"] for event in events if event.kind == "contract_checked"
    )
    return ContractCounts(
        valid=checked["valid"],
        syntax_errors=checked["syntax"],
        schema_errors=checked["schema"],
        request_errors=checked["request"],
        unchecked=sum(e.kind == "contract_unchecked" for e in events),
        fault_activations=sum(
            e.kind in {"response_fault_injected", "fault_injected"} for e in events
        ),
    )


class ReliabilityArtifact(Record):
    # Schema 1 is retained for the initial M06 live smoke. Its inherited
    # metrics.fault_exercised field counted dropped writes only; schema 2 counts
    # every activated fault. ContractCounts are authoritative in both versions.
    schema_version: Literal[1, 2] = 2

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_version(cls, value: object) -> object:
        if type(value) is not int or value not in (1, 2):
            raise ValueError("Unsupported reliability artifact schema version")
        return value


class ReliabilityObservation(ReliabilityArtifact):
    artifact: Literal["reliability-run"] = "reliability-run"
    config: ReliabilityConfig
    evaluation: Evaluation
    metrics: Metrics
    contracts: ContractCounts

    @model_validator(mode="after")
    def consistent(self) -> Self:
        c = self.contracts
        execution = self.evaluation.execution
        if (
            c.valid + c.syntax_errors + c.schema_errors + c.request_errors + c.unchecked
            != execution.tool_calls
        ):
            raise ValueError("Contract accounting does not match tool calls")
        if self.config.policy == "pass-through" and c.unchecked != execution.tool_calls:
            raise ValueError("Pass-through calls must remain unchecked")
        if self.config.policy == "validated" and c.unchecked:
            raise ValueError("Validated calls cannot be unchecked")
        if c.fault_activations > execution.tool_executions:
            raise ValueError("Fault activations exceed tool executions")
        if self.config.case == "healthy" and c.fault_activations:
            raise ValueError("Healthy case cannot activate a fault")
        if self.schema_version == 2 and self.metrics.fault_exercised != (
            c.fault_activations > 0
        ):
            raise ValueError("Fault activation accounting disagrees")
        if (
            self.metrics.model_calls,
            self.metrics.tool_calls,
            self.metrics.tool_executions,
        ) != (execution.model_calls, execution.tool_calls, execution.tool_executions):
            raise ValueError("Execution accounting disagrees with evaluation")
        return self


class ReliabilitySpec(Record):
    sequence: int = Field(ge=1)
    trial: int = Field(ge=1, le=5)
    config: ReliabilityConfig

    @property
    def directory(self) -> str:
        return f"{self.sequence:03d}-{self.config.policy}-{self.config.case}"


def reliability_schedule(
    case: ResponseCase, trials: int
) -> tuple[ReliabilitySpec, ...]:
    if type(trials) is not int or not 1 <= trials <= 5:
        raise ValueError("Expected 1–5 trials")
    specs: list[ReliabilitySpec] = []
    for trial in range(1, trials + 1):
        for policy in POLICIES if trial % 2 else POLICIES[::-1]:
            specs.append(
                ReliabilitySpec(
                    sequence=len(specs) + 1,
                    trial=trial,
                    config=ReliabilityConfig(case=case, policy=policy),
                )
            )
    return tuple(specs)


class ReliabilityEntry(Record):
    spec: ReliabilitySpec
    observation: ReliabilityObservation

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.spec.config != self.observation.config:
            raise ValueError("Scheduled policy/case does not match the observation")
        return self


class ReliabilityComparison(ReliabilityArtifact):
    artifact: Literal["reliability-comparison"] = "reliability-comparison"
    client: str
    planned: tuple[ReliabilitySpec, ...]
    entries: tuple[ReliabilityEntry, ...]
    status: Literal["finished", "stopped", "interrupted", "harness_error"]
    error: str | None = None
    partial_directory: str | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if not self.planned or len(self.planned) % 2:
            raise ValueError("Expected a complete paired schedule")
        expected = reliability_schedule(
            self.planned[0].config.case, len(self.planned) // 2
        )
        if self.planned != expected:
            raise ValueError("Invalid comparison schedule")
        if tuple(e.spec for e in self.entries) != self.planned[: len(self.entries)]:
            raise ValueError("Recorded entries must be a prefix of the schedule")
        if any(e.observation.evaluation.client != self.client for e in self.entries):
            raise ValueError("Comparison client disagrees with recorded entries")
        if self.status == "finished" and (
            len(self.entries) != len(self.planned)
            or self.error
            or self.partial_directory
        ):
            raise ValueError("Finished comparison must contain all runs")
        if self.partial_directory is not None and (
            len(self.entries) == len(self.planned)
            or self.partial_directory != self.planned[len(self.entries)].directory
        ):
            raise ValueError("Partial directory must identify the next scheduled run")
        return self


def render_reliability_report(observation: ReliabilityObservation) -> str:
    return (
        render_report(observation.evaluation)
        + "\n## M06 response contract experiment\n\n"
        + json_block(
            {
                "config": observation.config.model_dump(mode="json"),
                "contracts": observation.contracts.model_dump(mode="json"),
                "metrics": observation.metrics.model_dump(mode="json"),
            }
        )
        + "\nUnchecked responses were passed through, not verified. "
        "Contract validation "
        "checks syntax, schema and request consistency; it does not prove a write. "
        "A rejected response may follow a committed write. Fault activation is "
        "external evidence; an unexercised fault is not recovery.\n\n"
        + "Raw UTF-8 response bytes are base64 encoded in response_captured trace "
        "events. Tool messages contain only delivered content; execution accounting "
        "and fault metadata stay outside the model-facing envelope. Both policies "
        "share the prompt, tools, limits and grader; only response delivery differs.\n"
    )


def render_reliability_comparison(comparison: ReliabilityComparison) -> str:
    lines = [
        "# Agent Fault Lab — M06 response contract comparison\n",
        json_block(
            {
                "client": comparison.client,
                "status": comparison.status,
                "error": comparison.error,
                "partial_directory": comparison.partial_directory,
            }
        ),
        f"Recorded {len(comparison.entries)} of "
        f"{len(comparison.planned)} planned runs.\n",
        "Scripted results demonstrate test machinery, not model behavior. "
        "There is no automatic winner. Zero false-success claims with zero "
        "assessable completion claims is not evidence of reliability.\n",
    ]
    for policy in POLICIES:
        runs = [
            e.observation for e in comparison.entries if e.spec.config.policy == policy
        ]
        evaluations = [r.evaluation for r in runs]
        counts: dict[str, JsonValue] = {
            "planned": sum(s.config.policy == policy for s in comparison.planned),
            "recorded": len(runs),
            "execution": dict(Counter(e.execution.status for e in evaluations)),
            "task_outcome": dict(Counter(e.task_outcome for e in evaluations)),
            "report_status": dict(Counter(e.report.status for e in evaluations)),
            "claim_support": dict(Counter(e.claim_support for e in evaluations)),
            "false_success_claims": sum(e.false_success is True for e in evaluations),
            "assessable_completion_claims": sum(
                e.report.claim is not None
                and e.report.claim.status == "completed"
                and e.claim_support in {"supported", "contradicted"}
                for e in evaluations
            ),
            "unassessable_false_success": sum(
                e.false_success is None for e in evaluations
            ),
            "fault_exercised_runs": sum(
                r.contracts.fault_activations > 0 for r in runs
            ),
            "fault_not_exercised_runs": sum(
                r.config.case != "healthy" and r.contracts.fault_activations == 0
                for r in runs
            ),
            "contracts": {
                key: sum(r.contracts.model_dump()[key] for r in runs)
                for key in ContractCounts.model_fields
            },
        }
        lines.extend([f"## {policy}\n", json_block(counts)])
    lines.append("## Per-run evidence\n")
    for entry in comparison.entries:
        lines.extend(
            [
                f"### [{entry.spec.directory}]({entry.spec.directory}/report.md)\n",
                json_block(entry.observation.model_dump(mode="json")),
            ]
        )
    lines.append(
        "Only response delivery policy changes; both policies validate arguments. "
        "A response can pass validation while falsely describing storage. "
        "Invalid/absent claims, unknown outcomes and unexercised faults "
        "remain visible. "
        "Policy order reverses across trials; this is not randomization.\n"
    )
    return "\n".join(lines)
