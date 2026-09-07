"""The public example is real scripted output, not hand-authored model evidence."""

from pathlib import Path

import pytest

from agent_fault_lab.comparison import Comparison
from agent_fault_lab.saved_reports import render_saved_report, report_matches
from examples.capture_example import capture


def test_public_example_is_consistent_and_explicitly_scripted() -> None:
    root = Path(__file__).resolve().parents[1] / "examples/evidence/dropped-write"
    comparison = Comparison.model_validate_json((root / "comparison.json").read_text())
    assert comparison.client == "scripted-test-client (NOT an AI model)"
    assert comparison.status == "finished"
    assert len(comparison.entries) == len(comparison.planned) == 4
    assert [
        entry.observation.evaluation.false_success for entry in comparison.entries
    ] == [False, False, True, False]
    assert [
        entry.observation.evaluation.task_outcome for entry in comparison.entries
    ] == ["completed", "completed", "not_completed", "not_completed"]
    for entry in comparison.entries:
        assert entry.observation.metrics.output_tokens is None
        child = root / entry.spec.directory
        assert report_matches(child, render_saved_report(child)[1])
    assert report_matches(root, render_saved_report(root)[1])


def test_capture_uses_fresh_directory_and_only_portable_artifacts(
    tmp_path: Path,
) -> None:
    output = tmp_path / "capture"
    capture(output)
    assert report_matches(output, render_saved_report(output)[1])
    files = [path for path in output.rglob("*") if path.is_file()]
    assert len(files) == 14
    assert {path.name for path in files} == {
        "comparison.json",
        "evaluation.json",
        "observation.json",
        "report.md",
    }
    with pytest.raises(FileExistsError):
        capture(output)
