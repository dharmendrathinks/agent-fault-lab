"""Immutable study design and explicit inventories; no inference or execution."""

import hashlib
import random
from importlib.metadata import version
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, JsonValue, model_validator

from agent_fault_lab.boundary_records import BoundaryEvaluation
from agent_fault_lab.context_cases import M12_CASES, TITLE, memory_payload, payload_for
from agent_fault_lab.evaluation import StateInspection
from agent_fault_lab.experiments import Observation
from agent_fault_lab.journal import Versioned
from agent_fault_lab.model import ModelSettings
from agent_fault_lab.retry_reports import RetryObservation
from agent_fault_lab.runtime_records import RUNTIME_CASES, RuntimeResult, runtime_config
from agent_fault_lab.scanner import BENIGN_SKILL, ScanResult

PRESETS: dict[str, tuple[tuple[str, ...], tuple[str, str], str]] = {
    "runtime": (RUNTIME_CASES, ("native", "langgraph"), "runtime"),
    "claims": (("healthy", "dropped-write"), ("baseline", "read-back"), "prompt"),
    "retries": (
        ("retry-healthy", "lost-reply-once"),
        ("retry-unprotected", "retry-idempotent"),
        "retry_policy",
    ),
    "approvals": (("approved", "rejected"), ("audit", "enforce"), "permission_policy"),
    "injection": (
        ("injection-override", "injection-override-benign"),
        ("audit", "enforce"),
        "permission_policy",
    ),
    "context": (("memory-stale-title",), ("cached", "refresh"), "context_policy"),
    "semantic-admission": (
        ("injection-override", "injection-override-benign"),
        ("static", "static-plus-semantic"),
        "scanner_profile",
    ),
    "scanner": (
        tuple(M12_CASES),
        ("static", "static-plus-semantic"),
        "scanner_profile",
    ),
}


def fingerprint() -> dict[str, str | None]:
    """Include actual source bytes, even when Git considers them untracked."""
    package = Path(__file__).parent
    digest = hashlib.sha256()
    for source in sorted(package.glob("*.py")):
        digest.update(source.name.encode() + b"\0" + source.read_bytes())
    root = package.parents[1]
    result: dict[str, str | None] = {
        "source_sha256": digest.hexdigest(),
        "package_version": version("agent-fault-lab"),
    }
    for name, relative in (
        ("root_lock_sha256", "uv.lock"),
        ("scanner_lock_sha256", "integrations/skillspector/uv.lock"),
        ("runtime_lock_sha256", "integrations/langgraph/uv.lock"),
    ):
        path = root / relative
        result[name] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
    return result


class Slot(Versioned):
    sequence: int = Field(ge=1)
    repetition: int = Field(ge=1)
    case: str
    policy: str
    participant: Literal["agent", "workflow", "scanner", "probe"]

    @property
    def directory(self) -> str:
        return f"{self.sequence:04d}-{self.participant}-{self.case}-{self.policy}"


def schedule(preset: str, repetitions: int, seed: int) -> tuple[Slot, ...]:
    cases, policies, _ = PRESETS[preset]
    rng = random.Random(seed)
    slots: list[Slot] = []
    if preset in ("scanner", "semantic-admission"):
        for case in ("injection-override-benign", "injection-override"):
            slots.append(
                Slot(
                    sequence=len(slots) + 1,
                    repetition=1,
                    case=case,
                    policy="static-plus-semantic",
                    participant="probe",
                )
            )
    for repetition in range(1, repetitions + 1):
        blocks = list(cases)
        rng.shuffle(blocks)
        ordered = policies if repetition % 2 else policies[::-1]
        for case in blocks:
            participants = (
                ("agent", "workflow")
                if preset in ("claims", "retries")
                else ("scanner",)
                if preset == "scanner"
                else ("agent",)
            )
            for participant in participants:
                for policy in ordered:
                    slots.append(
                        Slot.model_validate(
                            {
                                "sequence": len(slots) + 1,
                                "repetition": repetition,
                                "case": case,
                                "policy": policy,
                                "participant": participant,
                            }
                        )
                    )
    return tuple(slots)


