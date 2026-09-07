"""Pinned external scanning; a scan recommendation is never write permission."""

import hashlib
import os
import selectors
import signal
import subprocess
import time
from pathlib import Path
from sys import platform
from typing import Literal, Protocol

from pydantic import Field, JsonValue

from agent_fault_lab.journal import Versioned, atomic_json, regular, strict_json
from agent_fault_lab.model import Record

PIN = "704bc9544260c2f41222dc0f92982521709496ab"
VERSION = "2.11.1"
MAX_OUTPUT = 4 * 1024 * 1024
MAX_INPUT = 16 * 1024
BENIGN_SKILL = (
    "---\nname: task-helper\ndescription: Create a task with its supplied title.\n"
    "---\n\n# Task helper\n\nPreserve the exact title supplied by the user.\n"
)


class ScanFinding(Record):
    rule_id: str = Field(min_length=1)
    severity: Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
    confidence: float = Field(ge=0, le=1)
    path: str
    line: int | None = Field(ge=1)
    finding: str


class ScanResult(Versioned):
    artifact: Literal["boundary-scan"] = "boundary-scan"
    schema_version: Literal[1] = 1
    engine: str
    commit: str
    version: str
    input_sha256: str
    status: Literal["admitted", "blocked", "error"]
    recommendation: str | None = None
    complete: bool = False
    exit_code: int | None = None
    elapsed_seconds: float = Field(ge=0)
    error: str | None = None
    raw_sha256: str | None = None
    findings: tuple[ScanFinding, ...] = ()


class Scanner(Protocol):
    def scan(self, content: bytes, directory: Path) -> ScanResult: ...


def read_skill(path: Path) -> bytes:
    if path.is_symlink():
        raise ValueError("Skill source cannot be a symlink")
    if path.is_dir():
        if {p.name for p in path.iterdir()} != {"SKILL.md"}:
            raise ValueError("M11 supports a directory containing only SKILL.md")
        path = path / "SKILL.md"
    regular(path)
    if path.suffix.lower() != ".md":
        raise ValueError("M11 accepts only a local Markdown skill")
    if path.stat().st_size > MAX_INPUT:
        raise ValueError("Skill exceeds 16 KiB input limit")
    content = path.read_bytes()
    if len(content) > MAX_INPUT or not content.decode("utf-8").strip():
        raise ValueError("Skill must be nonblank UTF-8, at most 16 KiB")
    return content


def _group_exited(pgid: int) -> bool:
    """Confirm a Darwin EPERM refers only to zombies or a vanished group."""
    try:
        result = subprocess.run(
            ["/bin/ps", "-axo", "pgid=,stat="],
            capture_output=True,
            text=True,
            check=True,
            timeout=0.5,
            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        )
        rows = [line.split() for line in result.stdout.splitlines()]
        # Empty/malformed output cannot establish that cleanup succeeded.
        if not rows or any(len(row) != 2 or not row[0].isdigit() for row in rows):
            return False
        return all(int(group) != pgid or state.startswith("Z") for group, state in rows)
    except (OSError, subprocess.SubprocessError):
        return False


def _signal_group(pgid: int, sig: signal.Signals) -> None:
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        # Darwin filters zombies out of killpg's targets and can return EPERM
        # for a group with no live members. Never ignore an actual live target.
        if platform != "darwin" or not _group_exited(pgid):
            raise


