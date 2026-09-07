"""M09 sequential conversation recovery across independent persistence files."""

import hashlib
import json
from contextlib import nullcontext
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Literal
from unittest.mock import patch
from uuid import uuid4

from agent_fault_lab.agent import SYSTEM_PROMPT, Limits
from agent_fault_lab.barriers import pause
from agent_fault_lab.claims import TerminalClaim
from agent_fault_lab.evaluation import evaluate_run
from agent_fault_lab.execution_types import (
    ExecutionLimits,
    ExecutionState,
    PausePoint,
    ProcessConfig,
)
from agent_fault_lab.experiments import measure
from agent_fault_lab.journal import (
    Journal,
    JournalRecorder,
    RunState,
    atomic_json,
    regular,
    run_lock,
    strict_json,
)
from agent_fault_lab.model import (
    ExecutionStatus,
    Message,
    ModelClient,
    ModelSettings,
    ModelTurn,
    ProviderError,
    RunResult,
    ToolCall,
)
from agent_fault_lab.ollama_adapter import OllamaClient
from agent_fault_lab.process_reports import (
    ProcessObservation,
    process_counts,
    render_process_report,
)
from agent_fault_lab.supervision import Supervisor
from agent_fault_lab.tasks import TaskStore, recover_task_database
from agent_fault_lab.tools import TOOL_SPECS
from agent_fault_lab.trace import Event

TITLE = "Review the invoice"
REQUEST = f"Create a task with the exact title {json.dumps(TITLE)}."
SCRIPT_CLIENT = "serializable-script-v1 (NOT an AI model)"


def compatibility() -> str:
    root = Path(__file__).parent
    files = (
        "durable_run.py",
        "journal.py",
        "supervision.py",
        "worker.py",
        "tasks.py",
        "contracts.py",
        "execution_types.py",
        "model.py",
        "agent.py",
        "claims.py",
        "tools.py",
        "evaluation.py",
    )
    digest = hashlib.sha256(version("agent-fault-lab").encode())
    for name in files:
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def scripted_turn(state: RunState) -> ModelTurn:
    """Named, serializable behavior; the durable cursor advances with the response."""
    if state.script_cursor == 0:
        call = ToolCall(name="create_task", arguments={"title": state.expected_title})
        return ModelTurn(
            tool_calls=(call, call) if state.script == "batch-two-v1" else (call,)
        )
    result = json.loads(state.messages[-1].content)
    value = result.get("value") if result.get("ok") else None
    if (
        state.script_cursor == 1
        and isinstance(value, dict)
        and state.script == "create-read-report-v1"
    ):
        return ModelTurn(
            tool_calls=(ToolCall(name="get_task", arguments={"task_id": value["id"]}),)
        )
    claim = (
        TerminalClaim(status="completed", task_id=value["id"])
        if isinstance(value, dict)
        else TerminalClaim(status="unknown", task_id=None)
    )
    return ModelTurn(content=claim.model_dump_json())


def import_worker_evidence(directory: Path, recorder: JournalRecorder) -> None:
    """Import surviving bytes only; do not reconstruct events that were not saved."""
    seen = {
        (e.data.get("evidence"), nested.get("sequence"))
        for e in recorder.records
        if e.kind == "worker_evidence"
        and isinstance(nested := e.data.get("event"), dict)
    }
    for path in sorted(directory.glob("worker-*.jsonl")):
        regular(path)
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = Event.model_validate_json(line)
            except ValueError:
                recorder.emit("worker_evidence_gap", evidence=path.name)
                break
            if (path.name, event.sequence) in seen:
                continue
            operation, attempt = path.stem.removeprefix("worker-").rsplit("-", 1)
            recorder.emit(
                "worker_evidence",
                operation_id=operation,
                attempt_id=f"{operation}:{attempt}",
                evidence=path.name,
                event=event.model_dump(mode="json"),
                imported_after_restart=True,
            )


