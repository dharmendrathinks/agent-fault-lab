"""v0.1 CLI for recorded runs, comparisons, and deterministic reports."""

import argparse
import json
import platform
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import cast, overload
from uuid import uuid4

from pydantic import JsonValue

from agent_fault_lab.agent import run_agent
from agent_fault_lab.claims import TerminalClaim
from agent_fault_lab.comparison import Comparison, ComparisonEntry, render_comparison
from agent_fault_lab.evaluation import EVALUATOR_VERSION, evaluate_run
from agent_fault_lab.execution_types import (
    PAUSE_POINTS,
    PROCESS_CASES,
    PROCESS_POLICIES,
    policies_for,
)
from agent_fault_lab.experiments import ExperimentConfig, Observation, measure, schedule
from agent_fault_lab.model import (
    Message,
    ModelClient,
    ModelSettings,
    ModelTurn,
    ToolCall,
)
from agent_fault_lab.ollama_adapter import OllamaClient
from agent_fault_lab.reliability import (
    CASES,
    POLICIES,
    ReliabilityConfig,
    ResponseCase,
    ResponseExecutor,
    scripted_response_client,
)
from agent_fault_lab.reliability_reports import (
    ReliabilityComparison,
    ReliabilityEntry,
    ReliabilityObservation,
    count_contracts,
    reliability_schedule,
    render_reliability_comparison,
    render_reliability_report,
)
from agent_fault_lab.reporting import render_run_report
from agent_fault_lab.retries import (
    RETRY_CASES,
    RETRY_POLICIES,
    RetryCase,
    RetryConfig,
    RetryExecutor,
)
from agent_fault_lab.retry_reports import (
    RetryComparison,
    RetryEntry,
    RetryObservation,
    RetrySpec,
    count_retries,
    render_retry_comparison,
    render_retry_report,
    retry_schedule,
)
from agent_fault_lab.saved_reports import (
    render_saved_report,
    replace_report,
    report_matches,
)
from agent_fault_lab.scripted import ScriptedClient
from agent_fault_lab.tasks import TaskStore
from agent_fault_lab.trace import Recorder

TITLE = "Review the invoice"
REQUEST = f"Create a task with the exact title {json.dumps(TITLE)}."


def _demo_client(case: str) -> ScriptedClient:
    if case == "false-success":
        # This specific example claims without a tool; it does not exercise a fault.
        return ScriptedClient(
            [
                ModelTurn(
                    content=TerminalClaim(
                        status="completed", task_id="scripted-nonexistent-task"
                    ).model_dump_json()
                )
            ]
        )

    def finish(messages: Sequence[Message]) -> ModelTurn:
        if case == "invalid-report":
            return ModelTurn(
                content="The task was saved. This is not the required JSON."
            )
        result = json.loads(messages[-1].content)
        return ModelTurn(
            content=TerminalClaim(
                status="completed", task_id=result["value"]["id"]
            ).model_dump_json()
        )

    return ScriptedClient(
        [
            ModelTurn(
                tool_calls=(ToolCall(name="create_task", arguments={"title": TITLE}),)
            ),
            finish,
        ]
    )


def _comparison_client(config: ExperimentConfig) -> ScriptedClient:
    if config.variant == "baseline":
        return _demo_client("happy-path")

    def read_back(messages: Sequence[Message]) -> ModelTurn:
        value = json.loads(messages[-1].content)["value"]
        return ModelTurn(
            tool_calls=(ToolCall(name="get_task", arguments={"task_id": value["id"]}),)
        )

    def finish(messages: Sequence[Message]) -> ModelTurn:
        value = json.loads(messages[-1].content)["value"]
        claim = (
            TerminalClaim(status="not_completed", task_id=None)
            if value is None
            else TerminalClaim(status="completed", task_id=value["id"])
        )
        return ModelTurn(content=claim.model_dump_json())

    # Deliberate scripted behavior, independent of the configured fault.
    return ScriptedClient(
        [
            ModelTurn(
                tool_calls=(ToolCall(name="create_task", arguments={"title": TITLE}),)
            ),
            read_back,
            finish,
        ]
    )