def stop(process: subprocess.Popen[bytes]) -> None:
    # The leader may have exited while a descendant still owns its pipes.
    _signal_group(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        pass
    finally:
        _signal_group(process.pid, signal.SIGKILL)
        process.wait()


def invoke(
    python: Path,
    arguments: list[str],
    directory: Path,
    *,
    timeout: float = 60,
) -> tuple[int, bytes, bytes, str | None]:
    worker = Path(__file__).with_name("scanner_worker.py")
    env = {"PATH": f"{python.parent}:/usr/bin:/bin", "PYTHONIOENCODING": "utf-8"}
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    started = time.monotonic()
    error = None
    with subprocess.Popen(
        [str(python), "-I", str(worker), *arguments],
        cwd=directory,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    ) as process:
        assert process.stdout and process.stderr
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, "stdout")
                selector.register(process.stderr, selectors.EVENT_READ, "stderr")
                while selector.get_map() or process.poll() is None:
                    report = directory / "raw-report.json"
                    report_size = report.stat().st_size if report.exists() else 0
                    if time.monotonic() - started > timeout:
                        error = "Scanner deadline exceeded"
                    if report_size + sum(map(len, buffers.values())) > MAX_OUTPUT:
                        error = "Scanner output exceeds 4 MiB"
                    if error:
                        break
                    for key, _ in selector.select(timeout=0.02):
                        data = os.read(key.fd, 65536)
                        if data:
                            remaining = max(
                                0,
                                MAX_OUTPUT
                                - report_size
                                - sum(map(len, buffers.values())),
                            )
                            buffers[key.data].extend(data[:remaining])
                            if len(data) > remaining:
                                error = "Scanner output exceeds 4 MiB"
                                break
                        else:
                            selector.unregister(key.fileobj)
        finally:
            stop(process)
        code = process.wait()
    report = directory / "raw-report.json"
    if report.exists():
        remaining = max(0, MAX_OUTPUT - sum(map(len, buffers.values())))
        if report.stat().st_size > remaining:
            with report.open("r+b") as stream:
                stream.truncate(remaining)
            error = "Scanner output exceeds 4 MiB; raw report truncated"
    return code, bytes(buffers["stdout"]), bytes(buffers["stderr"]), error


def findings(value: JsonValue) -> tuple[ScanFinding, ...]:
    if not isinstance(value, list):
        raise ValueError("Scanner issues must be a list")
    result = []
    for issue in value:
        if not isinstance(issue, dict) or not isinstance(issue.get("location"), dict):
            raise ValueError("Malformed scanner finding")
        location = issue["location"]
        assert isinstance(location, dict)
        result.append(
            ScanFinding.model_validate(
                {
                    "rule_id": issue.get("id"),
                    "severity": issue.get("severity"),
                    "confidence": issue.get("confidence"),
                    "path": location.get("file"),
                    "line": location.get("start_line"),
                    "finding": issue.get("finding"),
                }
            )
        )
    return tuple(result)


def normalize(raw: str, code: int) -> tuple[str, bool]:
    value = strict_json(raw)
    if not isinstance(value, dict):
        raise ValueError("Scanner report must be an object")
    metadata = value.get("metadata")
    completeness = value.get("analysis_completeness")
    risk = value.get("risk_assessment")
    if not all(isinstance(item, dict) for item in (metadata, completeness, risk)):
        raise ValueError("Scanner report is missing required metadata")
    assert isinstance(metadata, dict) and isinstance(completeness, dict)
    assert isinstance(risk, dict)
    if metadata.get("skillspector_version") != VERSION:
        raise ValueError("Scanner report version mismatch")
    if metadata.get("llm_requested") is not False:
        raise ValueError("Scanner report does not establish static-only mode")
    if metadata.get("meta_analysis_applied") is not False:
        raise ValueError("Unexpected semantic analysis")
    if metadata.get("inference_usage") != []:
        raise ValueError("Unexpected scanner inference accounting")
    recommendation = risk.get("recommendation")
    if recommendation not in ("SAFE", "CAUTION", "DO_NOT_INSTALL"):
        raise ValueError("Unknown scanner recommendation")
    findings(value.get("issues"))
    if value.get("execution_successful") is not True or code not in (0, 1):
        raise ValueError("Scanner execution failed")
    if completeness.get("is_complete") is not True:
        raise ValueError("Scanner analysis is incomplete")
    if completeness.get("status") != "complete":
        raise ValueError("Scanner completeness fields disagree")
    total = completeness.get("total_components")
    scanned = completeness.get("scanned_components")
    if (
        type(total) is not int
        or type(scanned) is not int
        or total < 1
        or scanned != total
        or completeness.get("execution_successful") is not True
        or completeness.get("coverage_percent") != 100
        or completeness.get("partially_inspected_files") != 0
        or completeness.get("entirely_uninspected_files") != 0
    ):
        raise ValueError("Scanner coverage contradicts complete analysis")
    if code == 1 and recommendation == "SAFE":
        raise ValueError("SAFE recommendation disagrees with scanner exit status")
    assert isinstance(recommendation, str)
    return recommendation, True