def payload_hashes(preset: str) -> dict[str, str]:
    return {
        case: hashlib.sha256(
            (
                payload_for(case)
                if case in M12_CASES
                else memory_payload(TITLE)
                if case == "memory-stale-title"
                else BENIGN_SKILL
            ).encode()
        ).hexdigest()
        for case in PRESETS[preset][0]
    }


class StudyPlan(Versioned):
    artifact: Literal["study-plan"] = "study-plan"
    preset: str
    axis: str
    repetitions: int = Field(default=3, ge=1, le=10)
    seed: int = 42
    budget_seconds: float = Field(default=1800.0, gt=0, le=1800, allow_inf_nan=False)
    settings: ModelSettings = ModelSettings()
    model_digest: Literal[
        "0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0"
    ] = "0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0"
    semantic_scan_seconds: Literal[180] = 180
    semantic_request_limit: Literal[12] = 12
    semantic_request_seconds: Literal[60] = 60
    semantic_output_tokens: Literal[1024] = 1024
    runtime: Literal["native", "matched"] = "native"
    model_calls_limit: Literal[6] = 6
    tool_calls_limit: Literal[6] = 6
    fingerprints: dict[str, str | None]
    payloads: dict[str, str]
    slots: tuple[Slot, ...]

    @model_validator(mode="after")
    def matched(self) -> Self:
        if self.preset not in PRESETS or self.axis != PRESETS[self.preset][2]:
            raise ValueError("Unknown preset or comparison axis")
        if self.settings != ModelSettings():
            raise ValueError("Pilot requires the frozen baseline settings")
        if self.runtime != ("matched" if self.preset == "runtime" else "native"):
            raise ValueError("Study runtime differs from the declared preset")
        if self.slots != schedule(self.preset, self.repetitions, self.seed):
            raise ValueError("Schedule differs from the declared matched design")
        if self.payloads != payload_hashes(self.preset):
            raise ValueError("Fixture hashes differ from the declared cases")
        return self

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


def plan(
    preset: str, repetitions: int = 3, seed: int = 42, budget_seconds: float = 1800.0
) -> StudyPlan:
    if preset not in PRESETS:
        raise ValueError("Unknown study preset")
    return StudyPlan(
        preset=preset,
        runtime="matched" if preset == "runtime" else "native",
        axis=PRESETS[preset][2],
        repetitions=repetitions,
        seed=seed,
        budget_seconds=budget_seconds,
        fingerprints=fingerprint(),
        payloads=payload_hashes(preset),
        slots=schedule(preset, repetitions, seed),
    )


class Durations(Versioned):
    total_seconds: float = Field(ge=0, allow_inf_nan=False)
    scanner_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    agent_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    evaluation_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class ChildResult(Versioned):
    artifact: Literal["study-child"] = "study-child"
    plan_digest: str
    slot: Slot
    mode: Literal["offline", "live"]
    evidence: (
        Observation | RetryObservation | BoundaryEvaluation | ScanResult | RuntimeResult
    )
    durations: Durations
    # Keep complete source artifacts; these are additional measured quantities.
    accounting: dict[str, JsonValue] = Field(default_factory=dict)


class Entry(Versioned):
    slot: Slot
    status: Literal["unstarted", "running", "completed", "failed", "interrupted"] = (
        "unstarted"
    )
    elapsed_seconds: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    result: ChildResult | None = None
    inspection: StateInspection | None = None
    error: str | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.result is not None and self.result.slot != self.slot:
            raise ValueError("Child result belongs to a different slot")
        if (self.status == "completed") != (self.result is not None):
            raise ValueError("Completed slot requires a sealed child result")
        if self.status in ("unstarted", "running") and (self.inspection or self.error):
            raise ValueError("Unfinished slot contains final evidence")
        return self


