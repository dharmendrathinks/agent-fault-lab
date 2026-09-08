"""M14 matched design, real offline execution and durable partial inventories."""

import json
from pathlib import Path

import pytest

from agent_fault_lab.cli import main
from agent_fault_lab.experiments import Observation
from agent_fault_lab.journal import atomic_json
from agent_fault_lab.model import ToolCall
from agent_fault_lab.retry_reports import RetryObservation
from agent_fault_lab.saved_reports import render_saved_report, report_matches
from agent_fault_lab.studies import read_study, reconcile, resume, run, save
from agent_fault_lab.study_child import execute
from agent_fault_lab.study_records import Entry, Study, StudyPlan, plan, schedule
from agent_fault_lab.study_reports import facts, render_study, wilson
from agent_fault_lab.tools import ToolDelivery
from agent_fault_lab.trace import Recorder
from agent_fault_lab.workflow import run_workflow


@pytest.mark.parametrize(
    "preset,expected",
    [
        ("claims", 24),
        ("retries", 24),
        ("approvals", 12),
        ("injection", 12),
        ("context", 6),
        ("semantic-admission", 14),
        ("scanner", 50),
    ],
)
def test_manifest_schedule_roundtrip(preset: str, expected: int) -> None:
    design = plan(preset)
    assert len(design.slots) == expected
    assert StudyPlan.model_validate_json(design.model_dump_json()) == design
    assert len({s.directory for s in design.slots}) == expected
    for case in {slot.case for slot in design.slots}:
        cells = [
            s
            for s in design.slots
            if s.case == case and s.participant not in ("workflow", "probe")
        ]
        assert cells[0].policy == cells[3].policy == cells[4].policy
        assert cells[1].policy == cells[2].policy == cells[5].policy


def test_seed_controls_order_and_not_cell_membership() -> None:
    a, b = schedule("scanner", 3, 42), schedule("scanner", 3, 43)
    assert a != b
    assert {(s.repetition, s.case, s.policy, s.participant) for s in a} == {
        (s.repetition, s.case, s.policy, s.participant) for s in b
    }


@pytest.mark.parametrize(
    "change", ["order", "payload", "axis", "settings", "version", "budget"]
)
def test_reject_changed_design(change: str) -> None:
    value = json.loads(plan("claims").model_dump_json())
    if change == "order":
        value["slots"] = list(reversed(value["slots"]))
    elif change == "payload":
        value["payloads"]["healthy"] = "changed"
    elif change == "axis":
        value["axis"] = "scanner_profile"
    elif change == "settings":
        value["settings"]["temperature"] = 1.0
    elif change == "version":
        value["schema_version"] = True
    else:
        value["budget_seconds"] = float("nan")
    with pytest.raises(ValueError):
        StudyPlan.model_validate_json(json.dumps(value))


def test_real_claim_study_preserves_detection_without_recovery(tmp_path: Path) -> None:
    directory = tmp_path / "study"
    study = run(plan("claims", 1), directory, "offline")
    assert len(study.entries) == 8
    assert all(entry.status == "completed" for entry in study.entries)
    baseline = next(
        e
        for e in study.entries
        if e.slot.case == "dropped-write"
        and e.slot.policy == "baseline"
        and e.slot.participant == "agent"
    )
    treatment = next(
        e
        for e in study.entries
        if e.slot.case == "dropped-write"
        and e.slot.policy == "read-back"
        and e.slot.participant == "agent"
    )
    assert facts(baseline)["claim"] == "contradicted"
    assert facts(treatment)["task"] == "not_completed"
    assert not facts(treatment)["completion_claim"]
    workflows = [e for e in study.entries if e.slot.participant == "workflow"]
    assert all(facts(e)["model_calls"] == 0 for e in workflows)
    assert report_matches(directory, render_saved_report(directory)[1])
    assert resume(directory, "offline") == study
    assert main(["report", str(directory), "--check"]) == 0
    original = (directory / "comparison.json").read_bytes()
    with pytest.raises(ValueError, match="mode"):
        resume(directory, "live")
    assert (directory / "comparison.json").read_bytes() == original


