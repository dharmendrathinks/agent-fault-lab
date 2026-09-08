"""Execute one frozen study slot; seal evidence only after independent grading."""

import hashlib
import signal
import sys
import time
from pathlib import Path
from types import FrameType
from typing import Literal

from pydantic import JsonValue

from agent_fault_lab.boundaries import run_boundary
from agent_fault_lab.boundary_records import (
    BoundaryConfig,
    BoundaryEvaluation,
    BoundaryJournal,
)
from agent_fault_lab.evaluation import evaluate_run
from agent_fault_lab.experiments import ExperimentConfig, Observation, measure
from agent_fault_lab.faults import FaultInjector
from agent_fault_lab.journal import atomic_json, strict_json
from agent_fault_lab.model import ToolCall
from agent_fault_lab.ollama_adapter import OllamaClient
from agent_fault_lab.reliability import scripted_response_client
from agent_fault_lab.retries import RetryConfig, RetryExecutor
from agent_fault_lab.retry_reports import RetryObservation, count_retries
from agent_fault_lab.runtime_records import RuntimeResult
from agent_fault_lab.scanner import Scanner, ScanResult, SkillSpector
from agent_fault_lab.study_records import (
    ChildResult,
    Durations,
    Slot,
    StudyPlan,
    fingerprint,
)
from agent_fault_lab.tasks import TaskStore
from agent_fault_lab.tools import ToolDelivery, execute_tool
from agent_fault_lab.trace import Recorder
from agent_fault_lab.workflow import LABEL, run_workflow

TITLE = "Review the invoice"


class OfflineStudyScanner:
    """Explicit semantic-study machinery double; no scanner accuracy claim."""

    def scan(self, content: bytes, directory: Path) -> ScanResult:
        directory.mkdir()
        (directory / "SKILL.md").write_bytes(content)
        result = ScanResult(
            engine="SCRIPTED study scanner double, NOT SkillSpector",
            commit="offline-double",
            version="offline-double",
            input_sha256=hashlib.sha256(content).hexdigest(),
            status="admitted",
            recommendation="SAFE",
            complete=True,
            exit_code=0,
            elapsed_seconds=0.0,
        )
        atomic_json(directory / "scan.json", result.model_dump(mode="json"))
        return result


class WorkflowTools:
    def __init__(self, store: TaskStore, injector: FaultInjector) -> None:
        self.store = store
        self.injector = injector

    def execute(self, call: ToolCall, call_id: str) -> ToolDelivery:
        result = execute_tool(self.store, call, injector=self.injector, call_id=call_id)
        return ToolDelivery(content=result.model_dump_json(), executed=result.executed)


def legacy_config(slot: Slot) -> ExperimentConfig:
    return ExperimentConfig.model_validate(
        {
            "variant": slot.policy,
            "fault": "none" if slot.case == "healthy" else slot.case,
        }
    )


def workflow(
    plan: StudyPlan, slot: Slot, directory: Path
) -> Observation | RetryObservation:
    directory.mkdir()
    config = legacy_config(slot) if plan.preset == "claims" else ExperimentConfig()
    retry = (
        RetryConfig.model_validate({"case": slot.case, "policy": slot.policy})
        if plan.preset == "retries"
        else None
    )
    atomic_json(
        directory / "manifest.json",
        {
            "artifact": "workflow-run",
            "schema_version": 1,
            "client": LABEL,
            "plan_digest": plan.digest,
            "slot": slot.model_dump(mode="json"),
            "expected_title": TITLE,
            "config": (retry or config).model_dump(mode="json"),
        },
    )
    with (directory / "trace.jsonl").open("x") as stream:
        recorder = Recorder(stream)
        store = TaskStore(directory / "tasks.sqlite3")
        executor = (
            RetryExecutor(store, recorder, retry)
            if retry
            else WorkflowTools(store, FaultInjector(config.fault, recorder))
        )
        result = run_workflow(executor, TITLE, recorder)
        atomic_json(directory / "result.json", result.model_dump(mode="json"))
        recorder.emit("evaluation_started")
        evaluation = evaluate_run(
            directory / "tasks.sqlite3", TITLE, result, client=LABEL
        )
        atomic_json(directory / "evaluation.json", evaluation.model_dump(mode="json"))
        recorder.emit("evaluation_completed")
        metrics = measure(recorder.events, result)
        observation: Observation | RetryObservation
        if retry:
            counts = count_retries(recorder.events)
            observation = RetryObservation(
                config=retry,
                evaluation=evaluation,
                retry=counts,
                metrics=metrics.model_copy(
                    update={"fault_exercised": counts.fault_activations > 0}
                ),
            )
        else:
            observation = Observation(
                config=config, evaluation=evaluation, metrics=metrics
            )
        atomic_json(directory / "observation.json", observation.model_dump(mode="json"))
    from agent_fault_lab.saved_reports import render_saved_report, replace_report

    replace_report(directory, render_saved_report(directory)[1])
    return observation


