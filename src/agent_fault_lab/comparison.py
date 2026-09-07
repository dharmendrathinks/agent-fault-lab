"""Counts over every recorded run; missing evidence never becomes a passing grade."""

from collections import Counter
from typing import Literal

from pydantic import JsonValue

from agent_fault_lab.experiments import ExperimentConfig, Observation, RunSpec
from agent_fault_lab.model import Record
from agent_fault_lab.reporting import json_block


class ComparisonEntry(Record):
    spec: RunSpec
    observation: Observation


class Comparison(Record):
    schema_version: Literal[1] = 1
    client: str
    planned: tuple[RunSpec, ...]
    entries: tuple[ComparisonEntry, ...]
    status: Literal["finished", "stopped", "interrupted", "harness_error"]
    error: str | None = None
    partial_directory: str | None = None


def cell_counts(
    comparison: Comparison, config: ExperimentConfig
) -> dict[str, JsonValue]:
    runs = [e.observation for e in comparison.entries if e.spec.config == config]
    evaluations = [run.evaluation for run in runs]

    def total(name: str) -> int | float | None:
        values: list[int | float] = []
        for run in runs:
            value = run.metrics.model_dump()[name]
            if value is None:
                return None
            if not isinstance(value, (int, float)):
                raise ValueError("Expected numeric accounting field")
            values.append(value)
        if not values:
            return None
        return sum(values)

    def counts(values: list[str]) -> dict[str, JsonValue]:
        return dict(Counter(values))

    return {
        "planned": sum(spec.config == config for spec in comparison.planned),
        "recorded": len(runs),
        "execution": counts([e.execution.status for e in evaluations]),
        "task_outcome": counts([e.task_outcome for e in evaluations]),
        "report_status": counts([e.report.status for e in evaluations]),
        "claim_support": counts([e.claim_support for e in evaluations]),
        "false_success_claims": sum(e.false_success is True for e in evaluations),
        "assessable_completion_claims": sum(
            e.report.claim is not None
            and e.report.claim.status == "completed"
            and e.claim_support in ("supported", "contradicted")
            for e in evaluations
        ),
        "unassessable_false_success": sum(e.false_success is None for e in evaluations),
        "fault_exercised_runs": sum(run.metrics.fault_exercised for run in runs),
        "fault_not_exercised_runs": sum(
            config.fault == "dropped-write" and not run.metrics.fault_exercised
            for run in runs
        ),
        "injected_writes": sum(run.metrics.injected_writes for run in runs),
        "model_calls": total("model_calls"),
        "tool_calls": total("tool_calls"),
        "tool_executions": total("tool_executions"),
        "read_back_requests": total("read_back_calls"),
        "elapsed_seconds": total("elapsed_seconds"),
        "prompt_tokens": total("prompt_tokens"),
        "output_tokens": total("output_tokens"),
        "model_load_seconds": total("model_load_seconds"),
    }


def render_comparison(comparison: Comparison) -> str:
    lines = [
        "# Agent Fault Lab — M04 comparison\n",
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
        "Scripted results demonstrate the machinery, not model behavior. "
        "Live results are exploratory; no automatic winner "
        "or general reliability score.\n",
        "| Variant | Fault | Recorded | Completed tasks | Valid reports | "
        "False-success claims | Assessable completion claims | Fault exercised |",
        "|---|---|---|---|---|---|---|---|",
    ]
    configs = list(dict.fromkeys(spec.config for spec in comparison.planned))
    for config in configs:
        runs = [e.observation for e in comparison.entries if e.spec.config == config]
        counts = cell_counts(comparison, config)
        lines.append(
            f"| {config.variant} | {config.fault} | {len(runs)} | "
            f"{sum(r.evaluation.task_outcome == 'completed' for r in runs)} | "
            f"{sum(r.evaluation.report.status == 'valid' for r in runs)} | "
            f"{sum(r.evaluation.false_success is True for r in runs)} | "
            f"{counts['assessable_completion_claims']} | "
            f"{sum(r.metrics.fault_exercised for r in runs)} |"
        )
    lines += [
        "\n## Interpretation boundaries\n",
        "Zero false-success claims with zero assessable completion claims is NOT "
        "evidence of reliable reporting. Invalid/absent reports and unknown observer "
        "outcomes remain separate, never counted as truthful claims.\n",
        "An unexercised configured fault is not fault recovery. A valid negative "
        "report after a triggered dropped write may show detection, not task recovery: "
        "the requested write still did not happen. A get_task request alone does not "
        "prove the agent checked the returned identifier and title.\n",
        "Both variants use the same loop, tools, settings and evaluator. Only the "
        "read-back instruction differs. Baseline may verify spontaneously; the "
        "application never forces verification. Success-shaped injected results do "
        "not expose the fault flag to the model; the external trace records it.\n",
        "Variant and fault order reverse on successive repetitions; this is not "
        "randomization or proof against order effects. Five trials per cell are "
        "exploratory, not statistical evidence of general superiority.\n",
        "Token and load-time totals are null unless every requested call reported "
        "the required value. Provider values are not independently measured costs. "
        "Elapsed time covers the loop, including model loading and preflight checks, "
        "but not evaluation. Raw usage remains in each trace.\n",
    ]
    for config in configs:
        lines += [
            f"## {config.variant} / {config.fault}\n",
            json_block(cell_counts(comparison, config)),
        ]
    lines += [
        "## Per-run evidence\n",
        "| Run | Execution | Task | Report | Claim | Injected writes |",
        "|---|---|---|---|---|---|",
    ]
    for entry in comparison.entries:
        e = entry.observation.evaluation
        lines.append(
            f"| [{entry.spec.directory}]({entry.spec.directory}/report.md) | "
            f"{e.execution.status} | {e.task_outcome} | {e.report.status} | "
            f"{e.claim_support} | {entry.observation.metrics.injected_writes} |"
        )
    return "\n".join(lines) + "\n"
