"""Offline contracts for the loop, not claims about a model's intelligence."""

import json
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path

import pytest
from pydantic import JsonValue, ValidationError

from agent_fault_lab.agent import Limits, run_agent
from agent_fault_lab.claims import CLAIM_INSTRUCTION, parse_claim
from agent_fault_lab.model import (
    Message,
    ModelSettings,
    ModelTurn,
    ProviderError,
    ToolCall,
)
from agent_fault_lab.scripted import ScriptedClient
from agent_fault_lab.tasks import TaskStore
from agent_fault_lab.tools import TOOL_SPECS, execute_tool
from agent_fault_lab.trace import Recorder


def create_turn(title: str = "Review the invoice") -> ModelTurn:
    return ModelTurn(
        tool_calls=(ToolCall(name="create_task", arguments={"title": title}),)
    )


def rows(database: Path) -> list[tuple[str, str]]:
    with closing(
        sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
    ) as connection:
        return list(connection.execute("SELECT id, title FROM tasks ORDER BY rowid"))


def test_scripted_create_read_and_finish(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite3"
    recorder = Recorder()

    def read_back(messages: Sequence[Message]) -> ModelTurn:
        result = json.loads(messages[-1].content)
        assert result["ok"] is True
        assert result["value"]["title"] == "Review the invoice"
        return ModelTurn(
            tool_calls=(
                ToolCall(
                    name="get_task",
                    arguments={"task_id": result["value"]["id"]},
                ),
            )
        )

    def finish(messages: Sequence[Message]) -> ModelTurn:
        saved = json.loads(messages[-1].content)["value"]
        return ModelTurn(content=f"Created {saved['id']}")

    client = ScriptedClient([create_turn(), read_back, finish])
    result = run_agent(client, TaskStore(database), "Create a task", recorder)

    assert result.status == "finished"
    assert (result.model_calls, result.tool_calls, result.tool_executions) == (3, 2, 2)
    stored = rows(database)
    assert len(stored) == 1 and stored[0][1] == "Review the invoice"
    assert result.final_content == f"Created {stored[0][0]}"
    assert client.requests[1][-1].call_id == "m1-t1"
    assert client.requests[2][-1].call_id == "m2-t1"
    assert [event.kind for event in recorder.events] == [
        "run_started",
        "model_requested",
        "model_returned",
        "tool_requested",
        "tool_returned",
        "model_requested",
        "model_returned",
        "tool_requested",
        "tool_returned",
        "model_requested",
        "model_returned",
        "run_stopped",
    ]


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"title": ""},
        {"title": " \n"},
        {"title": 123},
        {"title": None},
        {"title": True},
        {"title": "valid", "unexpected": "reject me"},
        ["title", "bad shape"],
        "not an object",
        None,
    ],
)
def test_invalid_arguments_do_not_execute(tmp_path: Path, arguments: JsonValue) -> None:
    database = tmp_path / "tasks.sqlite3"
    client = ScriptedClient(
        [
            ModelTurn(tool_calls=(ToolCall(name="create_task", arguments=arguments),)),
            ModelTurn(content="The arguments were rejected."),
        ]
    )
    result = run_agent(client, TaskStore(database), "Create task", Recorder())

    assert rows(database) == []
    assert result.tool_calls == 1 and result.tool_executions == 0
    returned = json.loads(client.requests[1][-1].content)
    assert not returned["ok"]
    assert "Invalid arguments" in returned["error"]


