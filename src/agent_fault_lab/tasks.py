"""M01: a file-backed task store, without an agent or any model dependencies."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class Task:
    """A snapshot of a stored task, not a live reference to the database."""

    id: str
    title: str


class TaskStore:
    """Bind two ordinary functions to one SQLite file.

    The parent directory must already exist. Reopening the same file preserves
    its tasks; callers must choose a fresh file for an isolated experiment.
    Connections are short-lived and always closed, even when an operation fails.
    """

    def __init__(self, database: Path) -> None:
        self._database = database.resolve()
        with self._connection(create=True) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS tasks ("
                "id TEXT PRIMARY KEY NOT NULL, title TEXT NOT NULL)"
            )

    def create_task(self, title: str) -> Task:
        """Persist a new task; return only after its transaction commits.

        Non-string values raise TypeError. Empty or whitespace-only strings raise
        ValueError. Valid titles are saved exactly as supplied. SQLite failures
        propagate to the caller instead of being converted to a success result.
        Repeated calls create distinct tasks: retry safety is not implemented yet.
        """
        _require_nonblank_string(title, "title")
        task = Task(id=str(uuid4()), title=title)
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO tasks (id, title) VALUES (?, ?)", (task.id, task.title)
            )
        return task

    def get_task(self, task_id: str) -> Task | None:
        """Read a task from storage; None explicitly means the ID was not found."""
        _require_nonblank_string(task_id, "task_id")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT id, title FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        if row is None:
            return None
        return Task(id=row[0], title=row[1])

    @contextmanager
    def _connection(self, *, create: bool = False) -> Iterator[sqlite3.Connection]:
        # A connection's context manager commits/rolls back, but does NOT close
        # it. closing() handles that separate responsibility on every exit path.
        # Only initialization may create the file. A vanished database is an
        # error, not a reason for an ordinary read/write to create an empty one.
        mode = "rwc" if create else "rw"
        uri = f"{self._database.as_uri()}?mode={mode}"
        with closing(sqlite3.connect(uri, uri=True, autocommit=False)) as connection:
            with connection:
                yield connection


def _require_nonblank_string(value: str, name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value.strip():
        raise ValueError(f"{name} must not be empty or whitespace-only")