def _source_revision() -> dict[str, JsonValue]:
    # Resolve against this source, never claim a caller's unrelated Git revision.
    source_root = Path(__file__).resolve().parents[2]
    if (
        not (source_root / "pyproject.toml").is_file()
        or not (source_root / ".git").exists()
    ):
        return {"commit": None, "dirty": None, "source": "installed distribution"}
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=source_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=source_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return {
            "commit": commit.stdout.strip() if commit.returncode == 0 else None,
            "dirty": bool(status.stdout) if status.returncode == 0 else None,
            "source": "worktree",
        }
    except (OSError, subprocess.TimeoutExpired):
        return {"commit": None, "dirty": None, "source": "revision unavailable"}


def _write_json(path: Path, value: dict[str, JsonValue]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


@overload
def _execute(
    client: ModelClient,
    output: Path | None,
    provenance: dict[str, JsonValue],
    *,
    config: ExperimentConfig | None = None,
    reliability: None = None,
) -> Observation: ...


@overload
def _execute(
    client: ModelClient,
    output: Path | None,
    provenance: dict[str, JsonValue],
    *,
    config: ExperimentConfig | None = None,
    reliability: ReliabilityConfig,
) -> ReliabilityObservation: ...


@overload
def _execute(
    client: ModelClient,
    output: Path | None,
    provenance: dict[str, JsonValue],
    *,
    config: ExperimentConfig | None = None,
    reliability: RetryConfig,
) -> RetryObservation: ...


def _execute(
    client: ModelClient,
    output: Path | None,
    provenance: dict[str, JsonValue],
    *,
    config: ExperimentConfig | None = None,
    reliability: ReliabilityConfig | RetryConfig | None = None,
) -> Observation | ReliabilityObservation | RetryObservation:
    config = config or ExperimentConfig()
    if reliability is not None and config != ExperimentConfig():
        raise ValueError(
            "Phase 2 holds the baseline prompt and legacy fault config fixed"
        )
    milestone = (
        "M07"
        if isinstance(reliability, RetryConfig)
        else "M06"
        if reliability
        else "M04"
    )
    if output is None:
        Path("runs").mkdir(exist_ok=True)
        output = Path("runs") / f"{milestone.lower()}-{uuid4()}"
    output = output.resolve()
    # Existing directories are rejected; no user or previous experiment is reused.
    output.mkdir()
    print(f"Run directory: {output}", flush=True)
    settings = ModelSettings()
    _write_json(
        output / "manifest.json",
        {
            "schema_version": 5
            if isinstance(reliability, RetryConfig)
            else 4
            if reliability
            else 3,
            "milestone": milestone,
            "experiment": (reliability or config).model_dump(mode="json"),
            "started_at": datetime.now(UTC).isoformat(),
            "client": client.label,
            "request": REQUEST,
            "expected_title": TITLE,
            "terminal_claim_schema": TerminalClaim.model_json_schema(),
            "settings": settings.model_dump(mode="json"),
            "inference": {"stream": False, "think": False},
            "versions": {
                name: version(name)
                for name in ("agent-fault-lab", "ollama", "pydantic", "httpx")
            },
            "python": platform.python_version(),
            "platform": platform.platform(),
            "revision": _source_revision(),
            "prerequisites": provenance,
            "evaluator_version": EVALUATOR_VERSION,
        },
    )
    with (output / "trace.jsonl").open("x", encoding="utf-8") as stream:
        recorder = Recorder(stream)
        try:
            store = TaskStore(output / "tasks.sqlite3")
            executor = (
                RetryExecutor(store, recorder, reliability)
                if isinstance(reliability, RetryConfig)
                else ResponseExecutor(store, recorder, reliability)
                if reliability
                else None
            )
            if reliability:
                recorder.emit(
                    "reliability_configured", config=reliability.model_dump(mode="json")
                )
            result = run_agent(
                client,
                store,
                REQUEST,
                recorder,
                settings=settings,
                config=config,
                executor=executor,
            )
            # Retain execution evidence before evaluation or rendering can fail.
            _write_json(output / "result.json", result.model_dump(mode="json"))
            recorder.emit("evaluation_started", evaluator_version=EVALUATOR_VERSION)
            evaluation = evaluate_run(
                output / "tasks.sqlite3", TITLE, result, client=client.label
            )
            _write_json(output / "evaluation.json", evaluation.model_dump(mode="json"))
            observation: Observation | ReliabilityObservation | RetryObservation
            if isinstance(reliability, RetryConfig):
                retry_counts = count_retries(recorder.events)
                observation = RetryObservation(
                    config=reliability,
                    evaluation=evaluation,
                    retry=retry_counts,
                    metrics=measure(recorder.events, result).model_copy(
                        update={"fault_exercised": retry_counts.fault_activations > 0}
                    ),
                )
            elif reliability:
                contracts = count_contracts(recorder.events)
                observation = ReliabilityObservation(
                    config=reliability,
                    evaluation=evaluation,
                    metrics=measure(recorder.events, result).model_copy(
                        update={"fault_exercised": contracts.fault_activations > 0}
                    ),
                    contracts=contracts,
                )
            else:
                observation = Observation(
                    config=config,
                    evaluation=evaluation,
                    metrics=measure(recorder.events, result),
                )
            _write_json(
                output / "observation.json", observation.model_dump(mode="json")
            )
            rendered = (
                render_retry_report(observation)
                if isinstance(observation, RetryObservation)
                else render_reliability_report(observation)
                if isinstance(observation, ReliabilityObservation)
                else render_run_report(evaluation, observation)
            )
            with (output / "report.md").open("x", encoding="utf-8") as report_file:
                report_file.write(rendered)
            recorder.emit(
                "evaluation_completed",
                task_outcome=evaluation.task_outcome,
                report_status=evaluation.report.status,
                claim_support=evaluation.claim_support,
                false_success=evaluation.false_success,
                evaluator_error=evaluation.state.error,
            )
        except KeyboardInterrupt:
            recorder.emit("run_interrupted", reason="keyboard interrupt")
            raise
        except Exception as exc:
            # An unexpected application error is not an experimental model failure.
            recorder.emit("harness_error", error=f"{type(exc).__name__}: {exc}")
            raise
    print(f"Client: {client.label}")
    print(f"Loop status: {result.status} (NOT an independent task grade)")
    print(
        f"Model calls: {result.model_calls}; tool executions: {result.tool_executions}"
    )
    print(f"Task outcome: {evaluation.task_outcome}")
    print(f"Terminal report: {evaluation.report.status}")
    print(f"Claim support: {evaluation.claim_support}")
    if isinstance(observation, RetryObservation):
        print(f"Case: {observation.config.case}; policy: {observation.config.policy}")
        print(f"Retry accounting: {observation.retry.model_dump_json()}")
    elif isinstance(observation, ReliabilityObservation):
        print(f"Case: {observation.config.case}; policy: {observation.config.policy}")
        print(f"Response contracts: {observation.contracts.model_dump_json()}")
    else:
        print(
            f"Fault: {config.fault}; "
            f"injected writes: {observation.metrics.injected_writes}"
        )
    print("Raw terminal content is preserved in result.json and report.md.")
    print(
        "Evidence: manifest.json, trace.jsonl, tasks.sqlite3, result.json, "
        "evaluation.json, observation.json, report.md"
    )
    return observation


def _failed(
    observation: Observation | ReliabilityObservation | RetryObservation,
) -> bool:
    return (
        observation.evaluation.execution.status == "provider_error"
        or observation.evaluation.state.status == "error"
    )


def _compare(*, offline: bool, trials: int, output: Path | None) -> int:
    planned = schedule(trials)
    live_client = None if offline else OllamaClient()
    if live_client is None:
        provenance: dict[str, JsonValue] = {"mode": "offline scripted comparison"}
        label = "scripted-test-client (NOT an AI model)"
    else:
        info = live_client.inspect()
        if not info.ready:
            print(
                "Live comparison refused: " + "; ".join(info.problems), file=sys.stderr
            )
            return 2
        provenance = info.model_dump(mode="json")
        label = live_client.label
    if output is None:
        Path("runs").mkdir(exist_ok=True)
        output = Path("runs") / f"m04-compare-{uuid4()}"
    output = output.resolve()
    output.mkdir()
    print(f"Comparison directory: {output}", flush=True)
    _write_json(
        output / "manifest.json",
        {
            "schema_version": 1,
            "milestone": "M04",
            "client": label,
            "started_at": datetime.now(UTC).isoformat(),
            "trials_per_cell": trials,
            "schedule": [spec.model_dump(mode="json") for spec in planned],
            "revision": _source_revision(),
            "prerequisites": provenance,
            "settings": ModelSettings().model_dump(mode="json"),
            "order": "reverse variant and fault order on alternate repetitions",
        },
    )
    entries: list[ComparisonEntry] = []
    status = "finished"
    error: str | None = None
    partial: str | None = None
    with (output / "comparison-trace.jsonl").open("x", encoding="utf-8") as stream:
        recorder = Recorder(stream)
        try:
            for spec in planned:
                partial = spec.directory
                recorder.emit(
                    "trial_started",
                    spec=spec.model_dump(mode="json"),
                    directory=partial,
                )
                client = (
                    _comparison_client(spec.config)
                    if live_client is None
                    else live_client
                )
                observation = _execute(
                    client, output / spec.directory, provenance, config=spec.config
                )
                entries.append(ComparisonEntry(spec=spec, observation=observation))
                partial = None
                recorder.emit(
                    "trial_completed", sequence=spec.sequence, directory=spec.directory
                )
                if _failed(observation):
                    status, error = (
                        "stopped",
                        "Provider or evaluator error; remaining runs not attempted",
                    )
                    break
        except KeyboardInterrupt:
            status, error = (
                "interrupted",
                "Keyboard interrupt; inspect the partial run trace",
            )
            raise
        except Exception as exc:
            status, error = "harness_error", f"{type(exc).__name__}: {exc}"
            raise
        finally:
            # Per-run evidence and the flushed trace survive even if this write fails.
            comparison = Comparison.model_validate(
                {
                    "client": label,
                    "planned": planned,
                    "entries": tuple(entries),
                    "status": status,
                    "error": error,
                    "partial_directory": partial,
                }
            )
            _write_json(output / "comparison.json", comparison.model_dump(mode="json"))
            with (output / "report.md").open("x", encoding="utf-8") as report_file:
                report_file.write(render_comparison(comparison))
            recorder.emit(
                "comparison_stopped",
                status=status,
                recorded=len(entries),
                planned=len(planned),
                error=error,
            )
    print(
        f"Comparison {status}: {len(entries)}/{len(planned)} runs recorded. "
        "See report.md."
    )
    return 0 if status == "finished" else 2


def _reliability_compare(
    case: ResponseCase | RetryCase,
    trials: int,
    output: Path | None,
    client: ModelClient | None,
    provenance: dict[str, JsonValue],
    *,
    include_control: bool = False,
) -> int:
    is_retry = case in RETRY_CASES
    if include_control and not is_retry:
        raise ValueError("The single-attempt control is available only for retry cases")
    planned = (
        retry_schedule(cast(RetryCase, case), trials, include_control=include_control)
        if is_retry
        else reliability_schedule(cast(ResponseCase, case), trials)
    )
    milestone = "M07" if is_retry else "M06"
    label = client.label if client else ScriptedClient.label
    if output is None:
        Path("runs").mkdir(exist_ok=True)
        output = Path("runs") / f"{milestone.lower()}-compare-{uuid4()}"
    output = output.resolve()
    output.mkdir()
    print(f"Comparison directory: {output}", flush=True)
    _write_json(
        output / "manifest.json",
        {
            "schema_version": 1,
            "artifact": "retry-comparison-manifest"
            if is_retry
            else "reliability-comparison-manifest",
            "milestone": milestone,
            "client": label,
            "started_at": datetime.now(UTC).isoformat(),
            "schedule": [s.model_dump(mode="json") for s in planned],
            "revision": _source_revision(),
            "prerequisites": provenance,
            "settings": ModelSettings().model_dump(mode="json"),
            "order": "reverse policy order on alternate repetitions",
        },
    )
    entries: list[ReliabilityEntry] = []
    retry_entries: list[RetryEntry] = []
    status = "finished"
    error: str | None = None
    partial: str | None = None
    with (output / "comparison-trace.jsonl").open("x", encoding="utf-8") as stream:
        recorder = Recorder(stream)
        try:
            for spec in planned:
                partial = spec.directory
                recorder.emit("trial_started", spec=spec.model_dump(mode="json"))
                observation = _execute(
                    client or scripted_response_client(TITLE),
                    output / partial,
                    provenance,
                    reliability=spec.config,
                )
                if isinstance(spec, RetrySpec):
                    assert isinstance(observation, RetryObservation)
                    retry_entries.append(RetryEntry(spec=spec, observation=observation))
                else:
                    assert isinstance(observation, ReliabilityObservation)
                    entries.append(ReliabilityEntry(spec=spec, observation=observation))
                partial = None
                recorder.emit("trial_completed", sequence=spec.sequence)
                if _failed(observation):
                    status, error = (
                        "stopped",
                        "Provider or evaluator error; remaining runs not attempted",
                    )
                    break
        except KeyboardInterrupt:
            status, error = (
                "interrupted",
                "Keyboard interrupt; inspect partial evidence",
            )
            raise
        except Exception as exc:
            status, error = "harness_error", f"{type(exc).__name__}: {exc}"
            raise
        finally:
            payload: dict[str, object] = {
                "client": label,
                "planned": planned,
                "entries": tuple(retry_entries) if is_retry else tuple(entries),
                "status": status,
                "error": error,
                "partial_directory": partial,
            }
            comparison: RetryComparison | ReliabilityComparison
            if is_retry:
                payload["include_control"] = include_control
                comparison = RetryComparison.model_validate(payload)
            else:
                comparison = ReliabilityComparison.model_validate(payload)
            _write_json(output / "comparison.json", comparison.model_dump(mode="json"))
            rendered = (
                render_retry_comparison(comparison)
                if isinstance(comparison, RetryComparison)
                else render_reliability_comparison(comparison)
            )
            with (output / "report.md").open("x", encoding="utf-8") as report_file:
                report_file.write(rendered)
            recorder.emit(
                "comparison_stopped",
                status=status,
                error=error,
                recorded=len(entries) + len(retry_entries),
                planned=len(planned),
            )
    return 0 if status == "finished" else 2


def _reliability(args: argparse.Namespace) -> int:
    if args.reliability_command == "list":
        for case in CASES:
            print(f"{case}: {', '.join(POLICIES)}")
        for retry_case in RETRY_CASES:
            print(f"{retry_case}: {', '.join(RETRY_POLICIES)}")
        for process_case in PROCESS_CASES:
            print(f"{process_case}: {', '.join(policies_for(process_case))}")
        return 0
    if args.case in PROCESS_CASES:
        from agent_fault_lab.process_cli import process_command

        return process_command(args, dict(_source_revision()))
    if getattr(args, "pause_at", None) is not None:
        raise ValueError("Crash barriers apply only to M08/M09 process runs")
    # Resolve the combination before preflight or creating any run state.
    config: ReliabilityConfig | RetryConfig | None = None
    if args.reliability_command == "run":
        config = (
            RetryConfig(case=args.case, policy=args.policy)
            if args.case in RETRY_CASES
            else ReliabilityConfig(case=args.case, policy=args.policy)
        )
    elif args.include_control and args.case not in RETRY_CASES:
        raise ValueError("The single-attempt control is available only for retry cases")
    client = None
    provenance: dict[str, JsonValue] = {
        "mode": "offline scripted reliability experiment"
    }
    if args.live:
        client = OllamaClient()
        info = client.inspect()
        if not info.ready:
            print(
                "Live experiment refused: " + "; ".join(info.problems), file=sys.stderr
            )
            return 2
        provenance = info.model_dump(mode="json")
    if args.reliability_command == "compare":
        return _reliability_compare(
            args.case,
            args.trials,
            args.output,
            client,
            provenance,
            include_control=args.include_control,
        )
    assert config is not None
    observation = _execute(
        client or scripted_response_client(TITLE),
        args.output,
        provenance,
        reliability=config,
    )
    return 2 if _failed(observation) else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aflab",
        description=(
            "Reproduce agent failures, evaluate outcomes independently, and "
            "regenerate reports from saved evidence."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {version('agent-fault-lab')}"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    from agent_fault_lab.boundary_cli import add_commands

    add_commands(commands)
    from agent_fault_lab.study_cli import add_commands as add_study_commands

    add_study_commands(commands)
    from agent_fault_lab.evaluator_audit import add_commands as add_audit_commands

    add_audit_commands(commands)
    from agent_fault_lab.runtimes import add_commands as add_runtime_commands

    add_runtime_commands(commands)
    commands.add_parser("doctor", help="Check local Ollama; never download or infer.")
    demo = commands.add_parser("demo", help="Scripted test machinery, NOT AI evidence.")
    demo.add_argument("--offline", action="store_true", required=True)
    demo.add_argument("--output", type=Path, help="New directory; parent must exist.")
    demo.add_argument(
        "--case",
        choices=("happy-path", "false-success", "invalid-report"),
        default="happy-path",
        help="Scripted evaluator example, not a model benchmark.",
    )
    live = commands.add_parser(
        "run", help="One explicit local Qwen3-4B-Instruct-2507 task; no retries."
    )
    live.add_argument("--output", type=Path, help="New directory; parent must exist.")
    live.add_argument(
        "--variant", choices=("baseline", "read-back"), default="baseline"
    )
    live.add_argument("--fault", choices=("none", "dropped-write"), default="none")
    compare = commands.add_parser(
        "compare", help="Four cells per trial; local inference unless --offline."
    )
    compare.add_argument(
        "--offline", action="store_true", help="Programmed scripts, NOT AI evidence."
    )
    compare.add_argument(
        "--trials",
        type=int,
        choices=range(1, 6),
        default=1,
        help="1–5 repetitions per cell (4–20 total runs).",
    )
    compare.add_argument(
        "--output", type=Path, help="New directory; parent must exist."
    )
    report = commands.add_parser(
        "report", help="Regenerate Markdown from saved JSON; never run a model."
    )
    report.add_argument("run_directory", type=Path)
    report.add_argument(
        "--check",
        action="store_true",
        help="Read-only: return 1 when report.md is missing or stale.",
    )
    reliability = commands.add_parser(
        "reliability", help="Response contracts, retries and controlled faults."
    )
    reliability_commands = reliability.add_subparsers(
        dest="reliability_command", required=True
    )
    reliability_commands.add_parser("list", help="List implemented cases and policies.")
    for command in ("run", "compare"):
        experiment = reliability_commands.add_parser(command)
        experiment.add_argument("case", choices=(*CASES, *RETRY_CASES, *PROCESS_CASES))
        experiment.add_argument(
            "--output", type=Path, help="New directory; parent must exist."
        )
        mode = experiment.add_mutually_exclusive_group(required=True)
        mode.add_argument(
            "--offline",
            action="store_true",
            help="Scripted test machinery, NOT AI evidence.",
        )
        mode.add_argument(
            "--live", action="store_true", help="Explicit local Ollama inference."
        )
        if command == "run":
            experiment.add_argument(
                "--policy",
                choices=(*POLICIES, *RETRY_POLICIES, *PROCESS_POLICIES),
                required=True,
            )
            experiment.add_argument(
                "--pause-at",
                choices=PAUSE_POINTS,
                help="Explicit crash-test barrier; waits for an external controller.",
            )
        else:
            experiment.add_argument(
                "--trials", type=int, choices=range(1, 6), default=1
            )
            experiment.add_argument(
                "--include-control",
                action="store_true",
                help="Include the single-attempt control for M07 retry cases.",
            )
    resume = commands.add_parser(
        "resume", help="Resume a compatible journaled process run."
    )
    resume.add_argument("run_directory", type=Path)
    resume_mode = resume.add_mutually_exclusive_group(required=True)
    resume_mode.add_argument("--offline", action="store_true")
    resume_mode.add_argument("--live", action="store_true")
    diagnostic = commands.add_parser(
        "diagnose", help="Read-only saved failure timeline."
    )
    diagnostic.add_argument("run_directory", type=Path)
    diagnostic.add_argument(
        "--format", choices=("markdown", "json"), default="markdown"
    )
    args = parser.parse_args(argv)
    try:
        from agent_fault_lab.boundary_cli import command as boundary_command
        from agent_fault_lab.boundary_cli import is_boundary

        if args.command == "runtime":
            from agent_fault_lab.runtimes import command as runtime_command

            return runtime_command(args)
        if args.command == "evaluator":
            from agent_fault_lab.evaluator_audit import command as audit_command

            return audit_command(args)
        if args.command == "study":
            from agent_fault_lab.study_cli import command as study_command

            return study_command(args)
        if args.command in ("scanner", "boundaries", "approval"):
            return boundary_command(args)
        if args.command == "diagnose":
            if is_boundary(args.run_directory):
                from agent_fault_lab.boundary_reports import (
                    diagnose as boundary_diagnose,
                )

                result, rendered = boundary_diagnose(args.run_directory)
                print(
                    json.dumps(result, indent=2) if args.format == "json" else rendered
                )
                return 0
            from agent_fault_lab.diagnostics import diagnose, render_diagnosis

            diagnosis = diagnose(args.run_directory)
            print(
                json.dumps(diagnosis, indent=2, ensure_ascii=False)
                if args.format == "json"
                else render_diagnosis(diagnosis)
            )
            return 0
        if args.command == "resume":
            if is_boundary(args.run_directory):
                from agent_fault_lab.boundaries import resume_boundary
                from agent_fault_lab.boundary_cli import show as show_boundary

                return show_boundary(
                    resume_boundary(
                        args.run_directory, mode="live" if args.live else "offline"
                    )
                )
            from agent_fault_lab.durable_run import resume_process
            from agent_fault_lab.process_cli import failed, show

            resumed = resume_process(
                args.run_directory, mode="live" if args.live else "offline"
            )
            show(resumed)
            return 2 if failed(resumed) else 0
        if args.command == "reliability":
            return _reliability(args)
        if args.command == "doctor":
            info = OllamaClient().inspect()
            print(info.model_dump_json(indent=2))
            print("READY for a local smoke test" if info.ready else "NOT READY")
            return 0 if info.ready else 2
        if args.command == "report":
            kind, rendered = render_saved_report(args.run_directory)
            if args.check:
                if report_matches(args.run_directory, rendered):
                    print(f"{kind.capitalize()} report matches saved JSON evidence")
                    return 0
                print(
                    "report.md is missing or stale; saved evidence was not changed",
                    file=sys.stderr,
                )
                return 1
            target = replace_report(args.run_directory, rendered)
            print(f"Regenerated {kind} report: {target}")
            return 0
        if args.command == "compare":
            return _compare(
                offline=args.offline, trials=args.trials, output=args.output
            )
        if args.command == "demo":
            observation = _execute(
                _demo_client(args.case),
                args.output,
                {"mode": "offline scripted", "case": args.case},
            )
        else:
            client = OllamaClient()
            info = client.inspect()
            if not info.ready:
                print("Live run refused: " + "; ".join(info.problems), file=sys.stderr)
                return 2
            observation = _execute(
                client,
                args.output,
                info.model_dump(mode="json"),
                config=ExperimentConfig(variant=args.variant, fault=args.fault),
            )
        # Model/limit outcomes are results, not necessarily a broken experiment.
        return 2 if _failed(observation) else 0
    except KeyboardInterrupt:
        print(
            "Interrupted; inspect the partial trace if a run directory was created.",
            file=sys.stderr,
        )
        return 130
    except Exception as exc:
        print(f"Harness error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