def _drive(
    journal: Journal,
    recorder: JournalRecorder,
    lock_fd: int,
    *,
    pause_at: PausePoint | None = None,
    client: ModelClient | None = None,
) -> RunState:
    directory = journal.directory

    def execution_checkpoint(execution: ExecutionState) -> None:
        recorder.transition(
            journal.state.model_copy(update={"execution": execution}),
            "execution_checkpoint",
        )

    supervisor = Supervisor(
        directory,
        recorder,
        journal.state.config,
        limits=journal.state.execution_limits,
        state=journal.state.execution,
        checkpoint=execution_checkpoint,
        lock_fd=lock_fd,
        pause_at=pause_at,
    )

    def stop(
        status: ExecutionStatus, content: str | None = None, error: str | None = None
    ) -> None:
        state = journal.state
        result = RunResult(
            status=status,
            final_content=content,
            model_calls=state.model_calls,
            tool_calls=state.tool_calls,
            tool_executions=state.tool_executions,
            error=error,
        )
        recorder.transition(
            state.model_copy(update={"terminal": result, "phase": "terminal"}),
            "run_stopped",
            result=result.model_dump(mode="json"),
        )
        pause(directory, pause_at, "terminal-checkpoint")

    try:
        while journal.state.phase != "terminal":
            state = journal.state
            if state.phase == "model":
                if state.model_calls >= state.limits.max_model_calls:
                    stop("model_limit", error="Model-call budget exhausted")
                    break
                recorder.transition(
                    state.model_copy(update={"model_calls": state.model_calls + 1}),
                    "model_requested",
                    model_call=state.model_calls + 1,
                )
                try:
                    turn = (
                        client.complete(state.messages, TOOL_SPECS, state.settings)
                        if client is not None
                        else scripted_turn(state)
                    )
                except ProviderError as exc:
                    stop("provider_error", error=str(exc))
                    break
                state = journal.state
                updated = state.model_copy(
                    update={
                        "messages": (
                            *state.messages,
                            Message(
                                role="assistant",
                                content=turn.content,
                                tool_calls=turn.tool_calls,
                                metadata=turn.metadata,
                            ),
                        ),
                        "script_cursor": state.script_cursor
                        + int(state.mode == "offline"),
                        "pending": turn.tool_calls,
                        "last_turn": turn,
                        "tool_cursor": 0,
                        "phase": "tools",
                    }
                )
                recorder.transition(
                    updated,
                    "model_returned",
                    model_call=state.model_calls,
                    turn=turn.model_dump(mode="json"),
                )
                pause(directory, pause_at, "assistant-checkpoint")
                if turn.finish_reason == "length":
                    stop(
                        "protocol_error",
                        turn.content if not turn.tool_calls else None,
                        "Model response hit its output limit",
                    )
                elif not turn.tool_calls:
                    stop(
                        "finished" if turn.content.strip() else "protocol_error",
                        turn.content,
                        None if turn.content.strip() else "Empty assistant response",
                    )
                continue
            # A crash can occur after the response checkpoint but before the
            # terminal/protocol decision. Interpret that saved response once.
            if (
                state.last_turn is not None
                and state.last_turn.finish_reason == "length"
            ):
                turn = state.last_turn
                stop(
                    "protocol_error",
                    turn.content if not turn.tool_calls else None,
                    "Model response hit its output limit",
                )
                continue
            if not state.pending and state.last_turn is not None:
                content = state.last_turn.content
                stop(
                    "finished" if content.strip() else "protocol_error",
                    content,
                    None if content.strip() else "Empty assistant response",
                )
                continue
            if state.tool_cursor == len(state.pending):
                recorder.transition(
                    state.model_copy(
                        update={"phase": "model", "pending": (), "tool_cursor": 0}
                    ),
                    "model_ready",
                )
                continue
            call = state.pending[state.tool_cursor]
            call_id = f"m{state.model_calls}-t{state.tool_cursor + 1}"
            if not state.tool_reserved:
                if state.tool_calls >= state.limits.max_tool_calls:
                    stop("tool_limit", error="Tool-call budget exhausted")
                    break
                recorder.transition(
                    state.model_copy(
                        update={
                            "tool_calls": state.tool_calls + 1,
                            "tool_reserved": True,
                        }
                    ),
                    "tool_requested",
                    call_id=call_id,
                    call=call.model_dump(mode="json"),
                )
            delivery = supervisor.execute(call, call_id)
            state = journal.state
            recorder.transition(
                state.model_copy(
                    update={
                        "messages": (
                            *state.messages,
                            Message(
                                role="tool",
                                content=delivery.content,
                                call_id=call_id,
                                tool_name=call.name,
                            ),
                        ),
                        "tool_cursor": state.tool_cursor + 1,
                        "tool_reserved": False,
                        "tool_executions": state.tool_executions
                        + int(delivery.executed),
                    }
                ),
                "tool_returned",
                call_id=call_id,
                result=delivery.model_dump(mode="json"),
            )
            pause(directory, pause_at, "tool-checkpoint")
    finally:
        supervisor.stop_worker()
    return journal.state


