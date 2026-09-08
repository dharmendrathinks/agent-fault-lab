"""Saved, stratified study results. Unknowns and failed slots stay visible."""

import json
import math
import statistics
from collections import Counter
from typing import Any

from agent_fault_lab.boundary_records import BoundaryEvaluation
from agent_fault_lab.experiments import Observation
from agent_fault_lab.retry_reports import RetryObservation
from agent_fault_lab.runtime_records import RuntimeResult
from agent_fault_lab.scanner import ScanResult
from agent_fault_lab.study_records import Entry, Study


def facts(entry: Entry) -> dict[str, Any]:
    if not entry.result:
        return {
            "task": "unknown",
            "report": "absent",
            "claim": "not_evaluated",
            "execution": entry.status,
            "storage": entry.inspection.status if entry.inspection else "not inspected",
        }
    evidence = entry.result.evidence
    if isinstance(evidence, RuntimeResult):
        evidence = evidence.evaluation
    if isinstance(evidence, ScanResult):
        benign = entry.slot.case.endswith("-benign")
        return {
            "scanner": evidence.status,
            "complete": evidence.complete,
            "scanner_error": evidence.status == "error",
            "scanner_detected": (evidence.status == "blocked")
            if not benign and evidence.complete
            else None,
            "false_alarm": (evidence.status == "blocked")
            if benign and evidence.complete
            else None,
        }
    evaluation = (
        evidence.evaluation
        if isinstance(evidence, (Observation, RetryObservation))
        else evidence
    )
    result: dict[str, Any] = {
        "task": evaluation.task_outcome,
        "report": evaluation.report.status,
        "claim": evaluation.claim_support,
        "execution": evaluation.execution.status
        if evaluation.execution
        else evidence.status
        if isinstance(evidence, BoundaryEvaluation)
        else "unknown",
        "completion_claim": bool(
            evaluation.report.claim and evaluation.report.claim.status == "completed"
        ),
        "storage": evaluation.state.status,
    }
    if isinstance(evidence, (Observation, RetryObservation)):
        result.update(evidence.metrics.model_dump())
        rows = evidence.evaluation.state.rows
        result["duplicate_effects"] = (
            max(0, len(rows) - 1) if rows is not None else None
        )
        if isinstance(evidence, RetryObservation):
            result["retry"] = evidence.retry.model_dump()
    if isinstance(evidence, BoundaryEvaluation):
        result.update(
            {
                "scanner": evidence.scan.status,
                "model_calls": evidence.model_calls,
                "tool_calls": evidence.tool_calls,
                "tool_executions": evidence.tool_executions,
                "scenario_exercised": evidence.scenario_exercised,
                "authorization": evidence.authorization.model_dump(),
                "context": evidence.context.model_dump() if evidence.context else None,
            }
        )
    return result


def wilson(successes: int, total: int) -> tuple[float, float] | None:
    if not 0 <= successes <= total:
        raise ValueError("Invalid proportion counts")
    if not total:
        return None
    z = 1.959963984540054
    p = successes / total
    divisor = 1 + z * z / total
    center = (p + z * z / (2 * total)) / divisor
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / divisor
    return max(0.0, center - half), min(1.0, center + half)


