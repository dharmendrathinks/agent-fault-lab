"""M07 retries expose ambiguous delivery without trusting injector knowledge."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from test_idempotency import rows

from agent_fault_lab.cli import TITLE, _execute, main
from agent_fault_lab.contracts import ResponseEnvelope
from agent_fault_lab.model import ModelTurn, ProviderError, ToolCall
from agent_fault_lab.reliability import scripted_response_client
from agent_fault_lab.retries import (
    RETRY_CASES,
    RETRY_POLICIES,
    DeliveryUnavailable,
    RetryCase,
    RetryConfig,
    RetryExecutor,
    RetryPolicy,
)
from agent_fault_lab.retry_reports import (
    RetryComparison,
    RetryObservation,
    count_retries,
    retry_schedule,
)
from agent_fault_lab.scripted import ScriptedClient
from agent_fault_lab.tasks import OperationConflict, TaskStore
from agent_fault_lab.trace import Recorder

CREATE = ToolCall(name="create_task", arguments={"title": TITLE})


@pytest.mark.parametrize("case", RETRY_CASES)
@pytest.mark.parametrize("policy", RETRY_POLICIES)
def test_delivery_matrix(tmp_path: Path, case: RetryCase, policy: RetryPolicy) -> None:
    database = tmp_path / "tasks.db"
    recorder = Recorder()
    executor = RetryExecutor(
        TaskStore(database), recorder, RetryConfig(case=case, policy=policy)
    )
    delivered = executor.execute(CREATE, "call")
    response = ResponseEnvelope.model_validate_json(delivered.content)
    counts = count_retries(recorder.events)
    fault = case != "retry-healthy"
    retried = fault and policy != "single-attempt"
    expected_rows = 1
    if case == "before-write-once" and policy == "single-attempt":
        expected_rows = 0
    elif case == "lost-reply-once" and policy == "retry-unprotected":
        expected_rows = 2
    assert delivered.executed
    assert response.ok == (not fault or retried)
    assert len(rows(database)) == expected_rows
    assert counts.operations == 1 and counts.attempts == 1 + retried
    assert counts.retries == retried and counts.delivery_errors == fault
    assert counts.fault_activations == fault
    assert counts.storage_entries == counts.attempts - (case == "before-write-once")
    assert counts.replayed_results == (
        case == "lost-reply-once" and policy == "retry-idempotent"
    )
    attempts = [e for e in recorder.events if e.kind == "attempt_started"]
    assert len({e.data["operation_id"] for e in attempts}) == 1
    assert len({e.data["attempt_id"] for e in attempts}) == len(attempts)
    if response.ok:
        assert response.value is not None
        assert (response.value.id, TITLE) in rows(database)
    for hidden in ("write_committed", "replayed", "operation_id", "attempt_id", case):
        assert hidden not in delivered.content


def test_missing_reply_is_identical_before_and_after_commit(tmp_path: Path) -> None:
    contents = []
    for case in ("before-write-once", "lost-reply-once"):
        executor = RetryExecutor(
            TaskStore(tmp_path / f"{case}.db"),
            Recorder(),
            RetryConfig(case=case, policy="single-attempt"),
        )
        contents.append(executor.execute(CREATE, "call").content)
    assert contents[0] == contents[1]
    assert "unknown" in contents[0]


def test_separate_calls_get_new_identity_even_with_same_call_id(tmp_path: Path) -> None:
    database = tmp_path / "tasks.db"
    recorder = Recorder()
    executor = RetryExecutor(
        TaskStore(database),
        recorder,
        RetryConfig(case="lost-reply-once", policy="retry-idempotent"),
    )
    first = executor.execute(CREATE, "reused-model-id")
    second = executor.execute(CREATE, "reused-model-id")
    assert first.content != second.content and len(rows(database)) == 2
    counts = count_retries(recorder.events)
    assert counts.operations == 2 and counts.attempts == 3
    assert counts.fault_activations == 1
    operations = [
        e.data["operation_id"] for e in recorder.events if e.kind == "operation_started"
    ]
    assert len(set(operations)) == 2


def test_invalid_inputs_and_reads_do_not_consume_create_fault(tmp_path: Path) -> None:
    database = tmp_path / "tasks.db"
    recorder = Recorder()
    executor = RetryExecutor(
        TaskStore(database),
        recorder,
        RetryConfig(case="before-write-once", policy="retry-idempotent"),
    )
    for call in (
        ToolCall(name="unknown", arguments={}),
        ToolCall(name="create_task", arguments={"title": " "}),
        ToolCall(
            name="create_task", arguments={"title": TITLE, "operation_id": "model-key"}
        ),
    ):
        assert not executor.execute(call, "invalid").executed
    assert count_retries(recorder.events).attempts == 0
    executor.execute(ToolCall(name="get_task", arguments={"task_id": "absent"}), "read")
    assert not executor.injector.consumed
    executor.execute(CREATE, "create")
    assert count_retries(recorder.events).fault_activations == 1
    assert len(rows(database)) == 1


@pytest.mark.parametrize(
    "failure,code",
    [
        (sqlite3.OperationalError("permanent"), "storage_error"),
        (OperationConflict("conflict"), "operation_conflict"),
    ],
)
def test_permanent_failures_are_not_retried(
    tmp_path: Path, failure: Exception, code: str
) -> None:
    database = tmp_path / "tasks.db"
    recorder = Recorder()
    executor = RetryExecutor(
        TaskStore(database),
        recorder,
        RetryConfig(case="retry-healthy", policy="retry-idempotent"),
    )
    with patch.object(
        executor.store, "create_task_idempotent", side_effect=failure
    ) as create:
        result = executor.execute(CREATE, "call")
    assert create.call_count == 1
    assert json.loads(result.content)["error"]["code"] == code
    assert count_retries(recorder.events).retries == 0
    assert rows(database) == []


def test_malformed_response_is_not_retried(tmp_path: Path) -> None:
    recorder = Recorder()
    executor = RetryExecutor(
        TaskStore(tmp_path / "tasks.db"),
        recorder,
        RetryConfig(case="retry-healthy", policy="retry-idempotent"),
    )
    with patch.object(executor, "_attempt", return_value=b"{broken") as attempt:
        result = executor.execute(CREATE, "call")
    assert attempt.call_count == 1
    assert json.loads(result.content)["error"]["code"] == "invalid_result"
    assert count_retries(recorder.events).contract_errors == 1
    captured = [e for e in recorder.events if e.kind == "response_captured"]
    assert len(captured) == 1


def test_exhaustion_preserves_unknown_reply_and_committed_effect(
    tmp_path: Path,
) -> None:
    database = tmp_path / "tasks.db"
    recorder = Recorder()
    executor = RetryExecutor(
        TaskStore(database),
        recorder,
        RetryConfig(case="retry-healthy", policy="retry-idempotent"),
    )
    original = executor._attempt

    def always_lose(*args: object) -> bytes:
        original(*args)  # type: ignore[arg-type]
        raise DeliveryUnavailable("lost")

    with patch.object(executor, "_attempt", side_effect=always_lose):
        result = executor.execute(CREATE, "call")
    assert json.loads(result.content)["error"]["code"] == "delivery_error"
    assert len(rows(database)) == 1
    counts = count_retries(recorder.events)
    assert counts.attempts == 2 and counts.retries == 1
    assert counts.delivery_errors == 2 and counts.replayed_results == 1


@pytest.mark.parametrize("case", RETRY_CASES)
@pytest.mark.parametrize("control", [False, True])
def test_comparison_reports_are_regenerable_without_database(
    tmp_path: Path, case: RetryCase, control: bool
) -> None:
    output = tmp_path / "comparison"
    args = ["reliability", "compare", case, "--offline", "--output", str(output)]
    if control:
        args.append("--include-control")
    with patch(
        "agent_fault_lab.cli.OllamaClient", side_effect=AssertionError("offline")
    ):
        assert main(args) == 0
    comparison = RetryComparison.model_validate_json(
        (output / "comparison.json").read_text()
    )
    assert len(comparison.entries) == (3 if control else 2)
    for entry in comparison.entries:
        child = output / entry.spec.directory
        before = (child / "report.md").read_bytes()
        for db in child.glob("*.sqlite3"):
            db.unlink()
        assert main(["report", str(child), "--check"]) == 0
        (child / "report.md").unlink()
        assert main(["report", str(child)]) == 0
        assert (child / "report.md").read_bytes() == before
        obs = entry.observation
        if (
            case == "lost-reply-once"
            and entry.spec.config.policy == "retry-unprotected"
        ):
            assert obs.evaluation.task_outcome == "not_completed"
            assert obs.evaluation.false_success is True
            assert (
                obs.evaluation.state.rows is not None
                and len(obs.evaluation.state.rows) == 2
            )
    assert main(["report", str(output), "--check"]) == 0


def test_policy_order_prompt_and_tool_equality(tmp_path: Path) -> None:
    specs = retry_schedule("retry-healthy", 2)
    assert [s.config.policy for s in specs] == [
        "retry-unprotected",
        "retry-idempotent",
        "retry-idempotent",
        "retry-unprotected",
    ]
    clients = [scripted_response_client(TITLE), scripted_response_client(TITLE)]
    requests = []
    for index, client in enumerate(clients):
        with patch.object(client, "complete", wraps=client.complete) as complete:
            _execute(client, tmp_path / str(index), {}, reliability=specs[index].config)
            requests.append(complete.call_args_list[0].args[1:])
    assert clients[0].requests[0] == clients[1].requests[0]
    assert requests[0] == requests[1]


@pytest.mark.parametrize(
    "args",
    [
        ["run", "healthy", "--policy", "retry-idempotent"],
        ["run", "lost-reply-once", "--policy", "validated"],
        ["compare", "healthy", "--include-control"],
    ],
)
def test_incompatible_options_fail_before_preflight(
    tmp_path: Path, args: list[str]
) -> None:
    output = tmp_path / "absent"
    with patch(
        "agent_fault_lab.cli.OllamaClient", side_effect=AssertionError("forbidden")
    ):
        assert main(["reliability", *args, "--live", "--output", str(output)]) == 2
    assert not output.exists()


@pytest.mark.parametrize(
    "failure",
    [
        ProviderError("offline failure"),
        KeyboardInterrupt(),
        RuntimeError("harness failure"),
    ],
)
def test_partial_comparison_preserves_evidence(
    tmp_path: Path, failure: BaseException
) -> None:
    output = tmp_path / "comparison"
    client = ScriptedClient([ModelTurn(content="unused")])
    with (
        patch("agent_fault_lab.cli.scripted_response_client", return_value=client),
        patch.object(client, "complete", side_effect=failure),
    ):
        result = main(
            [
                "reliability",
                "compare",
                "lost-reply-once",
                "--offline",
                "--output",
                str(output),
            ]
        )
    assert result in {2, 130}
    comparison = RetryComparison.model_validate_json(
        (output / "comparison.json").read_text()
    )
    assert comparison.status != "finished"
    if isinstance(failure, ProviderError):
        assert len(comparison.entries) == 1
        assert comparison.entries[0].observation.retry.fault_activations == 0
    else:
        assert comparison.partial_directory == comparison.planned[0].directory
    assert main(["report", str(output), "--check"]) == 0


@pytest.mark.parametrize("corruption", ["version", "counts"])
def test_corrupt_artifact_is_rejected_without_overwriting_report(
    tmp_path: Path, corruption: str
) -> None:
    output = tmp_path / "run"
    obs = _execute(
        scripted_response_client(TITLE),
        output,
        {},
        reliability=RetryConfig(case="lost-reply-once", policy="retry-idempotent"),
    )
    data = obs.model_dump(mode="json")
    if corruption == "version":
        data["schema_version"] = True
    else:
        data["retry"]["attempts"] += 1
    with pytest.raises(ValidationError):
        RetryObservation.model_validate(data)
    (output / "observation.json").write_text(json.dumps(data))
    before = (output / "report.md").read_bytes()
    assert main(["report", str(output)]) == 2
    assert (output / "report.md").read_bytes() == before
