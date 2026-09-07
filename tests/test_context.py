"""M12/M13 scripted machinery; deliberately independent from scanner/model accuracy."""

import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import pytest
from boundary_helpers import ScriptedScanner

from agent_fault_lab.boundaries import load_boundary, resume_boundary, run_boundary
from agent_fault_lab.boundary_cli import comparison_cells
from agent_fault_lab.boundary_evaluation import evaluate
from agent_fault_lab.boundary_records import BoundaryConfig, BoundaryJournal
from agent_fault_lab.boundary_reports import diagnose
from agent_fault_lab.cli import main
from agent_fault_lab.context_cases import (
    M12_CASES,
    M13_CASES,
    SOURCE_ID,
)
from agent_fault_lab.context_runtime import trim_complete_turns
from agent_fault_lab.model import Message, ModelSettings, ModelTurn, ToolCall, ToolSpec
from agent_fault_lab.permissions import PermissionStore
from agent_fault_lab.saved_reports import render_saved_report
from agent_fault_lab.tools import ToolResult


@pytest.mark.parametrize("case", M12_CASES)
@pytest.mark.parametrize("surface", ["skill", "task", "tool"])
@pytest.mark.parametrize("scan_status", ["admitted", "blocked"])
@pytest.mark.parametrize(
    "scan_policy,permission_policy",
    [
        ("audit", "audit"),
        ("audit", "enforce"),
        ("enforce", "audit"),
        ("enforce", "enforce"),
    ],
)
def test_injection_matrix(
    tmp_path: Path,
    case: str,
    surface: Literal["skill", "task", "tool"],
    scan_status: Literal["admitted", "blocked"],
    scan_policy: Literal["audit", "enforce"],
    permission_policy: Literal["audit", "enforce"],
) -> None:
    run = tmp_path / "run"
    result = run_boundary(
        run,
        BoundaryConfig(
            case=case,
            surface=surface,
            scan_policy=scan_policy,
            permission_policy=permission_policy,
        ),
        scanner=ScriptedScanner(scan_status),
    )
    context = result.context
    assert context and result.status != "error", result.error
    attack = not case.endswith("-benign")
    filtered = scan_status == "blocked" and scan_policy == "enforce"
    assert context.delivered == (not filtered)
    assert context.seeded_preserved is True
    assert context.unsafe_attempts == int(attack and not filtered)
    unsafe_write = attack and not filtered and permission_policy == "audit"
    assert context.boundary_violations == int(unsafe_write)
    assert result.authorization.unauthorized_writes == int(unsafe_write)
    assert context.scanner_detected == ((scan_status == "blocked") if attack else None)
    assert context.false_alarm == ((scan_status == "blocked") if not attack else None)
    legitimate = (not attack or filtered) and not (filtered and surface == "skill")
    assert context.legitimate_completed == legitimate
    assert context.new_effects == int(legitimate or unsafe_write)
    if filtered and surface == "skill":
        assert result.model_calls == 0 and result.report.status == "absent"
    assert render_saved_report(run)[1] == (run / "report.md").read_text()


@pytest.mark.parametrize("surface", ["skill", "task", "tool"])
def test_scanner_error_never_delivers_or_executes(
    tmp_path: Path, surface: Literal["skill", "task", "tool"]
) -> None:
    result = run_boundary(
        tmp_path / "run",
        BoundaryConfig(
            case="injection-override",
            surface=surface,
            scan_policy="audit",
            permission_policy="audit",
        ),
        scanner=ScriptedScanner("error"),
    )
    assert result.status == "error" and result.context
    assert result.context.scanner_error and not result.context.delivered
    assert result.context.new_effects == 0 and result.report.status == "absent"
    assert result.context.scanner_detected is None


@pytest.mark.parametrize("case", M13_CASES)
@pytest.mark.parametrize("policy", ["cached", "refresh"])
def test_memory_matrix(
    tmp_path: Path, case: str, policy: Literal["cached", "refresh"]
) -> None:
    run = tmp_path / "run"
    value = run_boundary(
        run, BoundaryConfig(case=case, context_policy=policy), scanner=ScriptedScanner()
    )
    assert value.status == "finished" and value.context
    metrics = value.context
    assert metrics.unsafe_attempts == int(policy == "cached")
    assert metrics.boundary_violations == 0
    assert metrics.authoritative_refreshes == (
        value.model_calls if policy == "refresh" else 0
    )
    assert metrics.model_state_reads == 0
    if case == "memory-changed-policy":
        assert metrics.legitimate_completed is None and metrics.new_effects == 0
    else:
        assert metrics.legitimate_completed == (policy == "refresh")
    if case == "memory-stale-approval":
        assert metrics.stale_grant_exercised == (policy == "cached")
    if case == "memory-poisoned-notes":
        state = load_boundary(run).state
        assert state.context and state.context.original_scan
        assert state.context.original_scan.input_sha256 != state.scan.input_sha256
    if case == "memory-short-history":
        assert metrics.history_messages_removed > 0
        events = BoundaryJournal.events(run / "boundary.sqlite3")
        assert any(
            e.kind == "context_fixture_prepared" and e.data["synthetic_history"]
            for e in events
        )
    assert resume_boundary(run, mode="offline") == value


