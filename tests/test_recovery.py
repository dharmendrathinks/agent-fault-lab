"""M09 restart regression at every declared external-action boundary."""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from recovery_helpers import await_unowned, crash, paused_run, wait_barrier

from agent_fault_lab.agent import Limits
from agent_fault_lab.cli import main
from agent_fault_lab.durable_run import resume_process, run_process
from agent_fault_lab.evaluation import inspect_state
from agent_fault_lab.execution_types import PAUSE_POINTS, PausePoint, ProcessConfig
from agent_fault_lab.journal import Journal, JournalRecorder
from agent_fault_lab.model import DEFAULT_MODEL
from agent_fault_lab.ollama_adapter import DoctorResult
from agent_fault_lab.saved_reports import render_saved_report, report_matches

CONFIG = ProcessConfig(case="restart-healthy", policy="bounded-retry")


@pytest.mark.parametrize("point", PAUSE_POINTS)
def test_crash_and_resume_matches_uninterrupted_effect(
    tmp_path: Path, point: PausePoint
) -> None:
    baseline = run_process(tmp_path / "baseline", CONFIG, mode="offline")
    output = tmp_path / "crashed"
    process, worker = paused_run(output, point)
    before = Journal.read_state(output / "journal.sqlite3")
    crash(process, worker)
    await_unowned(output)
    result = resume_process(output, mode="offline")
    after = Journal.read_state(output / "journal.sqlite3")
    assert (
        baseline.evaluation.task_outcome
        == result.evaluation.task_outcome
        == "completed"
    )
    assert result.evaluation.claim_support == "supported"
    assert (
        result.evaluation.state.rows is not None
        and len(result.evaluation.state.rows) == 1
    )
    assert after.model_calls == 3 and after.tool_calls == 2
    assert after.script_cursor == 3
    if before.execution.active:
        original_id = before.execution.active.operation_id
        events = Journal.read_events(output / "journal.sqlite3")
        creates = [
            e.operation_id
            for e in events
            if e.kind == "attempt_started"
            and e.call_id == before.execution.active.call_id
        ]
        assert creates and set(creates) == {original_id}
    if point in {"attempt-checkpoint", "transaction", "after-commit"}:
        assert result.process.attempts == 3
        assert result.process.interrupted_reservations == 1
    else:
        assert result.process.attempts == 2
    if point == "after-commit":
        assert result.process.replay_receipts == 1
    if point == "transaction":
        assert result.process.replay_receipts == 0
    assert report_matches(output, render_saved_report(output)[1])
    saved = {p.name: p.read_bytes() for p in output.iterdir() if p.is_file()}
    with patch(
        "agent_fault_lab.durable_run._drive", side_effect=AssertionError("no execution")
    ):
        assert resume_process(output, mode="offline") == result
    assert saved == {p.name: p.read_bytes() for p in output.iterdir() if p.is_file()}


def test_orphan_worker_holds_run_lock(tmp_path: Path) -> None:
    output = tmp_path / "run"
    parent, worker = paused_run(output, "after-commit")
    assert worker != parent.pid
    parent.kill()
    parent.communicate()
    try:
        with pytest.raises(ValueError, match="still owned"):
            resume_process(output, mode="offline")
        assert len(inspect_state(output / "tasks.sqlite3").rows or ()) == 1
    finally:
        os.kill(worker, signal.SIGKILL)
    await_unowned(output)
    assert resume_process(output, mode="offline").process.replay_receipts == 1


def test_model_reservation_survives_uncheckpointed_response(tmp_path: Path) -> None:
    output = tmp_path / "run"
    original = JournalRecorder.transition

    def lose_response(
        self: JournalRecorder, state: object, kind: str, **data: object
    ) -> None:
        if kind == "model_returned":
            raise RuntimeError("response lost before checkpoint")
        original(self, state, kind, **data)  # type: ignore[arg-type]

    with patch.object(JournalRecorder, "transition", lose_response):
        with pytest.raises(RuntimeError, match="response lost"):
            run_process(output, CONFIG, mode="offline")
    state = Journal.read_state(output / "journal.sqlite3")
    assert state.model_calls == 1 and state.script_cursor == 0
    result = resume_process(output, mode="offline")
    assert result.metrics.model_calls == 4
    assert result.evaluation.claim_support == "supported"