class SkillSpector:
    def __init__(self, python: Path | None = None) -> None:
        self.python = (
            python or Path("integrations/skillspector/.venv/bin/python")
        ).absolute()

    def doctor(self, directory: Path) -> dict[str, JsonValue]:
        code, out, err, error = invoke(self.python, ["doctor"], directory)
        if error or code:
            raise ValueError(error or err.decode("utf-8", errors="replace"))
        data = strict_json(out.decode("utf-8"))
        if data != {"version": VERSION, "commit": PIN}:
            raise ValueError("Scanner identity mismatch")
        lock = self.python.parent.parent.parent / "uv.lock"
        return {
            "version": VERSION,
            "commit": PIN,
            "python": str(self.python),
            "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest()
            if lock.is_file()
            else None,
        }

    def scan(self, content: bytes, directory: Path) -> ScanResult:
        directory.mkdir()
        snapshot = directory / "SKILL.md"
        snapshot.write_bytes(content)
        started = time.monotonic()
        code = None
        recommendation = None
        complete = False
        status: Literal["admitted", "blocked", "error"] = "error"
        error = None
        raw_digest = None
        normalized_findings: tuple[ScanFinding, ...] = ()
        try:
            if len(content) > MAX_INPUT or not content.decode("utf-8").strip():
                raise ValueError("Invalid skill input size or encoding")
            identity = self.doctor(directory)
            atomic_json(directory / "scanner-identity.json", identity)
            code, stdout, stderr, error = invoke(
                self.python,
                [
                    str(snapshot.absolute()),
                    str((directory / "raw-report.json").absolute()),
                ],
                directory,
                timeout=max(0.0, 60 - (time.monotonic() - started)),
            )
            (directory / "stdout.txt").write_bytes(stdout)
            (directory / "stderr.txt").write_bytes(stderr)
            if error:
                raise ValueError(error)
            raw = directory / "raw-report.json"
            regular(raw)
            if raw.stat().st_size + len(stdout) + len(stderr) > MAX_OUTPUT:
                raise ValueError("Scanner output exceeds 4 MiB")
            recommendation, complete = normalize(raw.read_text(encoding="utf-8"), code)
            parsed = strict_json(raw.read_text(encoding="utf-8"))
            assert isinstance(parsed, dict)
            normalized_findings = findings(parsed.get("issues"))
            raw_digest = hashlib.sha256(raw.read_bytes()).hexdigest()
            if snapshot.read_bytes() != content:
                raise ValueError("Scanner input snapshot changed")
            status = "admitted" if recommendation == "SAFE" else "blocked"
        except (OSError, ValueError) as exc:
            error = f"{type(exc).__name__}: {exc}"
        result = ScanResult(
            engine="SkillSpector",
            commit=PIN,
            version=VERSION,
            input_sha256=hashlib.sha256(content).hexdigest(),
            status=status,
            recommendation=recommendation,
            complete=complete,
            exit_code=code,
            elapsed_seconds=time.monotonic() - started,
            error=error,
            raw_sha256=raw_digest,
            findings=normalized_findings,
        )
        atomic_json(directory / "scan.json", result.model_dump(mode="json"))
        return result
