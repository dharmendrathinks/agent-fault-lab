"""Saved reports are validated, deterministic, atomic, and offline."""

import json
from pathlib import Path

import pytest

from agent_fault_lab.cli import main
from agent_fault_lab.ollama_adapter import OllamaClient
from agent_fault_lab.saved_reports import replace_report


def test_run_report_check_and_regeneration_use_only_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "run"
    assert main(["demo", "--offline", "--output", str(output)]) == 0
    expected = (output / "report.md").read_text()
    (output / "tasks.sqlite3").unlink()  # Regeneration is not a new evaluation.
    (output / "report.md").write_text("stale\n")

    def no_model(self: OllamaClient, model: str = "unused") -> object:
        raise AssertionError("report regeneration must not inspect Ollama")

    monkeypatch.setattr(OllamaClient, "inspect", no_model)
    assert main(["report", str(output), "--check"]) == 1
    assert (output / "report.md").read_text() == "stale\n"
    assert main(["report", str(output)]) == 0
    assert (output / "report.md").read_text() == expected
    assert main(["report", str(output), "--check"]) == 0


def test_comparison_report_regenerates_exactly(tmp_path: Path) -> None:
    output = tmp_path / "comparison"
    assert (
        main(
            [
                "compare",
                "--offline",
                "--trials",
                "1",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    expected = (output / "report.md").read_text()
    (output / "report.md").unlink()
    assert main(["report", str(output), "--check"]) == 1
    assert main(["report", str(output)]) == 0
    assert (output / "report.md").read_text() == expected


def test_mismatched_observation_does_not_replace_report(tmp_path: Path) -> None:
    output = tmp_path / "run"
    assert main(["demo", "--offline", "--output", str(output)]) == 0
    target = output / "report.md"
    before = target.read_bytes()
    observation_path = output / "observation.json"
    observation = json.loads(observation_path.read_text())
    observation["evaluation"]["task_reason"] = "tampered mismatch"
    observation_path.write_text(json.dumps(observation))
    assert main(["report", str(output)]) == 2
    assert target.read_bytes() == before


@pytest.mark.parametrize("sources", [(), ("evaluation.json", "comparison.json")])
def test_missing_or_ambiguous_source_fails_closed(
    tmp_path: Path, sources: tuple[str, ...]
) -> None:
    output = tmp_path / "evidence"
    output.mkdir()
    for source in sources:
        (output / source).write_text("{}")
    assert main(["report", str(output)]) == 2
    assert not (output / "report.md").exists()


def test_invalid_json_does_not_replace_report(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    output.mkdir()
    (output / "evaluation.json").write_text("not json")
    (output / "report.md").write_text("keep me\n")
    assert main(["report", str(output)]) == 2
    assert (output / "report.md").read_text() == "keep me\n"


def test_report_symlink_is_never_replaced(tmp_path: Path) -> None:
    output = tmp_path / "run"
    assert main(["demo", "--offline", "--output", str(output)]) == 0
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n")
    (output / "report.md").unlink()
    (output / "report.md").symlink_to(outside)
    assert main(["report", str(output)]) == 2
    assert outside.read_text() == "outside\n"


@pytest.mark.parametrize("filename", ["evaluation.json", "observation.json"])
@pytest.mark.parametrize("kind", ["symlink", "dangling", "directory"])
def test_evidence_requires_regular_files(
    tmp_path: Path, filename: str, kind: str
) -> None:
    output = tmp_path / "run"
    assert main(["demo", "--offline", "--output", str(output)]) == 0
    before = (output / "report.md").read_bytes()
    evidence = output / filename
    outside = tmp_path / filename
    evidence.rename(outside)
    if kind == "directory":
        evidence.mkdir()
    else:
        evidence.symlink_to(outside if kind == "symlink" else tmp_path / "missing")
    assert main(["report", str(output)]) == 2
    assert (output / "report.md").read_bytes() == before


@pytest.mark.parametrize(
    "replacement",
    [
        '"schema_version": 1, "schema_version": 1',
        '"schema_version": NaN',
        '"schema_version": 99',
    ],
)
def test_ambiguous_or_unsupported_json_preserves_report(
    tmp_path: Path, replacement: str
) -> None:
    output = tmp_path / "run"
    assert main(["demo", "--offline", "--output", str(output)]) == 0
    before = (output / "report.md").read_bytes()
    evidence = output / "evaluation.json"
    raw = evidence.read_text()
    assert '"schema_version": 1' in raw
    evidence.write_text(raw.replace('"schema_version": 1', replacement, 1))
    assert main(["report", str(output)]) == 2
    assert (output / "report.md").read_bytes() == before


def test_symlink_run_directory_is_rejected(tmp_path: Path) -> None:
    output = tmp_path / "run"
    assert main(["demo", "--offline", "--output", str(output)]) == 0
    linked = tmp_path / "linked"
    linked.symlink_to(output, target_is_directory=True)
    assert main(["report", str(linked), "--check"]) == 2


def test_evaluation_only_report_remains_supported(tmp_path: Path) -> None:
    output = tmp_path / "run"
    assert main(["demo", "--offline", "--output", str(output)]) == 0
    (output / "observation.json").unlink()
    assert main(["report", str(output)]) == 0
    assert main(["report", str(output), "--check"]) == 0


def test_atomic_replace_failure_preserves_report_and_removes_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "report.md"
    target.write_text("original\n")

    def failed_replace(source: Path, destination: Path) -> None:
        assert source.read_text() == "replacement\n"
        raise OSError("simulated replacement failure")

    monkeypatch.setattr("agent_fault_lab.saved_reports.os.replace", failed_replace)
    with pytest.raises(OSError, match="simulated replacement failure"):
        replace_report(tmp_path, "replacement\n")
    assert target.read_text() == "original\n"
    assert list(tmp_path.glob(".report.md.*.tmp")) == []
