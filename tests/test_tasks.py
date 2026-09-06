"""Check real SQLite state rather than merely trusting a returned Task object."""

import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import UUID

import pytest

from agent_fault_lab import Task, TaskStore


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return tmp_path / "tasks.sqlite3"


@pytest.fixture
def store(database: Path) -> TaskStore:
    return TaskStore(database)


def read_rows(database: Path) -> list[tuple[str, str]]:
    """Inspect committed state using a separate, read-only SQLite connection."""
    with closing(
        sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
    ) as connection:
        return [
            (row[0], row[1])
            for row in connection.execute("SELECT id, title FROM tasks")
        ]


def test_create_and_retrieve(store: TaskStore, database: Path) -> None:
    created = store.create_task("Review the invoice")

    assert isinstance(created, Task)
    assert UUID(created.id).version == 4
    assert store.get_task(created.id) == created
    assert read_rows(database) == [(created.id, "Review the invoice")]


@pytest.mark.parametrize(
    "title",
    [
        "Review the invoice",
        "  Keep these spaces  ",
        "First line\nSecond line\t",
        "चालान की समीक्षा करें — café",
        "Review O'Reilly's invoice",
        "'); DROP TABLE tasks; --",
    ],
)
def test_preserves_title_exactly(store: TaskStore, database: Path, title: str) -> None:
    created = store.create_task(title)

    assert store.get_task(created.id) == Task(id=created.id, title=title)
    assert read_rows(database) == [(created.id, title)]


@pytest.mark.parametrize("title", ["", " ", "\t\n", "\u2003"])
def test_rejects_blank_title_without_writing(
    store: TaskStore, database: Path, title: str
) -> None:
    with pytest.raises(ValueError, match="title must not be empty"):
        store.create_task(title)

    assert read_rows(database) == []


@pytest.mark.parametrize("title", [None, 42, False, [], {}, b"Review the invoice"])
def test_rejects_non_string_title_without_writing(
    store: TaskStore, database: Path, title: object
) -> None:
    with pytest.raises(TypeError, match="title must be a string"):
        # Runtime validation must also protect callers that do not use typing.
        store.create_task(title)  # type: ignore[arg-type]

    assert read_rows(database) == []


def test_rejects_missing_title_without_writing(
    store: TaskStore, database: Path
) -> None:
    with pytest.raises(TypeError):
        store.create_task()  # type: ignore[call-arg]

    assert read_rows(database) == []


def test_unknown_id_returns_none(store: TaskStore) -> None:
    assert store.get_task("unknown-task-id") is None


@pytest.mark.parametrize("task_id", ["", " ", "\t\n"])
def test_rejects_blank_lookup_id(store: TaskStore, task_id: str) -> None:
    with pytest.raises(ValueError, match="task_id must not be empty"):
        store.get_task(task_id)


@pytest.mark.parametrize("task_id", [None, 42, False])
def test_rejects_non_string_lookup_id(store: TaskStore, task_id: object) -> None:
    with pytest.raises(TypeError, match="task_id must be a string"):
        store.get_task(task_id)  # type: ignore[arg-type]


def test_lookup_id_is_not_interpreted_as_sql(store: TaskStore) -> None:
    created = store.create_task("Keep this task")

    assert store.get_task("' OR 1=1 --") is None
    assert store.get_task(created.id) == created


def test_reopening_database_preserves_tasks(store: TaskStore, database: Path) -> None:
    created = store.create_task("Review the invoice")

    reopened = TaskStore(database)

    assert reopened.get_task(created.id) == created
    assert read_rows(database) == [(created.id, created.title)]


def test_separate_databases_are_isolated(store: TaskStore, tmp_path: Path) -> None:
    other_database = tmp_path / "other.sqlite3"
    other = TaskStore(other_database)
    first_task = store.create_task("First experiment")
    other_task = other.create_task("Second experiment")

    assert other.get_task(first_task.id) is None
    assert store.get_task(other_task.id) is None
    assert read_rows(other_database) == [(other_task.id, other_task.title)]


def test_same_title_creates_distinct_tasks(store: TaskStore, database: Path) -> None:
    first = store.create_task("Repeated request")
    second = store.create_task("Repeated request")

    assert first.id != second.id
    assert set(read_rows(database)) == {
        (first.id, first.title),
        (second.id, second.title),
    }


def test_insert_failure_is_not_returned_as_success(
    store: TaskStore, database: Path
) -> None:
    original = store.create_task("Already saved")
    with closing(sqlite3.connect(database, autocommit=False)) as connection:
        with connection:
            connection.execute(
                "CREATE TRIGGER reject_insert BEFORE INSERT ON tasks "
                "BEGIN SELECT RAISE(ABORT, 'test write rejected'); END"
            )

    with pytest.raises(sqlite3.IntegrityError, match="test write rejected"):
        store.create_task("Must not report success")

    assert read_rows(database) == [(original.id, original.title)]


def test_missing_parent_directory_is_not_created(tmp_path: Path) -> None:
    parent = tmp_path / "missing"

    with pytest.raises(sqlite3.OperationalError):
        TaskStore(parent / "tasks.sqlite3")

    assert not parent.exists()


def test_missing_database_is_not_silently_recreated(
    store: TaskStore, database: Path
) -> None:
    created = store.create_task("A task in a database that will be moved")
    moved = database.with_name("moved.sqlite3")
    database.rename(moved)

    with pytest.raises(sqlite3.OperationalError):
        store.get_task(created.id)
    with pytest.raises(sqlite3.OperationalError):
        store.create_task("Do not create an empty replacement database")

    assert not database.exists()
    assert read_rows(moved) == [(created.id, created.title)]
