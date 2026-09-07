"""M07 saved evidence: attempts and duplicate effects remain distinct."""

from collections import Counter
from collections.abc import Sequence
from typing import Literal, Self

from pydantic import Field, JsonValue, field_validator, model_validator

from agent_fault_lab.evaluation import Evaluation
from agent_fault_lab.experiments import Metrics
from agent_fault_lab.model import Record
from agent_fault_lab.reporting import json_block, render_report
from agent_fault_lab.retries import RETRY_PAIR, RETRY_POLICIES, RetryCase, RetryConfig
from agent_fault_lab.trace import Event


class RetryCounts(Record):
    operations: int = Field(ge=0)
    attempts: int = Field(ge=0)
    retries: int = Field(ge=0)
    storage_entries: int = Field(ge=0)
    replayed_results: int = Field(ge=0)
    delivery_errors: int = Field(ge=0)
    contract_errors: int = Field(ge=0)
    fault_activations: int = Field(ge=0)


def count_retries(events: Sequence[Event]) -> RetryCounts:
    return RetryCounts(
        operations=sum(e.kind == "operation_started" for e in events),
        attempts=sum(e.kind == "attempt_started" for e in events),
        retries=sum(e.kind == "retry_scheduled" for e in events),
        storage_entries=sum(e.kind == "storage_entered" for e in events),
        replayed_results=sum(
            e.kind == "storage_returned" and e.data.get("replayed") is True
            for e in events
        ),
        delivery_errors=sum(
            e.kind == "attempt_failed" and e.data.get("reason") == "delivery_error"
            for e in events
        ),
        contract_errors=sum(
            e.kind == "attempt_failed" and e.data.get("reason") == "invalid_result"
            for e in events
        ),
        fault_activations=sum(e.kind == "retry_fault_injected" for e in events),
    )


class RetryArtifact(Record):
    schema_version: Literal[1] = 1

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("Unsupported retry artifact schema version")
        return value


class RetryObservation(RetryArtifact):
    artifact: Literal["retry-run"] = "retry-run"
    config: RetryConfig
    evaluation: Evaluation
    metrics: Metrics
    retry: RetryCounts

    @model_validator(mode="after")
    def consistent(self) -> Self:
        r = self.retry
        execution = self.evaluation.execution
        if (
            r.operations != execution.tool_executions
            or r.operations > execution.tool_calls
        ):
            raise ValueError("Logical operation accounting disagrees with execution")
        if r.attempts != r.operations + r.retries:
            raise ValueError("Attempts must include the initial operation and retries")
        maximum = 1 if self.config.policy == "single-attempt" else 2
        if not r.operations <= r.attempts <= maximum * r.operations:
            raise ValueError("Attempt count exceeds the declared policy")
        if not r.replayed_results <= r.storage_entries <= r.attempts:
            raise ValueError("Storage accounting exceeds attempts")
        if r.delivery_errors + r.contract_errors > r.attempts:
            raise ValueError("Error counts exceed attempts")
        if r.fault_activations > r.delivery_errors or r.fault_activations > 1:
            raise ValueError("A once-only fault must produce a delivery error")
        if self.config.case == "retry-healthy" and r.fault_activations:
            raise ValueError("Healthy execution cannot activate a fault")
        if self.config.policy != "retry-idempotent" and r.replayed_results:
            raise ValueError("Unprotected execution cannot replay a stored result")
        if self.metrics.fault_exercised != (r.fault_activations > 0):
            raise ValueError("Fault accounting disagrees")
        if (
            self.metrics.model_calls,
            self.metrics.tool_calls,
            self.metrics.tool_executions,
        ) != (execution.model_calls, execution.tool_calls, execution.tool_executions):
            raise ValueError("Execution metrics disagree")
        return self


class RetrySpec(Record):
    sequence: int = Field(ge=1)
    trial: int = Field(ge=1, le=5)
    config: RetryConfig

    @property
    def directory(self) -> str:
        return f"{self.sequence:03d}-{self.config.policy}-{self.config.case}"


