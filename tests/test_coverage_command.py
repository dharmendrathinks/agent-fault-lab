"""Coverage reporting must not turn a failed test run into a successful check."""

import runpy
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "failed_command", [None, "erase", "run", "combine", "json", "xml", "report"]
)
def test_coverage_command_preserves_failures(
    monkeypatch: pytest.MonkeyPatch, failed_command: str | None
) -> None:
    commands: list[str] = []

    def fake_run(
        arguments: list[str], **options: object
    ) -> subprocess.CompletedProcess[str]:
        command = arguments[3]
        commands.append(command)
        environment = options["env"]
        assert isinstance(environment, dict)
        assert environment["AFLAB_RUN_LIVE_TESTS"] == "0"
        assert environment["AFLAB_LIVE_TEST_COMMAND"] == "0"
        if command == "run":
            assert arguments[4] == f"--source={Path.cwd() / 'src/agent_fault_lab'}"
        return subprocess.CompletedProcess(
            arguments, 1 if command == failed_command else 0
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    module = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "scripts/check_coverage.py")
    )
    assert module["main"]() == (1 if failed_command else 0)
    if failed_command not in ("erase", "combine"):
        assert commands == ["erase", "run", "combine", "json", "xml", "report"]
