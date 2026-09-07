"""Saved M08/M09 observations; rendering performs no execution or SQL reads."""

from collections import Counter
from typing import Literal, Self

from pydantic import Field, model_validator

from agent_fault_lab.evaluation import Evaluation
from agent_fault_lab.execution_types import (
    ExecutionLimits,
    ProcessCase,
    ProcessConfig,
    policies_for,
)
from agent_fault_lab.experiments import Metrics
from agent_fault_lab.journal import JournalEvent, Versioned
from agent_fault_lab.reporting import json_block, render_report


class ProcessCounts(Versioned):
    attempts: int = Field(ge=0, le=18)
    retries_scheduled: int = Field(ge=0)
    deadlines: int = Field(ge=0)
    cancellations: int = Field(ge=0)
    kills: int = Field(ge=0)
    confirmed_exits: int = Field(ge=0)
    fault_activations: int = Field(ge=0)
    replay_receipts: int = Field(ge=0)
    sessions: int = Field(ge=1)
    interrupted_reservations: int = Field(ge=0)


def process_counts(events: list[JournalEvent], attempts: int) -> ProcessCounts:
    counts = Counter(e.kind for e in events)
    worker = [e.data.get("event") for e in events if e.kind == "worker_evidence"]
    return ProcessCounts(
        attempts=attempts,
        retries_scheduled=counts["retry_scheduled"],
        deadlines=counts["deadline_expired"],
        cancellations=counts["cancellation_requested"],
        kills=counts["kill_requested"],
        confirmed_exits=counts["worker_exit_confirmed"],
        fault_activations=sum(
            isinstance(e, dict) and e.get("kind") == "fault_activated" for e in worker
        ),
        replay_receipts=sum(
            isinstance(e, dict)
            and e.get("kind") == "storage_committed"
            and isinstance(data := e.get("data"), dict)
            and data.get("replayed") is True
            for e in worker
        ),
        sessions=len({e.session_id for e in events}),
        interrupted_reservations=counts["interrupted_reservation_charged"],
    )


class ProcessObservation(Versioned):
    artifact: Literal["execution-run"] = "execution-run"
    run_id: str
    config: ProcessConfig
    execution_limits: ExecutionLimits
    evaluation: Evaluation
    metrics: Metrics
    process: ProcessCounts

    @model_validator(mode="after")
    def consistent(self) -> Self:
        e, m = self.evaluation.execution, self.metrics
        if (e.model_calls, e.tool_calls, e.tool_executions) != (
            m.model_calls,
            m.tool_calls,
            m.tool_executions,
        ):
            raise ValueError("Execution metrics disagree")
        if self.process.attempts > self.execution_limits.total_attempts:
            raise ValueError("Attempt accounting exceeds run limit")
        if m.fault_exercised != (self.process.fault_activations > 0):
            raise ValueError("Fault accounting disagrees")
        return self


def render_process_report(observation: ProcessObservation) -> str:
    return (
        render_report(observation.evaluation)
        + "\n## Process execution\n\n"
        + json_block(
            {
                "config": observation.config.model_dump(mode="json"),
                "limits": observation.execution_limits.model_dump(mode="json"),
                "metrics": observation.metrics.model_dump(mode="json"),
                "process": observation.process.model_dump(mode="json"),
            }
        )
        + (
            "\nA deadline does not prove cancellation or undo a commit. Evaluation "
            "occurs after owned worker exit. Protected retries share one operation ID; "
            "separate "
            "model requests do not. Run and task journals are separate transactions. "
            "Elapsed time sums observed session time; unknown crash downtime "
            "is excluded. "
            "Missing usage, responses and claims remain unknown. Use `aflab diagnose` "
            "for journal checkpoints, evidence references and gaps.\n"
        )
    )


class ProcessSpec(Versioned):
    sequence: int = Field(ge=1)
    trial: int = Field(ge=1, le=5)
    config: ProcessConfig

    @property
    def directory(self) -> str:
        return f"{self.sequence:03d}-{self.config.policy}-{self.config.case}"


def process_schedule(case: ProcessCase, trials: int) -> tuple[ProcessSpec, ...]:
    if type(trials) is not int or not 1 <= trials <= 5:
        raise ValueError("Expected 1–5 trials")
    policies = policies_for(case)
    return tuple(
        ProcessSpec(
            sequence=2 * (trial - 1) + index,
            trial=trial,
            config=ProcessConfig(case=case, policy=policy),
        )
        for trial in range(1, trials + 1)
        for index, policy in enumerate(policies if trial % 2 else policies[::-1], 1)
    )