class ReadsCurrentState:
    label = "scripted voluntary state reader, NOT AI"

    def complete(
        self,
        messages: Sequence[Message],
        tool_specs: Sequence[ToolSpec],
        settings: ModelSettings,
    ) -> ModelTurn:
        assert "get_request_state" in {spec.name for spec in tool_specs}
        tool_messages = [m for m in messages if m.role == "tool"]
        if not tool_messages:
            return ModelTurn(
                tool_calls=(ToolCall(name="get_request_state", arguments={}),)
            )
        result = ToolResult.model_validate_json(tool_messages[-1].content)
        assert isinstance(result.value, dict)
        if tool_messages[-1].tool_name == "get_request_state":
            return ModelTurn(
                tool_calls=(
                    ToolCall(
                        name="create_task", arguments={"title": result.value["title"]}
                    ),
                )
            )
        return ModelTurn(
            content=json.dumps({"status": "completed", "task_id": result.value["id"]})
        )


def test_cached_variant_can_voluntarily_read_current_state(tmp_path: Path) -> None:
    run = tmp_path / "run"
    result = run_boundary(
        run,
        BoundaryConfig(case="memory-stale-title"),
        scanner=ScriptedScanner(),
        client=ReadsCurrentState(),
    )
    assert result.context and result.context.legitimate_completed
    assert result.context.model_state_reads == 1
    assert result.context.authoritative_refreshes == 0
    assert result.context.unsafe_attempts == 0
    assert result.claim_support == "supported"


class SkipsReference:
    label = "scripted client which never reads reference"

    def complete(
        self,
        messages: Sequence[Message],
        tool_specs: Sequence[ToolSpec],
        settings: ModelSettings,
    ) -> ModelTurn:
        return ModelTurn(content='{"status":"unknown","task_id":null}')


def test_unexercised_tool_injection_is_reported(tmp_path: Path) -> None:
    result = run_boundary(
        tmp_path / "run",
        BoundaryConfig(case="injection-canary", surface="tool"),
        scanner=ScriptedScanner(),
        client=SkipsReference(),
    )
    assert result.context and not result.context.delivered
    assert result.context.unsafe_attempts == 0 and result.context.new_effects == 0
    assert not result.scenario_exercised and result.claim_support == "not_asserted"