def test_saved_terminal_response_is_not_requested_again(tmp_path: Path) -> None:
    output = tmp_path / "run"
    checkpoints = 0

    def interrupt(directory: Path, selected: object, point: str) -> None:
        nonlocal checkpoints
        if point == "assistant-checkpoint":
            checkpoints += 1
            if checkpoints == 3:
                raise KeyboardInterrupt

    with patch("agent_fault_lab.durable_run.pause", side_effect=interrupt):
        with pytest.raises(KeyboardInterrupt):
            run_process(output, CONFIG, mode="offline")
    result = resume_process(output, mode="offline")
    assert (
        result.metrics.model_calls == 3
        and result.evaluation.claim_support == "supported"
    )


def test_pending_tool_order_and_fault_cursor_survive(tmp_path: Path) -> None:
    output = tmp_path / "run"
    stopped = False

    def interrupt(directory: Path, selected: object, point: str) -> None:
        nonlocal stopped
        if point == "tool-checkpoint" and not stopped:
            stopped = True
            raise KeyboardInterrupt

    config = ProcessConfig(case="transient-once", policy="bounded-retry")
    with patch("agent_fault_lab.durable_run.pause", side_effect=interrupt):
        with pytest.raises(KeyboardInterrupt):
            run_process(output, config, mode="offline", script="batch-two-v1")
    before = Journal.read_state(output / "journal.sqlite3")
    assert before.tool_cursor == 1 and len(before.pending) == 2
    assert before.execution.fault_cursor == 2
    result = resume_process(output, mode="offline")
    assert result.metrics.tool_calls == 2 and result.process.attempts == 3
    assert result.process.fault_activations == 1
    assert len(result.evaluation.state.rows or ()) == 2
    tools = [
        m.call_id
        for m in Journal.read_state(output / "journal.sqlite3").messages
        if m.role == "tool"
    ]
    assert tools == ["m1-t1", "m1-t2"]


def test_report_finalization_failure_does_not_rerun_agent(tmp_path: Path) -> None:
    output = tmp_path / "run"
    with patch(
        "agent_fault_lab.saved_reports.replace_report", side_effect=OSError("disk")
    ):
        with pytest.raises(OSError):
            run_process(output, CONFIG, mode="offline")
    before = Journal.read_state(output / "journal.sqlite3")
    assert before.terminal is not None and not before.finalized
    with patch(
        "agent_fault_lab.durable_run.scripted_turn",
        side_effect=AssertionError("no model"),
    ):
        result = resume_process(output, mode="offline")
    assert result.metrics.model_calls == before.model_calls
    assert result.process.attempts == before.execution.total_attempts


def test_partial_jsonl_is_not_authoritative(tmp_path: Path) -> None:
    output = tmp_path / "run"
    parent, worker = paused_run(output, "assistant-checkpoint")
    crash(parent, worker)
    with (output / "trace.jsonl").open("a") as stream:
        stream.write('{"truncated":')
    result = resume_process(output, mode="offline")
    assert result.evaluation.claim_support == "supported"
    assert '{"truncated":' in (output / "trace.jsonl").read_text()


def test_legacy_and_wrong_mode_resume_do_not_modify_state(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "manifest.json").write_text('{"schema_version":3}')
    assert main(["resume", str(legacy), "--offline"]) == 2
    assert [p.name for p in legacy.iterdir()] == ["manifest.json"]
    output = tmp_path / "run"
    run_process(output, CONFIG, mode="offline")
    before = (output / "journal.sqlite3").read_bytes()
    assert main(["resume", str(output), "--live"]) == 2
    assert (output / "journal.sqlite3").read_bytes() == before


