"""Deliberate tool lies remain isolated from validation, readback and grading."""

import json
from pathlib import Path

import pytest
from pydantic import JsonValue

from agent_fault_lab.agent import SYSTEM_PROMPT, run_agent
from agent_fault_lab.claims import TerminalClaim
from agent_fault_lab.evaluation import evaluate_run, inspect_state
from agent_fault_lab.experiments import (
    READ_BACK_INSTRUCTION,
    ExperimentConfig,
    Variant,
    measure,
)
from agent_fault_lab.faults import FaultInjector
from agent_fault_lab.model import ModelTurn, ToolCall
from agent_fault_lab.scripted import ScriptedClient
from agent_fault_lab.tasks import TaskStore
from agent_fault_lab.tools import execute_tool
from agent_fault_lab.trace import Recorder


def test_dropped_write_returns_success_without_touching_storage(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite3"
    store = TaskStore(database)
    existing = store.create_task("Existing")
    before = database.read_bytes()
    recorder = Recorder()
    injector = FaultInjector("dropped-write", recorder)
    call = ToolCall(name="create_task", arguments={"title": "  चालान  "})
    identifiers = []
    for index in range(2):
        result = execute_tool(store, call, injector=injector, call_id=f"call-{index}")
        assert result.ok and result.executed and isinstance(result.value, dict)
        assert result.value["title"] == "  चालान  "
        identifiers.append(result.value["id"])
        assert set(result.model_dump()) == {"ok", "value", "error", "executed"}
        lookup = execute_tool(
            store,
            ToolCall(name="get_task", arguments={"task_id": result.value["id"]}),
            injector=injector,
        )
        assert lookup.ok and lookup.value is None
    assert identifiers[0] != identifiers[1]
    assert database.read_bytes() == before
    assert store.get_task(existing.id) == existing
    assert [e.data["call_id"] for e in recorder.events] == ["call-0", "call-1"]
    assert all(e.kind == "fault_injected" for e in recorder.events)
    assert all(e.data["write_performed"] is False for e in recorder.events)


@pytest.mark.parametrize(
    "arguments", [{}, {"title": ""}, {"title": 4}, {"title": "x", "extra": True}]
)
def test_invalid_create_does_not_exercise_fault(
    tmp_path: Path, arguments: JsonValue
) -> None:
    recorder = Recorder()
    result = execute_tool(
        TaskStore(tmp_path / "tasks.sqlite3"),
        ToolCall(name="create_task", arguments=arguments),
        injector=FaultInjector("dropped-write", recorder),
    )
    assert not result.ok and not result.executed and not recorder.events


@pytest.mark.parametrize("variant", ["baseline", "read-back"])
def test_prompt_does_not_force_readback_or_leak_fault(
    tmp_path: Path, variant: Variant
) -> None:
    database = tmp_path / "tasks.sqlite3"
    client = ScriptedClient(
        [
            ModelTurn(
                tool_calls=(ToolCall(name="create_task", arguments={"title": "Exact"}),)
            ),
            ModelTurn(
                content=TerminalClaim(status="unknown", task_id=None).model_dump_json()
            ),
        ]
    )
    recorder = Recorder()
    config = ExperimentConfig(variant=variant, fault="dropped-write")
    result = run_agent(
        client, TaskStore(database), "Create Exact", recorder, config=config
    )
    assert result.tool_calls == result.tool_executions == 1
    expected = SYSTEM_PROMPT + (READ_BACK_INSTRUCTION if variant == "read-back" else "")
    assert client.requests[0][0].content == expected
    assert all(
        "dropped-write" not in m.content for request in client.requests for m in request
    )
    metrics = measure(recorder.events, result)
    assert metrics.fault_exercised and metrics.injected_writes == 1
    assert metrics.read_back_calls == 0
    assert inspect_state(database).rows == ()


def test_no_fault_really_writes_and_records_no_injection(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite3"
    recorder = Recorder()
    result = execute_tool(
        TaskStore(database),
        ToolCall(name="create_task", arguments={"title": "Exact"}),
        injector=FaultInjector("none", recorder),
    )
    assert result.ok and result.executed and isinstance(result.value, dict)
    assert TaskStore(database).get_task(str(result.value["id"])) is not None
    assert not recorder.events


def test_baseline_can_read_spontaneously_under_fault(tmp_path: Path) -> None:
    from agent_fault_lab.cli import _comparison_client

    database = tmp_path / "tasks.sqlite3"
    # The script chooses to verify even though the actual prompt is baseline.
    client = _comparison_client(ExperimentConfig(variant="read-back"))
    recorder = Recorder()
    result = run_agent(
        client,
        TaskStore(database),
        "Create",
        recorder,
        config=ExperimentConfig(fault="dropped-write"),
    )
    assert READ_BACK_INSTRUCTION not in client.requests[0][0].content
    assert result.tool_calls == 2
    assert json.loads(client.requests[-1][-1].content)["value"] is None
    evaluation = evaluate_run(
        database, "Review the invoice", result, client=client.label
    )
    assert evaluation.task_outcome == "not_completed"
    assert evaluation.claim_support == "supported"
    assert evaluation.false_success is False


def test_no_create_is_unexercised_not_recovery(tmp_path: Path) -> None:
    recorder = Recorder()
    result = run_agent(
        ScriptedClient([ModelTurn(content='{"status":"unknown","task_id":null}')]),
        TaskStore(tmp_path / "tasks.sqlite3"),
        "Create",
        recorder,
        config=ExperimentConfig(fault="dropped-write"),
    )
    metrics = measure(recorder.events, result)
    assert not metrics.fault_exercised and metrics.injected_writes == 0


def test_evidence_error_before_injected_return_is_harness_error(tmp_path: Path) -> None:
    class Broken(Recorder):
        def emit(self, kind: str, **data: JsonValue) -> None:
            raise OSError("No space for evidence")

    database = tmp_path / "tasks.sqlite3"
    with pytest.raises(OSError, match="No space"):
        execute_tool(
            TaskStore(database),
            ToolCall(name="create_task", arguments={"title": "Exact"}),
            injector=FaultInjector("dropped-write", Broken()),
        )
    assert inspect_state(database).rows == ()
