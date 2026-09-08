"""Explicit planning and execution entry points for bounded M14 pilots."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal

from agent_fault_lab.studies import read_plan, resume, run
from agent_fault_lab.study_records import PRESETS, plan


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser("study", help="Frozen, repeated M14 comparisons.")
    sub = parser.add_subparsers(dest="study_command", required=True)
    sub.add_parser("list")
    design = sub.add_parser("plan", help="Write an immutable manifest; never infer.")
    design.add_argument("preset", choices=tuple(PRESETS))
    design.add_argument("--repetitions", type=int, default=3, choices=range(1, 11))
    design.add_argument("--seed", type=int, default=42)
    design.add_argument("--budget-seconds", type=float, default=1800.0)
    design.add_argument("--output", type=Path, required=True)
    for name in ("run", "resume"):
        runner = sub.add_parser(name)
        runner.add_argument("path", type=Path)
        mode = runner.add_mutually_exclusive_group(required=True)
        mode.add_argument("--offline", action="store_true")
        mode.add_argument("--live", action="store_true")
        if name == "run":
            runner.add_argument("--output", type=Path, required=True)


def command(args: argparse.Namespace) -> int:
    if args.study_command == "list":
        for name, (cases, policies, axis) in PRESETS.items():
            print(
                f"{name}: {len(cases)} cases; {policies[0]} / {policies[1]}; "
                f"axis {axis}"
            )
        return 0
    if args.study_command == "plan":
        design = plan(args.preset, args.repetitions, args.seed, args.budget_seconds)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(design.model_dump_json(indent=2) + "\n")
        print(f"Planned {len(design.slots)} executions: {args.output}")
        return 0
    mode: Literal["offline", "live"] = "live" if args.live else "offline"
    study = (
        run(read_plan(args.path), args.output, mode)
        if args.study_command == "run"
        else resume(args.path, mode)
    )
    print(
        f"Sealed {sum(e.status == 'completed' for e in study.entries)} / "
        f"{len(study.entries)} scheduled executions"
    )
    return 0 if all(e.status == "completed" for e in study.entries) else 2
