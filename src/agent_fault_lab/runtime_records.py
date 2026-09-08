"""M16 identities and evidence keep runtime transfer separate from native history."""

from typing import Literal, Self

from pydantic import Field, JsonValue, model_validator

from agent_fault_lab.boundary_records import BoundaryConfig, BoundaryEvaluation
from agent_fault_lab.journal import Versioned

RUNTIME_CASES = ("approved", "rejected", "injection-override", "memory-stale-title")


def runtime_config(case: str, mode: Literal["offline", "live"]) -> BoundaryConfig:
    if case not in RUNTIME_CASES:
        raise ValueError("Runtime transfer supports only the four frozen M16 cases")
    return BoundaryConfig(
        case=case,
        mode=mode,
        surface="tool" if case == "injection-override" else "skill",
        context_policy="refresh" if case == "memory-stale-title" else "cached",
    )


class RuntimeResult(Versioned):
    artifact: Literal["runtime-run"] = "runtime-run"
    runtime: Literal["native", "langgraph"]
    identity: dict[str, JsonValue]
    evaluation: BoundaryEvaluation
    elapsed_seconds: float = Field(ge=0, allow_inf_nan=False)
    nodes: tuple[str, ...]
    resume_supported: Literal[False] = False

    @model_validator(mode="after")
    def matched(self) -> Self:
        if self.evaluation.config != runtime_config(
            self.evaluation.config.case, self.evaluation.config.mode
        ):
            raise ValueError("Runtime transfer changed a matched policy")
        if self.identity.get("langgraph") != "1.2.11":
            raise ValueError(
                "Runtime evidence requires the pinned LangGraph environment"
            )
        if self.runtime == "native" and self.nodes:
            raise ValueError("Native runtime cannot claim graph nodes")
        if any(node not in ("model", "tools", "terminal") for node in self.nodes):
            raise ValueError("Unknown graph node")
        if (
            self.runtime == "langgraph"
            and self.evaluation.status == "finished"
            and (not self.nodes or self.nodes[-1] != "terminal")
        ):
            raise ValueError("Finished LangGraph run lacks a terminal graph node")
        return self


def render_runtime(result: RuntimeResult) -> str:
    from agent_fault_lab.boundary_reports import render_report

    return (
        f"# M16 runtime: {result.runtime}\n\n"
        f"LangGraph environment: {result.identity.get('langgraph')}. "
        f"Elapsed: {result.elapsed_seconds:.3f} seconds.\n\n"
        f"Graph nodes: {', '.join(result.nodes) or 'none (native)'}.\n\n"
        "Manual approval, crash/restart and resume parity are unsupported. "
        "Offline model turns are scripted; they do not demonstrate model "
        "reliability.\n\n" + render_report(result.evaluation)
    )