def render_study(study: Study) -> str:
    inventory: Counter[str] = Counter(entry.status for entry in study.entries)
    lines = [
        f"# M14 study: {study.plan.preset}",
        "",
        f"Mode: **{study.mode}**. Offline agents are scripted test machinery, "
        "not AI evidence.",
        "",
        f"Declared axis: `{study.plan.axis}`. "
        f"Seed {study.plan.seed} controls order only.",
        f"Active time: {study.active_seconds:.3f} / "
        f"{study.plan.budget_seconds:.3f} seconds; "
        f"reserved after an unfinished checkpoint: "
        f"{study.reserved_seconds:.3f} seconds.",
        "",
        f"Planned: {len(study.entries)}; "
        f"started: {len(study.entries) - inventory['unstarted']}; "
        + "; ".join(
            f"{status}: {inventory[status]}"
            for status in ("completed", "failed", "interrupted", "running", "unstarted")
        )
        + ".",
        "Completed inventory means a sealed observation, "
        "not successful task completion.",
        "",
        "## Per-scenario cells",
        "",
        "| Case | Participant | Policy | Planned | Sealed | Known task outcomes | "
        "Completed tasks | Assessable completion claims | "
        "Contradicted completion claims | Total seconds min / median / max |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    keys = sorted(
        {(e.slot.case, e.slot.participant, e.slot.policy) for e in study.entries}
    )
    intervals = []
    for case, participant, policy in keys:
        entries = [
            e
            for e in study.entries
            if (e.slot.case, e.slot.participant, e.slot.policy)
            == (case, participant, policy)
        ]
        values = [facts(e) for e in entries]
        known = sum(v.get("task") in ("completed", "not_completed") for v in values)
        completed = sum(v.get("task") == "completed" for v in values)
        assessable = sum(
            bool(v.get("completion_claim"))
            and v.get("claim") in ("supported", "contradicted")
            for v in values
        )
        contradicted = sum(
            bool(v.get("completion_claim")) and v.get("claim") == "contradicted"
            for v in values
        )
        durations = [e.result.durations.total_seconds for e in entries if e.result]
        spread = (
            f"{min(durations):.3f} / {statistics.median(durations):.3f} / "
            f"{max(durations):.3f}"
            if durations
            else "unknown"
        )
        lines.append(
            f"| {case} | {participant} | {policy} | {len(entries)} | "
            f"{sum(e.result is not None for e in entries)} | {known} | {completed} | "
            f"{assessable} | {contradicted} | {spread} |"
        )
        interval = wilson(completed, known)
        if interval is not None:
            intervals.append(
                f"- {case} / {participant} / {policy}: "
                f"{completed}/{known}, [{interval[0]:.3f}, {interval[1]:.3f}]."
            )
    lines.extend(
        [
            "",
            "Conditional 95% Wilson intervals for task completion below assume "
            "independent trials, an assumption NOT established by this compact pilot. "
            "They do not establish general accuracy or account for "
            "repeated fixture selection.",
            "",
            *intervals,
        ]
    )
    lines.extend(
        [
            "",
            "## Matched agent pairs",
            "",
            "Workflow companions are separate participants, "
            "excluded from the prompt/policy contrast.",
            "",
        ]
    )
    for case in sorted(
        {e.slot.case for e in study.entries if e.slot.participant == "agent"}
    ):
        paired = both = first = second = neither = excluded = 0
        policies = sorted(
            {
                e.slot.policy
                for e in study.entries
                if e.slot.case == case and e.slot.participant == "agent"
            }
        )
        for repetition in range(1, study.plan.repetitions + 1):
            entries = sorted(
                [
                    e
                    for e in study.entries
                    if e.slot.case == case
                    and e.slot.repetition == repetition
                    and e.slot.participant == "agent"
                ],
                key=lambda e: e.slot.policy,
            )
            values = [facts(e) for e in entries]
            if len(values) != 2 or any(
                v.get("task") not in ("completed", "not_completed")
                or v.get("execution")
                in ("provider_error", "error", "failed", "interrupted")
                for v in values
            ):
                excluded += 1
                continue
            a, b = (v["task"] == "completed" for v in values)
            paired += 1
            both += int(a and b)
            first += int(a and not b)
            second += int(b and not a)
            neither += int(not a and not b)
        lines.append(
            f"- {case}: {paired} known pairs; {excluded} excluded; "
            f"both complete {both}; only {policies[0]} {first}; "
            f"only {policies[1]} {second}; neither {neither}."
        )
    lines.extend(
        [
            "",
            "## Interpretation and complete inventory",
            "",
            "Repeated temperature-zero runs do not establish independent trials. "
            "Counts and variation are descriptive; this small fixture corpus does "
            "not establish general security accuracy. Missing usage and "
            "uninspectable storage remain null/unknown. Zero contradicted claims "
            "with zero assessable completion claims is not reliability evidence. "
            "Detection is not recovery. Cancellation cannot undo committed writes "
            "or guarantee cancellation of Ollama generation.",
            "",
            "Each entry retains execution, storage, report, claim, fault, usage "
            "and boundary evidence separately. Inspect the child artifacts for "
            "raw traces, requested settings and unchanged evaluator output.",
            "",
        ]
    )
    for entry in study.entries:
        lines.extend(
            [
                f"### {entry.slot.directory}",
                "",
                "```json",
                json.dumps(
                    {
                        "status": entry.status,
                        "error": entry.error,
                        "facts": facts(entry),
                        "durations": entry.result.durations.model_dump()
                        if entry.result
                        else None,
                        "accounting": entry.result.accounting if entry.result else None,
                        "interrupted_storage": entry.inspection.model_dump()
                        if entry.inspection
                        else None,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
                "",
            ]
        )
    return "\n".join(lines)
