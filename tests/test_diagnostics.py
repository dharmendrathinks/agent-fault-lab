"""M10 saved evidence explains effects without executing or regrading tools."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pytest
from recovery_helpers import await_unowned, crash, paused_run

from agent_fault_lab.cli import TITLE, _execute, main
from agent_fault_lab.diagnostics import diagnose, render_diagnosis
from agent_fault_lab.durable_run import resume_process, run_process
from agent_fault_lab.execution_types import ExecutionLimits, ProcessCase, ProcessConfig
from agent_fault_lab.journal import Journal
from agent_fault_lab.reliability import ReliabilityConfig, scripted_response_client
from agent_fault_lab.retries import RetryConfig, RetryPolicy


@pytest.mark.parametrize(
    "policy,rows,support",
    [("retry-unprotected", 2, "contradicted"), ("retry-idempotent", 1, "supported")],
)
def test_duplicate_and_protected_replay_bundles(
    tmp_path: Path, policy: RetryPolicy, rows: int, support: str
) -> None:
    output = tmp_path / "run"
    _execute(
        scripted_response_client(TITLE),
        output,
        {},
        reliability=RetryConfig(case="lost-reply-once", policy=policy),
    )
    original = {p.name: p.read_bytes() for p in output.iterdir() if p.is_file()}
    with (
        patch("socket.socket", side_effect=AssertionError("network")),
        patch(
            "agent_fault_lab.evaluation.inspect_state",
            side_effect=AssertionError("fresh grade"),
        ),
        patch("agent_fault_lab.tasks.TaskStore", side_effect=AssertionError("tools")),
    ):
        diagnosis = diagnose(output)
    conclusion = diagnosis["conclusion"]
    assert isinstance(conclusion, dict)
    assert (
        isinstance(conclusion["stored_rows"], list)
        and len(conclusion["stored_rows"]) == rows
    )
    assert conclusion["claim_support"] == support
    assert len(diagnosis["observed_fault_activations"]) == 1  # type: ignore[arg-type]
    assert original == {p.name: p.read_bytes() for p in output.iterdir() if p.is_file()}
    markdown = render_diagnosis(diagnosis)
    assert "retry_scheduled" in markdown and "trace.jsonl:" in markdown
    assert "write_committed" in markdown
    assert diagnosis["gaps"] == []


def test_malformed_reply_after_write_diagnosis(tmp_path: Path) -> None:
    output = tmp_path / "run"
    _execute(
        scripted_response_client(TITLE),
        output,
        {},
        reliability=ReliabilityConfig(case="malformed-json", policy="validated"),
    )
    diagnosis = diagnose(output)
    conclusion = diagnosis["conclusion"]
    assert isinstance(conclusion, dict) and conclusion["task_outcome"] == "completed"
    assert conclusion["claim_support"] == "not_asserted"
    markdown = render_diagnosis(diagnosis)
    assert "contract_checked" in markdown and "syntax" in markdown
    # Golden event order and exact evidence references for this fixed script.
    timeline = diagnosis["timeline"]
    assert isinstance(timeline, list)
    selected = [
        (r["kind"], r["evidence"])
        for r in timeline
        if isinstance(r, dict)
        and r["kind"]
        in {
            "response_captured",
            "response_fault_injected",
            "contract_checked",
            "evaluation_completed",
        }
    ]
    assert selected == [
        ("response_fault_injected", "trace.jsonl:6"),
        ("response_captured", "trace.jsonl:7"),
        ("contract_checked", "trace.jsonl:8"),
        ("evaluation_completed", "trace.jsonl:14"),
    ]


@pytest.mark.parametrize(
    "case,expected",
    [("delay-before-write", "not_completed"), ("delay-after-commit", "completed")],
)
def test_cancellation_bundles(tmp_path: Path, case: ProcessCase, expected: str) -> None:
    output = tmp_path / "run"
    run_process(
        output,
        ProcessConfig(case=case, policy="terminate"),
        mode="offline",
        execution_limits=ExecutionLimits(attempt_seconds=1.0, delay_seconds=1.5),
    )
    diagnosis = diagnose(output)
    conclusion = diagnosis["conclusion"]
    assert isinstance(conclusion, dict) and conclusion["task_outcome"] == expected
    rendered = render_diagnosis(diagnosis)
    assert "deadline_expired" in rendered and "worker_exit_confirmed" in rendered
    assert "cancellation_requested" in rendered
    assert "journal.sqlite3#events/" in rendered
    assert diagnosis["gaps"] == []


def test_crash_recovery_and_projection_gap(tmp_path: Path) -> None:
    output = tmp_path / "run"
    parent, worker = paused_run(output, "after-commit")
    crash(parent, worker)
    await_unowned(output)
    partial = diagnose(output)
    assert "Pending operation" in str(partial["gaps"])
    resume_process(output, mode="offline")
    diagnosis = diagnose(output)
    assert "interrupted_reservation_charged" in render_diagnosis(diagnosis)
    assert "replayed" in render_diagnosis(diagnosis)
    assert diagnosis["gaps"] == []
    with (output / "trace.jsonl").open("a") as stream:
        stream.write('{"partial":')
    diagnosis = diagnose(output)
    assert "Partial or invalid JSONL" in str(diagnosis["gaps"])
    # Partial projection does not erase an intact independent evaluation.
    conclusion = diagnosis["conclusion"]
    assert isinstance(conclusion, dict) and conclusion["task_outcome"] == "completed"


def test_missing_bundle_has_explicit_unknown_conclusion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    diagnosis = diagnose(tmp_path)
    assert diagnosis["timeline"] == []
    assert diagnosis["conclusion"] == {
        "task_outcome": "unknown",
        "task_reason": "No consistent independent evaluation is available",
        "stored_rows": None,
        "execution": None,
        "terminal_report": None,
        "claim_support": "unknown",
        "evaluation_evidence": None,
        "causal_history": "incomplete or uncertain",
    }
    assert diagnosis["gaps"] == [
        "Manifest unavailable: Expected an existing regular file: manifest.json",
        "Trace unavailable: Expected an existing regular file: trace.jsonl",
        "Saved evaluation missing or inconsistent: "
        "Expected an existing regular file: evaluation.json",
    ]
    assert main(["diagnose", str(tmp_path), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == diagnosis
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("corruption", ["version", "timing", "evaluation"])
def test_inconsistent_evidence_is_reported(tmp_path: Path, corruption: str) -> None:
    output = tmp_path / "run"
    run_process(
        output,
        ProcessConfig(case="process-healthy", policy="bounded-retry"),
        mode="offline",
    )
    if corruption == "evaluation":
        data = json.loads((output / "evaluation.json").read_text())
        data["task_outcome"] = "not_completed"
        (output / "evaluation.json").write_text(json.dumps(data))
    else:
        with closing(
            sqlite3.connect(output / "journal.sqlite3", autocommit=False)
        ) as conn:
            with conn:
                event = json.loads(
                    conn.execute(
                        "SELECT event FROM events WHERE sequence=2"
                    ).fetchone()[0]
                )
                if corruption == "version":
                    event["schema_version"] = 99
                else:
                    event["wall_time"] = "2000-01-01T00:00:00+00:00"
                conn.execute(
                    "UPDATE events SET event=? WHERE sequence=2", (json.dumps(event),)
                )
    diagnosis = diagnose(output)
    assert diagnosis["gaps"]
    conclusion = diagnosis["conclusion"]
    assert isinstance(conclusion, dict)
    if corruption in {"version", "evaluation"}:
        assert conclusion["task_outcome"] == "unknown"
    else:
        assert "Wall-clock ordering conflicts" in str(diagnosis["gaps"])
        assert Journal.read_events(output / "journal.sqlite3")[1].sequence == 2
