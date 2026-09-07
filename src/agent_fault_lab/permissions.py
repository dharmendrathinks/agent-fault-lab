"""SQLite authorization and task effects, independent of any agent or scanner."""

import math
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from agent_fault_lab.model import Record
from agent_fault_lab.tasks import Task, TaskStore, _require_nonblank_string


def regular(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Task database must be an existing regular file")


class Proposal(Record):
    run_id: str
    operation_id: str
    title: str
    request_revision: int
    policy_revision: int
    decision: Literal["pending", "approved", "rejected"]
    granted_at: float | None
    expires_at: float | None
    consumed_task_id: str | None


@dataclass(frozen=True)
class WriteDecision:
    task: Task | None
    authorized: bool | None
    replayed: bool
    reason: str


class PermissionStore:
    def __init__(self, database: Path, run_id: str) -> None:
        regular(database)
        self.database = database.resolve()
        self.run_id = run_id
        with self.connection() as conn:
            row = conn.execute("SELECT run_id FROM boundary_authority").fetchone()
            if row != (run_id,):
                raise ValueError("Authorization database belongs to another run")

    @classmethod
    def create(
        cls, database: Path, run_id: str, expected_title: str
    ) -> "PermissionStore":
        if database.exists() or database.is_symlink():
            raise FileExistsError(database)
        _require_nonblank_string(run_id, "run_id")
        _require_nonblank_string(expected_title, "expected_title")
        TaskStore(database)
        with closing(sqlite3.connect(database)) as conn, conn:
            conn.executescript(
                "CREATE TABLE boundary_authority (run_id TEXT PRIMARY KEY, "
                "expected_title TEXT NOT NULL, request_revision INTEGER NOT NULL, "
                "policy_revision INTEGER NOT NULL);"
                "CREATE TABLE proposals (run_id TEXT NOT NULL, "
                "operation_id TEXT PRIMARY KEY, "
                "title TEXT NOT NULL, request_revision INTEGER NOT NULL, "
                "policy_revision INTEGER NOT NULL, decision TEXT NOT NULL "
                "CHECK(decision IN ('pending','approved','rejected')), "
                "granted_at REAL, expires_at REAL, consumed_task_id TEXT UNIQUE);"
                "CREATE TABLE task_operations (operation_id TEXT PRIMARY KEY, "
                "title TEXT NOT NULL, task_id TEXT UNIQUE NOT NULL);"
                "CREATE TABLE boundary_effects (operation_id TEXT PRIMARY KEY, "
                "run_id TEXT NOT NULL, task_id TEXT UNIQUE NOT NULL, "
                "title TEXT NOT NULL, "
                "admitted_at REAL NOT NULL, request_revision INTEGER NOT NULL, "
                "policy_revision INTEGER NOT NULL);"
            )
            conn.execute(
                "INSERT INTO boundary_authority VALUES (?, ?, 1, 1)",
                (run_id, expected_title),
            )
        return cls(database, run_id)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        regular(self.database)
        with closing(
            sqlite3.connect(
                f"{self.database.as_uri()}?mode=rw",
                uri=True,
                autocommit=True,
            )
        ) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    @staticmethod
    def _proposal(conn: sqlite3.Connection, operation_id: str) -> Proposal:
        cursor = conn.execute(
            "SELECT * FROM proposals WHERE operation_id=?", (operation_id,)
        )
        row = cursor.fetchone()
        if row is None:
            raise ValueError("Unknown approval proposal")
        return Proposal.model_validate(
            dict(zip((c[0] for c in cursor.description), row, strict=True))
        )

    def propose(self, operation_id: str, title: str) -> Proposal:
        _require_nonblank_string(operation_id, "operation_id")
        _require_nonblank_string(title, "title")
        with self.connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM proposals WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if exists:
                proposal = self._proposal(conn, operation_id)
                if proposal.run_id != self.run_id or proposal.title != title:
                    raise ValueError("Operation proposal is immutable")
                return proposal
            revision = conn.execute(
                "SELECT request_revision,policy_revision "
                "FROM boundary_authority WHERE run_id=?",
                (self.run_id,),
            ).fetchone()
            if revision is None:
                raise ValueError("Run authority disappeared")
            conn.execute(
                "INSERT INTO proposals VALUES (?,?,?,?,?,'pending',NULL,NULL,NULL)",
                (self.run_id, operation_id, title, *revision),
            )
            return self._proposal(conn, operation_id)

    def proposal(self, operation_id: str) -> Proposal:
        with self.connection() as conn:
            return self._proposal(conn, operation_id)

    def decide(
        self,
        operation_id: str,
        *,
        approve: bool,
        ttl_seconds: float = 300,
        now: float | None = None,
    ) -> Proposal:
        now = time.time() if now is None else now
        if (
            not math.isfinite(now)
            or not math.isfinite(ttl_seconds)
            or not 0 < ttl_seconds <= 3600
        ):
            raise ValueError("Approval TTL must be positive and at most 3600 seconds")
        with self.connection() as conn:
            proposal = self._proposal(conn, operation_id)
            if proposal.run_id != self.run_id or proposal.decision != "pending":
                raise ValueError("Proposal is foreign or already decided")
            conn.execute(
                "UPDATE proposals SET decision=?,granted_at=?,expires_at=? "
                "WHERE operation_id=?",
                (
                    "approved" if approve else "rejected",
                    now if approve else None,
                    now + ttl_seconds if approve else None,
                    operation_id,
                ),
            )
            return self._proposal(conn, operation_id)

    def change_revision(self) -> None:
        """Trusted M11 scenario controller; not a model-facing operation."""
        with self.connection() as conn:
            conn.execute(
                "UPDATE boundary_authority SET policy_revision=policy_revision+1"
            )

    def write(
        self,
        operation_id: str,
        title: str,
        *,
        enforce: bool,
        now: float | None = None,
    ) -> WriteDecision:
        _require_nonblank_string(title, "title")
        if now is not None and not math.isfinite(now):
            raise ValueError("Admission time must be finite")
        with self.connection() as conn:
            # Lock acquisition can outlast a grant. Measure admission after it.
            now = time.time() if now is None else now
            # A committed receipt is authoritative even when its grant has expired.
            receipt = conn.execute(
                "SELECT title,task_id FROM task_operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if receipt is not None:
                if receipt[0] != title:
                    raise ValueError("Committed operation arguments cannot change")
                return WriteDecision(
                    Task(receipt[1], title), None, True, "committed replay"
                )
            proposal = self._proposal(conn, operation_id)
            revision = conn.execute(
                "SELECT request_revision,policy_revision "
                "FROM boundary_authority WHERE run_id=?",
                (self.run_id,),
            ).fetchone()
            if revision is None:
                raise ValueError("Run authority disappeared")
            reason = "approved"
            if proposal.run_id != self.run_id or proposal.title != title:
                reason = "proposal does not match the operation"
            elif (proposal.request_revision, proposal.policy_revision) != revision:
                reason = "request or policy revision changed"
            elif proposal.decision != "approved":
                reason = f"approval {proposal.decision}"
            elif proposal.granted_at is None or proposal.expires_at is None:
                reason = "approval is missing its validity interval"
            elif not proposal.granted_at <= now < proposal.expires_at:
                reason = "approval expired or not yet valid"
            elif proposal.consumed_task_id is not None:
                reason = "approval already consumed"
            if (
                reason == "approved"
                and conn.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE name='request_policy' AND type='table'"
                ).fetchone()
            ):
                policy = conn.execute(
                    "SELECT p.write_allowed,a.expected_title FROM request_policy p "
                    "CROSS JOIN boundary_authority a"
                ).fetchall()
                if len(policy) != 1 or policy[0][0] not in (0, 1):
                    raise ValueError("Invalid authoritative request policy")
                already_created = conn.execute(
                    "SELECT count(*) FROM tasks WHERE title=?", (policy[0][1],)
                ).fetchone()[0]
                if policy[0][0] != 1 or title != policy[0][1] or already_created:
                    reason = "operation is outside the current request scope"
            authorized = reason == "approved"
            if enforce and not authorized:
                return WriteDecision(None, False, False, reason)
            task = Task(str(uuid4()), title)
            conn.execute("INSERT INTO tasks VALUES (?,?)", (task.id, title))
            conn.execute(
                "INSERT INTO task_operations VALUES (?,?,?)",
                (operation_id, title, task.id),
            )
            conn.execute(
                "INSERT INTO boundary_effects VALUES (?,?,?,?,?,?,?)",
                (operation_id, self.run_id, task.id, title, now, *revision),
            )
            if authorized:
                conn.execute(
                    "UPDATE proposals SET consumed_task_id=? WHERE operation_id=?",
                    (task.id, operation_id),
                )
            return WriteDecision(task, authorized, False, reason)

    def get_task(self, task_id: str) -> Task | None:
        _require_nonblank_string(task_id, "task_id")
        regular(self.database)
        with closing(
            sqlite3.connect(f"{self.database.as_uri()}?mode=ro", uri=True)
        ) as conn:
            row = conn.execute(
                "SELECT id,title FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
        return Task(*row) if row else None

    def configure_request(
        self, title: str, *, write_allowed: bool, revision: int
    ) -> None:
        """Trusted scenario setup; never exposed as a model tool."""
        _require_nonblank_string(title, "title")
        with self.connection() as conn:
            conn.execute("CREATE TABLE request_policy (write_allowed INTEGER NOT NULL)")
            conn.execute("INSERT INTO request_policy VALUES (?)", (int(write_allowed),))
            conn.execute(
                "UPDATE boundary_authority SET expected_title=?,request_revision=?,"
                "policy_revision=?",
                (title, revision, revision),
            )

    def request_state(self) -> dict[str, str | int | bool]:
        regular(self.database)
        with closing(
            sqlite3.connect(f"{self.database.as_uri()}?mode=ro", uri=True)
        ) as conn:
            row = conn.execute(
                "SELECT expected_title,request_revision,policy_revision "
                "FROM boundary_authority"
            ).fetchone()
            allowed = conn.execute(
                "SELECT write_allowed FROM request_policy"
            ).fetchone()
        if row is None or allowed is None:
            raise ValueError("Authoritative request is unavailable")
        return {
            "title": row[0],
            "request_revision": row[1],
            "policy_revision": row[2],
            "write_allowed": bool(allowed[0]),
        }

    def scenario_grant(self, operation: str, *, stale: bool = False) -> None:
        """Synthetic scoped approval: only the current requested title is eligible."""
        request = self.request_state()
        proposal = self.proposal(operation)
        if proposal.decision != "pending":
            return
        if stale:
            with self.connection() as conn:
                conn.execute(
                    "UPDATE proposals SET request_revision=1,policy_revision=1 "
                    "WHERE operation_id=?",
                    (operation,),
                )
            self.decide(operation, approve=True)
        else:
            with self.connection() as conn:
                existing = conn.execute(
                    "SELECT count(*) FROM tasks WHERE title=?", (request["title"],)
                ).fetchone()[0]
            self.decide(
                operation,
                approve=(
                    request["write_allowed"] is True
                    and proposal.title == request["title"]
                    and existing == 0
                ),
            )
