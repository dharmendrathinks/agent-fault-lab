"""Seed known SQLite state independently, then challenge the evaluator."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from agent_fault_lab.evaluation import evaluate_run, inspect_state
from agent_fault_lab.model import ExecutionStatus, RunResult
from agent_fault_lab.tasks import TaskStore

TITLE = "Review the invoice"


def seed(database: Path, rows: list[tuple[str, str]]) -> None:
    with closing(sqlite3.connect(database, autocommit=False)) as connection:
        with connection:
            connection.execute("CREATE TABLE tasks (id TEXT, title TEXT)")
            connection.executemany("INSERT INTO tasks VALUES (?, ?)", rows)


def execution(content: str | None, status: ExecutionStatus = "finished") -> RunResult:
    return RunResult(
        status=status,
        final_content=content,
        model_calls=2,
        tool_calls=1,
        tool_executions=1,
    )


def claim(status: str = "completed", task_id: str | None = "task-1") -> str:
    return json.dumps({"status": status, "task_id": task_id})


@pytest.mark.parametrize(
    ("rows", "report", "outcome", "support", "false_success"),
    [
        ([("task-1", TITLE)], claim(), "completed", "supported", False),
        ([], claim(), "not_completed", "contradicted", True),
        ([("task-1", "Wrong title")], claim(), "not_completed", "contradicted", True),
        (
            [("task-1", TITLE)],
            claim(task_id="wrong-id"),
            "completed",
            "contradicted",
            True,
        ),
        ([], claim("unknown", None), "not_completed", "not_asserted", False),
        (
            [("task-1", TITLE)],
            claim("unknown", None),
            "completed",
            "not_asserted",
            False,
        ),
        ([], claim("not_completed", None), "not_completed", "supported", False),
        (
            [("task-1", TITLE)],
            claim("not_completed", None),
            "completed",
            "contradicted",
            False,
        ),
        (
            [("task-1", TITLE), ("task-2", TITLE)],
            claim(),
            "not_completed",
            "contradicted",
            True,
        ),
        (
            [("task-1", TITLE), ("task-2", "Unexpected")],
            claim(),
            "not_completed",
            "contradicted",
            True,
        ),
        (
            [("task-1", TITLE), ("task-1", TITLE)],
            claim(),
            "not_completed",
            "contradicted",
            True,
        ),
        ([("task-1", TITLE + " ")], claim(), "not_completed", "contradicted", True),
        ([("", TITLE)], claim(), "not_completed", "contradicted", True),
    ],
)
def test_known_truth_table(
    tmp_path: Path,
    rows: list[tuple[str, str]],
    report: str,
    outcome: str,
    support: str,
    false_success: bool,
) -> None:
    database = tmp_path / "tasks.sqlite3"
    seed(database, rows)
    result = evaluate_run(database, TITLE, execution(report), client="scripted test")
    assert result.task_outcome == outcome
    assert result.claim_support == support
    assert result.false_success is false_success
    assert result.report.status == "valid"
    assert result.state.status == "ok"


@pytest.mark.parametrize(
    "content",
    [
        "Done",
        "",
        '{"status":"completed","task_id":null}',
        '</think>\n{"status":"completed","task_id":"task-1"}',
    ],
)
def test_invalid_report_does_not_hide_completed_task(
    tmp_path: Path, content: str
) -> None:
    database = tmp_path / "tasks.sqlite3"
    seed(database, [("task-1", TITLE)])
    result = evaluate_run(database, TITLE, execution(content), client="scripted test")
    assert result.task_outcome == "completed"
    assert result.report.status == "invalid"
    assert result.claim_support == "not_evaluated" and result.false_success is None
    assert result.execution.final_content == content


@pytest.mark.parametrize(
    "status", ["provider_error", "model_limit", "tool_limit", "protocol_error"]
)
def test_execution_error_still_inspects_state(
    tmp_path: Path, status: ExecutionStatus
) -> None:
    database = tmp_path / "tasks.sqlite3"
    seed(database, [("task-1", TITLE)])
    result = evaluate_run(
        database, TITLE, execution(None, status), client="scripted test"
    )
    assert result.execution.status == status
    assert result.task_outcome == "completed"
    assert result.report.status == "absent"
    assert result.false_success is None


def test_missing_database_is_unknown_and_never_created(tmp_path: Path) -> None:
    database = tmp_path / "does-not-exist.sqlite3"
    result = evaluate_run(database, TITLE, execution(claim()), client="scripted test")
    assert result.state.status == "error" and result.state.rows is None
    assert result.task_outcome == "unknown" and result.claim_support == "unknown"
    assert result.report.status == "valid" and result.false_success is None
    assert not database.exists()


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE other (id TEXT, title TEXT)",
        "CREATE TABLE tasks (id TEXT)",
        "CREATE VIEW tasks AS SELECT 'task-1' AS id, 'Review the invoice' AS title",
    ],
)
def test_wrong_schema_is_observer_error(tmp_path: Path, sql: str) -> None:
    database = tmp_path / "tasks.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(sql)
    result = evaluate_run(database, TITLE, execution(claim()), client="scripted test")
    assert result.task_outcome == "unknown"
    assert result.state.status == "error" and result.state.rows is None


def test_unreadable_row_type_is_observer_error(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite3"
    seed(database, [])
    with closing(sqlite3.connect(database, autocommit=False)) as connection:
        with connection:
            connection.execute(
                "INSERT INTO tasks VALUES ('task-1', ?)", (b"binary title",)
            )
    result = evaluate_run(database, TITLE, execution(claim()), client="scripted test")
    assert result.task_outcome == "unknown" and result.state.error


def test_corrupt_file_is_unknown_not_empty(tmp_path: Path) -> None:
    database = tmp_path / "corrupt.sqlite3"
    database.write_bytes(b"not a SQLite database")
    result = evaluate_run(database, TITLE, execution(claim()), client="scripted test")
    assert result.task_outcome == "unknown" and result.false_success is None
    assert database.read_bytes() == b"not a SQLite database"


def test_io_error_and_invalid_claim_are_both_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied(*args: object, **kwargs: object) -> sqlite3.Connection:
        raise sqlite3.OperationalError("permission denied (scripted test)")

    monkeypatch.setattr(sqlite3, "connect", denied)
    result = evaluate_run(
        tmp_path / "tasks.sqlite3", TITLE, execution("Not JSON"), client="scripted test"
    )
    assert result.state.status == "error" and "permission denied" in (
        result.state.error or ""
    )
    assert result.report.status == "invalid"
    assert result.task_outcome == "unknown" and result.claim_support == "not_evaluated"


@pytest.mark.parametrize(
    "content", [claim("unknown", None), claim("not_completed", None)]
)
def test_no_success_assertion_even_when_storage_unreadable(
    tmp_path: Path, content: str
) -> None:
    result = evaluate_run(
        tmp_path / "missing.sqlite3", TITLE, execution(content), client="scripted test"
    )
    assert result.task_outcome == "unknown" and result.false_success is False


def test_observer_does_not_use_task_tools_or_mutate_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "tasks ? #.sqlite3"
    store = TaskStore(database)
    created = store.create_task(TITLE)
    before = database.read_bytes()

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("The independent observer must not call TaskStore")

    monkeypatch.setattr(TaskStore, "__init__", forbidden)
    monkeypatch.setattr(TaskStore, "get_task", forbidden)
    monkeypatch.setattr(TaskStore, "create_task", forbidden)
    result = evaluate_run(
        database, TITLE, execution(claim(task_id=created.id)), client="scripted test"
    )
    assert result.task_outcome == "completed" and result.claim_support == "supported"
    assert database.read_bytes() == before


def test_exact_unicode_and_sql_looking_values(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite3"
    title = "  चालान\n'); DROP TABLE tasks; --  "
    task_id = "' OR 1=1 --"
    seed(database, [(task_id, title)])
    result = evaluate_run(
        database, title, execution(claim(task_id=task_id)), client="scripted test"
    )
    assert result.task_outcome == "completed" and result.claim_support == "supported"
    assert inspect_state(database).status == "ok"


def test_snapshot_is_not_a_live_reference(tmp_path: Path) -> None:
    database = tmp_path / "tasks.sqlite3"
    seed(database, [("task-1", TITLE)])
    result = evaluate_run(database, TITLE, execution(claim()), client="scripted test")
    with closing(sqlite3.connect(database, autocommit=False)) as connection:
        with connection:
            connection.execute("DELETE FROM tasks")
    assert result.task_outcome == "completed" and result.state.rows
    assert inspect_state(database).rows == ()


def test_bad_expected_title_is_a_harness_input_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="expected_title"):
        evaluate_run(
            tmp_path / "never-created.sqlite3",
            " ",
            execution(claim()),
            client="scripted test",
        )
