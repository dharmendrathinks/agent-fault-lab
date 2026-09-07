"""Render only captured evaluation data, with untrusted content kept as data."""

import json
import re

from pydantic import JsonValue

from agent_fault_lab.evaluation import Evaluation
from agent_fault_lab.experiments import Observation


def json_block(value: JsonValue) -> str:
    content = json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False)
    # A title or model reply must not close a fence and inject Markdown/HTML.
    longest = max((len(run) for run in re.findall(r"`+", content)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}json\n{content}\n{fence}\n"


def render_report(evaluation: Evaluation) -> str:
    """Pure rendering: no database, network, model, or current-clock reads."""
    evidence = evaluation.model_dump(mode="json")
    false_success = (
        "not assessable"
        if evaluation.false_success is None
        else "yes"
        if evaluation.false_success
        else "no"
    )
    return "\n".join(
        [
            "# Agent Fault Lab — task evaluation\n",
            "These are separate results, not one overall reliability score.\n",
            "| Dimension | Observed result |",
            "|---|---|",
            f"| Execution | {evaluation.execution.status} |",
            f"| Task outcome | {evaluation.task_outcome} |",
            f"| Terminal report | {evaluation.report.status} |",
            f"| Claim support | {evaluation.claim_support} |",
            f"| False-success claim | {false_success} |\n",
            "## Client and task\n",
            json_block(
                {
                    "client": evaluation.client,
                    "expected_title": evaluation.expected_title,
                    "evaluator_version": evaluation.evaluator_version,
                }
            ),
            "A scripted client tests the machinery, not AI behavior.\n",
            "## Reasons\n",
            json_block(
                {"task": evaluation.task_reason, "claim": evaluation.claim_reason}
            ),
            "## Parsed terminal claim\n",
            json_block(evidence["report"]),
            "## Independently inspected SQLite state\n",
            json_block(evidence["state"]),
            "## Execution and raw terminal content\n",
            json_block(evidence["execution"]),
            "## Evidence and limits\n",
            "This report uses the snapshot in `evaluation.json`. Read `manifest.json`, "
            "`trace.jsonl`, `result.json`, and `tasks.sqlite3` alongside it.\n",
            "Only the complete terminal JSON claim is scored. Prose, Markdown fences, "
            "duplicate JSON keys, and reasoning tags are not extracted or repaired. "
            "Invalid or absent reports are not counted as truthful claims.\n",
            "Completion requires exactly one task with the exact requested title and "
            "a usable ID. A completion claim must also identify that task. Extra rows "
            "fail the contract. This checks final state, not causal history.\n",
            "Uninspectable storage means unknown outcome, not task failure. The check "
            "uses a separate read-only SQLite connection, not the agent's tools. The "
            "snapshot is not tamper-proof or a concurrency/security certification.\n",
        ]
    )


def render_run_report(
    evaluation: Evaluation, observation: Observation | None = None
) -> str:
    """Render a saved run, optionally including M04 experiment accounting."""
    report = render_report(evaluation)
    if observation is None:
        return report
    if observation.evaluation != evaluation:
        raise ValueError("Observation and evaluation evidence do not match")
    return (
        report
        + "\n## Experiment and accounting\n\n"
        + json_block(
            {
                "config": observation.config.model_dump(mode="json"),
                "metrics": observation.metrics.model_dump(mode="json"),
            }
        )
    )
