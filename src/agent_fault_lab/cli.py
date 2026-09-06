"""M03: task execution followed by independent state/claim evaluation."""

import argparse
import json
import platform
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from pydantic import JsonValue

from agent_fault_lab.agent import run_agent
from agent_fault_lab.claims import TerminalClaim
from agent_fault_lab.evaluation import EVALUATOR_VERSION, Evaluation, evaluate_run
from agent_fault_lab.model import (
    Message,
    ModelClient,
    ModelSettings,
    ModelTurn,
    ToolCall,
)
from agent_fault_lab.ollama_adapter import OllamaClient
from agent_fault_lab.reporting import render_report
from agent_fault_lab.scripted import ScriptedClient
from agent_fault_lab.tasks import TaskStore
from agent_fault_lab.trace import Recorder

TITLE = "Review the invoice"
REQUEST = f"Create a task with the exact title {json.dumps(TITLE)}."


def _demo_client(case: str) -> ScriptedClient:
    if case == "false-success":
        # No faulty tool yet (M04): the script simply claims a task it never created.
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


def _execute(
    client: ModelClient,
    output: Path | None,
    provenance: dict[str, JsonValue],
) -> Evaluation:
    if output is None:
        Path("runs").mkdir(exist_ok=True)
        output = Path("runs") / f"m03-{uuid4()}"
    output = output.resolve()
    # Existing directories are rejected; no user or previous experiment is reused.
    output.mkdir()
    print(f"Run directory: {output}", flush=True)
    settings = ModelSettings()
    _write_json(
        output / "manifest.json",
        {
            "schema_version": 2,
            "milestone": "M03",
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
            result = run_agent(client, store, REQUEST, recorder, settings=settings)
            # Retain execution evidence before evaluation or rendering can fail.
            _write_json(output / "result.json", result.model_dump(mode="json"))
            recorder.emit("evaluation_started", evaluator_version=EVALUATOR_VERSION)
            evaluation = evaluate_run(
                output / "tasks.sqlite3", TITLE, result, client=client.label
            )
            _write_json(output / "evaluation.json", evaluation.model_dump(mode="json"))
            with (output / "report.md").open("x", encoding="utf-8") as report_file:
                report_file.write(render_report(evaluation))
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
    print("Raw terminal content is preserved in result.json and report.md.")
    print(
        "Evidence: manifest.json, trace.jsonl, tasks.sqlite3, result.json, "
        "evaluation.json, report.md"
    )
    return evaluation


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aflab",
        description="M03: compare a terminal claim with independently inspected state.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
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
        "run", help="One explicit local qwen3:4b task; no retries."
    )
    live.add_argument("--output", type=Path, help="New directory; parent must exist.")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            info = OllamaClient().inspect()
            print(info.model_dump_json(indent=2))
            print("READY for a local smoke test" if info.ready else "NOT READY")
            return 0 if info.ready else 2
        if args.command == "demo":
            evaluation = _execute(
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
            evaluation = _execute(client, args.output, info.model_dump(mode="json"))
        # Model/limit outcomes are results, not necessarily a broken experiment.
        return (
            2
            if (
                evaluation.execution.status == "provider_error"
                or evaluation.state.status == "error"
            )
            else 0
        )
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
