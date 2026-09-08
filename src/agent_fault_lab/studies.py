"""Sequential, deadline-bounded study control with conservative crash accounting."""

import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

from pydantic import JsonValue

from agent_fault_lab.evaluation import inspect_state
from agent_fault_lab.journal import atomic_json, regular, run_lock, strict_json
from agent_fault_lab.ollama_adapter import OllamaClient
from agent_fault_lab.scanner import _signal_group
from agent_fault_lab.study_records import (
    ChildResult,
    Entry,
    Study,
    StudyPlan,
    fingerprint,
)


def read_plan(path: Path) -> StudyPlan:
    regular(path)
    # JSON mode allows JSON arrays for immutable tuple fields, with strict values.
    raw = path.read_text()
    strict_json(raw)
    return StudyPlan.model_validate_json(raw)


def read_study(directory: Path) -> Study:
    if directory.is_symlink():
        raise ValueError("Study directory cannot be a symlink")
    path = directory / "comparison.json"
    regular(path)
    raw = path.read_text()
    strict_json(raw)
    study = Study.model_validate_json(raw)
    if read_plan(directory / "plan.json") != study.plan:
        raise ValueError("Saved study plan changed")
    return study


def save(directory: Path, study: Study) -> Study:
    from agent_fault_lab.saved_reports import replace_report
    from agent_fault_lab.study_reports import render_study

    study = Study.model_validate_json(study.model_dump_json())
    atomic_json(directory / "comparison.json", study.model_dump(mode="json"))
    replace_report(directory, render_study(study))
    return study


def replace_entry(
    study: Study, index: int, entry: Entry, **changes: JsonValue
) -> Study:
    entries = list(study.entries)
    entries[index] = entry
    return study.model_copy(update={"entries": tuple(entries), **changes})