class ProcessEntry(Versioned):
    spec: ProcessSpec
    observation: ProcessObservation

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.spec.config != self.observation.config:
            raise ValueError("Scheduled configuration disagrees")
        return self


class ProcessComparison(Versioned):
    artifact: Literal["execution-comparison"] = "execution-comparison"
    client: str
    planned: tuple[ProcessSpec, ...]
    entries: tuple[ProcessEntry, ...]
    status: Literal["finished", "stopped", "interrupted", "harness_error"]
    error: str | None = None
    partial_directory: str | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if (
            not self.planned
            or len(self.planned) % 2
            or self.planned
            != process_schedule(self.planned[0].config.case, len(self.planned) // 2)
        ):
            raise ValueError("Invalid process schedule")
        if tuple(e.spec for e in self.entries) != self.planned[: len(self.entries)]:
            raise ValueError("Entries must be a schedule prefix")
        if any(e.observation.evaluation.client != self.client for e in self.entries):
            raise ValueError("Comparison client disagrees")
        if self.status == "finished" and (
            len(self.entries) != len(self.planned)
            or self.error
            or self.partial_directory
        ):
            raise ValueError("Finished comparison is incomplete")
        if self.partial_directory is not None and (
            len(self.entries) >= len(self.planned)
            or self.partial_directory != self.planned[len(self.entries)].directory
        ):
            raise ValueError("Invalid partial directory")
        return self


def render_process_comparison(comparison: ProcessComparison) -> str:
    lines = [
        "# Process execution comparison\n",
        json_block(
            {
                "status": comparison.status,
                "error": comparison.error,
                "partial_directory": comparison.partial_directory,
            }
        ),
    ]
    for policy in dict.fromkeys(s.config.policy for s in comparison.planned):
        runs = [
            e.observation for e in comparison.entries if e.spec.config.policy == policy
        ]
        evaluations = [r.evaluation for r in runs]
        lines.extend(
            [
                f"## {policy}\n",
                json_block(
                    {
                        "planned": sum(
                            s.config.policy == policy for s in comparison.planned
                        ),
                        "recorded": len(runs),
                        "execution": dict(
                            Counter(e.execution.status for e in evaluations)
                        ),
                        "task_outcome": dict(
                            Counter(e.task_outcome for e in evaluations)
                        ),
                        "report_status": dict(
                            Counter(e.report.status for e in evaluations)
                        ),
                        "claim_support": dict(
                            Counter(e.claim_support for e in evaluations)
                        ),
                        "assessable_completion_claims": sum(
                            e.report.claim is not None
                            and e.report.claim.status == "completed"
                            and e.claim_support in {"supported", "contradicted"}
                            for e in evaluations
                        ),
                        "false_success_claims": sum(
                            e.false_success is True for e in evaluations
                        ),
                        "unassessable_false_success": sum(
                            e.false_success is None for e in evaluations
                        ),
                        "fault_exercised_runs": sum(
                            r.metrics.fault_exercised for r in runs
                        ),
                        "fault_not_exercised_runs": sum(
                            not r.metrics.fault_exercised
                            and r.config.case
                            not in {"process-healthy", "restart-healthy"}
                            for r in runs
                        ),
                        "attempts": sum(r.process.attempts for r in runs),
                        "deadlines": sum(r.process.deadlines for r in runs),
                        "cancellations": sum(r.process.cancellations for r in runs),
                        "stored_task_rows": [
                            len(e.state.rows) if e.state.rows is not None else None
                            for e in evaluations
                        ],
                    }
                ),
            ]
        )
    for entry in comparison.entries:
        lines.extend(
            [
                f"## [{entry.spec.directory}]({entry.spec.directory}/report.md)\n",
                json_block(entry.observation.model_dump(mode="json")),
            ]
        )
    lines.append(
        "Scripted runs demonstrate machinery. No automatic winner is declared. "
        "Zero false-success claims without assessable claims is not "
        "reliability evidence. "
        "Only the declared retry or cancellation policy changes within a pair.\n"
    )
    return "\n".join(lines)