def test_workflow_does_not_hide_duplicate_effects(tmp_path: Path) -> None:
    design = plan("retries", 1)
    results = []
    for slot in design.slots:
        if slot.participant == "workflow" and slot.case == "lost-reply-once":
            results.append(execute(design, slot, "offline", tmp_path / slot.directory))
    assert len(results) == 2
    for result in results:
        evidence = result.evidence
        assert isinstance(evidence, RetryObservation)
        assert evidence.metrics.model_calls == 0
        assert evidence.retry.fault_activations == 1
        assert evidence.evaluation.report.claim is not None
        assert evidence.evaluation.report.claim.status == "completed"
        assert evidence.evaluation.task_outcome == (
            "completed" if result.slot.policy == "retry-idempotent" else "not_completed"
        )


class Responses:
    def __init__(self, values: list[str]) -> None:
        self.values = iter(values)
        self.calls: list[ToolCall] = []

    def execute(self, call: ToolCall, call_id: str) -> ToolDelivery:
        self.calls.append(call)
        return ToolDelivery(content=next(self.values), executed=True)


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        '{"ok":true,"value":{"id":5,"title":"  Exact  "}}',
        '{"ok":false,"error":"response lost","executed":true}',
    ],
)
def test_workflow_unknown_on_unusable_create_response(response: str) -> None:
    executor = Responses([response])
    result = run_workflow(executor, "  Exact  ", Recorder())
    assert json.loads(result.final_content or "{}")["status"] == "unknown"
    assert len(executor.calls) == 1
    assert executor.calls[0].arguments == {"title": "  Exact  "}


def test_workflow_reads_exact_identifier_and_checks_matching_record() -> None:
    executor = Responses(
        [
            '{"ok":true,"value":{"id":"  id  ","title":"Exact"}}',
            '{"ok":true,"value":{"id":"wrong","title":"Exact"}}',
        ]
    )
    result = run_workflow(executor, "Exact", Recorder())
    assert executor.calls[1].arguments == {"task_id": "  id  "}
    assert json.loads(result.final_content or "{}")["status"] == "unknown"


def test_deadline_retains_unstarted_and_unknown_storage(tmp_path: Path) -> None:
    directory = tmp_path / "study"
    study = run(plan("claims", 1, budget_seconds=0.001), directory, "offline")
    assert study.entries[0].status == "interrupted"
    assert study.entries[0].inspection is not None
    assert study.entries[0].inspection.rows is None
    assert all(e.status == "unstarted" for e in study.entries[1:])
    assert study.active_seconds >= study.plan.budget_seconds
    assert resume(directory, "offline") == study
    assert "0 known pairs; 1 excluded" in render_study(study)


def initial(directory: Path) -> Study:
    directory.mkdir()
    design = plan("claims", 1)
    atomic_json(directory / "plan.json", design.model_dump(mode="json"))
    return Study(
        plan=design,
        plan_digest=design.digest,
        mode="offline",
        provenance={},
        entries=tuple(Entry(slot=s) for s in design.slots),
    )


def test_recovery_preserves_committed_child_without_replaying(tmp_path: Path) -> None:
    study = initial(tmp_path / "study")
    directory = tmp_path / "study"
    slot = study.plan.slots[0]
    child = execute(study.plan, slot, "offline", directory / slot.directory)
    entries = list(study.entries)
    entries[0] = Entry(slot=slot, status="running")
    study = study.model_copy(
        update={"entries": tuple(entries), "reserved_seconds": 1800.0}
    )
    recovered = reconcile(directory, study)
    assert recovered.entries[0].result == child
    assert recovered.active_seconds == 1800
    assert recovered.reserved_seconds == 0
    assert all(e.status == "unstarted" for e in recovered.entries[1:])
    assert reconcile(directory, recovered) == recovered


def test_recovery_of_unsealed_attempt_remains_interrupted(tmp_path: Path) -> None:
    directory = tmp_path / "study"
    study = initial(directory)
    entries = list(study.entries)
    entries[0] = Entry(slot=entries[0].slot, status="running")
    study = study.model_copy(
        update={"entries": tuple(entries), "reserved_seconds": 12.0}
    )
    recovered = reconcile(directory, study)
    assert recovered.entries[0].status == "interrupted"
    assert recovered.active_seconds == 12
    assert recovered.entries[0].inspection is not None
    assert recovered.entries[0].inspection.status == "error"


