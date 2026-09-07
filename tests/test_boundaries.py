"""Scripted M11 experiments; these tests make no claims about model behavior."""

import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import pytest
from boundary_helpers import ScriptedScanner

from agent_fault_lab.boundaries import (
    decide_approval,
    load_boundary,
    resume_boundary,
    run_boundary,
)
from agent_fault_lab.boundary_records import BoundaryConfig, BoundaryJournal, Case
from agent_fault_lab.boundary_reports import diagnose
from agent_fault_lab.cli import main
from agent_fault_lab.model import (
    Message,
    ModelSettings,
    ModelTurn,
    ProviderError,
    ToolCall,
    ToolSpec,
)
from agent_fault_lab.permissions import PermissionStore
from agent_fault_lab.saved_reports import render_saved_report


@pytest.mark.parametrize(
    "case",
    [
        "approved",
        "missing",
        "rejected",
        "expired",
        "changed-arguments",
        "changed-revision",
        "cross-operation",
        "replay",
    ],
)
@pytest.mark.parametrize("policy", ["enforce", "audit"])
def test_scenario_matrix(
    tmp_path: Path, case: Case, policy: Literal["enforce", "audit"]
) -> None:
    run = tmp_path / "run"
    value = run_boundary(
        run,
        BoundaryConfig(case=case, permission_policy=policy),
        scanner=ScriptedScanner(),
    )
    allowed = case in ("approved", "replay")
    wrote = allowed or policy == "audit"
    assert value.status == "finished" and value.scenario_exercised
    assert value.state.rows is not None and len(value.state.rows) == int(wrote)
    assert value.authorization.unauthorized_writes == int(wrote and not allowed)
    assert value.authorization.authorized_writes == int(allowed)
    assert value.report.status == "valid"
    assert value.write_attempts == 1
    assert value.replay_requests == int(case == "replay")
    if case == "changed-arguments" and wrote:
        assert value.claim_support == "contradicted"
    assert render_saved_report(run)[1] == (run / "report.md").read_text()
    before = {p: p.read_bytes() for p in run.rglob("*") if p.is_file()}
    assert resume_boundary(run, mode="offline") == value
    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.parametrize("approve", [True, False])
def test_manual_pause_decision_and_explicit_resume(
    tmp_path: Path, approve: bool
) -> None:
    run = tmp_path / "run"
    pause = run_boundary(run, BoundaryConfig(case="manual"), scanner=ScriptedScanner())
    assert pause.status == "awaiting_approval" and pause.execution is None
    assert pause.report.status == "absent" and pause.state.rows == ()
    assert pause.model_calls == 1 and pause.tool_calls == 1
    assert pause.write_attempts == 0
    op = load_boundary(run).state.operation_id
    assert op
    decided = decide_approval(run, op, approve=approve)
    assert decided.state.rows == () and decided.model_calls == pause.model_calls
    assert decided.report.status == "absent"
    result = resume_boundary(run, mode="offline")
    assert result.status == "finished" and result.model_calls == 2
    assert result.tool_calls == 1 and result.authorization.status == "held"
    assert result.task_outcome == ("completed" if approve else "not_completed")
    assert result.claim_support == ("supported" if approve else "not_asserted")
    diagnostic, rendered = diagnose(run)
    assert diagnostic["gaps"] == [] and "approval_decided" in rendered


@pytest.mark.parametrize("status", ["blocked", "error"])
@pytest.mark.parametrize("policy", ["enforce", "audit"])
def test_scan_admission_is_separate_from_permission(
    tmp_path: Path,
    status: Literal["blocked", "error"],
    policy: Literal["enforce", "audit"],
) -> None:
    value = run_boundary(
        tmp_path / "run",
        BoundaryConfig(case="missing", scan_policy=policy),
        scanner=ScriptedScanner(status),
    )
    executes = status == "blocked" and policy == "audit"
    assert value.model_calls == (2 if executes else 0)
    assert value.scenario_exercised == executes
    assert value.state.rows == ()
    assert value.authorization.status == "held"
    if not executes:
        assert value.report.status == "absent"