def test_unknown_tool_is_not_executed(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite3"
    client = ScriptedClient(
        [
            ModelTurn(tool_calls=(ToolCall(name="drop_database", arguments={}),)),
            ModelTurn(content="That tool is unavailable."),
        ]
    )
    result = run_agent(client, TaskStore(database), "Create task", Recorder())

    assert result.tool_executions == 0
    assert rows(database) == []
    message = client.requests[1][-1]
    assert message.call_id == "m1-t1" and message.tool_name == "drop_database"
    assert "Unknown tool" in json.loads(message.content)["error"]


def test_multiple_same_name_calls_keep_result_order(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite3"
    client = ScriptedClient(
        [
            ModelTurn(
                tool_calls=(
                    ToolCall(name="create_task", arguments={"title": "First"}),
                    ToolCall(name="create_task", arguments={"title": "Second"}),
                )
            ),
            ModelTurn(content="Two calls processed."),
        ]
    )
    recorder = Recorder()
    run_agent(client, TaskStore(database), "Create two tasks", recorder)

    messages = client.requests[1]
    assert messages[-3].role == "assistant"
    assert len(messages[-3].tool_calls) == 2
    assert [m.call_id for m in messages[-2:]] == ["m1-t1", "m1-t2"]
    assert [json.loads(m.content)["value"]["title"] for m in messages[-2:]] == [
        "First",
        "Second",
    ]
    assert [row[1] for row in rows(database)] == ["First", "Second"]
    assert [
        e.data["call_id"] for e in recorder.events if e.kind == "tool_returned"
    ] == ["m1-t1", "m1-t2"]


def test_validation_error_can_be_corrected_next_turn(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite3"
    client = ScriptedClient(
        [create_turn(""), create_turn("  Exact title  "), ModelTurn(content="Done")]
    )
    result = run_agent(client, TaskStore(database), "Create task", Recorder())
    assert result.tool_calls == 2 and result.tool_executions == 1
    assert [row[1] for row in rows(database)] == ["  Exact title  "]


def test_storage_error_reaches_model_without_success(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite3"
    store = TaskStore(database)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "CREATE TRIGGER reject_insert BEFORE INSERT ON tasks "
            "BEGIN SELECT RAISE(ABORT, 'blocked'); END"
        )
    client = ScriptedClient([create_turn(), ModelTurn(content="I could not save it.")])
    result = run_agent(client, store, "Create task", Recorder())
    assert result.tool_executions == 1
    returned = json.loads(client.requests[1][-1].content)
    assert returned["ok"] is False and "Storage error" in returned["error"]
    assert rows(database) == []


def test_get_not_found_is_explicit_null(tmp_path: Path) -> None:
    result = execute_tool(
        TaskStore(tmp_path / "tasks.sqlite3"),
        ToolCall(name="get_task", arguments={"task_id": "unknown"}),
    )
    assert result.ok and result.executed and result.value is None


def test_provider_error_keeps_committed_write_and_partial_trace(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite3"
    trace_path = tmp_path / "trace.jsonl"
    client = ScriptedClient([create_turn(), ProviderError("Timed out")])
    with trace_path.open("x", encoding="utf-8") as stream:
        result = run_agent(client, TaskStore(database), "Create task", Recorder(stream))
    assert result.status == "provider_error" and result.error == "Timed out"
    assert result.model_calls == 2 and result.tool_executions == 1
    assert len(rows(database)) == 1
    events = [json.loads(line) for line in trace_path.read_text().splitlines()]
    assert events[-1]["data"]["result"]["status"] == "provider_error"
    assert any(e["kind"] == "tool_returned" for e in events)


def test_model_limit_stops_without_seventh_call(tmp_path: Path) -> None:
    client = ScriptedClient([create_turn()] * 7)
    result = run_agent(
        client, TaskStore(tmp_path / "tasks.sqlite3"), "Create task", Recorder()
    )
    assert result.status == "model_limit"
    assert result.model_calls == len(client.requests) == 6
    assert result.tool_executions == 6  # Duplicate prevention is M07, not hidden here.


def test_tool_limit_does_not_execute_seventh_call(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite3"
    call = ToolCall(name="create_task", arguments={"title": "Repeated"})
    client = ScriptedClient([ModelTurn(tool_calls=(call,) * 7)])
    recorder = Recorder()
    result = run_agent(client, TaskStore(database), "Create task", recorder)
    assert result.status == "tool_limit"
    assert result.model_calls == 1 and result.tool_executions == 6
    assert len(rows(database)) == 6
    assert recorder.events[-2].kind == "tool_skipped"


def test_rejected_calls_consume_budget(tmp_path: Path) -> None:
    call = ToolCall(name="unknown", arguments={})
    result = run_agent(
        ScriptedClient([ModelTurn(tool_calls=(call,) * 3)]),
        TaskStore(tmp_path / "tasks.sqlite3"),
        "Create task",
        Recorder(),
        limits=Limits(max_tool_calls=2),
    )
    assert result.status == "tool_limit"
    assert result.tool_calls == 2 and result.tool_executions == 0


@pytest.mark.parametrize(
    "turn",
    [
        ModelTurn(),
        ModelTurn(content=" "),
        ModelTurn(content="partial", finish_reason="length"),
        ModelTurn(tool_calls=create_turn().tool_calls, finish_reason="length"),
    ],
)
def test_empty_or_truncated_turn_is_not_completion(
    tmp_path: Path, turn: ModelTurn
) -> None:
    result = run_agent(
        ScriptedClient([turn]),
        TaskStore(tmp_path / "tasks.sqlite3"),
        "Create task",
        Recorder(),
    )
    assert result.status == "protocol_error"
    assert result.tool_executions == 0


def test_finished_does_not_mean_task_success(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite3"
    result = run_agent(
        ScriptedClient([ModelTurn(content="Done! Trust me.")]),
        TaskStore(database),
        "Create task",
        Recorder(),
    )
    assert result.status == "finished" and result.tool_executions == 0
    assert rows(database) == []  # Loop termination alone is still not a task grade.


def test_terminal_contract_does_not_force_tool_turns_or_repair_prose(
    tmp_path: Path,
) -> None:
    prose = '</think>\n{"status":"completed","task_id":"task-1"}'
    client = ScriptedClient([create_turn(), ModelTurn(content=prose)])
    recorder = Recorder()
    result = run_agent(
        client, TaskStore(tmp_path / "tasks.sqlite3"), "Create task", recorder
    )
    assert CLAIM_INSTRUCTION in client.requests[0][0].content
    assert result.tool_executions == 1 and result.model_calls == 2
    assert result.final_content == prose
    assert parse_claim(result.final_content).status == "invalid"
    recorded_turn = recorder.events[-2].data["turn"]
    assert isinstance(recorded_turn, dict)
    assert recorded_turn["content"] == prose


def test_truncated_terminal_content_is_preserved(tmp_path: Path) -> None:
    partial = '{"status":"completed","task_id":"task-1"}'
    result = run_agent(
        ScriptedClient([ModelTurn(content=partial, finish_reason="length")]),
        TaskStore(tmp_path / "tasks.sqlite3"),
        "Create task",
        Recorder(),
    )
    assert result.status == "protocol_error" and result.final_content == partial


def test_empty_script_is_a_provider_error(tmp_path: Path) -> None:
    result = run_agent(
        ScriptedClient([]),
        TaskStore(tmp_path / "tasks.sqlite3"),
        "Create task",
        Recorder(),
    )
    assert result.status == "provider_error" and "Script exhausted" in (
        result.error or ""
    )


def test_trace_snapshots_values_and_flushes(tmp_path: Path) -> None:
    payload: dict[str, JsonValue] = {"title": "Original"}
    path = tmp_path / "trace.jsonl"
    with path.open("x", encoding="utf-8") as stream:
        recorder = Recorder(stream)
        recorder.emit("example", value=payload)
        payload["title"] = "Changed later"
        assert json.loads(path.read_text())["data"]["value"]["title"] == "Original"
        assert recorder.events[0].data["value"] == {"title": "Original"}


def test_trace_failure_before_tool_prevents_write(tmp_path: Path) -> None:
    class BrokenRecorder(Recorder):
        def emit(self, kind: str, **data: JsonValue) -> None:
            if kind == "tool_requested":
                raise OSError("Disk full")
            super().emit(kind, **data)

    database = tmp_path / "tasks.sqlite3"
    with pytest.raises(OSError, match="Disk full"):
        run_agent(
            ScriptedClient([create_turn()]),
            TaskStore(database),
            "Create task",
            BrokenRecorder(),
        )
    assert rows(database) == []


def test_spec_and_settings_boundaries() -> None:
    assert [spec.name for spec in TOOL_SPECS] == ["create_task", "get_task"]
    assert TOOL_SPECS[0].parameters["required"] == ["title"]
    assert TOOL_SPECS[0].parameters["additionalProperties"] is False
    with pytest.raises(ValidationError):
        Limits(max_model_calls=7)
    with pytest.raises(ValidationError):
        ModelSettings(request_timeout_seconds=61.0)
    with pytest.raises(ValidationError):
        ModelSettings(context_tokens=0)
