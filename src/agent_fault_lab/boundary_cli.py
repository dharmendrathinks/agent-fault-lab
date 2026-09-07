"""Public M11 commands; no automatic inference when approving an operation."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from uuid import uuid4

from agent_fault_lab.boundaries import decide_approval, load_boundary, run_boundary
from agent_fault_lab.boundary_records import CASES, BoundaryConfig, BoundaryEvaluation
from agent_fault_lab.boundary_reports import (
    BoundaryComparison,
    read_evaluation,
    render_comparison,
)
from agent_fault_lab.context_cases import M12_CASES, M13_CASES
from agent_fault_lab.journal import atomic_json
from agent_fault_lab.saved_reports import replace_report
from agent_fault_lab.scanner import BENIGN_SKILL, SkillSpector, read_skill


def is_boundary(directory: Path) -> bool:
    path = directory / "boundary.sqlite3"
    return path.exists() or path.is_symlink()


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    scanner = commands.add_parser(
        "scanner", help="Pinned static SkillSpector integration."
    )
    scans = scanner.add_subparsers(dest="scanner_command", required=True)
    doctor = scans.add_parser(
        "doctor", help="Verify installation identity; no scan or inference."
    )
    doctor.add_argument("--python", type=Path)
    scan = scans.add_parser(
        "scan", help="Scan a local Markdown skill, never execute it."
    )
    scan.add_argument("path", type=Path)
    scan.add_argument("--python", type=Path)
    scan.add_argument("--output", type=Path, required=True)
    boundaries = commands.add_parser(
        "boundaries", help="Scanned context and task write approval experiments."
    )
    experiments = boundaries.add_subparsers(dest="boundary_command", required=True)
    experiments.add_parser("list")
    for name in ("run", "compare"):
        experiment = experiments.add_parser(name)
        experiment.add_argument("case", choices=(*CASES, *M12_CASES, *M13_CASES))
        mode = experiment.add_mutually_exclusive_group(required=True)
        mode.add_argument("--offline", action="store_true")
        mode.add_argument("--live", action="store_true")
        experiment.add_argument("--output", type=Path)
        experiment.add_argument("--scanner-python", type=Path)
        experiment.add_argument("--skill", type=Path)
        experiment.add_argument(
            "--surface", choices=("skill", "task", "tool"), default="skill"
        )
        experiment.add_argument(
            "--permission-policy", choices=("enforce", "audit"), default=None
        )
        experiment.add_argument(
            "--scan-policy", choices=("enforce", "audit"), default=None
        )
        if name == "run":
            experiment.add_argument(
                "--context-policy", choices=("cached", "refresh"), default="cached"
            )
    approval = commands.add_parser(
        "approval", help="Inspect or decide an exact pending write; never infer."
    )
    decisions = approval.add_subparsers(dest="approval_command", required=True)
    for name in ("show", "approve", "reject"):
        decision = decisions.add_parser(name)
        decision.add_argument("run_directory", type=Path)
        if name != "show":
            decision.add_argument("operation_id")
        if name == "approve":
            decision.add_argument("--ttl-seconds", type=float, default=300)


def show(evaluation: BoundaryEvaluation) -> int:
    print(
        f"Run {evaluation.run_id}: {evaluation.status}; "
        f"task={evaluation.task_outcome}; "
        f"authorization={evaluation.authorization.status}; "
        f"claim={evaluation.claim_support}"
    )
    if evaluation.status == "awaiting_approval":
        for proposal in evaluation.authorization.proposals:
            print("Approval proposal: " + json.dumps(proposal, ensure_ascii=False))
        print(
            "Use aflab approval approve|reject RUN OPERATION_ID, "
            "then aflab resume RUN --offline|--live."
        )
        return 3
    return (
        2
        if evaluation.status == "error"
        or evaluation.authorization.status == "unknown"
        or (
            evaluation.execution is not None
            and evaluation.execution.status == "provider_error"
        )
        else 0
    )


def command(args: argparse.Namespace) -> int:
    if args.command == "scanner":
        scanner = SkillSpector(args.python)
        if args.scanner_command == "doctor":
            with tempfile.TemporaryDirectory(
                prefix="aflab-scanner-doctor-"
            ) as temporary:
                print(json.dumps(scanner.doctor(Path(temporary)), indent=2))
            return 0
        scan_result = scanner.scan(read_skill(args.path), args.output.absolute())
        print(scan_result.model_dump_json(indent=2))
        return (
            2
            if scan_result.status == "error"
            else 1
            if scan_result.status == "blocked"
            else 0
        )
    if args.command == "approval":
        if args.approval_command == "show":
            journal = load_boundary(args.run_directory)
            print(
                f"Pending operation: {journal.state.operation_id}; "
                f"status: {journal.state.status}"
            )
            print(read_evaluation(args.run_directory).model_dump_json(indent=2))
            return 0
        evaluation = decide_approval(
            args.run_directory,
            args.operation_id,
            approve=args.approval_command == "approve",
            ttl=getattr(args, "ttl_seconds", 300),
        )
        print(
            "Approval decision saved. Explicit resume is required; "
            "no model or task action was executed."
        )
        print(evaluation.model_dump_json(indent=2))
        return 0
    if args.boundary_command == "list":
        print("M11 cases: " + ", ".join(CASES))
        print("M12 cases: " + ", ".join(M12_CASES))
        print("M13 cases: " + ", ".join(M13_CASES))
        print("Permission policies: enforce, audit. Scanner policies: enforce, audit.")
        print(
            "M12 surfaces: skill/task/tool; M13 context: cached/refresh. "
            "--offline scripts the agent but uses real static scanning."
        )
        return 0
    if args.boundary_command == "compare" and args.case == "manual":
        raise ValueError(
            "Use run manual for operator approval; comparisons "
            "require a scripted approval scenario"
        )
    skill = read_skill(args.skill) if args.skill else BENIGN_SKILL.encode()
    if args.skill and args.case in (*M12_CASES, *M13_CASES):
        raise ValueError("M12/M13 use the fixed synthetic corpus; --skill is M11 only")
    if args.boundary_command == "compare":
        if args.case in M12_CASES and (args.scan_policy or args.permission_policy):
            raise ValueError(
                "M12 comparison varies both policies across its four cells"
            )
        if args.case in CASES and args.permission_policy:
            raise ValueError("M11 comparison varies permission policy")
    config = BoundaryConfig(
        case=args.case,
        mode="live" if args.live else "offline",
        permission_policy=args.permission_policy or "enforce",
        scan_policy=args.scan_policy or "enforce",
        surface=args.surface,
        context_policy=getattr(args, "context_policy", "cached"),
    )
    scanner = SkillSpector(args.scanner_python)
    output = args.output
    if output is None:
        Path("runs").mkdir(exist_ok=True)
        output = Path("runs") / f"boundaries-{uuid4()}"
    print(f"Run directory: {output}", flush=True)
    if args.boundary_command == "run":
        return show(run_boundary(output, config, scanner=scanner, skill=skill))
    output.mkdir()
    cells, axes = comparison_cells(config)
    planned = tuple(name for name, _ in cells)
    entries: list[BoundaryEvaluation] = []
    error = None
    try:
        for name, variant in cells:
            result = run_boundary(output / name, variant, scanner=scanner, skill=skill)
            entries.append(result)
            if show(result) == 2:
                error = (
                    "Harness, scanner, provider or evaluator error; "
                    "remaining cells not attempted"
                )
                break
    except (Exception, KeyboardInterrupt) as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        comparison = BoundaryComparison(
            case=args.case,
            planned=planned,
            entries=tuple(entries),
            status="finished"
            if len(entries) == len(planned) and error is None
            else "stopped",
            error=error,
            axes=axes,
        )
        atomic_json(output / "comparison.json", comparison.model_dump(mode="json"))
        replace_report(output, render_comparison(comparison))
    return 2 if error else 0


def comparison_cells(
    config: BoundaryConfig,
) -> tuple[tuple[tuple[str, BoundaryConfig], ...], tuple[str, ...]]:
    if config.case in M12_CASES:
        return tuple(
            (
                f"scan-{scan}_permission-{permission}",
                config.model_copy(
                    update={"scan_policy": scan, "permission_policy": permission}
                ),
            )
            for scan in ("audit", "enforce")
            for permission in ("audit", "enforce")
        ), ("scan_policy", "permission_policy")
    if config.case in M13_CASES:
        return tuple(
            (policy, config.model_copy(update={"context_policy": policy}))
            for policy in ("cached", "refresh")
        ), ("context_policy",)
    return tuple(
        (policy, config.model_copy(update={"permission_policy": policy}))
        for policy in ("audit", "enforce")
    ), ("permission_policy",)