def finalize(journal: Journal, recorder: JournalRecorder) -> ProcessObservation:
    state = journal.state
    assert state.terminal is not None
    if state.evaluation is None:
        # The owning storage layer recovers any hot SQLite journal before the
        # evaluator opens its independent read-only connection. No schema repair.
        recover_task_database(journal.directory / "tasks.sqlite3")
        evaluation = evaluate_run(
            journal.directory / "tasks.sqlite3",
            state.expected_title,
            state.terminal,
            client=state.client,
        )
        recorder.transition(
            state.model_copy(update={"evaluation": evaluation}),
            "evaluation_completed",
            task_outcome=evaluation.task_outcome,
            claim_support=evaluation.claim_support,
        )
    state = journal.state
    assert state.evaluation is not None
    assert state.terminal is not None
    counts = process_counts(recorder.records, state.execution.total_attempts)
    session_seconds: dict[str, float] = {}
    for event in recorder.records:
        session_seconds[event.session_id] = max(
            session_seconds.get(event.session_id, 0.0), event.elapsed_seconds
        )
    metrics = measure(recorder.events, state.terminal).model_copy(
        update={
            "elapsed_seconds": sum(session_seconds.values()),
            "fault_exercised": counts.fault_activations > 0,
        }
    )
    observation = ProcessObservation(
        run_id=state.run_id,
        config=state.config,
        execution_limits=state.execution_limits,
        evaluation=state.evaluation,
        metrics=metrics,
        process=counts,
    )
    atomic_json(
        journal.directory / "result.json", state.terminal.model_dump(mode="json")
    )
    atomic_json(
        journal.directory / "evaluation.json", state.evaluation.model_dump(mode="json")
    )
    atomic_json(
        journal.directory / "observation.json", observation.model_dump(mode="json")
    )
    # Import lazily: saved_reports dispatch imports this artifact's renderer.
    from agent_fault_lab.saved_reports import replace_report

    replace_report(journal.directory, render_process_report(observation))
    recorder.transition(
        state.model_copy(update={"finalized": True}), "artifacts_finalized"
    )
    return observation


