"""Read-only M11 reports and journal diagnosis; no scanner, tools or inference."""

import html
import sqlite3
from pathlib import Path
from typing import Literal, Self

from pydantic import JsonValue, model_validator

from agent_fault_lab.boundary_records import BoundaryEvaluation, BoundaryJournal
from agent_fault_lab.context_cases import M12_CASES, M13_CASES
from agent_fault_lab.journal import Versioned, regular, strict_json


class BoundaryComparison(Versioned):
    artifact: Literal["boundary-comparison"] = "boundary-comparison"
    case: str
    planned: tuple[str, ...]
    entries: tuple[BoundaryEvaluation, ...]
    status: Literal["finished", "stopped"]
    error: str | None = None
    axes: tuple[str, ...] = ("permission_policy",)

    @model_validator(mode="after")
    def comparable(self) -> Self:
        expected = (
            ("scan_policy", "permission_policy")
            if self.case in M12_CASES
            else (
                ("context_policy",)
                if self.case in M13_CASES
                else ("permission_policy",)
            )
        )
        if self.axes != expected:
            raise ValueError("Comparison axes do not match the experiment")
        if len(set(self.planned)) != len(self.planned) or len(self.entries) > len(
            self.planned
        ):
            raise ValueError("Invalid comparison cell inventory")
        if self.status == "finished" and len(self.entries) != len(self.planned):
            raise ValueError("Finished comparison has missing cells")
        fixed = None
        for entry in self.entries:
            if entry.config.case != self.case:
                raise ValueError("Comparison mixes different experiments")
            configuration = entry.config.model_dump(exclude=set(self.axes))
            if fixed is not None and fixed != configuration:
                raise ValueError("Comparison changes an undeclared setting")
            fixed = configuration
        return self


def cell(value: object) -> str:
    return (
        html.escape(str(value))
        .replace("|", "\\|")
        .replace("`", "&#96;")
        .replace("\n", "<br>")
    )


def read_evaluation(directory: Path) -> BoundaryEvaluation:
    path = directory / "evaluation.json"
    regular(path)
    raw = path.read_text(encoding="utf-8")
    strict_json(raw)
    return BoundaryEvaluation.model_validate_json(raw)


def render_report(value: BoundaryEvaluation) -> str:
    auth = value.authorization
    agent = (
        "scripted test machinery, NOT an AI model"
        if value.config.mode == "offline"
        else "local Ollama"
    )
    source = (
        "operator CLI"
        if value.config.case == "manual"
        else "synthetic scenario controller, NOT human approval"
    )
    lines = [
        (
            f"# {value.context.milestone} — {cell(value.config.case)}"
            if value.context
            else "# M11 — Permissions and human approval"
        ),
        "",
        f"Run: {cell(value.run_id)}",
        "",
        f"Agent: {agent}. Approval source: {source}.",
        "",
        "| Result | Observation |",
        "|---|---|",
        f"| Run status | {cell(value.status)} |",
        f"| Scanner | {cell(value.scan.engine)}; {cell(value.scan.status)}; "
        f"{cell(value.scan.recommendation)} |",
        f"| Scanner input SHA-256 | {value.scan.input_sha256} |",
        f"| Scanner policy | {value.config.scan_policy} |",
        f"| Permission policy | {value.config.permission_policy} |",
        f"| Scenario exercised | {value.scenario_exercised} |",
        f"| Model requests | {value.model_calls} |",
        f"| Tool calls / executions | {value.tool_calls} / {value.tool_executions} |",
        f"| Write attempts / replay requests | "
        f"{value.write_attempts} / {value.replay_requests} |",
        f"| Task outcome | {value.task_outcome} |",
        f"| Authorization boundary | {auth.status} |",
        f"| Authorized writes | {auth.authorized_writes} |",
        f"| Unauthorized writes | {auth.unauthorized_writes} |",
        f"| Terminal report | {value.report.status} |",
        f"| Claim support | {value.claim_support} |",
        "",
        "Task outcome and authorization are independently checked through "
        "read-only SQL. An admitted skill does not grant write permission. "
        "Missing claims and paused runs "
        "are not evidence of reliable model completion.",
        "",
        "## Approval proposals",
        "",
        "| Operation | Exact title | Decision | Expiry (Unix seconds) | "
        "Consumed task |",
        "|---|---|---|---|---|",
    ]
    for proposal in auth.proposals:
        lines.append(
            "| "
            + " | ".join(
                cell(proposal.get(key))
                for key in (
                    "operation_id",
                    "title",
                    "decision",
                    "expires_at",
                    "consumed_task_id",
                )
            )
            + " |"
        )
    if value.status == "awaiting_approval":
        lines.extend(
            [
                "",
                "The agent is paused. Approve or reject the exact pending "
                "operation, then explicitly resume.",
            ]
        )
    for error in (value.error, value.scan.error, auth.error):
        if error:
            lines.extend(["", f"Recorded error: {cell(error)}"])
    if value.scan.findings:
        lines.extend(["", "## Static scanner findings", ""])
        for finding in value.scan.findings:
            lines.append(
                f"- {cell(finding.rule_id)} ({finding.severity}, "
                f"confidence {finding.confidence}): {cell(finding.finding)} "
                f"at {cell(finding.path)}:{finding.line}"
            )
    if value.context:
        lines.extend(
            [
                "",
                "## Context evidence",
                "",
                f"Surface: {value.config.surface}; "
                f"context policy: {value.config.context_policy}.",
                "",
                "| Measurement | Observation |",
                "|---|---|",
            ]
        )
        for key, observation in value.context.model_dump(mode="json").items():
            lines.append(f"| {cell(key)} | {cell(observation)} |")
        lines.extend(
            [
                "",
                "Delivery means content was attached to the durable agent "
                "conversation. It does not prove a model followed it. "
                "No live behavior is established by scripted runs.",
            ]
        )
    return "\n".join(lines) + "\n"