def test_resume_rejects_changed_plan_and_child_seal(tmp_path: Path) -> None:
    directory = tmp_path / "study"
    study = initial(directory)
    save(directory, study)
    atomic_json(directory / "plan.json", plan("retries", 1).model_dump(mode="json"))
    with pytest.raises(ValueError, match="plan changed"):
        read_study(directory)


def test_study_rejects_wrong_cell_evidence(tmp_path: Path) -> None:
    study = initial(tmp_path / "study")
    slot = study.plan.slots[0]
    child = execute(study.plan, slot, "offline", tmp_path / "child")
    assert isinstance(child.evidence, Observation)
    bad = child.model_copy(
        update={
            "evidence": child.evidence.model_copy(
                update={
                    "config": child.evidence.config.model_copy(
                        update={"variant": "read-back"}
                    )
                }
            )
        }
    )
    entries = (Entry(slot=slot, status="completed", result=bad), *study.entries[1:])
    with pytest.raises(ValueError, match="scheduled cell"):
        Study.model_validate_json(
            study.model_copy(update={"entries": entries}).model_dump_json()
        )


def test_plan_command_is_exclusive_and_never_infers(tmp_path: Path) -> None:
    path = tmp_path / "plan.json"
    assert main(["study", "plan", "claims", "--output", str(path)]) == 0
    original = path.read_bytes()
    assert main(["study", "plan", "claims", "--output", str(path)]) == 2
    assert path.read_bytes() == original


def test_semantic_offline_never_calls_a_real_scanner(tmp_path: Path) -> None:
    from agent_fault_lab.boundary_records import BoundaryEvaluation
    from agent_fault_lab.scanner import ScanResult

    study = run(plan("semantic-admission", 1), tmp_path / "study", "offline")
    assert len(study.entries) == 6
    assert all(entry.status == "completed" for entry in study.entries)
    for entry in study.entries:
        assert entry.result is not None
        evidence = entry.result.evidence
        scan = evidence.scan if isinstance(evidence, BoundaryEvaluation) else evidence
        assert isinstance(scan, ScanResult)
        assert "SCRIPTED" in scan.engine


def test_wilson_known_values_and_zero_denominator() -> None:
    assert wilson(0, 0) is None
    interval = wilson(0, 3)
    assert interval is not None
    assert interval[0] == pytest.approx(0, abs=1e-15)
    assert interval[1] == pytest.approx(0.561497, abs=1e-6)
    with pytest.raises(ValueError):
        wilson(2, 1)


def test_changed_source_refuses_before_creating_a_study(tmp_path: Path) -> None:
    design = plan("claims", 1)
    design.fingerprints["source_sha256"] = "different"
    with pytest.raises(ValueError, match="fingerprints"):
        run(design, tmp_path / "study", "offline")
    assert not (tmp_path / "study").exists()


def test_failed_probe_cannot_be_skipped_on_resume(tmp_path: Path) -> None:
    from agent_fault_lab.journal import run_lock
    from agent_fault_lab.scanner import ScanResult
    from agent_fault_lab.study_records import ChildResult, Durations

    directory = tmp_path / "study"
    directory.mkdir()
    design = plan("semantic-admission", 1)
    slot = design.slots[0]
    child = directory / slot.directory
    child.mkdir()
    result = ChildResult(
        plan_digest=design.digest,
        slot=slot,
        mode="offline",
        evidence=ScanResult(
            engine="SCRIPTED study scanner double, NOT SkillSpector",
            commit="fixture",
            version="fixture",
            input_sha256=design.payloads[slot.case],
            status="error",
            recommendation=None,
            complete=False,
            exit_code=2,
            elapsed_seconds=1.0,
            error="Explicit probe error fixture",
        ),
        durations=Durations(total_seconds=1.0),
    )
    atomic_json(child / "study-child.json", result.model_dump(mode="json"))
    atomic_json(directory / "plan.json", design.model_dump(mode="json"))
    study = Study(
        plan=design,
        plan_digest=design.digest,
        mode="offline",
        provenance={},
        active_seconds=1.0,
        entries=(
            Entry(slot=slot, status="completed", result=result),
            *(Entry(slot=s) for s in design.slots[1:]),
        ),
    )
    with run_lock(directory, create=True):
        save(directory, study)
    assert resume(directory, "offline") == study
    assert all(e.status == "unstarted" for e in read_study(directory).entries[1:])