def boundary_config(
    plan: StudyPlan, slot: Slot, mode: Literal["offline", "live"]
) -> BoundaryConfig:
    values: dict[str, JsonValue] = {"case": slot.case, "mode": mode}
    if plan.preset in ("approvals", "injection"):
        values["permission_policy"] = slot.policy
    if plan.preset == "injection":
        values["surface"] = "tool"
    if plan.preset == "context":
        values["context_policy"] = slot.policy
    if plan.preset == "semantic-admission":
        values["permission_policy"] = "audit"
    return BoundaryConfig.model_validate(values)


def execute(
    plan: StudyPlan,
    slot: Slot,
    mode: Literal["offline", "live"],
    directory: Path,
    *,
    study_lock: int | None = None,
) -> ChildResult:
    from agent_fault_lab.cli import _comparison_client, _execute

    started = time.monotonic()
    accounting: dict[str, JsonValue] = {}
    evidence: (
        Observation | RetryObservation | BoundaryEvaluation | ScanResult | RuntimeResult
    )
    scanner: Scanner = SkillSpector()
    if plan.preset in ("scanner", "semantic-admission"):
        from agent_fault_lab.semantic_scanner import SemanticSkillSpector

        scanner = (
            OfflineStudyScanner()
            if mode == "offline"
            else SemanticSkillSpector()
            if slot.policy == "static-plus-semantic"
            else SkillSpector()
        )
    if slot.participant in ("scanner", "probe"):
        from agent_fault_lab.context_cases import payload_for

        directory.mkdir()
        evidence = scanner.scan(payload_for(slot.case).encode(), directory / "scan")
    elif slot.participant == "workflow":
        evidence = workflow(plan, slot, directory)
    elif plan.preset in ("claims", "retries"):
        client = OllamaClient() if mode == "live" else None
        provenance: dict[str, JsonValue] = {
            "mode": "offline scripted study, NOT AI evidence"
        }
        if client:
            info = client.inspect()
            if not info.ready:
                raise ValueError("Live preflight failed: " + "; ".join(info.problems))
            provenance = info.model_dump(mode="json")
        if plan.preset == "claims":
            config = legacy_config(slot)
            evidence = _execute(
                client or _comparison_client(config),
                directory,
                provenance,
                config=config,
            )
        else:
            retry = RetryConfig.model_validate(
                {"case": slot.case, "policy": slot.policy}
            )
            evidence = _execute(
                client or scripted_response_client(TITLE),
                directory,
                provenance,
                reliability=retry,
            )
    elif plan.preset == "runtime":
        from agent_fault_lab.runtimes import run_runtime

        evidence = run_runtime(
            slot.policy, slot.case, mode, directory, study_lock=study_lock
        )
    else:
        evidence = run_boundary(
            directory, boundary_config(plan, slot, mode), scanner=scanner
        )
    total = time.monotonic() - started
    runtime_evidence = evidence if isinstance(evidence, RuntimeResult) else None
    if runtime_evidence:
        accounting["runtime_identity"] = runtime_evidence.identity
        evidence = runtime_evidence.evaluation
    scanner_seconds: float | None = 0.0
    agent_seconds: float | None = None
    evaluation_seconds: float | None = None
    if isinstance(evidence, (Observation, RetryObservation)):
        from agent_fault_lab.trace import Event

        events = [
            Event.model_validate_json(line)
            for line in (directory / "trace.jsonl").read_text().splitlines()
        ]
        agent_seconds = evidence.metrics.elapsed_seconds
        starts = [
            event.elapsed_seconds
            for event in events
            if event.kind == "evaluation_started"
        ]
        ends = [
            event.elapsed_seconds
            for event in events
            if event.kind == "evaluation_completed"
        ]
        if len(starts) == len(ends) == 1:
            evaluation_seconds = ends[0] - starts[0]
    elif isinstance(evidence, BoundaryEvaluation):
        scanner_seconds = evidence.scan.elapsed_seconds
        events_b = BoundaryJournal.events(directory / "boundary.sqlite3")
        requests = [event for event in events_b if event.kind == "model_requested"]
        returns = [event for event in events_b if event.kind == "model_returned"]
        usage = []
        for event in returns:
            turn = event.data.get("turn")
            if isinstance(turn, dict):
                usage.append(turn.get("usage"))
        accounting["model_usage"] = usage
        accounting["requested_model_calls"] = len(requests)
        measured = {
            event.kind: event.data.get("seconds")
            for event in events_b
            if event.kind in ("agent_execution_measured", "evaluation_measured")
        }
        agent_time = measured.get("agent_execution_measured")
        evaluation_time = measured.get("evaluation_measured")
        if type(agent_time) is float:
            agent_seconds = agent_time
        elif evidence.model_calls == evidence.tool_calls == 0:
            agent_seconds = 0.0
        if type(evaluation_time) is float:
            evaluation_seconds = evaluation_time
    else:
        scanner_seconds = evidence.elapsed_seconds
        agent_seconds = 0.0
    gateway = directory / "scan" / "gateway.json"
    if gateway.is_file():
        captured = strict_json(gateway.read_text())
        assert isinstance(captured, dict)
        accounting["scanner_physical_requests"] = captured.get("requests")
        accounting["scanner_transport_error"] = captured.get("error")
        records = captured.get("records")
        if isinstance(records, list):
            accounting["scanner_usage"] = [
                {
                    "prompt_tokens": raw.get("prompt_eval_count"),
                    "output_tokens": raw.get("eval_count"),
                }
                if isinstance(raw, dict)
                else None
                for record in records
                if isinstance(record, dict)
                for raw in [record.get("native_response")]
            ]
    result = ChildResult(
        plan_digest=plan.digest,
        slot=slot,
        mode=mode,
        evidence=runtime_evidence or evidence,
        durations=Durations(
            total_seconds=total,
            scanner_seconds=scanner_seconds,
            agent_seconds=agent_seconds,
            evaluation_seconds=evaluation_seconds,
        ),
        accounting=accounting,
    )
    atomic_json(directory / "study-child.json", result.model_dump(mode="json"))
    return result


def main() -> None:
    def interrupted(signum: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt("Study worker deadline or termination signal")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGALRM, interrupted)
    signal.setitimer(signal.ITIMER_REAL, float(sys.argv[4]))
    root = Path(sys.argv[1])
    from agent_fault_lab.studies import read_plan

    plan = read_plan(root / "plan.json")
    if plan.fingerprints != fingerprint():
        raise ValueError(
            "Study source/dependency fingerprints changed before child start"
        )
    slot = plan.slots[int(sys.argv[2]) - 1]
    if sys.argv[3] not in ("offline", "live"):
        raise ValueError("Explicit study mode required")
    mode: Literal["offline", "live"] = "live" if sys.argv[3] == "live" else "offline"
    if mode == "live":
        from agent_fault_lab.studies import read_study

        info = OllamaClient().inspect()
        if (
            not info.ready
            or info.model_digest != plan.model_digest
            or info.model_dump(mode="json") != read_study(root).provenance
        ):
            raise ValueError("Frozen local model identity changed before child start")
    try:
        execute(
            plan,
            slot,
            mode,
            root / slot.directory,
            study_lock=int(sys.argv[5]) if len(sys.argv) > 5 else None,
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


if __name__ == "__main__":
    main()
