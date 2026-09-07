"""M10 read-only diagnosis from evidence, never execution or fresh grading."""

import base64
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from pydantic import JsonValue

from agent_fault_lab.evaluation import Evaluation
from agent_fault_lab.journal import (
    Journal,
    JournalEvent,
    RunState,
    regular,
    strict_json,
)
from agent_fault_lab.reporting import json_block
from agent_fault_lab.saved_reports import render_saved_report
from agent_fault_lab.trace import Event


def _text(value: JsonValue) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def describe(kind: str, data: dict[str, JsonValue]) -> str:
    if kind == "worker_evidence" and isinstance(event := data.get("event"), dict):
        return (
            f"worker {event.get('kind')}: {_text(event.get('data'))} "
            f"[{data.get('evidence')}:{event.get('sequence')}]"
        )
    if kind == "model_returned" and isinstance(turn := data.get("turn"), dict):
        return "assistant: " + _text(
            {
                "content": turn.get("content"),
                "tool_calls": turn.get("tool_calls"),
                "finish_reason": turn.get("finish_reason"),
            }
        )
    if kind == "response_captured" and isinstance(raw := data.get("raw_base64"), str):
        try:
            return "raw reply: " + base64.b64decode(raw, validate=True).decode("utf-8")
        except (ValueError, UnicodeError):
            return "raw reply is not valid base64/UTF-8; inspect referenced bytes"
    return _text(data)


