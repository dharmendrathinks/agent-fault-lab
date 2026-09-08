"""Deterministically rebuild Markdown from validated, already-captured JSON."""

import json
import os
from pathlib import Path
from typing import Literal
from uuid import uuid4

from agent_fault_lab.comparison import Comparison, render_comparison
from agent_fault_lab.evaluation import Evaluation
from agent_fault_lab.experiments import Observation
from agent_fault_lab.process_reports import (
    ProcessComparison,
    ProcessObservation,
    render_process_comparison,
    render_process_report,
)
from agent_fault_lab.reliability_reports import (
    ReliabilityComparison,
    ReliabilityObservation,
    render_reliability_comparison,
    render_reliability_report,
)
from agent_fault_lab.reporting import render_run_report
from agent_fault_lab.retry_reports import (
    RetryComparison,
    RetryObservation,
    render_retry_comparison,
    render_retry_report,
)

type ReportKind = Literal["run", "comparison"]


def _present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _read_evidence(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Evidence must be a regular, non-symlink file: {path.name}")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ValueError(f"Non-finite JSON number: {value}")

    raw = path.read_text(encoding="utf-8")
    json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    return raw


def render_saved_report(directory: Path) -> tuple[ReportKind, str]:
    """Read no database or model; validate one unambiguous JSON evidence source."""
    if directory.is_symlink():
        raise ValueError("Run directory must not be a symbolic link")
    if not directory.is_dir():
        raise ValueError(f"Run directory does not exist: {directory}")

    comparison_path = directory / "comparison.json"
    evaluation_path = directory / "evaluation.json"
    has_comparison = _present(comparison_path)
    has_evaluation = _present(evaluation_path)
    if has_comparison == has_evaluation:
        raise ValueError(
            "Expected exactly one report source: comparison.json or evaluation.json"
        )

    if has_comparison:
        raw = _read_evidence(comparison_path)
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and parsed.get("artifact") == "evaluator-audit":
            from agent_fault_lab.evaluator_audit import Audit, render_audit

            return "comparison", render_audit(Audit.model_validate_json(raw))
        if isinstance(parsed, dict) and parsed.get("artifact") == "study-comparison":
            from agent_fault_lab.study_records import Study
            from agent_fault_lab.study_reports import render_study

            return "comparison", render_study(Study.model_validate_json(raw))
        if isinstance(parsed, dict) and parsed.get("artifact") == "boundary-comparison":
            from agent_fault_lab.boundary_reports import BoundaryComparison
            from agent_fault_lab.boundary_reports import (
                render_comparison as render_boundary_comparison,
            )

            return "comparison", render_boundary_comparison(
                BoundaryComparison.model_validate_json(raw)
            )
        if (
            isinstance(parsed, dict)
            and parsed.get("artifact") == "execution-comparison"
        ):
            return "comparison", render_process_comparison(
                ProcessComparison.model_validate_json(raw)
            )
        if isinstance(parsed, dict) and parsed.get("artifact") == "retry-comparison":
            retry_comparison = RetryComparison.model_validate_json(raw)
            return "comparison", render_retry_comparison(retry_comparison)
        if isinstance(parsed, dict) and "artifact" in parsed:
            reliability_comparison = ReliabilityComparison.model_validate_json(raw)
            return "comparison", render_reliability_comparison(reliability_comparison)
        comparison = Comparison.model_validate_json(raw)
        return "comparison", render_comparison(comparison)

    raw_evaluation = _read_evidence(evaluation_path)
    parsed = json.loads(raw_evaluation)
    if isinstance(parsed, dict) and parsed.get("artifact") == "boundary-evaluation":
        from agent_fault_lab.boundary_records import BoundaryEvaluation
        from agent_fault_lab.boundary_reports import (
            render_report as render_boundary_report,
        )

        boundary = BoundaryEvaluation.model_validate_json(raw_evaluation)
        runtime_path = directory / "runtime.json"
        if _present(runtime_path):
            from agent_fault_lab.runtime_records import RuntimeResult, render_runtime

            runtime = RuntimeResult.model_validate_json(_read_evidence(runtime_path))
            if runtime.evaluation != boundary:
                raise ValueError("Runtime and evaluation evidence do not match")
            return "run", render_runtime(runtime)
        return "run", render_boundary_report(boundary)
    evaluation = Evaluation.model_validate_json(raw_evaluation)
    observation_path = directory / "observation.json"
    if _present(observation_path):
        raw = _read_evidence(observation_path)
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and parsed.get("artifact") == "execution-run":
            process = ProcessObservation.model_validate_json(raw)
            if process.evaluation != evaluation:
                raise ValueError("Observation and evaluation evidence do not match")
            return "run", render_process_report(process)
        if isinstance(parsed, dict) and parsed.get("artifact") == "retry-run":
            retry = RetryObservation.model_validate_json(raw)
            if retry.evaluation != evaluation:
                raise ValueError("Observation and evaluation evidence do not match")
            return "run", render_retry_report(retry)
        if isinstance(parsed, dict) and "artifact" in parsed:
            reliability = ReliabilityObservation.model_validate_json(raw)
            if reliability.evaluation != evaluation:
                raise ValueError("Observation and evaluation evidence do not match")
            return "run", render_reliability_report(reliability)
    observation = (
        Observation.model_validate_json(_read_evidence(observation_path))
        if _present(observation_path)
        else None
    )
    return "run", render_run_report(evaluation, observation)


def report_matches(directory: Path, rendered: str) -> bool:
    target = directory / "report.md"
    return (
        target.is_file()
        and not target.is_symlink()
        and target.read_text(encoding="utf-8") == rendered
    )


def replace_report(directory: Path, rendered: str) -> Path:
    """Atomically replace only report.md after evidence has fully validated."""
    target = directory / "report.md"
    if target.is_symlink():
        raise ValueError("Refusing to replace a symbolic-link report")
    temporary = directory / f".report.md.{uuid4()}.tmp"
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
