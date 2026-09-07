"""M06 comparison evidence, legacy compatibility, and explicit execution modes."""

import json
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from agent_fault_lab.cli import TITLE, _execute, main
from agent_fault_lab.model import Message, ModelTurn, ProviderError, ToolCall
from agent_fault_lab.reliability import (
    CASES,
    ReliabilityConfig,
    ResponseCase,
    scripted_response_client,
)
from agent_fault_lab.reliability_reports import (
    ReliabilityComparison,
    ReliabilityObservation,
    reliability_schedule,
)
from agent_fault_lab.saved_reports import render_saved_report, report_matches
from agent_fault_lab.scripted import ScriptedClient


@pytest.mark.parametrize("case", CASES)
def test_offline_paired_case_and_report_regeneration(
    tmp_path: Path, case: ResponseCase
) -> None:
    output = tmp_path / "comparison"
    with patch(
        "agent_fault_lab.cli.OllamaClient",
        side_effect=AssertionError("Model forbidden"),
    ):
        assert (
            main(["reliability", "compare", case, "--offline", "--output", str(output)])
            == 0
        )
        assert main(["report", str(output), "--check"]) == 0
    comparison = ReliabilityComparison.model_validate_json(
        (output / "comparison.json").read_text()
    )
    assert len(comparison.entries) == len(comparison.planned) == 2
    assert comparison.status == "finished"
    for entry in comparison.entries:
        run = entry.observation
        assert run.evaluation.task_outcome == (
            "not_completed" if case == "dropped-write" else "completed"
        )
        assert run.contracts.fault_activations == (0 if case == "healthy" else 1)
        assert run.metrics.fault_exercised == (case != "healthy")
        assert run.metrics.prompt_tokens is None
        child = output / entry.spec.directory
        assert report_matches(child, render_saved_report(child)[1])
        (child / "report.md").unlink()
        assert main(["report", str(child)]) == 0
        assert main(["report", str(child), "--check"]) == 0
    if case == "wrong-create-title":
        baseline, validated = [e.observation for e in comparison.entries]
        assert baseline.evaluation.claim_support == "supported"
        assert validated.contracts.request_errors == 1
        assert validated.evaluation.claim_support == "not_asserted"
    if case == "wrong-get-id":
        baseline, validated = [e.observation for e in comparison.entries]
        assert baseline.evaluation.false_success is True
        assert validated.contracts.request_errors == 1


def test_policy_order_and_prompt_equality(tmp_path: Path) -> None:
    specs = reliability_schedule("wrong-create-title", 2)
    assert [s.config.policy for s in specs] == [
        "pass-through",
        "validated",
        "validated",
        "pass-through",
    ]
    clients = [scripted_response_client(TITLE), scripted_response_client(TITLE)]
    for index, (client, spec) in enumerate(zip(clients, specs, strict=False)):
        _execute(client, tmp_path / str(index), {}, reliability=spec.config)
    assert clients[0].requests[0] == clients[1].requests[0]
    # Validation changes the delivered result, not the model's requested sequence.
    assert clients[0].requests[1][-1].content != clients[1].requests[1][-1].content


@pytest.mark.parametrize(
    "args",
    [
        ["run", "healthy", "--policy", "validated"],
        ["run", "healthy", "--policy", "validated", "--offline", "--live"],
        ["compare", "future-case", "--offline"],
        ["compare", "healthy", "--trials", "6", "--offline"],
    ],
)
def test_invalid_cli_never_starts_execution(tmp_path: Path, args: list[str]) -> None:
    output = tmp_path / "never-created"
    with patch(
        "agent_fault_lab.cli.OllamaClient",
        side_effect=AssertionError("Model forbidden"),
    ):
        with pytest.raises(SystemExit) as caught:
            main(["reliability", *args, "--output", str(output)])
    assert caught.value.code == 2 and not output.exists()


