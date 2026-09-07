"""Response validity is neither committed storage nor truthful task completion."""

import base64
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import JsonValue

from agent_fault_lab.contracts import ContractError, validate_response
from agent_fault_lab.evaluation import inspect_state
from agent_fault_lab.model import ToolCall
from agent_fault_lab.reliability import (
    CASES,
    POLICIES,
    ReliabilityConfig,
    ResponseCase,
    ResponseExecutor,
    ResponsePolicy,
)
from agent_fault_lab.tasks import TaskStore
from agent_fault_lab.trace import Recorder

CREATE = ToolCall(name="create_task", arguments={"title": "Review the invoice"})


def envelope(task_value: JsonValue, **changes: JsonValue) -> bytes:
    payload = {"schema_version": 1, "ok": True, "value": task_value, "error": None}
    payload.update(changes)
    return json.dumps(payload).encode()


@pytest.mark.parametrize(
    "raw",
    [
        b"{",
        b"{} prose",
        b"```json\n{}\n```",
        b"\xff",
        b'{"ok":true,"ok":false}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"x":{"a":1,"a":2}}',
    ],
)
def test_rejects_whole_invalid_json(raw: bytes) -> None:
    with pytest.raises(ContractError) as caught:
        validate_response(raw, CREATE)
    assert caught.value.stage == "syntax"


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": 2},
        {"schema_version": True},
        {"schema_version": 1.0},
        {"ok": "true"},
        {"ok": 1},
        {"unknown": True},
        {"value": {"id": " ", "title": "Review the invoice"}},
        {"value": {"id": 7, "title": "Review the invoice"}},
        {"value": {"id": "id", "title": ""}},
        {"value": {"id": "id", "title": "Review the invoice", "extra": 1}},
        {"ok": False},
        {"error": {"code": "storage_error", "message": "error"}},
        {"ok": False, "value": None, "error": {"code": "unexpected", "message": "x"}},
    ],
)
def test_rejects_invalid_envelope(changes: dict[str, JsonValue]) -> None:
    raw = envelope({"id": "id", "title": "Review the invoice"}, **changes)
    with pytest.raises(ContractError) as caught:
        validate_response(raw, CREATE)
    assert caught.value.stage == "schema"


@pytest.mark.parametrize("field", ["schema_version", "ok", "value", "error"])
def test_requires_explicit_envelope_fields(field: str) -> None:
    payload = json.loads(envelope({"id": "id", "title": "Review the invoice"}))
    del payload[field]
    with pytest.raises(ContractError) as caught:
        validate_response(json.dumps(payload).encode(), CREATE)
    assert caught.value.stage == "schema"


def test_request_consistency_and_exact_preservation() -> None:
    title = "  Résumé\n发票  "
    call = ToolCall(name="create_task", arguments={"title": title})
    task: dict[str, JsonValue] = {"id": " id ", "title": title}
    result = validate_response(envelope(task), call)
    assert result.value is not None and result.value.title == title
    assert result.value.id == " id "
    for raw in (envelope(None), envelope({"id": "id", "title": title.strip()})):
        with pytest.raises(ContractError) as caught:
            validate_response(raw, call)
        assert caught.value.stage == "request"
    lookup = ToolCall(name="get_task", arguments={"task_id": " id "})
    assert validate_response(envelope(None), lookup).value is None
    assert validate_response(envelope(task), lookup).value is not None
    with pytest.raises(ContractError) as caught:
        validate_response(
            envelope(task), ToolCall(name="get_task", arguments={"task_id": "id"})
        )
    assert caught.value.stage == "request"


@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize(
    "call",
    [
        ToolCall(name="delete_task", arguments={}),
        ToolCall(name="create_task", arguments={"title": " "}),
        ToolCall(name="create_task", arguments={"title": 1}),
        ToolCall(name="create_task", arguments={"title": "valid", "extra": True}),
        ToolCall(name="create_task", arguments={}),
        ToolCall(name="get_task", arguments={"task_id": ""}),
    ],
)
def test_invalid_inputs_never_enter_storage(
    tmp_path: Path, policy: ResponsePolicy, call: ToolCall
) -> None:
    database = tmp_path / "tasks.sqlite3"
    store = TaskStore(database)
    recorder = Recorder()
    executor = ResponseExecutor(
        store, recorder, ReliabilityConfig(case="wrong-create-title", policy=policy)
    )
    with (
        patch.object(
            store, "create_task", side_effect=AssertionError("Entered storage")
        ),
        patch.object(store, "get_task", side_effect=AssertionError("Entered storage")),
    ):
        result = executor.execute(call, "call")
    assert not result.executed
    assert json.loads(result.content)["ok"] is False
    assert inspect_state(database).rows == ()
    assert not any(e.kind.endswith("fault_injected") for e in recorder.events)


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("policy", POLICIES)
def test_fault_delivery_preserves_bytes_and_separate_storage(
    tmp_path: Path, case: ResponseCase, policy: ResponsePolicy
) -> None:
    database = tmp_path / "tasks.sqlite3"
    store = TaskStore(database)
    recorder = Recorder()
    executor = ResponseExecutor(
        store, recorder, ReliabilityConfig(case=case, policy=policy)
    )
    call = CREATE
    if case == "wrong-get-id":
        task = store.create_task("Review the invoice")
        call = ToolCall(name="get_task", arguments={"task_id": task.id})
    result = executor.execute(call, "call")
    assert result.executed
    rows = inspect_state(database).rows
    assert rows is not None and len(rows) == (0 if case == "dropped-write" else 1)
    if rows:
        assert rows[0].title == "Review the invoice"
    captured = next(e for e in recorder.events if e.kind == "response_captured")
    encoded = captured.data["raw_base64"]
    assert isinstance(encoded, str)
    raw = base64.b64decode(encoded)
    if policy == "pass-through" or case in {"healthy", "dropped-write"}:
        assert result.content.encode() == raw
    else:
        assert result.content.encode() != raw
        response = json.loads(result.content)
        assert response["error"]["code"] == "invalid_result"
        assert case not in response["error"]["message"]
        assert response["value"] is None
    assert '"executed"' not in result.content and '"fault"' not in result.content


@pytest.mark.parametrize("policy", POLICIES)
def test_storage_errors_and_not_found_remain_truthful(
    tmp_path: Path, policy: ResponsePolicy
) -> None:
    store = TaskStore(tmp_path / "tasks.sqlite3")
    recorder = Recorder()
    executor = ResponseExecutor(
        store, recorder, ReliabilityConfig(case="malformed-json", policy=policy)
    )
    with patch.object(
        store, "create_task", side_effect=sqlite3.OperationalError("locked")
    ):
        result = executor.execute(CREATE, "create")
    assert result.executed
    assert json.loads(result.content)["error"]["code"] == "storage_error"
    absent = executor.execute(
        ToolCall(name="get_task", arguments={"task_id": "absent"}), "get"
    )
    assert json.loads(absent.content) == {
        "schema_version": 1,
        "ok": True,
        "value": None,
        "error": None,
    }
    assert not any(e.kind.endswith("fault_injected") for e in recorder.events)
