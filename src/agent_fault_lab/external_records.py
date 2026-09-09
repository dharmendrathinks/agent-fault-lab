"""M17 evidence: framework execution is not a model completion claim."""

from typing import Literal, Self

from pydantic import Field, model_validator

from agent_fault_lab.evaluation import Evaluation
from agent_fault_lab.journal import Versioned
from agent_fault_lab.model import Record, RunResult

CASE = "langgraph-router-resume"
SOURCE: Literal["https://github.com/langchain-ai/langgraph/issues/8834"] = (
    "https://github.com/langchain-ai/langgraph/issues/8834"
)
TITLE = "Review the invoice."
type Condition = Literal["healthy", "node-failure", "router-failure"]
type Mode = Literal["memory-same", "sqlite-same", "sqlite-fresh"]
type Status = Literal["completed", "failed", "interrupted", "unstarted"]
type Symptom = Literal["reproduced", "not_reproduced", "inconclusive"]
CONDITIONS: tuple[Condition, ...] = ("healthy", "node-failure", "router-failure")
MODES: tuple[Mode, ...] = ("memory-same", "sqlite-same", "sqlite-fresh")


class Identity(Record):
    python: str
    platform: str
    dependencies: dict[str, str]
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    harness_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def pinned(self) -> Self:
        if not self.python.startswith("3.12.") or any(
            self.dependencies.get(name) != version
            for name, version in (
                ("langgraph", "1.2.11"),
                ("langgraph-checkpoint-sqlite", "3.1.1"),
            )
        ):
            raise ValueError("External reproduction requires the pinned Python/runtime")
        return self


class Snapshot(Record):
    values: dict[str, int]
    pending: tuple[Literal["work", "sink"], ...]
    task_errors: tuple[str, ...]


class Counts(Record):
    work: int = Field(ge=0)
    router: int = Field(ge=0)
    sink: int = Field(ge=0)


class Invocation(Record):
    phase: Literal["initial", "resume"]
    pid: int = Field(gt=0)
    before: Snapshot
    after: Snapshot
    returned: dict[str, int] | None
    error: str | None
    counts: Counts
    fault_activated: bool
    elapsed_seconds: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if (self.returned is None) == (self.error is None):
            raise ValueError("Invocation must have either a return or an exception")
        if self.phase == "resume" and self.fault_activated:
            raise ValueError("Resume must not reinject the fault")
        return self


def execution(invocation: Invocation | None) -> RunResult:
    return RunResult(
        status="finished"
        if invocation and invocation.error is None
        else "protocol_error",
        model_calls=0,
        tool_calls=0,
        tool_executions=0,
        final_content=None,
        error=invocation.error if invocation else "No complete invocation evidence",
    )


def check_evaluation(evaluation: Evaluation, invocation: Invocation | None) -> None:
    """Reject contradictory saved summaries without reopening any database."""
    if (
        evaluation.expected_title != TITLE
        or evaluation.client != "external-framework-no-model"
        or evaluation.execution != execution(invocation)
        or evaluation.report.status != "absent"
        or evaluation.report.claim is not None
        or evaluation.false_success is not None
        or evaluation.claim_support != "not_evaluated"
    ):
        raise ValueError("External execution must retain an absent model claim")
    state = evaluation.state
    if state.status == "error":
        if state.rows is not None or not state.error:
            raise ValueError("Unknown storage must retain an inspection error")
        expected = "unknown"
    else:
        if state.rows is None or state.error is not None:
            raise ValueError("Inspectable storage requires rows")
        expected = (
            "completed"
            if len(state.rows) == 1
            and state.rows[0].title == TITLE
            and state.rows[0].id.strip()
            else "not_completed"
        )
    if evaluation.task_outcome != expected:
        raise ValueError("Task summary contradicts captured SQL rows")


class Observation(Record):
    invocation: Invocation
    evaluation: Evaluation

    @model_validator(mode="after")
    def consistent(self) -> Self:
        check_evaluation(self.evaluation, self.invocation)
        return self


def classify(
    condition: Condition,
    status: Status,
    observations: tuple[Observation, ...],
    final: Evaluation | None,
) -> Symptom:
    if status != "completed" or final is None or len(observations) != 2:
        return "inconclusive"
    initial, resumed = (o.invocation for o in observations)
    return (
        "reproduced"
        if condition == "router-failure"
        and initial.fault_activated
        and resumed.error is None
        and not resumed.after.pending
        and resumed.after.values == {"value": 1}
        and initial.counts.sink + resumed.counts.sink == 0
        and final.state.rows == ()
        else "not_reproduced"
    )


