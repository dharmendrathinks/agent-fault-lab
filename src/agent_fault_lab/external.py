"""Bounded offline controller for registered standalone external reproductions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import selectors
import subprocess
import time
import tomllib
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agent_fault_lab.evaluation import Evaluation, evaluate_run
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
    Status,
    classify,
    execution,
    render_external,
)
from agent_fault_lab.journal import atomic_json, run_lock
from agent_fault_lab.runtimes import environment
from agent_fault_lab.saved_reports import _read_evidence, replace_report
from agent_fault_lab.studies import stop_worker


def integration() -> Path:
    return Path(__file__).resolve().parents[2] / "reproductions" / "langgraph-8834"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def doctor() -> Identity:
    project = integration()
    python = project / ".venv/bin/python"
    if (
        not all((project / name).is_file() for name in ("uv.lock", "reproduce.py"))
        or not python.is_file()
    ):
        raise ValueError(
            "External environment unavailable; run make external-setup "
            "in a source checkout"
        )
    check = subprocess.run(
        [str(python), "-I", str(project / "reproduce.py"), "doctor"],
        env=environment(),
        cwd=project,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if check.returncode:
        raise ValueError(
            "External doctor failed: " + check.stderr.decode(errors="replace")[-2000:]
        )
    data = json.loads(check.stdout)
    locked = {
        p["name"].lower().replace("_", "-"): p["version"]
        for p in tomllib.loads((project / "uv.lock").read_text())["package"]
        if "registry" in p["source"]
    }
    installed = data.get("dependencies")
    # The fingerprinted standalone doctor checks the complete active dependency
    # closure using lock markers in its own interpreter. Inactive platform-only
    # entries in the universal lock need not be installed here.
    if not isinstance(installed, dict) or any(
        locked.get(name) != version for name, version in installed.items()
    ):
        raise ValueError(
            "Installed external dependencies differ from the complete lock"
        )
    if data.get("source_sha256") != digest(project / "reproduce.py"):
        raise ValueError("External worker source fingerprint differs")
    data["lock_sha256"] = digest(project / "uv.lock")
    # Include all grader/record/controller dependencies, without local paths.
    package = Path(__file__).parent
    hasher = hashlib.sha256()
    for path in sorted(package.glob("*.py")):
        hasher.update(path.name.encode() + b"\0" + path.read_bytes())
    data["harness_sha256"] = hasher.hexdigest()
    return Identity.model_validate(data)


def inspect(directory: Path, invocation: Invocation | None) -> Evaluation:
    return evaluate_run(
        directory / "tasks.sqlite3",
        TITLE,
        execution(invocation),
        client="external-framework-no-model",
    )


def read_line(process: subprocess.Popen[bytes], deadline: float) -> bytes:
    """Bounded reads avoid a blocking readline and unbounded worker output."""
    assert process.stdout is not None
    buffer = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise TimeoutError("External worker deadline exceeded")
            chunk = os.read(process.stdout.fileno(), 1)
            if not chunk:
                raise ValueError("External worker ended before its invocation record")
            buffer.extend(chunk)
            if len(buffer) > 65536:
                raise ValueError("External worker record exceeds 64 KiB")
            if chunk == b"\n":
                return bytes(buffer)


def run_slot(slot: Slot, root: Path, deadline: float, lock: int) -> Slot:
    project = integration()
    directory = root / slot.id
    started = time.monotonic()
    observations: list[Observation] = []
    failure: str | None = None
    interrupted = False
    process: subprocess.Popen[bytes] | None = None
    try:
        modes = ("initial", "resume") if slot.mode == "sqlite-fresh" else ("both",)
        for mode in modes:
            worker_deadline = min(deadline, time.monotonic() + 30)
            if worker_deadline <= time.monotonic():
                raise TimeoutError("Matrix budget exhausted before worker start")
            command = [
                str(project / ".venv/bin/python"),
                "-I",
                str(project / "reproduce.py"),
                mode,
                "--backend",
                "memory" if slot.mode == "memory-same" else "sqlite",
                "--condition",
                slot.condition,
                "--directory",
                str(directory),
                "--thread-id",
                slot.thread_id,
            ]
            # Fixed source script; its output is bounded by the parent. stderr is
            # discarded, because expected exceptions are structured evidence and
            # arbitrary dependency diagnostics must not fill disk or pipe buffers.
            process = subprocess.Popen(
                command,
                cwd=project,
                env=environment(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                pass_fds=(lock,),
            )
            phases = ("initial", "resume") if mode == "both" else (mode,)
            for phase in phases:
                if phase == "resume" and mode == "both":
                    assert process.stdin is not None
                    process.stdin.write(b"resume\n")
                    process.stdin.flush()
                line = read_line(process, worker_deadline)
                # The strict reader also rejects duplicate keys and non-finite JSON.
                raw = _read_evidence(directory / (phase + ".json"))
                invocation = Invocation.model_validate_json(raw)
                if (
                    json.loads(line) != json.loads(raw)
                    or invocation.phase != phase
                    or invocation.pid != process.pid
                ):
                    raise ValueError(
                        "Worker record differs from the requested invocation"
                    )
                observation = Observation(
                    invocation=invocation, evaluation=inspect(directory, invocation)
                )
                observations.append(observation)
                atomic_json(
                    directory / (phase + "-evaluation.json"),
                    observation.model_dump(mode="json"),
                )
            process.wait(timeout=max(0.001, worker_deadline - time.monotonic()))
            if process.returncode:
                raise ValueError(f"External worker exited {process.returncode}")
            stop_worker(process)
            for stream in (process.stdin, process.stdout):
                if stream:
                    with suppress(BrokenPipeError):
                        stream.close()
            process = None
    except KeyboardInterrupt:
        interrupted = True
        failure = "Interrupted during external lifecycle"
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        if process is not None:
            try:
                stop_worker(process)
            finally:
                for stream in (process.stdin, process.stdout):
                    if stream:
                        # A worker may close stdin after its initial observation.
                        # Preserve the original failure and SQL evidence even if
                        # closing the buffered resume command raises again.
                        with suppress(BrokenPipeError):
                            stream.close()
    final = inspect(directory, observations[-1].invocation if observations else None)
    fields = slot.model_dump()
    status: Status = (
        "interrupted" if interrupted else "failed" if failure else "completed"
    )
    fields.update(
        status=status,
        symptom=classify(slot.condition, status, tuple(observations), final),
        observations=tuple(observations),
        final_evaluation=final,
        error=failure,
        elapsed_seconds=time.monotonic() - started,
    )
    try:
        return Slot.model_validate(fields)
    except ValueError as exc:
        fields.update(
            status="failed",
            symptom="inconclusive",
            error=f"Incomplete or unexpected evidence: {exc}",
        )
        return Slot.model_validate(fields)


def save(root: Path, result: Reproduction) -> None:
    atomic_json(root / "comparison.json", result.model_dump(mode="json"))
    replace_report(root, render_external(result))


def run(directory: Path) -> Reproduction:
    if directory.exists() or directory.is_symlink():
        raise ValueError("External output must be a new directory")
    started = time.monotonic()
    identity = doctor()
    directory = directory.absolute()
    directory.mkdir(parents=True, exist_ok=False)
    slots = [
        Slot(
            id=f"{mode}-{condition}-{repetition}",
            mode=mode,
            condition=condition,
            repetition=repetition,
            thread_id=str(uuid4()),
        )
        for mode in MODES
        for condition in CONDITIONS
        for repetition in range(1, 4)
    ]
    result = Reproduction(
        identity=identity,
        created_at=datetime.now(UTC).isoformat(),
        status="unstarted",
        slots=tuple(slots),
    )
    with run_lock(directory, create=True) as lock:
        save(directory, result)
        try:
            for index, slot in enumerate(slots):
                if time.monotonic() >= started + 300:
                    break
                # Reserve before spawning: a hard-killed controller cannot leave
                # a started lifecycle labeled unstarted in its last checkpoint.
                slots[index] = slot.model_copy(
                    update={
                        "status": "interrupted",
                        "error": "Started; finalization not yet captured",
                    }
                )
                result = result.model_copy(
                    update={"status": "interrupted", "slots": tuple(slots)}
                )
                save(directory, result)
                slots[index] = run_slot(slot, directory, started + 300, lock)
                result = result.model_copy(
                    update={
                        "slots": tuple(slots),
                        "elapsed_seconds": time.monotonic() - started,
                    }
                )
                save(directory, result)
                if slots[index].status == "interrupted":
                    break
        except KeyboardInterrupt:
            # Invoked between workers: inventory and completed SQL remain intact.
            result = result.model_copy(update={"status": "interrupted"})
        else:
            status = (
                "interrupted"
                if any(s.status == "interrupted" for s in slots)
                else "completed"
                if all(s.status == "completed" for s in slots)
                else "failed"
            )
            result = result.model_copy(update={"status": status})
        result = Reproduction.model_validate(
            result.model_dump()
            | {
                "slots": tuple(slots),
                "elapsed_seconds": time.monotonic() - started,
            }
        )
        save(directory, result)
    return result


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser(
        "external", help="Offline external failure reproductions."
    )
    sub = parser.add_subparsers(dest="external_command", required=True)
    sub.add_parser("list")
    check = sub.add_parser("doctor")
    check.add_argument("case", choices=(CASE,))
    execute = sub.add_parser("run")
    execute.add_argument("case", choices=(CASE,))
    execute.add_argument("--output", type=Path, required=True)


def command(args: argparse.Namespace) -> int:
    if args.external_command == "list":
        print(f"{CASE}: LangGraph #8834; 27 offline lifecycles; separate source setup")
        return 0
    if args.external_command == "doctor":
        print(doctor().model_dump_json(indent=2))
        return 0
    result = run(args.output)
    counts = {
        name: sum(s.symptom == name for s in result.slots)
        for name in (
            "reproduced",
            "not_reproduced",
            "inconclusive",
        )
    }
    print(
        f"External matrix {result.status}: {counts}; "
        f"report: {args.output / 'report.md'}"
    )
    return (
        130
        if result.status == "interrupted"
        else 0
        if result.status == "completed"
        else 2
    )