def diagnose(directory: Path) -> dict[str, JsonValue]:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Expected a regular run directory")
    directory = directory.resolve()
    gaps: list[str] = []
    timeline: list[dict[str, JsonValue]] = []
    state: RunState | None = None
    records: tuple[JournalEvent, ...] = ()
    evaluation: Evaluation | None = None
    config: JsonValue = None
    crash_barrier: JsonValue = None
    crash_controller: JsonValue = None
    request: JsonValue = None
    evidence_valid = True
    journal_path = directory / "journal.sqlite3"
    trace = directory / "trace.jsonl"

    def read(name: str) -> JsonValue:
        path = directory / name
        regular(path)
        return strict_json(path.read_text(encoding="utf-8"))

    try:
        manifest = read("manifest.json")
        if isinstance(manifest, dict):
            crash_barrier = manifest.get("crash_barrier")
            initial = manifest.get("initial_state")
            if isinstance(initial, dict):
                config, request = initial.get("config"), initial.get("request")
            else:
                config, request = manifest.get("experiment"), manifest.get("request")
            if type(manifest.get("schema_version")) is not int or manifest[
                "schema_version"
            ] not in range(1, 7):
                gaps.append("Unsupported manifest schema; configuration is untrusted")
                config = request = None
        else:
            gaps.append("Manifest is not an object")
    except (OSError, ValueError) as exc:
        gaps.append(f"Manifest unavailable: {exc}")
    if (directory / "controller.json").exists():
        try:
            controller = read("controller.json")
            if (
                not isinstance(controller, dict)
                or controller.get("artifact") != "crash-controller"
                or type(controller.get("schema_version")) is not int
                or controller["schema_version"] != 1
            ):
                raise ValueError("Unsupported crash-controller evidence")
            crash_controller = controller
        except (OSError, ValueError) as exc:
            gaps.append(f"Crash-controller evidence unavailable: {exc}")
    if journal_path.exists() or journal_path.is_symlink():
        try:
            state = Journal.read_state(journal_path)
            records = Journal.read_events(journal_path)
            if any(e.run_id != state.run_id for e in records):
                raise ValueError("Run identities disagree")
            config, request = state.config.model_dump(mode="json"), state.request
            last_elapsed: dict[str, float] = {}
            last_wall: datetime | None = None
            for event in records:
                wall = datetime.fromisoformat(event.wall_time)
                if wall.tzinfo is None:
                    gaps.append(f"Event {event.sequence} has no wall-clock timezone")
                elif last_wall is not None and wall < last_wall:
                    gaps.append(
                        f"Wall-clock ordering conflicts at event {event.sequence}; "
                        "journal sequence takes precedence"
                    )
                if event.elapsed_seconds < last_elapsed.get(event.session_id, 0):
                    gaps.append(f"Session timing decreases at event {event.sequence}")
                last_elapsed[event.session_id] = event.elapsed_seconds
                if wall.tzinfo is not None:
                    last_wall = wall
                timeline.append(
                    {
                        "sequence": event.sequence,
                        "run_id": event.run_id,
                        "session_id": event.session_id,
                        "elapsed_seconds": event.elapsed_seconds,
                        "kind": event.kind,
                        "call_id": event.call_id,
                        "operation_id": event.operation_id,
                        "attempt_id": event.attempt_id,
                        "detail": describe(event.kind, event.data),
                        "evidence": f"journal.sqlite3#events/{event.sequence}",
                    }
                )
            projection: list[JournalEvent] = []
            try:
                regular(trace)
                for index, line in enumerate(
                    trace.read_text(encoding="utf-8").splitlines(), 1
                ):
                    try:
                        strict_json(line)
                        projection.append(JournalEvent.model_validate_json(line))
                    except ValueError:
                        gaps.append(
                            "Partial or invalid JSONL projection at "
                            f"trace.jsonl:{index}"
                        )
                if tuple(projection) != records:
                    gaps.append(
                        "JSONL projection differs from committed journal events; "
                        "journal ordering is authoritative"
                    )
            except (OSError, ValueError) as exc:
                gaps.append(f"JSONL projection unavailable: {exc}")
            if state.execution.active and state.execution.active.result is None:
                gaps.append(
                    "Pending operation has no durable reply; committed task effect "
                    "cannot be inferred from this checkpoint"
                )
            imported = {
                e.data.get("evidence") for e in records if e.kind == "worker_evidence"
            }
            for path in sorted(directory.glob("worker-*.jsonl")):
                if path.name not in imported:
                    gaps.append(
                        f"Unimported worker evidence: {path.name}; "
                        "runner may have crashed before collection"
                    )
        except (OSError, ValueError, sqlite3.Error) as exc:
            gaps.append(f"Journal unavailable or incompatible: {exc}")
            state, records = None, ()
            evidence_valid = False
    else:
        try:
            regular(trace)
            last_elapsed = {"legacy": 0.0}
            for index, line in enumerate(
                trace.read_text(encoding="utf-8").splitlines(), 1
            ):
                try:
                    strict_json(line)
                    legacy = Event.model_validate_json(line)
                    if legacy.sequence != index:
                        gaps.append(f"Legacy sequence gap at trace.jsonl:{index}")
                    if legacy.elapsed_seconds < last_elapsed["legacy"]:
                        gaps.append(f"Legacy timing decreases at trace.jsonl:{index}")
                    last_elapsed["legacy"] = legacy.elapsed_seconds
                    timeline.append(
                        {
                            "sequence": legacy.sequence,
                            "run_id": None,
                            "session_id": "legacy",
                            "elapsed_seconds": legacy.elapsed_seconds,
                            "kind": legacy.kind,
                            "call_id": legacy.data.get("call_id"),
                            "operation_id": legacy.data.get("operation_id"),
                            "attempt_id": legacy.data.get("attempt_id"),
                            "detail": describe(legacy.kind, legacy.data),
                            "evidence": f"trace.jsonl:{index}",
                        }
                    )
                except ValueError:
                    gaps.append(
                        f"Partial or invalid legacy trace at trace.jsonl:{index}"
                    )
        except (OSError, ValueError) as exc:
            gaps.append(f"Trace unavailable: {exc}")
    evaluation_reference: JsonValue = None
    try:
        raw = read("evaluation.json")
        evaluation = Evaluation.model_validate_json(json.dumps(raw))
        render_saved_report(directory)  # Cross-check optional observation; no SQL.
        if state is not None and state.evaluation != evaluation:
            raise ValueError("Saved evaluation disagrees with journal checkpoint")
        evaluation_reference = "evaluation.json"
    except (OSError, ValueError) as exc:
        gaps.append(f"Saved evaluation missing or inconsistent: {exc}")
        evaluation = None
        if (
            not (directory / "evaluation.json").exists()
            and state is not None
            and state.evaluation is not None
        ):
            evaluation = state.evaluation
            evaluation_reference = "journal.sqlite3#checkpoint/evaluation"
        else:
            evidence_valid = False
    if not evidence_valid:
        evaluation = None
    checkpoint: JsonValue = None
    if state is not None:
        checkpoint = {
            "phase": state.phase,
            "finalized": state.finalized,
            "model_calls": state.model_calls,
            "tool_calls": state.tool_calls,
            "pending_tools": len(state.pending),
            "tool_cursor": state.tool_cursor,
            "script_cursor": state.script_cursor,
            "execution": state.execution.model_dump(mode="json"),
            "resume_action": "none; already finalized"
            if state.finalized
            else "finalize saved terminal result"
            if state.terminal
            else "continue saved conversation; reconcile pending operation "
            "with its retained ID",
            "evidence": "journal.sqlite3#checkpoint",
        }
    activation_kinds = {
        "response_fault_injected",
        "retry_fault_injected",
        "fault_injected",
    }
    activations = [
        row["evidence"]
        for row in timeline
        if row["kind"] in activation_kinds
        or (
            row["kind"] == "worker_evidence"
            and str(row["detail"]).startswith("worker fault_activated:")
        )
    ]
    return {
        "schema_version": 1,
        "artifact": "diagnosis",
        "request": request,
        "configured_experiment": config,
        "configured_crash_barrier": crash_barrier,
        "crash_controller": crash_controller,
        "observed_fault_activations": activations,
        "checkpoint": checkpoint,
        "conclusion": {
            "task_outcome": evaluation.task_outcome if evaluation else "unknown",
            "task_reason": evaluation.task_reason
            if evaluation
            else "No consistent independent evaluation is available",
            "stored_rows": [r.model_dump(mode="json") for r in evaluation.state.rows]
            if evaluation and evaluation.state.rows is not None
            else None,
            "execution": evaluation.execution.model_dump(mode="json")
            if evaluation
            else None,
            "terminal_report": evaluation.report.model_dump(mode="json")
            if evaluation
            else None,
            "claim_support": evaluation.claim_support if evaluation else "unknown",
            "evaluation_evidence": evaluation_reference if evaluation else None,
            "causal_history": "incomplete or uncertain"
            if gaps
            else "recorded events available; no missing history inferred",
        },
        "timeline": [row for row in timeline],
        "gaps": [gap for gap in gaps],
        "limitations": (
            "Read-only saved evidence; no model calls, tool execution or fresh "
            "task grading. Worker timing is local to its process. Parent collection "
            "order does not establish cross-process commit/cancellation ordering. "
            "Unknown downtime is not inferred from checkpoint gaps. "
            "Evidence is not authenticated."
        ),
    }


def render_diagnosis(diagnosis: dict[str, JsonValue]) -> str:
    lines = [
        "# Failure diagnosis\n",
        json_block(
            {
                key: diagnosis[key]
                for key in (
                    "request",
                    "configured_experiment",
                    "configured_crash_barrier",
                    "crash_controller",
                    "observed_fault_activations",
                    "conclusion",
                    "checkpoint",
                )
            }
        ),
        "## Timeline\n",
    ]
    timeline = diagnosis["timeline"]
    assert isinstance(timeline, list)
    for row in timeline:
        assert isinstance(row, dict)
        detail = str(row["detail"])
        preview = (
            detail
            if len(detail) <= 500
            else detail[:500] + "… [see evidence for full data]"
        )
        lines.append(
            f"- **{row['sequence']} · {row['kind']}** "
            f"(session `{row['session_id']}`, operation `{row['operation_id']}`, "
            f"attempt `{row['attempt_id']}`) — `{row['evidence']}`\n\n    {preview}\n"
        )
    lines.extend(
        [
            "## Evidence gaps\n",
            json_block(diagnosis["gaps"]),
            str(diagnosis["limitations"]) + "\n",
        ]
    )
    return "\n".join(lines)
