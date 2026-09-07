"""Deterministically rebuild Markdown from validated, already-captured JSON."""

import json
import os
from pathlib import Path
from typing import Literal
from uuid import uuid4

from agent_fault_lab.comparison import Comparison, render_comparison
from agent_fault_lab.evaluation import Evaluation
from agent_fault_lab.experiments import Observation
from agent_fault_lab.reporting import render_run_report

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
        comparison = Comparison.model_validate_json(_read_evidence(comparison_path))
        return "comparison", render_comparison(comparison)

    evaluation = Evaluation.model_validate_json(_read_evidence(evaluation_path))
    observation_path = directory / "observation.json"
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
