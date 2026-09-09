"""Dependency-independent M17 tests; real framework behavior is external-check."""

import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent_fault_lab import external
from agent_fault_lab.cli import main
from agent_fault_lab.external_records import (
    CASE,
    CONDITIONS,
    MODES,
    TITLE,
    Identity,
    Invocation,
    Observation,
    Reproduction,
    Slot,
    classify,
)
from agent_fault_lab.saved_reports import render_saved_report, report_matches


@pytest.fixture
def identity() -> Identity:
    return Identity(
        python="3.12.0",
        platform="synthetic test fixture",
        dependencies={"langgraph": "1.2.11", "langgraph-checkpoint-sqlite": "3.1.1"},
        source_sha256="0" * 64,
        lock_sha256="1" * 64,
        harness_sha256="2" * 64,
    )


def table(directory: Path, rows: tuple[tuple[str, str], ...] = ()) -> None:
    directory.mkdir(exist_ok=True)
    with closing(sqlite3.connect(directory / "tasks.sqlite3")) as connection:
        with connection:
            connection.execute("CREATE TABLE tasks (id TEXT, title TEXT)")
            connection.executemany("INSERT INTO tasks VALUES (?, ?)", rows)


def invocation(phase: str = "initial", **changes: Any) -> Invocation:
    data: dict[str, Any] = {
        "phase": phase,
        "pid": 42,
        "before": {"values": {}, "pending": [], "task_errors": []},
        "after": {"values": {"value": 1}, "pending": [], "task_errors": []},
        "returned": None,
        "error": "RuntimeError: injected:router-failure",
        "counts": {"work": 1, "router": 1, "sink": 0},
        "fault_activated": True,
        "elapsed_seconds": 0.001,
    }
    if phase == "resume":
        data.update(
            before=data["after"],
            returned={"value": 1},
            error=None,
            counts={"work": 0, "router": 0, "sink": 0},
            fault_activated=False,
        )
    return Invocation.model_validate_json(json.dumps(data | changes))


def completed_slot(directory: Path) -> Slot:
    table(directory)
    observations = tuple(
        Observation(
            invocation=invocation(p),
            evaluation=external.inspect(directory, invocation(p)),
        )
        for p in ("initial", "resume")
    )
    return Slot(
        id="memory-same-router-failure-1",
        mode="memory-same",
        condition="router-failure",
        repetition=1,
        thread_id="fixture",
        status="completed",
        symptom="reproduced",
        observations=observations,
        final_evaluation=observations[-1].evaluation,
    )


@pytest.mark.parametrize(
    "rows,outcome",
    [
        ((), "not_completed"),
        ((("1", TITLE),), "completed"),
        ((("1", TITLE), ("2", TITLE)), "not_completed"),
        ((("1", TITLE + " "),), "not_completed"),
        (((" ", TITLE),), "not_completed"),
    ],
)
def test_independent_sql(
    tmp_path: Path, rows: tuple[tuple[str, str], ...], outcome: str
) -> None:
    table(tmp_path, rows)
    before = (tmp_path / "tasks.sqlite3").read_bytes()
    evaluation = external.inspect(tmp_path, invocation("resume"))
    assert evaluation.task_outcome == outcome
    assert evaluation.report.status == "absent"
    assert evaluation.false_success is None
    assert evaluation.execution.model_calls == evaluation.execution.tool_calls == 0
    assert (tmp_path / "tasks.sqlite3").read_bytes() == before


@pytest.mark.parametrize("kind", ["absent", "corrupt", "view"])
def test_uninspectable_is_unknown(tmp_path: Path, kind: str) -> None:
    if kind == "corrupt":
        (tmp_path / "tasks.sqlite3").write_bytes(b"not sqlite")
    elif kind == "view":
        with closing(sqlite3.connect(tmp_path / "tasks.sqlite3")) as connection:
            connection.execute(
                "CREATE VIEW tasks AS SELECT 'id' AS id, 'title' AS title"
            )
    result = external.inspect(tmp_path, None)
    assert result.task_outcome == "unknown" and result.state.rows is None
    if kind == "absent":
        assert not (tmp_path / "tasks.sqlite3").exists()


@pytest.mark.parametrize("change", ["no-fault", "pending", "sink", "wrong-state"])
def test_symptom_requires_whole_predicate(tmp_path: Path, change: str) -> None:
    slot = completed_slot(tmp_path)
    initial, resume = (o.invocation for o in slot.observations)
    if change == "no-fault":
        initial = initial.model_copy(update={"fault_activated": False})
    elif change == "pending":
        resume = resume.model_copy(
            update={"after": resume.after.model_copy(update={"pending": ("sink",)})}
        )
    elif change == "sink":
        resume = resume.model_copy(
            update={"counts": resume.counts.model_copy(update={"sink": 1})}
        )
    else:
        resume = resume.model_copy(
            update={"after": resume.after.model_copy(update={"values": {"value": 2}})}
        )
    observations = tuple(
        Observation(invocation=i, evaluation=external.inspect(tmp_path, i))
        for i in (initial, resume)
    )
    assert (
        classify(slot.condition, "completed", observations, slot.final_evaluation)
        == "not_reproduced"
    )
    assert (
        classify(slot.condition, "failed", observations, slot.final_evaluation)
        == "inconclusive"
    )