def render_comparison(value: BoundaryComparison) -> str:
    if value.axes != ("permission_policy",):
        return render_context_comparison(value)
    lines = [
        "# M11 permission comparison",
        "",
        f"Case: {cell(value.case)}; status: {value.status}.",
        "",
        "Both cells use the same skill, scanner settings, prompt, agent limits and "
        "approval scenario; only permission enforcement changes.",
        "",
        "| Policy | Run | Task | Authorization | Terminal | Claim |",
        "|---|---|---|---|---|---|",
    ]
    for entry in value.entries:
        lines.append(
            f"| {entry.config.permission_policy} | {cell(entry.status)} | "
            f"{entry.task_outcome} | {entry.authorization.status} | "
            f"{entry.report.status} | {entry.claim_support} |"
        )
    lines.extend(
        [
            "",
            f"Recorded {len(value.entries)} of {len(value.planned)} planned cells.",
            "",
            "Scanner/approval failures, absent claims and blocked runs "
            "must be retained. "
            "Scripted agents demonstrate machinery, not model behavior.",
        ]
    )
    if value.error:
        lines.extend(["", cell(value.error)])
    return "\n".join(lines) + "\n"


def render_context_comparison(value: BoundaryComparison) -> str:
    lines = [
        f"# Context comparison — {cell(value.case)}",
        "",
        f"Status: {value.status}; varied axes: {cell(', '.join(value.axes))}.",
        "",
        "Hold other settings fixed and compare one axis at a time. "
        "Every policy scans the same payload. Scripted results are machinery evidence.",
        "",
        "| Scan / Permission / Context | Delivered | Unsafe attempts | "
        "Violations | Legitimate task | Terminal | Claim |",
        "|---|---|---|---|---|---|---|",
    ]
    for entry in value.entries:
        context = entry.context
        assert context
        lines.append(
            f"| {entry.config.scan_policy} / {entry.config.permission_policy} / "
            f"{entry.config.context_policy} | {context.delivered} | "
            f"{context.unsafe_attempts} | "
            f"{context.boundary_violations} | {context.legitimate_completed} | "
            f"{entry.report.status} | {entry.claim_support} |"
        )
    lines.extend(
        [
            "",
            "| Scan / Permission / Context | Detection | False alarm | "
            "Scanner error | Seeds preserved | Work blocked | Refresh / model reads |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for entry in value.entries:
        context = entry.context
        assert context
        lines.append(
            f"| {entry.config.scan_policy} / {entry.config.permission_policy} / "
            f"{entry.config.context_policy} | {context.scanner_detected} | "
            f"{context.false_alarm} | {context.scanner_error} | "
            f"{context.seeded_preserved} | {context.legitimate_blocked} | "
            f"{context.authoritative_refreshes} / {context.model_state_reads} |"
        )
    lines.extend(
        [
            "",
            f"Recorded {len(value.entries)} of {len(value.planned)} planned cells.",
            "Absent/invalid claims, unexercised content and errors "
            "remain in the evidence. "
            "None means unknown or not applicable; it is never scored as success.",
        ]
    )
    if value.error:
        lines.extend(["", cell(value.error)])
    return "\n".join(lines) + "\n"


def diagnose(directory: Path) -> tuple[dict[str, JsonValue], str]:
    gaps: list[str] = []
    timeline: list[JsonValue] = []
    status: str
    try:
        state = BoundaryJournal.read_state(directory / "boundary.sqlite3")
        for event in BoundaryJournal.events(directory / "boundary.sqlite3"):
            timeline.append(
                {
                    **event.model_dump(mode="json"),
                    "evidence": f"boundary.sqlite3:events:{event.sequence}",
                }
            )
        status = state.status
    except (ValueError, OSError, sqlite3.Error) as exc:
        status = "unknown"
        gaps.append(str(exc))
    try:
        evaluation = read_evaluation(directory)
        report: JsonValue = evaluation.model_dump(mode="json")
    except (ValueError, OSError) as exc:
        report = None
        gaps.append(str(exc))
    result: dict[str, JsonValue] = {
        "artifact": "boundary-diagnosis",
        "schema_version": 1,
        "status": status,
        "timeline": timeline,
        "saved_evaluation": report,
        "gaps": [str(gap) for gap in gaps],
    }
    lines = [
        "# Boundary diagnostic timeline",
        "",
        "Read-only saved evidence; no new grading, scanning or inference.",
        "",
    ]
    for entry in timeline:
        assert isinstance(entry, dict)
        lines.append(
            f"- {entry['sequence']}: {cell(entry['kind'])} — {cell(entry['data'])} "
            f"({cell(entry['evidence'])})"
        )
    if gaps:
        lines.extend(["", "Evidence gaps: " + cell("; ".join(gaps))])
    return result, "\n".join(lines) + "\n"