class Slot(Record):
    id: str
    condition: Condition
    mode: Mode
    repetition: int = Field(ge=1, le=3)
    thread_id: str = Field(min_length=1)
    status: Status = "unstarted"
    symptom: Symptom = "inconclusive"
    observations: tuple[Observation, ...] = ()
    final_evaluation: Evaluation | None = None
    error: str | None = None
    elapsed_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.id != f"{self.mode}-{self.condition}-{self.repetition}":
            raise ValueError("Slot identity disagrees with its matrix cell")
        phases = tuple(o.invocation.phase for o in self.observations)
        if phases not in ((), ("initial",), ("initial", "resume")):
            raise ValueError("Invocation sequence must be initial then resume")
        if self.symptom != classify(
            self.condition, self.status, self.observations, self.final_evaluation
        ):
            raise ValueError("Symptom classification contradicts captured evidence")
        if self.status == "completed" and len(self.observations) == 2:
            first, second = (o.invocation for o in self.observations)
            if self.mode != "sqlite-fresh" and first.pid != second.pid:
                raise ValueError("Same-process mode has different worker identities")
            if first.after != second.before:
                raise ValueError("Resume did not start from the captured checkpoint")
        if self.status == "unstarted" and (
            self.observations or self.final_evaluation or self.error
        ):
            raise ValueError("Unstarted slot cannot contain execution evidence")
        if self.status == "completed":
            if (
                phases != ("initial", "resume")
                or self.error
                or not self.final_evaluation
            ):
                raise ValueError("Completed lifecycle needs both invocations and SQL")
            if self.final_evaluation.state.status != "ok":
                raise ValueError("Unknown final storage is a harness failure")
            for observation in self.observations:
                inv = observation.invocation
                expected_fault = inv.phase == "initial" and self.condition != "healthy"
                if inv.fault_activated != expected_fault:
                    raise ValueError("Configured fault was not faithfully exercised")
                expected_error = (
                    "RuntimeError: injected:" + self.condition
                    if expected_fault
                    else None
                )
                if (
                    inv.phase == "initial" and inv.error != expected_error
                ) or observation.evaluation.state.status != "ok":
                    raise ValueError("Unexpected execution or inspection error")
        if self.status in ("failed", "interrupted") and not self.error:
            raise ValueError("Incomplete execution needs an explanation")
        if self.final_evaluation:
            check_evaluation(
                self.final_evaluation,
                self.observations[-1].invocation if self.observations else None,
            )
        return self


class Reproduction(Versioned):
    artifact: Literal["external-reproduction"] = "external-reproduction"
    case: Literal["langgraph-router-resume"] = "langgraph-router-resume"
    source: Literal["https://github.com/langchain-ai/langgraph/issues/8834"] = SOURCE
    upstream_reference_commit: Literal["81bf17b23123e4ef8b9d5f49fa09a0122fc2edd1"] = (
        "81bf17b23123e4ef8b9d5f49fa09a0122fc2edd1"
    )
    identity: Identity
    created_at: str
    status: Status
    slots: tuple[Slot, ...]
    elapsed_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    worker_limit_seconds: Literal[30] = 30
    matrix_limit_seconds: Literal[300] = 300
    model_calls: Literal[0] = 0
    model_claim: Literal["absent"] = "absent"

    @model_validator(mode="after")
    def inventory(self) -> Self:
        expected = [(m, c, r) for m in MODES for c in CONDITIONS for r in range(1, 4)]
        if [(s.mode, s.condition, s.repetition) for s in self.slots] != expected:
            raise ValueError(
                "External evidence requires the complete ordered 27-slot inventory"
            )
        if len({s.thread_id for s in self.slots}) != len(self.slots):
            raise ValueError("Every lifecycle needs a fresh thread identity")
        if self.status == "completed" and any(
            s.status != "completed" for s in self.slots
        ):
            raise ValueError("Completed matrix has incomplete slots")
        if self.status == "unstarted" and any(
            s.status != "unstarted" for s in self.slots
        ):
            raise ValueError("Unstarted matrix has started slots")
        return self


def render_external(result: Reproduction) -> str:
    rows = [
        "# External reproduction: LangGraph router resume\n",
        f"Source: {result.source}\n",
        f"Harness: **{result.status}**; elapsed {result.elapsed_seconds:.3f}s. "
        "27 reserved lifecycles; 30s per worker, 300s per matrix.\n",
        f"Python {result.identity.python}; {result.identity.platform}. "
        "LangGraph 1.2.11; SQLite saver 3.1.1.\n",
        "Model calls: **0**. Model claims: **absent**. A normal framework return "
        "is not a model claim or proof of a saved task.\n",
        "| Lifecycle | Harness | Symptom | Task | Initial → resume | Sink calls |",
        "|---|---|---|---|---|---|",
    ]
    for slot in result.slots:
        outcome = (
            slot.final_evaluation.task_outcome if slot.final_evaluation else "unknown"
        )
        invocations = (
            " → ".join(
                "exception" if o.invocation.error else "returned"
                for o in slot.observations
            )
            or "unobserved"
        )
        sinks = sum(o.invocation.counts.sink for o in slot.observations)
        rows.append(
            f"| {slot.id} | {slot.status} | {slot.symptom} | {outcome} | "
            f"{invocations} | {sinks} |"
        )
    rows.extend(
        [
            "",
            "## Evidence and limits",
            "",
            "Each invocation has state/pending-task snapshots, call counts, fault "
            "activation, timing and independent SQL grading in comparison.json. "
            "Per-lifecycle events.jsonl and invocation JSON retain worker evidence. "
            "Reports read captured JSON only; they do not inspect current databases.",
            "",
            "The symptom requires an exercised initial router failure, normal resume, "
            "value=1, no pending work, no sink calls and a verified empty task table. "
            "Other fully captured outcomes remain not_reproduced. Incomplete or "
            "uninspectable attempts remain inconclusive.",
            "",
            "Fresh-process SQLite is restart after an exception, not abrupt-crash or "
            "power-loss recovery. Python socket blocking is not an OS sandbox. "
            "This application-contract reproduction neither confirms a general "
            "framework guarantee nor constitutes independent outside review.",
            "",
            f"Worker SHA-256: `{result.identity.source_sha256}`.  ",
            f"Lock SHA-256: `{result.identity.lock_sha256}`.  ",
            f"Harness SHA-256: `{result.identity.harness_sha256}`.",
            "",
        ]
    )
    for slot in result.slots:
        if slot.error:
            rows.append(f"- {slot.id}: {slot.error.replace(chr(10), ' ')}")
    return "\n".join(rows) + "\n"