@pytest.mark.parametrize(
    "change", ["claim", "task", "phase", "fault", "symptom", "pid", "snapshot"]
)
def test_reject_contradictory_evidence(tmp_path: Path, change: str) -> None:
    data = completed_slot(tmp_path).model_dump(mode="json")
    if change == "claim":
        data["final_evaluation"]["execution"]["model_calls"] = 1
    elif change == "task":
        data["final_evaluation"]["task_outcome"] = "completed"
    elif change == "phase":
        data["observations"].reverse()
    elif change == "fault":
        data["observations"][1]["invocation"]["fault_activated"] = True
    elif change == "pid":
        data["observations"][1]["invocation"]["pid"] = 43
    elif change == "snapshot":
        data["observations"][1]["invocation"]["before"]["values"] = {}
    else:
        data["symptom"] = "not_reproduced"
    with pytest.raises(ValueError):
        Slot.model_validate_json(json.dumps(data))


def reserved(identity: Identity) -> Reproduction:
    return Reproduction(
        identity=identity,
        created_at="fixture",
        status="unstarted",
        slots=tuple(
            Slot(
                id=f"{m}-{c}-{r}",
                mode=m,
                condition=c,
                repetition=r,
                thread_id=f"{m}-{c}-{r}",
            )
            for m in MODES
            for c in CONDITIONS
            for r in range(1, 4)
        ),
    )


def test_saved_report_needs_no_database_or_framework(
    tmp_path: Path, identity: Identity, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = reserved(identity)
    external.save(tmp_path, result)
    monkeypatch.setattr(external, "doctor", lambda: pytest.fail("doctor during report"))
    monkeypatch.setattr(
        sqlite3, "connect", lambda *a, **k: pytest.fail("SQL during report")
    )
    kind, text = render_saved_report(tmp_path)
    assert kind == "comparison" and "Model claims: **absent**" in text
    assert report_matches(tmp_path, text)
    assert main(["report", str(tmp_path), "--check"]) == 0
    for bad in (
        result.model_dump_json().replace('"schema_version":1', '"schema_version":2'),
        result.model_dump_json().replace(
            '"model_calls":0', '"model_calls":0,"model_calls":0'
        ),
    ):
        (tmp_path / "comparison.json").write_text(bad)
        assert main(["report", str(tmp_path), "--check"]) == 2


def test_inventory_cannot_drop_slots(identity: Identity) -> None:
    data = reserved(identity).model_dump()
    data["slots"] = data["slots"][:-1]
    with pytest.raises(ValueError, match="27-slot"):
        Reproduction.model_validate(data)


def test_exposed_resume_exception_is_not_silent_success(tmp_path: Path) -> None:
    slot = completed_slot(tmp_path)
    resumed = invocation("resume", returned=None, error="RuntimeError: unresolved")
    final = external.inspect(tmp_path, resumed)
    result = Slot.model_validate(
        slot.model_dump()
        | {
            "symptom": "not_reproduced",
            "final_evaluation": final,
            "observations": (
                slot.observations[0],
                Observation(invocation=resumed, evaluation=final),
            ),
        }
    )
    assert result.status == "completed" and result.symptom == "not_reproduced"
    assert final.task_outcome == "not_completed"


@pytest.mark.parametrize("interrupt", [False, True])
def test_stop_preserves_committed_effect_even_without_final_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupt: bool
) -> None:
    fake_project(
        tmp_path,
        monkeypatch,
        """
import os, sys, sqlite3, time
from pathlib import Path
directory = Path(sys.argv[sys.argv.index('--directory') + 1])
directory.mkdir()
with sqlite3.connect(directory / 'tasks.sqlite3') as connection:
    connection.execute('CREATE TABLE tasks (id TEXT, title TEXT)')
    connection.execute(
        'INSERT INTO tasks VALUES (?, ?)', ('committed', 'Review the invoice.')
    )
print('committed', flush=True)
time.sleep(60)
""",
    )
    original = external.read_line

    def wait_then_stop(process: subprocess.Popen[bytes], deadline: float) -> bytes:
        assert original(process, deadline) == b"committed\n"
        if interrupt:
            raise KeyboardInterrupt
        raise TimeoutError("Controlled timeout after committed write")

    monkeypatch.setattr(external, "read_line", wait_then_stop)
    slot = Slot(
        id="memory-same-healthy-1",
        mode="memory-same",
        condition="healthy",
        repetition=1,
        thread_id="test",
    )
    with (tmp_path / "lock").open("wb") as lock:
        result = external.run_slot(slot, tmp_path, time.monotonic() + 2, lock.fileno())
    assert result.status == ("interrupted" if interrupt else "failed")
    assert result.symptom == "inconclusive" and not result.observations
    assert (
        result.final_evaluation and result.final_evaluation.task_outcome == "completed"
    )
    assert result.final_evaluation.report.status == "absent"


