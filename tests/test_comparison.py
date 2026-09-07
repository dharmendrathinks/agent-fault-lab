"""Four-cell accounting, bounded execution and retained unfavorable/partial runs."""

import json
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_fault_lab import cli
from agent_fault_lab.comparison import Comparison, cell_counts, render_comparison
from agent_fault_lab.experiments import ExperimentConfig, Observation, measure, schedule
from agent_fault_lab.model import DEFAULT_MODEL, ModelTurn, ProviderError, RunResult
from agent_fault_lab.ollama_adapter import DoctorResult, OllamaClient
from agent_fault_lab.scripted import ScriptedClient
from agent_fault_lab.trace import Recorder


def load_comparison(output: Path) -> Comparison:
    return Comparison.model_validate_json((output / "comparison.json").read_text())


def test_schedule_balances_cells_and_reverses_order() -> None:
    plan = schedule(5)
    assert len(plan) == 20
    assert list(Counter(s.config for s in plan).values()) == [5, 5, 5, 5]
    assert [s.config.variant for s in plan[:4]] == ["baseline", "read-back"] * 2
    assert [s.config.variant for s in plan[4:8]] == ["read-back", "baseline"] * 2
    assert [s.config.fault for s in plan[4:8]] == ["dropped-write"] * 2 + ["none"] * 2
    assert len({s.directory for s in plan}) == 20


@pytest.mark.parametrize("trials", [0, -1, 6, True])
def test_schedule_refuses_unbounded_trials(trials: int) -> None:
    with pytest.raises(ValueError):
        schedule(trials)


@pytest.mark.parametrize("option", ["--fault", "--variant"])
def test_single_run_rejects_unknown_config(option: str) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", option, "made-up"])
    assert exc.value.code == 2


@pytest.mark.parametrize("trials", ["0", "6", "-1", "1.5"])
def test_cli_rejects_bad_trial_budget(trials: str) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["compare", "--offline", "--trials", trials])
    assert exc.value.code == 2


def test_complete_scripted_comparison_and_independent_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "comparison"
    assert (
        cli.main(["compare", "--offline", "--trials", "2", "--output", str(output)])
        == 0
    )
    comparison = load_comparison(output)
    assert comparison.status == "finished" and len(comparison.entries) == 8
    ids: list[str] = []
    for entry in comparison.entries:
        o = entry.observation
        fault = entry.spec.config.fault == "dropped-write"
        read = entry.spec.config.variant == "read-back"
        assert o.config == entry.spec.config
        assert o.evaluation.task_outcome == ("not_completed" if fault else "completed")
        assert o.evaluation.report.status == "valid"
        assert o.evaluation.false_success is (fault and not read)
        assert o.metrics.fault_exercised is fault
        assert o.metrics.injected_writes == int(fault)
        assert o.metrics.read_back_calls == int(read)
        assert o.metrics.model_calls == (3 if read else 2)
        assert o.metrics.output_tokens is None and o.metrics.prompt_tokens is None
        assert o.metrics.model_load_seconds is None
        directory = output / entry.spec.directory
        assert (
            Observation.model_validate_json(
                (directory / "observation.json").read_text()
            )
            == o
        )
        manifest = json.loads((directory / "manifest.json").read_text())
        assert manifest["experiment"] == entry.spec.config.model_dump()
        if o.evaluation.state.rows:
            ids.append(o.evaluation.state.rows[0].id)
    assert len(ids) == len(set(ids)) == 4
    report = (output / "report.md").read_text()
    assert report == render_comparison(comparison)
    assert "not model behavior" in report and "not task recovery" in report
    counts = cell_counts(comparison, ExperimentConfig(fault="dropped-write"))
    assert counts["false_success_claims"] == counts["assessable_completion_claims"] == 2
    assert counts["fault_exercised_runs"] == 2
    assert counts["fault_not_exercised_runs"] == 0
    assert counts["output_tokens"] is None
    # Rendering saved evidence remains independent of current SQLite state.
    (output / comparison.entries[0].spec.directory / "tasks.sqlite3").rename(
        tmp_path / "moved.sqlite3"
    )
    assert render_comparison(comparison) == report


@pytest.mark.parametrize("reply", ['{"status":"unknown","task_id":null}', "Done!", ""])
def test_no_create_or_invalid_report_is_not_fault_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reply: str
) -> None:
    monkeypatch.setattr(
        cli,
        "_comparison_client",
        lambda config: ScriptedClient([ModelTurn(content=reply)]),
    )
    output = tmp_path / "comparison"
    assert cli.main(["compare", "--offline", "--output", str(output)]) == 0
    comparison = load_comparison(output)
    assert len(comparison.entries) == 4
    counts = cell_counts(comparison, ExperimentConfig(fault="dropped-write"))
    assert counts["false_success_claims"] == counts["assessable_completion_claims"] == 0
    assert counts["fault_exercised_runs"] == 0
    assert counts["fault_not_exercised_runs"] == 1
    if reply in ("Done!", ""):
        assert counts["report_status"] == {"invalid": 1}
        assert counts["unassessable_false_success"] == 1


