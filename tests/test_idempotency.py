"""Atomic effects and durable operation identity, inspected outside the tools."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_fault_lab.tasks import OperationConflict, TaskStore


def rows(database: Path, table: str = "tasks") -> list[tuple[str, ...]]:
    assert table in {"tasks", "task_operations", "sqlite_master"}
    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as conn:
        return conn.execute(f"SELECT * FROM {table}").fetchall()


def test_replay_is_durable_and_preserves_exact_arguments(tmp_path: Path) -> None:
    database = tmp_path / "tasks.db"
    store = TaskStore(database)
    title = "  café\nचालान\t"
    original = store.create_task_idempotent(title, " operation ")
    replay = TaskStore(database).create_task_idempotent(title, " operation ")
    assert not original.replayed and replay.replayed
    assert original.task == replay.task
    assert rows(database) == [(original.task.id, title)]
    assert rows(database, "task_operations") == [
        (" operation ", title, original.task.id)
    ]


def test_identity_is_key_not_title(tmp_path: Path) -> None:
    database = tmp_path / "tasks.db"
    store = TaskStore(database)
    first = store.create_task_idempotent("same", "key")
    with pytest.raises(OperationConflict):
        store.create_task_idempotent("same ", "key")
    assert rows(database) == [(first.task.id, "same")]
    second = store.create_task_idempotent("same", "key ")
    assert first.task.id != second.task.id
    assert len(rows(database)) == len(rows(database, "task_operations")) == 2


@pytest.mark.parametrize("value", ["", " ", None, 42, False])
@pytest.mark.parametrize("argument", ["title", "operation_id"])
def test_invalid_input_does_not_initialize_ledger(
    tmp_path: Path, value: object, argument: str
) -> None:
    database = tmp_path / "tasks.db"
    store = TaskStore(database)
    args = {"title": "valid", "operation_id": "key"}
    args[argument] = value  # type: ignore[assignment]
    with pytest.raises((TypeError, ValueError)):
        store.create_task_idempotent(**args)
    assert rows(database) == []
    assert not any(
        row[1] == "task_operations" for row in rows(database, "sqlite_master")
    )


@pytest.mark.parametrize("table", ["tasks", "task_operations"])
def test_insert_failure_rolls_back_task_and_ledger(tmp_path: Path, table: str) -> None:
    database = tmp_path / "tasks.db"
    store = TaskStore(database)
    store.create_task_idempotent("existing", "old-key")
    before = rows(database), rows(database, "task_operations")
    with closing(sqlite3.connect(database, autocommit=False)) as conn:
        with conn:
            conn.execute(
                f"CREATE TRIGGER reject_insert BEFORE INSERT ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'rejected'); END"
            )
    with pytest.raises(sqlite3.IntegrityError, match="rejected"):
        store.create_task_idempotent("new", "new-key")
    assert (rows(database), rows(database, "task_operations")) == before


def test_concurrent_same_key_has_one_effect(tmp_path: Path) -> None:
    database = tmp_path / "tasks.db"
    store = TaskStore(database)
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(
            pool.map(lambda _: store.create_task_idempotent("same", "key"), range(8))
        )
    assert len({receipt.task.id for receipt in receipts}) == 1
    assert sum(not receipt.replayed for receipt in receipts) == 1
    assert len(rows(database)) == len(rows(database, "task_operations")) == 1


def test_commit_failure_never_returns_success_and_rolls_back(tmp_path: Path) -> None:
    database = tmp_path / "tasks.db"
    store = TaskStore(database)
    connect = sqlite3.connect

    def no_wait(
        database_uri: str, *, uri: bool, autocommit: bool
    ) -> sqlite3.Connection:
        return connect(database_uri, timeout=0, uri=uri, autocommit=autocommit)

    # In the default rollback-journal mode a reader permits BEGIN IMMEDIATE and
    # inserts, but prevents the writer's COMMIT until its read transaction ends.
    with closing(connect(database, autocommit=False)) as reader:
        assert reader.execute("SELECT * FROM tasks").fetchall() == []
        with patch("agent_fault_lab.tasks.sqlite3.connect", side_effect=no_wait):
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                store.create_task_idempotent("new", "key")
    assert rows(database) == []
    assert not any(
        row[1] == "task_operations" for row in rows(database, "sqlite_master")
    )
    assert not store.create_task_idempotent("new", "key").replayed


def test_missing_database_does_not_get_recreated(tmp_path: Path) -> None:
    database = tmp_path / "tasks.db"
    store = TaskStore(database)
    database.rename(tmp_path / "moved.db")
    with pytest.raises(sqlite3.OperationalError):
        store.create_task_idempotent("new", "key")
    assert not database.exists()


def test_ordinary_calls_do_not_create_ledger(tmp_path: Path) -> None:
    database = tmp_path / "tasks.db"
    store = TaskStore(database)
    assert store.create_task("same") != store.create_task("same")
    assert not any(
        row[1] == "task_operations" for row in rows(database, "sqlite_master")
    )