def run_process(
    directory: Path,
    config: ProcessConfig,
    *,
    mode: Literal["offline", "live"],
    provenance: dict[str, object] | None = None,
    pause_at: PausePoint | None = None,
    script: Literal["create-read-report-v1", "batch-two-v1"] = "create-read-report-v1",
    limits: Limits | None = None,
    execution_limits: ExecutionLimits | None = None,
) -> ProcessObservation:
    client = None
    info = None
    if mode == "live":
        client = OllamaClient()
        info = client.inspect()
        if not info.ready:
            raise ValueError("Live preflight refused: " + "; ".join(info.problems))
    directory = directory.resolve()
    directory.mkdir()
    print(f"Run directory: {directory}", flush=True)
    with run_lock(directory, create=True) as lock_fd:
        TaskStore(directory / "tasks.sqlite3")
        state = RunState(
            run_id=str(uuid4()),
            compatibility=compatibility(),
            config=config,
            mode=mode,
            client=client.label if client else SCRIPT_CLIENT,
            provenance=json.loads(
                json.dumps(
                    {
                        "source": provenance or {},
                        "model": info.model_dump(mode="json") if info else None,
                    }
                )
            ),
            settings=ModelSettings(),
            request=REQUEST,
            expected_title=TITLE,
            limits=limits or Limits(),
            execution_limits=execution_limits or ExecutionLimits(),
            script=script,
            messages=(
                Message(role="system", content=SYSTEM_PROMPT),
                Message(role="user", content=REQUEST),
            ),
        )
        atomic_json(
            directory / "manifest.json",
            {
                "schema_version": 6,
                "artifact": "execution-manifest",
                "crash_barrier": pause_at,
                "initial_state": state.model_dump(mode="json"),
                "started_at": datetime.now(UTC).isoformat(),
            },
        )
        journal = Journal(directory, initial=state)
        recorder = JournalRecorder(journal)
        recorder.emit("session_started", resumed=False, downtime_seconds=None)
        with (
            patch("socket.socket", side_effect=AssertionError("Offline runner"))
            if mode == "offline"
            else nullcontext()
        ):
            _drive(journal, recorder, lock_fd, pause_at=pause_at, client=client)
        return finalize(journal, recorder)


def resume_process(
    directory: Path, *, mode: Literal["offline", "live"]
) -> ProcessObservation:
    if directory.is_symlink():
        raise ValueError("Run directory must not be a symlink")
    directory = directory.resolve()
    regular(directory / "journal.sqlite3")
    regular(directory / "tasks.sqlite3")
    with run_lock(directory) as lock_fd:
        journal = Journal(directory)
        state = journal.state
        regular(directory / "manifest.json")
        manifest = strict_json((directory / "manifest.json").read_text())
        if (
            not isinstance(manifest, dict)
            or manifest.get("artifact") != "execution-manifest"
            or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 6
        ):
            raise ValueError("Missing or unsupported execution manifest")
        original = RunState.model_validate_json(
            json.dumps(manifest.get("initial_state"))
        )
        for field in (
            "run_id",
            "compatibility",
            "config",
            "mode",
            "client",
            "provenance",
            "settings",
            "limits",
            "execution_limits",
            "request",
            "expected_title",
            "script",
        ):
            if getattr(state, field) != getattr(original, field):
                raise ValueError(f"Saved immutable configuration changed: {field}")
        if state.mode != mode or state.compatibility != compatibility():
            raise ValueError(
                "Saved execution mode or compatibility fingerprint differs"
            )
        if state.finalized:
            regular(directory / "observation.json")
            observation = ProcessObservation.model_validate_json(
                (directory / "observation.json").read_text()
            )
            if observation.evaluation != state.evaluation:
                raise ValueError("Finalized journal and observation disagree")
            return observation
        client = None
        if mode == "live" and state.terminal is None:
            client = OllamaClient()
            info = client.inspect()
            saved = state.provenance.get("model")
            if (
                not info.ready
                or not isinstance(saved, dict)
                or info.model_digest != saved.get("model_digest")
                or state.settings != ModelSettings()
            ):
                raise ValueError(
                    "Saved model digest/settings no longer match preflight"
                )
        recorder = JournalRecorder(journal)
        last = recorder.records[-1] if recorder.records else None
        gap = (
            (datetime.now(UTC) - datetime.fromisoformat(last.wall_time)).total_seconds()
            if last
            else None
        )
        recorder.emit(
            "session_started",
            resumed=True,
            downtime_seconds=None,
            checkpoint_gap_seconds=gap,
            uncertainty="Checkpoint gap includes unobserved execution and downtime",
        )
        import_worker_evidence(directory, recorder)
        recover_task_database(directory / "tasks.sqlite3")
        with (
            patch("socket.socket", side_effect=AssertionError("Offline runner"))
            if mode == "offline"
            else nullcontext()
        ):
            _drive(journal, recorder, lock_fd, client=client)
        return finalize(journal, recorder)