@pytest.mark.parametrize("interrupted", [False, True])
def test_partial_matrix_keeps_all_slots(
    tmp_path: Path,
    identity: Identity,
    monkeypatch: pytest.MonkeyPatch,
    interrupted: bool,
) -> None:
    monkeypatch.setattr(external, "doctor", lambda: identity)
    ticks = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: ticks[0])

    def fail(slot: Slot, root: Path, deadline: float, lock: int) -> Slot:
        checkpoint = Reproduction.model_validate_json(
            (root / "comparison.json").read_text()
        )
        assert checkpoint.slots[0].status == "interrupted"
        assert os.fstat(lock)
        ticks[0] = 301
        return slot.model_copy(
            update={
                "status": "interrupted" if interrupted else "failed",
                "error": "test interruption",
            }
        )

    monkeypatch.setattr(external, "run_slot", fail)
    result = external.run(tmp_path / "matrix")
    assert result.status == ("interrupted" if interrupted else "failed")
    assert len(result.slots) == 27
    assert sum(s.status == "unstarted" for s in result.slots) == 26
    assert all(s.symptom == "inconclusive" for s in result.slots)
    assert main(["report", str(tmp_path / "matrix"), "--check"]) == 0


def fake_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: str) -> Path:
    project = tmp_path / "project"
    (project / ".venv/bin").mkdir(parents=True)
    (project / ".venv/bin/python").symlink_to(sys.executable)
    (project / "reproduce.py").write_text(code)
    monkeypatch.setattr(external, "integration", lambda: project)
    return project


@pytest.mark.parametrize("kind", ["timeout", "oversize", "early-exit"])
def test_real_worker_failure_is_bounded_and_reaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    code = (
        "import os, time\nfrom pathlib import Path\n"
        "Path('worker.pid').write_text(str(os.getpid()))\n"
    )
    code += {
        "timeout": "time.sleep(60)\n",
        "oversize": "print('x' * 70000, flush=True)\ntime.sleep(60)\n",
        "early-exit": "raise SystemExit(3)\n",
    }[kind]
    project = fake_project(tmp_path, monkeypatch, code)
    slot = Slot(
        id="memory-same-healthy-1",
        mode="memory-same",
        condition="healthy",
        repetition=1,
        thread_id="test",
    )
    with (tmp_path / "lock").open("wb") as lock:
        result = external.run_slot(slot, tmp_path, time.monotonic() + 1, lock.fileno())
    assert result.status == "failed" and result.symptom == "inconclusive"
    assert result.final_evaluation and result.final_evaluation.task_outcome == "unknown"
    assert result.elapsed_seconds < 5
    pid = int((project / "worker.pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_missing_environment_and_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(external, "integration", lambda: tmp_path)
    assert main(["external", "list"]) == 0
    assert main(["external", "doctor", CASE]) == 2
    with pytest.raises(ValueError, match="new directory"):
        external.run(tmp_path)


def test_worker_closing_resume_input_preserves_initial_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = invocation().model_dump_json()
    code = f"""
import json, os, sqlite3, sys, time
from pathlib import Path
directory = Path(sys.argv[sys.argv.index('--directory') + 1])
directory.mkdir()
with sqlite3.connect(directory / 'tasks.sqlite3') as connection:
    connection.execute('CREATE TABLE tasks (id TEXT, title TEXT)')
record = json.loads({record!r})
record['pid'] = os.getpid()
(directory / 'initial.json').write_text(json.dumps(record))
os.close(0)
print(json.dumps(record), flush=True)
time.sleep(60)
"""
    fake_project(tmp_path, monkeypatch, code)
    slot = Slot(
        id="memory-same-router-failure-1",
        mode="memory-same",
        condition="router-failure",
        repetition=1,
        thread_id="test",
    )
    with (tmp_path / "lock").open("wb") as lock:
        result = external.run_slot(slot, tmp_path, time.monotonic() + 2, lock.fileno())
    assert result.status == "failed" and "BrokenPipeError" in str(result.error)
    assert len(result.observations) == 1
    assert result.final_evaluation and result.final_evaluation.state.rows == ()


@pytest.mark.parametrize("drift", ["python", "source", "dependency"])
def test_doctor_rejects_drift(
    tmp_path: Path, identity: Identity, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    project = fake_project(tmp_path, monkeypatch, "# fixture")
    (project / "uv.lock").write_text(
        '[[package]]\nname="langgraph"\nversion="1.2.11"\nsource={registry="test"}\n'
        '[[package]]\nname="langgraph-checkpoint-sqlite"\nversion="3.1.1"\nsource={registry="test"}\n'
    )
    data = identity.model_dump(exclude={"lock_sha256", "harness_sha256"})
    data["source_sha256"] = external.digest(project / "reproduce.py")
    if drift == "python":
        data["python"] = "3.13.0"
    elif drift == "source":
        data["source_sha256"] = "0" * 64
    else:
        data["dependencies"]["langgraph"] = "0.1.0"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(data),
            stderr=b"",
        ),
    )
    with pytest.raises(ValueError):
        external.doctor()