def test_list_and_fresh_directory_rule(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["reliability", "list"]) == 0
    assert "wrong-get-id: pass-through, validated" in capsys.readouterr().out
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "user.txt"
    marker.write_text("preserve")
    assert (
        main(
            [
                "reliability",
                "run",
                "healthy",
                "--policy",
                "validated",
                "--offline",
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert marker.read_text() == "preserve" and list(output.iterdir()) == [marker]


def test_fault_not_exercised_is_reported(tmp_path: Path) -> None:
    client = ScriptedClient([ModelTurn(content='{"status":"unknown","task_id":null}')])
    run = _execute(
        client,
        tmp_path / "run",
        {},
        reliability=ReliabilityConfig(case="wrong-get-id", policy="validated"),
    )
    assert run.contracts.fault_activations == 0
    assert run.evaluation.task_outcome == "not_completed"
    assert run.evaluation.claim_support == "not_asserted"


@pytest.mark.parametrize(
    "failure",
    [
        ProviderError("offline provider failure"),
        KeyboardInterrupt(),
        RuntimeError("harness failure"),
    ],
)
def test_comparison_keeps_partial_evidence(
    tmp_path: Path, failure: BaseException
) -> None:
    output = tmp_path / "comparison"
    with patch("agent_fault_lab.cli.scripted_response_client") as factory:
        client = ScriptedClient([ProviderError("unused")])
        factory.return_value = client
        with patch.object(client, "complete", side_effect=failure):
            result = main(
                [
                    "reliability",
                    "compare",
                    "healthy",
                    "--offline",
                    "--output",
                    str(output),
                ]
            )
    comparison = ReliabilityComparison.model_validate_json(
        (output / "comparison.json").read_text()
    )
    if isinstance(failure, ProviderError):
        assert result == 2 and comparison.status == "stopped"
        assert len(comparison.entries) == 1
        assert comparison.partial_directory is None
    else:
        assert result == (130 if isinstance(failure, KeyboardInterrupt) else 2)
        assert comparison.status == (
            "interrupted" if isinstance(failure, KeyboardInterrupt) else "harness_error"
        )
        assert not comparison.entries
        assert comparison.partial_directory == comparison.planned[0].directory
    assert not (output / comparison.planned[1].directory).exists()
    assert report_matches(output, render_saved_report(output)[1])


def test_partial_write_remains_evaluable_after_provider_error(tmp_path: Path) -> None:
    client = ScriptedClient(
        [
            ModelTurn(
                tool_calls=(ToolCall(name="create_task", arguments={"title": TITLE}),)
            ),
            ProviderError("lost model response"),
        ]
    )
    run = _execute(
        client,
        tmp_path / "run",
        {},
        reliability=ReliabilityConfig(case="healthy", policy="validated"),
    )
    assert run.evaluation.execution.status == "provider_error"
    assert run.evaluation.task_outcome == "completed"
    assert run.evaluation.false_success is None


@pytest.mark.parametrize(
    "mutation",
    ["schema", "boolean-version", "artifact", "evaluation", "counts", "duplicate"],
)
def test_saved_evidence_fails_without_replacing_report(
    tmp_path: Path, mutation: str
) -> None:
    output = tmp_path / "run"
    _execute(
        scripted_response_client(TITLE),
        output,
        {},
        reliability=ReliabilityConfig(case="healthy", policy="validated"),
    )
    path = output / "observation.json"
    payload = json.loads(path.read_text())
    if mutation == "schema":
        payload["schema_version"] = 99
    elif mutation == "boolean-version":
        payload["schema_version"] = True
    elif mutation == "artifact":
        payload["artifact"] = "future"
    elif mutation == "evaluation":
        payload["evaluation"]["expected_title"] = "other"
    elif mutation == "counts":
        payload["contracts"]["unchecked"] = 1
    raw = json.dumps(payload)
    if mutation == "duplicate":
        raw = '{"artifact":"reliability-run",' + raw[1:]
    path.write_text(raw)
    before = (output / "report.md").read_bytes()
    assert main(["report", str(output)]) == 2
    assert (output / "report.md").read_bytes() == before


def test_saved_comparison_rejects_invented_completion(tmp_path: Path) -> None:
    output = tmp_path / "compare"
    assert (
        main(
            ["reliability", "compare", "healthy", "--offline", "--output", str(output)]
        )
        == 0
    )
    payload = json.loads((output / "comparison.json").read_text())
    payload["entries"] = payload["entries"][:1]
    with pytest.raises(ValidationError):
        ReliabilityComparison.model_validate_json(json.dumps(payload))


def test_observation_preserves_unknown_usage(tmp_path: Path) -> None:
    output = tmp_path / "run"
    observation = _execute(
        scripted_response_client(TITLE),
        output,
        {},
        reliability=ReliabilityConfig(case="healthy", policy="validated"),
    )
    saved = ReliabilityObservation.model_validate_json(
        (output / "observation.json").read_text()
    )
    assert saved == observation
    assert saved.metrics.output_tokens is None and saved.metrics.prompt_tokens is None


def test_valid_contract_can_support_a_false_storage_claim(tmp_path: Path) -> None:
    def trust_response(messages: Sequence[Message]) -> ModelTurn:
        identifier = json.loads(messages[-1].content)["value"]["id"]
        return ModelTurn(
            content=json.dumps({"status": "completed", "task_id": identifier})
        )

    client = ScriptedClient(
        [
            ModelTurn(
                tool_calls=(ToolCall(name="create_task", arguments={"title": TITLE}),)
            ),
            trust_response,
        ]
    )
    run = _execute(
        client,
        tmp_path / "run",
        {},
        reliability=ReliabilityConfig(case="dropped-write", policy="validated"),
    )
    assert run.contracts.valid == 1 and run.contracts.fault_activations == 1
    assert run.evaluation.state.rows == ()
    assert run.evaluation.task_outcome == "not_completed"
    assert run.evaluation.false_success is True


def test_renderer_failure_preserves_regenerable_evidence(tmp_path: Path) -> None:
    output = tmp_path / "run"
    with patch(
        "agent_fault_lab.cli.render_reliability_report",
        side_effect=RuntimeError("renderer failed"),
    ):
        with pytest.raises(RuntimeError, match="renderer failed"):
            _execute(
                scripted_response_client(TITLE),
                output,
                {},
                reliability=ReliabilityConfig(case="healthy", policy="validated"),
            )
    assert (output / "result.json").is_file()
    assert (output / "evaluation.json").is_file()
    assert (output / "observation.json").is_file()
    # Regeneration has only saved JSON available, no state to inspect or trace to run.
    (output / "tasks.sqlite3").unlink()
    (output / "trace.jsonl").unlink()
    assert main(["report", str(output)]) == 0
    assert main(["report", str(output), "--check"]) == 0


def test_initial_smoke_schema_remains_readable(tmp_path: Path) -> None:
    output = tmp_path / "run"
    observation = _execute(
        scripted_response_client(TITLE),
        output,
        {},
        reliability=ReliabilityConfig(case="wrong-create-title", policy="validated"),
    )
    payload = observation.model_dump(mode="json")
    payload["schema_version"] = 1
    metrics = payload["metrics"]
    assert isinstance(metrics, dict)
    metrics["fault_exercised"] = False  # Initial schema counted dropped writes only.
    legacy = ReliabilityObservation.model_validate_json(json.dumps(payload))
    assert legacy.contracts.fault_activations == 1
    payload["schema_version"] = 2
    with pytest.raises(ValidationError, match="Fault activation"):
        ReliabilityObservation.model_validate_json(json.dumps(payload))