def test_concurrent_resume_admits_one_owner(tmp_path: Path) -> None:
    output = tmp_path / "run"
    with patch("agent_fault_lab.durable_run._drive", side_effect=RuntimeError("stop")):
        with pytest.raises(RuntimeError):
            run_process(output, CONFIG, mode="offline")
    barrier = output / "competition"
    barrier.mkdir()
    script = """
import sys
from pathlib import Path
from agent_fault_lab import durable_run
from agent_fault_lab.barriers import pause
original = durable_run.scripted_turn
def blocked(state):
    directory = Path(sys.argv[1]) / 'competition'
    pause(directory, 'assistant-checkpoint', 'assistant-checkpoint')
    return original(state)
durable_run.scripted_turn = blocked
durable_run.resume_process(Path(sys.argv[1]), mode='offline')
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(output)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_barrier(barrier, process)
        with pytest.raises(ValueError, match="still owned"):
            resume_process(output, mode="offline")
        (barrier / "barrier-release").touch()
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stdout + stderr
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


@pytest.mark.parametrize("corruption", ["schema", "budget", "fingerprint", "broken-db"])
def test_corrupt_checkpoint_fails_before_execution(
    tmp_path: Path, corruption: str
) -> None:
    import sqlite3
    from contextlib import closing

    output = tmp_path / "run"
    with patch("agent_fault_lab.durable_run._drive", side_effect=RuntimeError("stop")):
        with pytest.raises(RuntimeError):
            run_process(output, CONFIG, mode="offline")
    database = output / "journal.sqlite3"
    if corruption == "broken-db":
        database.write_bytes(b"broken")
    else:
        with closing(sqlite3.connect(database, autocommit=False)) as connection:
            with connection:
                state = json.loads(
                    connection.execute("SELECT state FROM checkpoint").fetchone()[0]
                )
                if corruption == "schema":
                    state["schema_version"] = True
                elif corruption == "budget":
                    state["execution"]["total_attempts"] = 19
                else:
                    state["compatibility"] = "different"
                connection.execute(
                    "UPDATE checkpoint SET state=?", (json.dumps(state),)
                )
    with patch(
        "agent_fault_lab.durable_run._drive", side_effect=AssertionError("forbidden")
    ):
        with pytest.raises((ValueError, sqlite3.DatabaseError)):
            resume_process(output, mode="offline")


def test_model_budget_is_not_reset_after_crash(tmp_path: Path) -> None:
    output = tmp_path / "run"
    with patch(
        "agent_fault_lab.durable_run.scripted_turn", side_effect=RuntimeError("lost")
    ):
        with pytest.raises(RuntimeError):
            run_process(
                output, CONFIG, mode="offline", limits=Limits(max_model_calls=1)
            )
    with patch(
        "agent_fault_lab.durable_run.scripted_turn",
        side_effect=AssertionError("budget exhausted"),
    ):
        result = resume_process(output, mode="offline")
    assert result.evaluation.execution.status == "model_limit"
    assert result.metrics.model_calls == 1 and result.process.attempts == 0
    assert result.evaluation.false_success is None


def test_live_resume_refuses_changed_digest_without_inference(tmp_path: Path) -> None:
    output = tmp_path / "run"
    original = DoctorResult(model=DEFAULT_MODEL, model_digest="original-digest")
    with patch("agent_fault_lab.durable_run.OllamaClient") as factory:
        factory.return_value.label = "ollama-local"
        factory.return_value.inspect.return_value = original
        with patch(
            "agent_fault_lab.durable_run._drive", side_effect=RuntimeError("stop")
        ):
            with pytest.raises(RuntimeError):
                run_process(output, CONFIG, mode="live")
        factory.return_value.inspect.return_value = original.model_copy(
            update={"model_digest": "replacement-digest"}
        )
        before = (output / "journal.sqlite3").read_bytes()
        with pytest.raises(ValueError, match="digest/settings"):
            resume_process(output, mode="live")
        factory.return_value.complete.assert_not_called()
        assert (output / "journal.sqlite3").read_bytes() == before
