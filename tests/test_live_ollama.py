"""Explicit local-model smoke test; skipped unless the operator opts in."""

import json
import os
from pathlib import Path

import pytest

from agent_fault_lab.cli import main
from agent_fault_lab.evaluation import Evaluation

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("AFLAB_RUN_LIVE_TESTS") != "1"
        or os.environ.get("AFLAB_LIVE_TEST_COMMAND") != "1",
        reason="requires the explicit AFLAB_RUN_LIVE_TESTS=1 make live-test path",
    ),
]


def test_local_ollama_records_an_evaluable_run(tmp_path: Path) -> None:
    """Check the harness, not model task success or general reliability."""
    output = tmp_path / "live-run"
    assert main(["run", "--output", str(output)]) == 0
    manifest = json.loads((output / "manifest.json").read_text())
    evaluation = Evaluation.model_validate_json(
        (output / "evaluation.json").read_text()
    )
    assert manifest["client"] == "ollama-local"
    assert manifest["prerequisites"]["cloud_disabled"] is True
    assert manifest["prerequisites"]["problems"] == []
    assert evaluation.execution.status != "provider_error"
    assert (output / "trace.jsonl").is_file()
    assert (output / "report.md").is_file()
