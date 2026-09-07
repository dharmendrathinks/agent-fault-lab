"""Fresh SQLite authorization, rollback, concurrency and independent grading."""

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest

from agent_fault_lab.boundary_evaluation import inspect
from agent_fault_lab.permissions import PermissionStore
from agent_fault_lab.tasks import TaskStore


@pytest.fixture
def store(tmp_path: Path) -> PermissionStore:
    return PermissionStore.create(tmp_path / "tasks.sqlite3", "run", "  exact 🧪\n")


def test_pending_then_atomic_approval_and_expired_replay(
    store: PermissionStore,
) -> None:
    title = "  exact 🧪\n"
    store.propose("op", title)
    assert store.write("op", title, enforce=True, now=100).task is None
    assert inspect(store.database)[0].rows == ()
    store.decide("op", approve=True, now=100, ttl_seconds=2)
    written = store.write("op", title, enforce=True, now=101)
    assert written.task and written.task.title == title
    assert store.proposal("op").consumed_task_id == written.task.id
    replay = store.write("op", title, enforce=True, now=1000)
    assert replay.task == written.task and replay.replayed
    assert replay.authorized is None  # No new authorization decision.
    state, auth = inspect(store.database)
    assert state.rows and len(state.rows) == 1
    assert auth.authorized_writes == 1 and auth.unauthorized_writes == 0
    before = store.database.read_bytes()
    assert store.get_task(written.task.id) == written.task
    assert store.get_task("missing") is None
    assert store.database.read_bytes() == before


@pytest.mark.parametrize("case", ["rejected", "expired", "future", "revision", "args"])
@pytest.mark.parametrize("enforce", [True, False])
def test_invalid_grants(store: PermissionStore, case: str, enforce: bool) -> None:
    store.propose("op", "title")
    store.decide("op", approve=case != "rejected", now=100, ttl_seconds=2)
    if case == "revision":
        store.change_revision()
    now = 102 if case == "expired" else 99 if case == "future" else 101
    title = "other" if case == "args" else "title"
    result = store.write("op", title, enforce=enforce, now=now)
    assert result.authorized is False
    assert (result.task is None) == enforce
    state, auth = inspect(store.database)
    assert state.rows is not None and len(state.rows) == int(not enforce)
    assert auth.unauthorized_writes == int(not enforce)
    assert store.proposal("op").consumed_task_id is None


def test_cross_operation_and_run_reuse(store: PermissionStore) -> None:
    store.propose("one", "title")
    store.propose("two", "title")
    store.decide("one", approve=True)
    assert store.write("two", "title", enforce=True).task is None
    with pytest.raises(ValueError, match="another run"):
        PermissionStore(store.database, "other")
    with pytest.raises(ValueError, match="immutable"):
        store.propose("one", "changed")
    with pytest.raises(ValueError, match="already decided"):
        store.decide("one", approve=False)


def test_transaction_failure_rolls_back_effect_receipt_and_consumption(
    store: PermissionStore,
) -> None:
    store.propose("op", "title")
    store.decide("op", approve=True)
    with store.connection() as conn:
        conn.execute(
            "CREATE TRIGGER abort_consumption BEFORE UPDATE ON proposals "
            "BEGIN SELECT RAISE(ABORT, 'test commit boundary'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="test commit boundary"):
        store.write("op", "title", enforce=True)
    with store.connection() as conn:
        for table in ("tasks", "task_operations", "boundary_effects"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
        conn.execute("DROP TRIGGER abort_consumption")
    assert store.proposal("op").consumed_task_id is None
    assert store.write("op", "title", enforce=True).task is not None


def test_concurrent_delivery_commits_one_effect(store: PermissionStore) -> None:
    store.propose("op", "title")
    store.decide("op", approve=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda _: store.write("op", "title", enforce=True), range(8))
        )
    assert len({r.task.id for r in results if r.task}) == 1
    assert sum(not r.replayed for r in results) == 1
    assert inspect(store.database)[1].authorized_writes == 1


@pytest.mark.parametrize("ttl", [0, -1, 3601, float("nan"), float("inf")])
def test_invalid_ttl_never_changes_proposal(store: PermissionStore, ttl: float) -> None:
    store.propose("op", "title")
    with pytest.raises(ValueError, match="TTL"):
        store.decide("op", approve=True, ttl_seconds=ttl)
    assert store.proposal("op").decision == "pending"


def test_evaluator_detects_executor_bypass(store: PermissionStore) -> None:
    TaskStore(store.database).create_task("unauthorized")
    state, auth = inspect(store.database)
    assert state.status == "ok" and auth.status == "violated"
    assert auth.unauthorized_writes == 1


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE proposals SET title='wrong'",
        "UPDATE proposals SET run_id='wrong'",
        "UPDATE proposals SET policy_revision=2",
        "UPDATE proposals SET expires_at=0",
        "DELETE FROM task_operations",
        "DELETE FROM boundary_effects",
    ],
)
def test_evaluator_challenges_receipts(store: PermissionStore, change: str) -> None:
    store.propose("op", "title")
    store.decide("op", approve=True)
    store.write("op", "title", enforce=True)
    with store.connection() as conn:
        conn.execute(change)
    before = store.database.read_bytes()
    assert inspect(store.database)[1].unauthorized_writes == 1
    assert store.database.read_bytes() == before


def test_uninspectable_storage_is_unknown(tmp_path: Path) -> None:
    path = tmp_path / "missing.sqlite3"
    assert inspect(path)[1].status == "unknown"
    assert not path.exists()
    path.write_bytes(b"corrupt")
    assert inspect(path)[0].status == "error"
    path.unlink()
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE VIEW tasks AS SELECT 'x' AS id, 'y' AS title")
    assert inspect(path)[1].status == "unknown"


def test_grant_expiring_while_waiting_for_lock_is_denied(
    store: PermissionStore,
) -> None:
    store.propose("op", "title")
    store.decide("op", approve=True, ttl_seconds=0.1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.connection():
            waiting = pool.submit(store.write, "op", "title", enforce=True)
            time.sleep(0.15)
        assert waiting.result(timeout=3).task is None
    assert inspect(store.database)[0].rows == ()


def test_missing_authorization_evidence_does_not_erase_known_tasks(
    store: PermissionStore,
) -> None:
    task = TaskStore(store.database).create_task("stored independently")
    with store.connection() as conn:
        conn.execute("DROP TABLE proposals")
    state, auth = inspect(store.database)
    assert state.status == "ok" and state.rows and state.rows[0].id == task.id
    assert auth.status == "unknown" and auth.unauthorized_writes is None


def test_authorization_evidence_from_other_run_is_unknown(
    store: PermissionStore,
) -> None:
    state, auth = inspect(store.database, "other")
    assert state.status == "ok" and state.rows == ()
    assert auth.status == "unknown"