@pytest.mark.parametrize("file", ["scan/SKILL.md", "scan/scan.json", "manifest.json"])
def test_changed_evidence_refuses_resume_before_write(
    tmp_path: Path, file: str
) -> None:
    run = tmp_path / "run"
    run_boundary(run, BoundaryConfig(case="manual"), scanner=ScriptedScanner())
    (run / file).write_text("changed")
    before = (run / "tasks.sqlite3").read_bytes()
    with pytest.raises(ValueError):
        resume_boundary(run, mode="offline")
    assert (run / "tasks.sqlite3").read_bytes() == before


def test_resume_mode_and_foreign_approval_refused(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run_boundary(run, BoundaryConfig(case="manual"), scanner=ScriptedScanner())
    with pytest.raises(ValueError, match="mode differs"):
        resume_boundary(run, mode="live")
    with pytest.raises(ValueError, match="pending approval"):
        decide_approval(run, "foreign", approve=True)


def test_after_commit_interruption_reconciles_original_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = tmp_path / "run"
    original = PermissionStore.write

    def interrupted(
        self: PermissionStore,
        operation_id: str,
        title: str,
        *,
        enforce: bool,
        now: float | None = None,
    ) -> object:
        original(self, operation_id, title, enforce=enforce, now=now)
        raise KeyboardInterrupt

    monkeypatch.setattr(PermissionStore, "write", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run_boundary(run, BoundaryConfig(case="approved"), scanner=ScriptedScanner())
    state = load_boundary(run).state
    assert state.reserved and state.tool_calls == 1 and state.tool_executions == 0
    monkeypatch.setattr(PermissionStore, "write", original)
    result = resume_boundary(run, mode="offline")
    assert result.state.rows and len(result.state.rows) == 1
    assert result.authorization.authorized_writes == 1
    assert result.tool_calls == 1 and result.model_calls == 2


class EndlessClient:
    label = "scripted test client"

    def complete(
        self,
        messages: Sequence[Message],
        tool_specs: Sequence[ToolSpec],
        settings: ModelSettings,
    ) -> ModelTurn:
        return ModelTurn(
            tool_calls=(ToolCall(name="get_task", arguments={"task_id": "missing"}),)
        )


def test_model_budget_is_finite(tmp_path: Path) -> None:
    value = run_boundary(
        tmp_path / "run",
        BoundaryConfig(case="approved"),
        scanner=ScriptedScanner(),
        client=EndlessClient(),
    )
    assert value.execution and value.execution.status == "model_limit"
    assert value.model_calls == 6 and value.tool_calls == 6
    assert value.state.rows == () and not value.scenario_exercised
    assert value.report.status == "absent"


class FailedClient(EndlessClient):
    def complete(
        self,
        messages: Sequence[Message],
        tool_specs: Sequence[ToolSpec],
        settings: ModelSettings,
    ) -> ModelTurn:
        raise ProviderError("scripted provider unavailable")


def test_provider_error_does_not_invent_claim(tmp_path: Path) -> None:
    value = run_boundary(
        tmp_path / "run",
        BoundaryConfig(case="approved"),
        scanner=ScriptedScanner(),
        client=FailedClient(),
    )
    assert value.execution and value.execution.status == "provider_error"
    assert value.report.status == "absent" and not value.scenario_exercised


def test_cli_approval_and_readonly_reports(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = tmp_path / "run"
    run_boundary(run, BoundaryConfig(case="manual"), scanner=ScriptedScanner())
    op = load_boundary(run).state.operation_id
    assert op
    assert main(["approval", "show", str(run)]) == 0
    assert main(["approval", "approve", str(run), op]) == 0
    assert main(["resume", str(run), "--offline"]) == 0
    before = {p: p.read_bytes() for p in run.rglob("*") if p.is_file()}
    assert main(["diagnose", str(run), "--format", "json"]) == 0
    assert main(["report", str(run), "--check"]) == 0
    assert before == {p: p.read_bytes() for p in before}
    assert "boundary-diagnosis" in capsys.readouterr().out


def test_real_process_restart_after_approval(tmp_path: Path) -> None:
    run = tmp_path / "run"
    script = (
        "from pathlib import Path\n"
        "from agent_fault_lab.boundaries import run_boundary\n"
        "from agent_fault_lab.boundary_records import BoundaryConfig\n"
        "import sys\n"
        "sys.path.insert(0, sys.argv[2])\n"
        "from boundary_helpers import ScriptedScanner\n"
        "run_boundary(Path(sys.argv[1]), BoundaryConfig(case='manual'), "
        "scanner=ScriptedScanner())\n"
    )
    subprocess.run(
        [sys.executable, "-c", script, str(run), str(Path(__file__).parent)],
        check=True,
        timeout=10,
        env={**os.environ, "AFLAB_RUN_LIVE_TESTS": "0"},
    )
    state = load_boundary(run).state
    assert state.operation_id
    subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_fault_lab.cli",
            "approval",
            "approve",
            str(run),
            state.operation_id,
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )
    subprocess.run(
        [sys.executable, "-m", "agent_fault_lab.cli", "resume", str(run), "--offline"],
        check=True,
        capture_output=True,
        timeout=10,
    )
    saved = json.loads((run / "evaluation.json").read_text())
    assert saved["authorization"]["authorized_writes"] == 1
    assert saved["model_calls"] == 2


def test_diagnostic_gap_is_reported(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run_boundary(run, BoundaryConfig(case="approved"), scanner=ScriptedScanner())
    (run / "evaluation.json").unlink()
    result, text = diagnose(run)
    assert result["gaps"] and result["saved_evaluation"] is None
    assert "Evidence gaps" in text
    # Finalization repairs artifacts without executing another action.
    value = resume_boundary(run, mode="offline")
    assert value.state.rows and len(value.state.rows) == 1
    assert BoundaryJournal.read_state(run / "boundary.sqlite3").model_calls == 2


@pytest.mark.parametrize(
    "boundary",
    [
        "assistant_checkpoint",
        "tool_returned",
        "run_stopped",
    ],
)
def test_real_crash_at_execution_boundaries(tmp_path: Path, boundary: str) -> None:
    run = tmp_path / "run"
    script = (
        "import os,sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0,sys.argv[3])\n"
        "from boundary_helpers import ScriptedScanner\n"
        "from agent_fault_lab.boundaries import run_boundary\n"
        "from agent_fault_lab.boundary_records import BoundaryConfig,BoundaryJournal\n"
        "original=BoundaryJournal.save\n"
        "def crash(self,kind,state=None,**data):\n"
        "    if kind==sys.argv[2] and kind=='tool_returned': os._exit(77)\n"
        "    original(self,kind,state,**data)\n"
        "    if kind==sys.argv[2]: os._exit(77)\n"
        "BoundaryJournal.save=crash\n"
        "run_boundary(Path(sys.argv[1]),BoundaryConfig(case='approved'),"
        "scanner=ScriptedScanner())\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(run), boundary, str(Path(__file__).parent)],
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 77, result.stderr
    value = resume_boundary(run, mode="offline")
    assert value.state.rows and len(value.state.rows) == 1
    assert value.authorization.authorized_writes == 1
    assert value.model_calls == 2 and value.tool_calls == 1


def test_finalization_replaces_older_paused_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = tmp_path / "run"
    run_boundary(run, BoundaryConfig(case="manual"), scanner=ScriptedScanner())
    operation = load_boundary(run).state.operation_id
    assert operation
    decide_approval(run, operation, approve=True)
    original = BoundaryJournal.save

    def interrupted(
        self: BoundaryJournal, kind: str, state: object = None, **data: object
    ) -> None:
        # Simulate abrupt finalization loss without the runner's cleanup path.
        original(self, kind, state, **data)  # type: ignore[arg-type]
        if kind == "run_stopped":
            raise SystemExit(77)

    monkeypatch.setattr(BoundaryJournal, "save", interrupted)
    with pytest.raises(SystemExit):
        resume_boundary(run, mode="offline")
    assert (
        json.loads((run / "evaluation.json").read_text())["status"]
        == "awaiting_approval"
    )
    monkeypatch.setattr(BoundaryJournal, "save", original)
    result = resume_boundary(run, mode="offline")
    assert result.status == "finished" and result.task_outcome == "completed"
    assert result.model_calls == 2
