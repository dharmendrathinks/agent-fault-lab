"""Run M01 without a model; all demonstration data is temporary."""

import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_fault_lab import TaskStore


def main() -> None:
    with TemporaryDirectory(prefix="agent-fault-lab-m01-") as directory:
        database = Path(directory) / "tasks.sqlite3"
        store = TaskStore(database)

        print("M01: ordinary Python functions and SQLite; no AI or network.")
        print(f"Temporary database: {database}")
        created = store.create_task("Review the invoice")
        print(f"create_task returned: {created}")

        reopened = TaskStore(database)
        print(f"get_task after reopening: {reopened.get_task(created.id)}")
        print(f"get_task for an unknown ID: {reopened.get_task('unknown')}")

        with closing(
            sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
        ) as connection:
            rows = connection.execute("SELECT id, title FROM tasks").fetchall()
        print(f"Independent SQL read: {rows}")

    print("Temporary demonstration database removed; no persistent tasks were changed.")


if __name__ == "__main__":
    main()
