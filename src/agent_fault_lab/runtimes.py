"""Launch either M16 runtime in one separate locked environment; never fallback."""

from __future__ import annotations

import argparse
import hashlib
import json
import signal
import subprocess
import time
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import JsonValue

from agent_fault_lab.runtime_records import RUNTIME_CASES, RuntimeResult, runtime_config


def integration() -> Path:
    return Path(__file__).resolve().parents[2] / "integrations" / "langgraph"


def environment() -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "PYTHONIOENCODING": "utf-8",
        "LANGSMITH_TRACING": "false",
        "LANGCHAIN_TRACING_V2": "false",
    }


def doctor() -> dict[str, JsonValue]:
    project = integration()
    python = project / ".venv" / "bin" / "python"
    lock = project / "uv.lock"
    if not python.is_file() or not lock.is_file():
        raise ValueError(
            "LangGraph environment unavailable; run make runtime-setup in the "
            "source checkout"
        )
    check = subprocess.run(
        [str(python), "-I", "-m", "agent_fault_lab.runtime_worker", "doctor"],
        cwd=project.parents[1],
        env=environment(),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if check.returncode:
        raise ValueError("LangGraph doctor failed: " + check.stderr[-2000:])
    result: dict[str, JsonValue] = json.loads(check.stdout)
    if result.get("langgraph") != "1.2.11" or result.get("python") != "3.12":
        raise ValueError("Runtime version differs from the frozen integration")
    from agent_fault_lab.study_records import fingerprint

    if result.get("source_sha256") != fingerprint()["source_sha256"]:
        raise ValueError("Runtime environment imports a different project source")
    locked = {
        p["name"].lower().replace("_", "-"): p["version"]
        for p in tomllib.loads(lock.read_text())["package"]
    }
    installed = result.get("dependencies")
    if not isinstance(installed, dict) or any(
        locked.get(name.lower().replace("_", "-")) != value
        for name, value in installed.items()
    ):
        raise ValueError(
            "Installed runtime dependencies differ from the integration lock"
        )
    result["lock_sha256"] = hashlib.sha256(lock.read_bytes()).hexdigest()
    return result


def run_runtime(
    runtime: str,
    case: str,
    mode: Literal["offline", "live"],
    directory: Path,
    *,
    study_lock: int | None = None,
) -> RuntimeResult:
    if runtime not in ("native", "langgraph"):
        raise ValueError("Unknown runtime")
    runtime_config(case, mode)
    if directory.exists() or directory.is_symlink():
        raise ValueError("Runtime output must be a new directory")
    identity = doctor()
    project = integration()
    remaining = signal.getitimer(signal.ITIMER_REAL)[0]
    deadline = min(450.0, remaining) if remaining > 0 else 450.0
    # Both runtimes use exactly this interpreter and provider dependency set.
    command = [
        str(project / ".venv/bin/python"),
        "-I",
        "-m",
        "agent_fault_lab.runtime_worker",
        "run",
        runtime,
        case,
        mode,
        str(directory.absolute()),
        json.dumps(identity),
        str(deadline),
    ]
    # Remain in the study's process group so its deadline also stops this worker.
    # The worker has an independent 450-second timer if its controller disappears.
    process = subprocess.Popen(
        command,
        cwd=project.parents[1],
        env=environment(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        pass_fds=() if study_lock is None else (study_lock,),
    )
    try:
        _, error = process.communicate(timeout=deadline + 5)
    except BaseException:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        raise
    if process.returncode:
        detail = error.decode(errors="replace")[-2000:]
        raise ValueError(f"Runtime worker exited {process.returncode}: {detail}")
    from agent_fault_lab.saved_reports import _read_evidence

    result = RuntimeResult.model_validate_json(
        _read_evidence(directory / "runtime.json")
    )
    if (
        result.runtime != runtime
        or result.evaluation.config != runtime_config(case, mode)
        or result.identity != identity
    ):
        raise ValueError("Runtime worker evidence differs from requested configuration")
    return result


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser("runtime", help="Matched native/LangGraph execution.")
    sub = parser.add_subparsers(dest="runtime_command", required=True)
    inspect = sub.add_parser("doctor")
    inspect.add_argument("runtime", choices=("langgraph",))
    run = sub.add_parser("run")
    run.add_argument("runtime", choices=("native", "langgraph"))
    run.add_argument("case", choices=RUNTIME_CASES)
    mode = run.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true")
    mode.add_argument("--live", action="store_true")
    run.add_argument("--output", type=Path, required=True)


def command(args: argparse.Namespace) -> int:
    if args.runtime_command == "doctor":
        print(json.dumps(doctor(), indent=2))
        return 0
    started = time.monotonic()
    result = run_runtime(
        args.runtime, args.case, "live" if args.live else "offline", args.output
    )
    print(
        f"Recorded {result.runtime} / {args.case} "
        f"in {time.monotonic() - started:.3f}s: {args.output}"
    )
    return (
        2
        if result.evaluation.status == "error"
        or result.evaluation.state.status == "error"
        or (
            result.evaluation.execution is not None
            and result.evaluation.execution.status == "provider_error"
        )
        else 0
    )
