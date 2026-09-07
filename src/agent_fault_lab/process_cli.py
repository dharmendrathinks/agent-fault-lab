"""Command orchestration for process experiments and saved-run recovery."""

import argparse
from pathlib import Path
from typing import Literal
from uuid import uuid4

from agent_fault_lab.durable_run import SCRIPT_CLIENT, run_process
from agent_fault_lab.execution_types import ProcessConfig
from agent_fault_lab.journal import atomic_json
from agent_fault_lab.ollama_adapter import OllamaClient
from agent_fault_lab.process_reports import (
    ProcessComparison,
    ProcessEntry,
    ProcessObservation,
    process_schedule,
    render_process_comparison,
)
from agent_fault_lab.saved_reports import replace_report


def failed(observation: ProcessObservation) -> bool:
    return (
        observation.evaluation.execution.status == "provider_error"
        or observation.evaluation.state.status == "error"
    )


def show(observation: ProcessObservation) -> None:
    evaluation = observation.evaluation
    print(
        f"Task outcome: {evaluation.task_outcome}; "
        f"terminal: {evaluation.report.status}; claim: {evaluation.claim_support}"
    )
    print("Process accounting: " + observation.process.model_dump_json())


def process_command(args: argparse.Namespace, provenance: dict[str, object]) -> int:
    if args.reliability_command == "run":
        config = ProcessConfig(case=args.case, policy=args.policy)
    else:
        if args.include_control:
            raise ValueError("--include-control applies only to M07 comparisons")
        planned = process_schedule(args.case, args.trials)
        config = planned[0].config
    # Validate before creating a run directory, including the parent runs folder.
    label = SCRIPT_CLIENT
    if args.live:
        info = OllamaClient().inspect()
        if not info.ready:
            raise ValueError("Live preflight refused: " + "; ".join(info.problems))
        label = OllamaClient.label
    mode: Literal["offline", "live"] = "live" if args.live else "offline"
    output = args.output
    if output is None:
        Path("runs").mkdir(exist_ok=True)
        prefix = "m09" if args.case == "restart-healthy" else "m08"
        output = Path("runs") / f"{prefix}-{args.reliability_command}-{uuid4()}"
    if args.reliability_command == "run":
        observation = run_process(
            output, config, mode=mode, provenance=provenance, pause_at=args.pause_at
        )
        show(observation)
        return 2 if failed(observation) else 0
    output = output.resolve()
    output.mkdir()
    print(f"Comparison directory: {output}", flush=True)
    atomic_json(
        output / "manifest.json",
        {
            "artifact": "execution-comparison-manifest",
            "schema_version": 1,
            "planned": [s.model_dump(mode="json") for s in planned],
        },
    )
    entries: list[ProcessEntry] = []
    status = "finished"
    error = partial = None
    try:
        for spec in planned:
            partial = spec.directory
            observation = run_process(
                output / partial, spec.config, mode=mode, provenance=provenance
            )
            entries.append(ProcessEntry(spec=spec, observation=observation))
            partial = None
            show(observation)
            if failed(observation):
                status, error = (
                    "stopped",
                    "Provider/evaluator error; remaining runs not attempted",
                )
                break
    except KeyboardInterrupt:
        status, error = "interrupted", "Interrupted; inspect the partial child journal"
        raise
    except Exception as exc:
        status, error = "harness_error", f"{type(exc).__name__}: {exc}"
        raise
    finally:
        comparison = ProcessComparison.model_validate(
            {
                "client": label,
                "planned": planned,
                "entries": tuple(entries),
                "status": status,
                "error": error,
                "partial_directory": partial,
            }
        )
        atomic_json(output / "comparison.json", comparison.model_dump(mode="json"))
        replace_report(output, render_process_comparison(comparison))
    return 0 if status == "finished" else 2