def stop_worker(process: subprocess.Popen[bytes]) -> None:
    # Allow the child's scanner finally-block to terminate/reap its own group.
    _signal_group(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    finally:
        _signal_group(process.pid, signal.SIGKILL)
        process.wait(timeout=2)


def sealed(directory: Path, study: Study, entry: Entry) -> ChildResult | None:
    child = directory / entry.slot.directory
    if child.is_symlink():
        raise ValueError("Child directory cannot be a symlink")
    path = child / "study-child.json"
    if not path.exists() and not path.is_symlink():
        return None
    regular(path)
    raw = path.read_text()
    strict_json(raw)
    result = ChildResult.model_validate_json(raw)
    if (
        result.slot != entry.slot
        or result.mode != study.mode
        or result.plan_digest != study.plan_digest
    ):
        raise ValueError("Sealed child identity mismatch")
    return result


def reconcile(directory: Path, study: Study) -> Study:
    """Never repeat an action from a started slot, even with no terminal receipt."""
    for index, entry in enumerate(study.entries):
        if entry.status == "completed":
            if sealed(directory, study, entry) != entry.result:
                raise ValueError(
                    "Previously captured child seal changed or disappeared"
                )
        if entry.status != "running":
            continue
        result = sealed(directory, study, entry)
        recovered = Entry(
            slot=entry.slot,
            status="completed" if result else "interrupted",
            result=result,
            elapsed_seconds=study.reserved_seconds,
            inspection=None
            if result
            else inspect_state(directory / entry.slot.directory / "tasks.sqlite3"),
            error=None
            if result
            else "Controller interrupted; child is preserved and never replayed",
        )
        study = replace_entry(
            study,
            index,
            recovered,
            active_seconds=study.active_seconds + study.reserved_seconds,
            reserved_seconds=0.0,
        )
    return save(directory, study)


def _continue(directory: Path, study: Study, lock_fd: int) -> Study:
    if study.plan.fingerprints != fingerprint():
        raise ValueError(
            "Study source or dependency fingerprints changed; create a new study"
        )
    study = reconcile(directory, study)
    if study.plan.preset == "runtime" and any(
        e.status == "unstarted" for e in study.entries
    ):
        from agent_fault_lab.runtimes import doctor

        doctor()
    for entry in study.entries:
        if entry.slot.participant == "probe" and entry.status != "unstarted":
            from agent_fault_lab.scanner import ScanResult

            if (
                not entry.result
                or not isinstance(entry.result.evidence, ScanResult)
                or not entry.result.evidence.complete
            ):
                return study
    for index, entry in enumerate(study.entries):
        if entry.status != "unstarted":
            continue
        remaining = study.plan.budget_seconds - study.active_seconds
        if remaining <= 0:
            break
        child = directory / entry.slot.directory
        if child.exists() or child.is_symlink():
            raise ValueError(
                "Unstarted child already has artifacts; refusing to reuse them"
            )
        study = save(
            directory,
            replace_entry(
                study,
                index,
                Entry(slot=entry.slot, status="running"),
                reserved_seconds=remaining,
            ),
        )
        started = time.monotonic()
        error = None
        status: Literal["failed", "interrupted"] = "failed"
        interrupted = False
        process = None
        try:
            with (directory / f"{entry.slot.sequence:04d}-worker.log").open(
                "xb"
            ) as log:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-I",
                        "-m",
                        "agent_fault_lab.study_child",
                        str(directory),
                        str(entry.slot.sequence),
                        study.mode,
                        str(remaining),
                        str(lock_fd),
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    pass_fds=(lock_fd,),
                )
                try:
                    code = process.wait(
                        timeout=max(0.001, remaining - (time.monotonic() - started))
                    )
                    if code:
                        error = f"Child exited with status {code}; inspect worker log"
                except subprocess.TimeoutExpired:
                    error = "Study active-time budget exhausted; worker terminated"
                    status = "interrupted"
                except KeyboardInterrupt:
                    error = "Study interrupted by user; worker terminated"
                    status = "interrupted"
                    interrupted = True
                finally:
                    stop_worker(process)
        except OSError as exc:
            error = f"{type(exc).__name__}: {exc}"
        elapsed = time.monotonic() - started
        result = sealed(directory, study, entry)
        completed = Entry(
            slot=entry.slot,
            status="completed" if result else status,
            elapsed_seconds=elapsed,
            result=result,
            inspection=None if result else inspect_state(child / "tasks.sqlite3"),
            error=error
            if result
            else error or "Worker exited without sealed child evidence",
        )
        study = save(
            directory,
            replace_entry(
                study,
                index,
                completed,
                active_seconds=study.active_seconds + elapsed,
                reserved_seconds=0.0,
            ),
        )
        if interrupted:
            break
        if entry.slot.participant == "probe":
            from agent_fault_lab.scanner import ScanResult

            if (
                not result
                or not isinstance(result.evidence, ScanResult)
                or not result.evidence.complete
            ):
                break
    return study


def run(plan: StudyPlan, directory: Path, mode: Literal["offline", "live"]) -> Study:
    if plan.fingerprints != fingerprint():
        raise ValueError(
            "Plan source/dependency fingerprints changed; regenerate the plan"
        )
    if plan.preset == "runtime":
        from agent_fault_lab.runtimes import doctor

        doctor()
    provenance: dict[str, JsonValue] = {
        "mode": "offline scripted agents, NOT model evidence"
    }
    if mode == "live":
        info = OllamaClient().inspect()
        if not info.ready or info.model_digest != plan.model_digest:
            raise ValueError("Live preflight failed: " + "; ".join(info.problems))
        provenance = info.model_dump(mode="json")
    directory = directory.absolute()
    directory.mkdir()
    with run_lock(directory, create=True) as lock_fd:
        atomic_json(directory / "plan.json", plan.model_dump(mode="json"))
        study = Study(
            plan=plan,
            plan_digest=plan.digest,
            mode=mode,
            provenance=provenance,
            entries=tuple(Entry(slot=slot) for slot in plan.slots),
        )
        return _continue(directory, save(directory, study), lock_fd)


def resume(directory: Path, mode: Literal["offline", "live"]) -> Study:
    directory = directory.absolute()
    with run_lock(directory) as lock_fd:
        study = read_study(directory)
        if mode != study.mode:
            raise ValueError("Resume mode differs from the captured study")
        if mode == "live":
            info = OllamaClient().inspect()
            if not info.ready or info.model_dump(mode="json") != study.provenance:
                raise ValueError(
                    "Live provider identity/settings changed; start a new study"
                )
        return _continue(directory, study, lock_fd)