def retry_schedule(
    case: RetryCase, trials: int, *, include_control: bool = False
) -> tuple[RetrySpec, ...]:
    if type(trials) is not int or not 1 <= trials <= 5:
        raise ValueError("Expected 1–5 trials")
    policies = RETRY_POLICIES if include_control else RETRY_PAIR
    specs: list[RetrySpec] = []
    for trial in range(1, trials + 1):
        for policy in policies if trial % 2 else policies[::-1]:
            specs.append(
                RetrySpec(
                    sequence=len(specs) + 1,
                    trial=trial,
                    config=RetryConfig(case=case, policy=policy),
                )
            )
    return tuple(specs)


class RetryEntry(Record):
    spec: RetrySpec
    observation: RetryObservation

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.spec.config != self.observation.config:
            raise ValueError("Scheduled retry policy/case does not match observation")
        return self


class RetryComparison(RetryArtifact):
    artifact: Literal["retry-comparison"] = "retry-comparison"
    client: str
    include_control: bool
    planned: tuple[RetrySpec, ...]
    entries: tuple[RetryEntry, ...]
    status: Literal["finished", "stopped", "interrupted", "harness_error"]
    error: str | None = None
    partial_directory: str | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        width = 3 if self.include_control else 2
        if not self.planned or len(self.planned) % width:
            raise ValueError("Expected the complete retry schedule")
        if self.planned != retry_schedule(
            self.planned[0].config.case,
            len(self.planned) // width,
            include_control=self.include_control,
        ):
            raise ValueError("Invalid retry schedule")
        if tuple(e.spec for e in self.entries) != self.planned[: len(self.entries)]:
            raise ValueError("Entries must be a prefix of the schedule")
        if any(e.observation.evaluation.client != self.client for e in self.entries):
            raise ValueError("Comparison client disagrees")
        if self.status == "finished" and (
            len(self.entries) != len(self.planned)
            or self.error
            or self.partial_directory
        ):
            raise ValueError("Finished comparison must contain every run")
        if self.partial_directory is not None and (
            len(self.entries) == len(self.planned)
            or self.partial_directory != self.planned[len(self.entries)].directory
        ):
            raise ValueError("Partial directory must identify the next run")
        return self


def render_retry_report(observation: RetryObservation) -> str:
    return (
        render_report(observation.evaluation)
        + "\n## M07 retry experiment\n\n"
        + json_block(
            {
                "config": observation.config.model_dump(mode="json"),
                "metrics": observation.metrics.model_dump(mode="json"),
                "retry": observation.retry.model_dump(mode="json"),
            }
        )
        + "\nLogical calls, delivery attempts and storage entries "
        "are different counts. "
        "A missing reply does not establish whether a write committed. Inspect the "
        "independent task snapshot; replay receipts do not replace evaluation.\n\n"
        "One operation ID is reused for executor retries. Separate model calls get "
        "new IDs, even with identical titles. Protection is at most one task effect "
        "per retained operation ID, not exactly-once delivery or model intent. "
        "There are no delayed retries, cancellation or process resume in M07.\n"
    )


def render_retry_comparison(comparison: RetryComparison) -> str:
    lines = [
        "# Agent Fault Lab — M07 retry comparison\n",
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
        "Scripted behavior demonstrates machinery, not model behavior. No automatic "
        "winner is declared. Invalid/absent claims and unknown outcomes "
        "remain visible.\n",
    ]
    for policy in dict.fromkeys(spec.config.policy for spec in comparison.planned):
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
            "fault_exercised_runs": sum(r.retry.fault_activations > 0 for r in runs),
            "fault_not_exercised_runs": sum(
                r.config.case != "retry-healthy" and r.retry.fault_activations == 0
                for r in runs
            ),
            "stored_task_rows": [
                len(e.state.rows) if e.state.rows is not None else None
                for e in evaluations
            ],
            "retry": {
                key: sum(r.retry.model_dump()[key] for r in runs)
                for key in RetryCounts.model_fields
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
        "Both retry policies use one immediate retry and the same fault schedule. "
        "Only deduplication differs. The optional single-attempt control changes "
        "retry admission. Prompts, tools, model settings and grading stay fixed. "
        "Fault metadata stays outside model-facing results. Zero false-success "
        "claims with zero assessable completion claims is not reliability evidence.\n"
    )
    return "\n".join(lines)