def test_provider_error_stops_batch_and_retains_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli,
        "_comparison_client",
        lambda config: ScriptedClient([ProviderError("unavailable")]),
    )
    output = tmp_path / "comparison"
    assert (
        cli.main(["compare", "--offline", "--trials", "5", "--output", str(output)])
        == 2
    )
    comparison = load_comparison(output)
    assert comparison.status == "stopped" and len(comparison.entries) == 1
    assert len(comparison.planned) == 20
    assert (
        comparison.entries[0].observation.evaluation.execution.status
        == "provider_error"
    )
    assert "1 of 20 planned" in (output / "report.md").read_text()


@pytest.mark.parametrize("interrupt", [False, True])
def test_harness_failure_or_interrupt_preserves_completed_and_partial_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupt: bool
) -> None:
    original = cli._execute
    calls = 0

    def fail_second(*args: object, **kwargs: object) -> Observation:
        nonlocal calls
        calls += 1
        if calls == 2:
            if interrupt:
                raise KeyboardInterrupt()
            raise RuntimeError("deliberate batch failure")
        # Keep the first execution genuine, using known arguments from the schedule.
        spec = schedule(1)[0]
        return original(
            cli._comparison_client(spec.config),
            tmp_path / "comparison" / spec.directory,
            {"mode": "scripted test"},
            config=spec.config,
        )

    monkeypatch.setattr(cli, "_execute", fail_second)
    output = tmp_path / "comparison"
    assert cli.main(["compare", "--offline", "--output", str(output)]) == (
        130 if interrupt else 2
    )
    comparison = load_comparison(output)
    assert len(comparison.entries) == 1
    assert comparison.status == ("interrupted" if interrupt else "harness_error")
    assert comparison.partial_directory == schedule(1)[1].directory
    assert (output / schedule(1)[0].directory / "result.json").is_file()


def test_comparison_never_overwrites_existing_directory(tmp_path: Path) -> None:
    output = tmp_path / "comparison"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("Existing user data")
    assert cli.main(["compare", "--offline", "--output", str(output)]) == 2
    assert marker.read_text() == "Existing user data"
    assert list(output.iterdir()) == [marker]


def test_comparison_refuses_live_before_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def inspect(self: OllamaClient, model: str = DEFAULT_MODEL) -> DoctorResult:
        return DoctorResult(model=model, problems=("Cloud unverified",))

    monkeypatch.setattr(OllamaClient, "inspect", inspect)
    output = tmp_path / "never-created"
    assert cli.main(["compare", "--output", str(output)]) == 2
    assert not output.exists()


def test_config_schema_rejects_unsupported_fault() -> None:
    with pytest.raises(ValidationError):
        ExperimentConfig.model_validate({"fault": "slow-write"})


@pytest.mark.parametrize("complete_usage", [True, False])
def test_metrics_preserve_unknown_vs_reported_usage(complete_usage: bool) -> None:
    recorder = Recorder()
    recorder.emit(
        "model_returned",
        turn={
            "usage": {
                "prompt_eval_count": 10,
                "eval_count": 5,
                "load_duration": 2_000_000_000,
            }
        },
    )
    if complete_usage:
        recorder.emit(
            "model_returned",
            turn={
                "usage": {"prompt_eval_count": 20, "eval_count": 7, "load_duration": 0}
            },
        )
    recorder.emit("run_stopped")
    result = RunResult(
        status="finished" if complete_usage else "provider_error",
        final_content=None,
        model_calls=2,
        tool_calls=0,
        tool_executions=0,
    )
    metrics = measure(recorder.events, result)
    assert metrics.prompt_tokens == (30 if complete_usage else None)
    assert metrics.output_tokens == (12 if complete_usage else None)
    assert metrics.model_load_seconds == (2.0 if complete_usage else None)
    assert metrics.usage_calls_reported == (2 if complete_usage else 1)


def test_missing_stop_event_does_not_fabricate_zero_latency() -> None:
    with pytest.raises(ValueError, match="stop event"):
        measure(
            [],
            RunResult(
                status="finished",
                final_content=None,
                model_calls=1,
                tool_calls=0,
                tool_executions=0,
            ),
        )