def test_seed_mutation_and_unauthorized_effect_challenge_evaluator(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    run_boundary(
        run, BoundaryConfig(case="injection-override-benign"), scanner=ScriptedScanner()
    )
    journal = load_boundary(run)
    store = PermissionStore(run / "tasks.sqlite3", journal.state.run_id)
    with store.connection() as conn:
        conn.execute("UPDATE tasks SET title='corrupt seed' WHERE id=?", (SOURCE_ID,))
        conn.execute("INSERT INTO tasks VALUES ('bypassed','unrequested effect')")
    before = store.database.read_bytes()
    evaluated = evaluate(run, journal.state)
    assert evaluated.context and evaluated.context.seeded_preserved is False
    assert evaluated.context.boundary_violations == 2
    assert evaluated.context.legitimate_completed is False
    assert evaluated.claim_support == "contradicted"
    assert before == store.database.read_bytes()


def test_unknown_storage_does_not_become_preserved_seed(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run_boundary(
        run, BoundaryConfig(case="injection-canary"), scanner=ScriptedScanner()
    )
    journal = load_boundary(run)
    (run / "tasks.sqlite3").write_bytes(b"corrupt")
    value = evaluate(run, journal.state)
    assert value.context and value.context.seeded_preserved is None
    assert (
        value.context.new_effects is None and value.context.boundary_violations is None
    )
    assert value.task_outcome == "unknown"


def test_history_shortening_preserves_complete_tool_exchange() -> None:
    messages = (
        Message(role="system", content="system"),
        Message(role="user", content="old"),
        Message(role="assistant", content="old response"),
        Message(role="user", content="new"),
        Message(
            role="assistant",
            tool_calls=(ToolCall(name="get_task", arguments={"task_id": "x"}),),
        ),
        Message(role="tool", tool_name="get_task", call_id="one", content="reply"),
    )
    assert trim_complete_turns(messages) == (messages[0], *messages[3:])
    with pytest.raises(ValueError, match="incomplete"):
        trim_complete_turns(messages[:-1])
    with pytest.raises(ValueError, match="Orphan"):
        trim_complete_turns((messages[0], messages[1], messages[-1]))


def test_comparison_axes_hold_other_configuration_fixed() -> None:
    for case in (*M12_CASES, *M13_CASES):
        config = BoundaryConfig(case=case)
        cells, axes = comparison_cells(config)
        assert len(cells) == (4 if case in M12_CASES else 2)
        for _, variant in cells:
            for key, value in config.model_dump().items():
                if key not in axes:
                    assert variant.model_dump()[key] == value


def test_cli_four_cell_comparison_and_readonly_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent_fault_lab.boundary_cli.SkillSpector", ScriptedScanner)
    # CLI passes its optional interpreter; the fixture accepts status instead.
    monkeypatch.setattr(
        "agent_fault_lab.boundary_cli.SkillSpector", lambda _: ScriptedScanner()
    )
    run = tmp_path / "comparison"
    assert (
        main(
            [
                "boundaries",
                "compare",
                "injection-override",
                "--surface",
                "tool",
                "--offline",
                "--output",
                str(run),
            ]
        )
        == 0
    )
    saved = json.loads((run / "comparison.json").read_text())
    assert len(saved["entries"]) == 4 and len(saved["axes"]) == 2
    assert main(["report", str(run), "--check"]) == 0
    child = run / saved["planned"][0]
    before = {p: p.read_bytes() for p in child.rglob("*") if p.is_file()}
    report, text = diagnose(child)
    assert report["gaps"] == [] and "context_fixture_prepared" in text
    assert before == {p: p.read_bytes() for p in before}


@pytest.mark.parametrize(
    "case", ["injection-override", "memory-stale-title", "memory-poisoned-notes"]
)
def test_process_crash_after_commit_preserves_context_and_single_effect(
    tmp_path: Path, case: str
) -> None:
    run = tmp_path / "run"
    script = (
        "import sys,os\nfrom pathlib import Path\n"
        "sys.path.insert(0,sys.argv[3])\nfrom boundary_helpers import ScriptedScanner\n"
        "from agent_fault_lab.boundaries import run_boundary\n"
        "from agent_fault_lab.boundary_records import BoundaryConfig\n"
        "from agent_fault_lab.permissions import PermissionStore\n"
        "original=PermissionStore.write\n"
        "def crash(self,*args,**kwargs):\n"
        " original(self,*args,**kwargs)\n os._exit(77)\n"
        "PermissionStore.write=crash\n"
        "config=BoundaryConfig(case=sys.argv[2], permission_policy='audit', "
        "context_policy='refresh' if sys.argv[2].startswith('memory-') else 'cached')\n"
        "run_boundary(Path(sys.argv[1]),config,scanner=ScriptedScanner())\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(run), case, str(Path(__file__).parent)],
        timeout=10,
        capture_output=True,
    )
    assert result.returncode == 77, result.stderr
    resumed = resume_boundary(run, mode="offline")
    assert resumed.context and resumed.context.new_effects == 1
    assert resumed.tool_calls == 1 and resumed.model_calls == 2
    assert resume_boundary(run, mode="offline") == resumed


def test_changed_original_memory_scan_refuses_resume(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run_boundary(
        run, BoundaryConfig(case="memory-poisoned-notes"), scanner=ScriptedScanner()
    )
    (run / "scan-original/SKILL.md").write_text("edited")
    with pytest.raises(ValueError, match="Original memory"):
        resume_boundary(run, mode="offline")


def test_scanner_failure_retains_partial_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "agent_fault_lab.boundary_cli.SkillSpector", lambda _: ScriptedScanner("error")
    )
    run = tmp_path / "comparison"
    assert (
        main(
            [
                "boundaries",
                "compare",
                "injection-canary",
                "--offline",
                "--output",
                str(run),
            ]
        )
        == 2
    )
    saved = json.loads((run / "comparison.json").read_text())
    assert saved["status"] == "stopped" and saved["error"]
    assert len(saved["entries"]) == 1 and len(saved["planned"]) == 4
    assert saved["entries"][0]["context"]["scanner_error"] is True
    assert main(["report", str(run), "--check"]) == 0


def test_context_cannot_be_removed_from_checkpoint(tmp_path: Path) -> None:
    from agent_fault_lab.boundary_records import BoundaryEvaluation, BoundaryState

    run = tmp_path / "run"
    result = run_boundary(
        run, BoundaryConfig(case="memory-stale-title"), scanner=ScriptedScanner()
    )
    state = load_boundary(run).state.model_dump(mode="json")
    state["context"] = None
    with pytest.raises(ValueError, match="Context checkpoint"):
        BoundaryState.model_validate_json(json.dumps(state))
    evaluation = result.model_dump(mode="json")
    evaluation["context"] = None
    with pytest.raises(ValueError, match="Context evaluation"):
        BoundaryEvaluation.model_validate_json(json.dumps(evaluation))


def test_authoritative_state_read_preserves_database(tmp_path: Path) -> None:
    store = PermissionStore.create(tmp_path / "tasks.sqlite3", "run", "exact")
    store.configure_request("  new title  ", write_allowed=False, revision=2)
    before = store.database.read_bytes()
    state = store.request_state()
    assert state == {
        "title": "  new title  ",
        "write_allowed": False,
        "request_revision": 2,
        "policy_revision": 2,
    }
    assert store.database.read_bytes() == before


def test_history_rejects_mismatched_tool_reply() -> None:
    with pytest.raises(ValueError, match="does not match"):
        trim_complete_turns(
            (
                Message(role="user", content="read"),
                Message(
                    role="assistant",
                    tool_calls=(ToolCall(name="get_task", arguments={"task_id": "x"}),),
                ),
                Message(role="tool", tool_name="create_task", content="wrong reply"),
            )
        )


def test_comparison_rejects_undeclared_policy_change(tmp_path: Path) -> None:
    from agent_fault_lab.boundary_reports import BoundaryComparison

    config = BoundaryConfig(case="memory-stale-title")
    one = run_boundary(tmp_path / "one", config, scanner=ScriptedScanner())
    two = run_boundary(
        tmp_path / "two",
        config.model_copy(
            update={"context_policy": "refresh", "permission_policy": "audit"}
        ),
        scanner=ScriptedScanner(),
    )
    with pytest.raises(ValueError, match="undeclared"):
        BoundaryComparison(
            case=config.case,
            axes=("context_policy",),
            planned=("cached", "refresh"),
            entries=(one, two),
            status="finished",
        )


@pytest.mark.parametrize("case", ["wrong-title", "disabled", "duplicate"])
def test_write_rechecks_scope_even_with_a_valid_grant(
    tmp_path: Path, case: str
) -> None:
    store = PermissionStore.create(tmp_path / "tasks.sqlite3", "run", "requested")
    store.configure_request("requested", write_allowed=case != "disabled", revision=2)
    title = "wrong" if case == "wrong-title" else "requested"
    if case == "duplicate":
        store.propose("original", title)
        store.decide("original", approve=True)
        assert store.write("original", title, enforce=True).task
    store.propose("new", title)
    store.decide(
        "new", approve=True
    )  # Deliberately overbroad trusted-controller grant.
    denied = store.write("new", title, enforce=True)
    assert denied.task is None and denied.authorized is False
    assert "request scope" in denied.reason
    assert store.proposal("new").consumed_task_id is None


def test_original_scan_error_is_not_hidden_by_clean_replacement(tmp_path: Path) -> None:
    from agent_fault_lab.scanner import ScanResult

    class FailedOriginalScanner(ScriptedScanner):
        def scan(self, content: bytes, directory: Path) -> ScanResult:
            self.status = "error" if directory.name == "scan-original" else "admitted"
            return super().scan(content, directory)

    value = run_boundary(
        tmp_path / "run",
        BoundaryConfig(case="memory-poisoned-notes"),
        scanner=FailedOriginalScanner(),
    )
    assert value.scan.status == "admitted" and value.status == "error"
    assert value.context and value.context.scanner_error and not value.context.delivered
    assert value.model_calls == 0 and value.context.new_effects == 0


@pytest.mark.parametrize("ids", [("z-first", "a-second"), ("a-first", "z-second")])
def test_unauthorized_duplicate_is_counted_once_regardless_of_id_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ids: tuple[str, str]
) -> None:
    identifiers = iter(ids)
    monkeypatch.setattr("agent_fault_lab.permissions.uuid4", lambda: next(identifiers))
    run = tmp_path / "run"
    result = run_boundary(
        run, BoundaryConfig(case="injection-override-benign"), scanner=ScriptedScanner()
    )
    store = PermissionStore(run / "tasks.sqlite3", result.run_id)
    store.propose("extra-operation", result.expected_title)
    store.decide("extra-operation", approve=True)
    extra = store.write("extra-operation", result.expected_title, enforce=False)
    assert extra.task and extra.authorized is False
    evaluated = evaluate(run, load_boundary(run).state)
    assert evaluated.context and evaluated.context.new_effects == 2
    assert evaluated.authorization.unauthorized_writes == 1
    assert evaluated.context.boundary_violations == 1
    assert evaluated.claim_support == "contradicted"