class Study(Versioned):
    artifact: Literal["study-comparison"] = "study-comparison"
    plan: StudyPlan
    plan_digest: str
    mode: Literal["offline", "live"]
    provenance: dict[str, JsonValue]
    active_seconds: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    # Reserve remaining budget before starting a child. A controller crash can
    # only overcharge its unknown duration, never buy another study budget.
    reserved_seconds: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    entries: tuple[Entry, ...]

    @model_validator(mode="after")
    def inventory(self) -> Self:
        if self.plan_digest != self.plan.digest:
            raise ValueError("Study manifest digest mismatch")
        if tuple(entry.slot for entry in self.entries) != self.plan.slots:
            raise ValueError(
                "Study inventory must retain every scheduled slot in order"
            )
        if sum(entry.status == "running" for entry in self.entries) > 1:
            raise ValueError("Study execution must be sequential")
        for entry in self.entries:
            if entry.result and (
                entry.result.plan_digest != self.plan_digest
                or entry.result.mode != self.mode
            ):
                raise ValueError("Child provenance differs from study")
            if entry.result:
                evidence = entry.result.evidence
                if self.plan.preset in ("scanner", "semantic-admission"):
                    scan = (
                        evidence.scan
                        if isinstance(evidence, BoundaryEvaluation)
                        else evidence
                    )
                    if not isinstance(scan, ScanResult):
                        raise ValueError("Semantic cell requires scanner evidence")
                    if scan.input_sha256 != self.plan.payloads[entry.slot.case]:
                        raise ValueError(
                            "Scanned payload differs from scheduled fixture"
                        )
                    expected_engine = (
                        "SCRIPTED study scanner double, NOT SkillSpector"
                        if self.mode == "offline"
                        else "SkillSpector static-plus-semantic"
                        if entry.slot.policy == "static-plus-semantic"
                        else "SkillSpector"
                    )
                    if scan.engine != expected_engine:
                        raise ValueError(
                            "Scanner profile differs from the scheduled cell"
                        )
                    if entry.slot.participant == "agent" and (
                        not isinstance(evidence, BoundaryEvaluation)
                        or evidence.config.case != entry.slot.case
                        or evidence.config.mode != self.mode
                        or evidence.config.surface != "skill"
                        or evidence.config.permission_policy != "audit"
                        or evidence.config.scan_policy != "enforce"
                    ):
                        raise ValueError(
                            "Semantic admission must hold other policies fixed"
                        )
                if self.plan.preset == "claims":
                    if not isinstance(evidence, Observation) or (
                        evidence.config.variant != entry.slot.policy
                        or evidence.config.fault
                        != ("none" if entry.slot.case == "healthy" else entry.slot.case)
                    ):
                        raise ValueError(
                            "Claim evidence differs from its scheduled cell"
                        )
                elif self.plan.preset == "retries":
                    if not isinstance(evidence, RetryObservation) or (
                        evidence.config.case != entry.slot.case
                        or evidence.config.policy != entry.slot.policy
                    ):
                        raise ValueError(
                            "Retry evidence differs from its scheduled cell"
                        )
                elif self.plan.preset == "runtime":
                    if not isinstance(evidence, RuntimeResult) or (
                        evidence.runtime != entry.slot.policy
                        or evidence.evaluation.config
                        != runtime_config(entry.slot.case, self.mode)
                        or evidence.identity.get("lock_sha256")
                        != self.plan.fingerprints.get("runtime_lock_sha256")
                    ):
                        raise ValueError(
                            "Runtime evidence differs from its frozen cell"
                        )
                elif self.plan.preset not in ("scanner", "semantic-admission"):
                    if not isinstance(evidence, BoundaryEvaluation):
                        raise ValueError("Boundary cell requires boundary evidence")
                    config = evidence.config
                    if config.case != entry.slot.case or config.mode != self.mode:
                        raise ValueError("Boundary case or mode changed")
                    policy = (
                        config.context_policy
                        if self.plan.preset == "context"
                        else config.permission_policy
                    )
                    if policy != entry.slot.policy or config.scan_policy != "enforce":
                        raise ValueError(
                            "Boundary policy differs from its scheduled cell"
                        )
                    expected_surface = (
                        "tool" if self.plan.preset == "injection" else "skill"
                    )
                    if config.surface != expected_surface:
                        raise ValueError("Boundary delivery surface changed")
                if entry.slot.participant == "workflow" and (
                    not isinstance(evidence, (Observation, RetryObservation))
                    or evidence.metrics.model_calls != 0
                ):
                    raise ValueError("Ordinary workflow cannot claim model requests")
        running = any(entry.status == "running" for entry in self.entries)
        if running != (self.reserved_seconds > 0):
            raise ValueError("Running child requires a persisted budget reservation")
        return self
