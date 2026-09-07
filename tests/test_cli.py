"""CLI evidence and safety checks; no real daemon, inference, or downloads."""

import json
import sqlite3
from contextlib import closing
from importlib.metadata import version
from pathlib import Path

import pytest

from agent_fault_lab import cli
from agent_fault_lab.cli import main
from agent_fault_lab.evaluation import Evaluation
from agent_fault_lab.experiments import Observation
from agent_fault_lab.model import DEFAULT_MODEL, ModelTurn, RunResult
from agent_fault_lab.ollama_adapter import DoctorResult, OllamaClient
from agent_fault_lab.reporting import render_report, render_run_report
from agent_fault_lab.scripted import ScriptedClient


def test_version_is_the_installed_package_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"aflab {version('agent-fault-lab')}"


def test_offline_demo_saves_real_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "run"
    assert main(["demo", "--offline", "--output", str(output)]) == 0
    assert {path.name for path in output.iterdir()} == {
        "manifest.json",
        "trace.jsonl",
        "result.json",
        "tasks.sqlite3",
        "evaluation.json",
        "observation.json",
        "report.md",
    }
    manifest = json.loads((output / "manifest.json").read_text())
    result = json.loads((output / "result.json").read_text())
    events = [
        json.loads(line) for line in (output / "trace.jsonl").read_text().splitlines()
    ]
    assert "NOT an AI model" in manifest["client"]
    assert manifest["prerequisites"] == {
        "mode": "offline scripted",
        "case": "happy-path",
    }
    assert manifest["milestone"] == "M04" and manifest["schema_version"] == 3
    assert manifest["terminal_claim_schema"]["required"] == ["status", "task_id"]
    assert result["status"] == "finished" and result["tool_executions"] == 1
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert events[-2]["kind"] == "evaluation_started"
    assert events[-1]["kind"] == "evaluation_completed"
    evaluation = Evaluation.model_validate_json(
        (output / "evaluation.json").read_text()
    )
    assert evaluation.task_outcome == "completed"
    assert evaluation.claim_support == "supported"
    assert evaluation.report.status == "valid"
    assert (output / "report.md").read_text().startswith(render_report(evaluation))
    assert (output / "report.md").read_text() == render_run_report(
        evaluation,
        Observation.model_validate_json((output / "observation.json").read_text()),
    )
    with closing(
        sqlite3.connect(f"{(output / 'tasks.sqlite3').as_uri()}?mode=ro", uri=True)
    ) as connection:
        rows = list(connection.execute("SELECT id, title FROM tasks"))
    assert len(rows) == 1 and rows[0][1] == "Review the invoice"
    assert rows[0][0] in result["final_content"]
    stdout = capsys.readouterr().out
    assert "NOT an independent task grade" in stdout and "NOT an AI model" in stdout


def test_existing_run_is_never_overwritten(tmp_path: Path) -> None:
    output = tmp_path / "run"
    assert main(["demo", "--offline", "--output", str(output)]) == 0
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    assert main(["demo", "--offline", "--output", str(output)]) == 2
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before


def test_default_output_is_fresh_each_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["demo", "--offline"]) == 0
    assert main(["demo", "--offline"]) == 0
    assert len(list((tmp_path / "runs").iterdir())) == 2


def test_missing_output_parent_is_not_created(tmp_path: Path) -> None:
    output = tmp_path / "missing" / "run"
    assert main(["demo", "--offline", "--output", str(output)]) == 2
    assert not output.parent.exists()


@pytest.mark.parametrize("command", [[], ["demo"], ["report"]])
def test_required_or_future_commands_are_not_silently_selected(
    command: list[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(command)
    assert exc.value.code == 2


def test_live_run_refused_before_creating_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def not_ready(self: OllamaClient, model: str = DEFAULT_MODEL) -> DoctorResult:
        return DoctorResult(model=model, problems=("Cloud mode unverified",))

    monkeypatch.setattr(OllamaClient, "inspect", not_ready)
    output = tmp_path / "must-not-exist"
    assert main(["run", "--output", str(output)]) == 2
    assert not output.exists()
    assert "Live run refused" in capsys.readouterr().err


@pytest.mark.parametrize("ready", [True, False])
def test_doctor_exit_status(ready: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    def inspect(self: OllamaClient, model: str = DEFAULT_MODEL) -> DoctorResult:
        return DoctorResult(model=model, problems=() if ready else ("Not installed",))

    monkeypatch.setattr(OllamaClient, "inspect", inspect)
    assert main(["doctor"]) == (0 if ready else 2)


@pytest.mark.parametrize(
    ("case", "outcome", "report", "support"),
    [
        ("false-success", "not_completed", "valid", "contradicted"),
        ("invalid-report", "completed", "invalid", "not_evaluated"),
    ],
)
def test_negative_demo_is_an_experiment_not_a_cli_failure(
    tmp_path: Path, case: str, outcome: str, report: str, support: str
) -> None:
    output = tmp_path / "run"
    assert main(["demo", "--offline", "--case", case, "--output", str(output)]) == 0
    evaluation = Evaluation.model_validate_json(
        (output / "evaluation.json").read_text()
    )
    assert evaluation.task_outcome == outcome
    assert evaluation.report.status == report
    assert evaluation.claim_support == support
    assert evaluation.false_success is (True if case == "false-success" else None)
    assert "scripted" in evaluation.client


def test_evaluator_error_keeps_execution_and_returns_harness_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def finish_and_move(messages: object) -> ModelTurn:
        database = tmp_path / "run" / "tasks.sqlite3"
        database.rename(tmp_path / "moved.sqlite3")
        return ModelTurn(content='{"status":"completed","task_id":"task-1"}')

    monkeypatch.setattr(
        cli, "_demo_client", lambda case: ScriptedClient([finish_and_move])
    )
    output = tmp_path / "run"
    assert main(["demo", "--offline", "--output", str(output)]) == 2
    assert (output / "result.json").is_file()
    evaluation = Evaluation.model_validate_json(
        (output / "evaluation.json").read_text()
    )
    assert evaluation.task_outcome == "unknown" and evaluation.state.status == "error"
    assert not (output / "tasks.sqlite3").exists()
    assert "| Task outcome | unknown |" in (output / "report.md").read_text()


def test_unexpected_evaluator_bug_keeps_partial_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(
        database: Path, expected_title: str, execution: RunResult, *, client: str
    ) -> Evaluation:
        raise RuntimeError("deliberate evaluator test error")

    monkeypatch.setattr(cli, "evaluate_run", broken)
    output = tmp_path / "run"
    assert main(["demo", "--offline", "--output", str(output)]) == 2
    assert (output / "result.json").is_file()
    assert not (output / "evaluation.json").exists()
    events = [
        json.loads(line) for line in (output / "trace.jsonl").read_text().splitlines()
    ]
    assert events[-1]["kind"] == "harness_error"
    assert "deliberate evaluator" in events[-1]["data"]["error"]
