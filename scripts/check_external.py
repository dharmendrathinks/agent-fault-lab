"""Real pinned M17 matrix; no model or network, no fabricated framework result."""

import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from agent_fault_lab.external import inspect, integration, run
from agent_fault_lab.external_records import Reproduction
from agent_fault_lab.saved_reports import render_saved_report, report_matches


def standalone_check() -> None:
    """A clean copy installs only its own lock and runs without importing the lab."""
    with TemporaryDirectory(prefix="aflab-external-standalone-") as temporary:
        project = Path(temporary)
        for name in ("pyproject.toml", "uv.lock", "reproduce.py", "README.md"):
            shutil.copyfile(integration() / name, project / name)
        subprocess.run(
            ["uv", "sync", "--project", str(project), "--locked", "--offline"],
            check=True,
            timeout=60,
            capture_output=True,
        )
        command = [
            str(project / ".venv/bin/python"),
            "-I",
            str(project / "reproduce.py"),
        ]
        checked = subprocess.run(
            [*command, "doctor"],
            check=True,
            capture_output=True,
            timeout=30,
        )
        assert "agent-fault-lab" not in json.loads(checked.stdout)["dependencies"]
        for condition in ("healthy", "node-failure", "router-failure"):
            output = project / condition
            worker = subprocess.run(
                [
                    *command,
                    "both",
                    "--backend",
                    "memory",
                    "--condition",
                    condition,
                    "--directory",
                    str(output),
                    "--thread-id",
                    condition,
                ],
                input=b"resume\n",
                check=True,
                capture_output=True,
                timeout=30,
            )
            assert len(worker.stdout.splitlines()) == 2
            grade = inspect(output, None)
            assert grade.task_outcome == (
                "not_completed" if condition == "router-failure" else "completed"
            )
        print(
            "PASS standalone clean copy: no lab installation; three conditions",
            flush=True,
        )


def check() -> None:
    standalone_check()
    directory = Path("runs") / f"external-check-{uuid4()}"
    result = run(directory)
    # Round-trip validation is deliberately separate from execution.
    captured = Reproduction.model_validate_json(
        (directory / "comparison.json").read_text()
    )
    assert captured == result and result.status == "completed", directory
    assert len(result.slots) == 27
    for slot in result.slots:
        first, resumed = (o.invocation for o in slot.observations)
        initial_grade = slot.observations[0].evaluation
        assert slot.final_evaluation is not None
        final = slot.final_evaluation
        assert final.state.status == "ok" and final.report.status == "absent"
        assert final.execution.model_calls == final.execution.tool_executions == 0
        assert first.fault_activated == (slot.condition != "healthy")
        assert not resumed.fault_activated
        assert first.before.values == {} and resumed.before == first.after
        assert (first.pid == resumed.pid) == (slot.mode != "sqlite-fresh")
        if slot.condition == "router-failure":
            assert slot.symptom == "reproduced", slot.id
            assert initial_grade.state.rows == final.state.rows == ()
            assert first.counts.work == first.counts.router == 1
            assert resumed.counts.work == resumed.counts.router == 0
            assert first.counts.sink == resumed.counts.sink == 0
        else:
            assert slot.symptom == "not_reproduced", slot.id
            assert final.task_outcome == "completed", slot.id
            assert first.counts.sink + resumed.counts.sink == 1
            if slot.condition == "healthy":
                assert initial_grade.state.rows == final.state.rows
                assert first.counts.sink == 1 and resumed.counts.sink == 0
            else:
                assert initial_grade.state.rows == ()
                assert first.after.pending == ("work",)
                assert (
                    resumed.counts.work
                    == resumed.counts.router
                    == resumed.counts.sink
                    == 1
                )
        events = [
            json.loads(line)
            for line in (directory / slot.id / "events.jsonl").read_text().splitlines()
        ]
        faults = [e for e in events if e["event"] == "fault-activated"]
        assert len(faults) == (0 if slot.condition == "healthy" else 1)
        assert all(e["phase"] == "initial" for e in faults)
        for observation in slot.observations:
            inv = observation.invocation
            for node in ("work", "router", "sink"):
                assert sum(
                    e["event"] == node and e["phase"] == inv.phase for e in events
                ) == getattr(inv.counts, node)
        print(f"PASS {slot.id}: {slot.symptom}; task={final.task_outcome}", flush=True)
    _, rendered = render_saved_report(directory)
    assert report_matches(directory, rendered)
    print(f"PASS 27 real external lifecycles; evidence: {directory}", flush=True)


if __name__ == "__main__":
    check()
