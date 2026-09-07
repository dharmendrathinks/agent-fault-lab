"""Real static-scanner acceptance for M12/M13; all agents are scripted."""

import argparse
from pathlib import Path
from uuid import uuid4

from agent_fault_lab.boundaries import run_boundary
from agent_fault_lab.boundary_cli import comparison_cells
from agent_fault_lab.boundary_records import BoundaryConfig, BoundaryEvaluation
from agent_fault_lab.boundary_reports import BoundaryComparison, render_comparison
from agent_fault_lab.context_cases import M12_CASES, M13_CASES
from agent_fault_lab.journal import atomic_json
from agent_fault_lab.saved_reports import render_saved_report, replace_report
from agent_fault_lab.scanner import SkillSpector


def check(output: Path, python: Path) -> None:
    output.mkdir(parents=True)
    scanner = SkillSpector(python)
    entries: list[BoundaryEvaluation] = []

    def run(path: Path, config: BoundaryConfig) -> BoundaryEvaluation:
        result = run_boundary(path, config, scanner=scanner)
        assert result.context and result.status != "error", result.error
        assert result.scan.engine == "SkillSpector" and result.scan.complete
        assert result.context.seeded_preserved is True
        if config.permission_policy == "enforce":
            assert result.context.boundary_violations == 0
        assert render_saved_report(path)[1] == (path / "report.md").read_text()
        entries.append(result)
        print(
            f"{config.case} {config.surface} {config.scan_policy}/"
            f"{config.permission_policy}/{config.context_policy}: "
            f"scan={result.scan.recommendation}; delivered={result.context.delivered}; "
            f"unsafe={result.context.unsafe_attempts}; "
            f"violations={result.context.boundary_violations}; "
            f"task={result.task_outcome}",
            flush=True,
        )
        return result

    for case in M12_CASES:
        run(output / case, BoundaryConfig(case=case))
    for surface in ("task", "tool"):
        config = BoundaryConfig.model_validate(
            {"case": "injection-override", "surface": surface}
        )
        directory = output / surface
        directory.mkdir()
        cells, axes = comparison_cells(config)
        observations = tuple(run(directory / name, variant) for name, variant in cells)
        comparison = BoundaryComparison(
            case=config.case,
            axes=axes,
            planned=tuple(name for name, _ in cells),
            entries=observations,
            status="finished",
        )
        atomic_json(directory / "comparison.json", comparison.model_dump(mode="json"))
        replace_report(directory, render_comparison(comparison))
        assert (
            render_saved_report(directory)[1] == (directory / "report.md").read_text()
        )
    for case in M13_CASES:
        directory = output / case
        directory.mkdir()
        cells, axes = comparison_cells(BoundaryConfig(case=case))
        observations = tuple(run(directory / name, variant) for name, variant in cells)
        comparison = BoundaryComparison(
            case=case,
            axes=axes,
            planned=tuple(name for name, _ in cells),
            entries=observations,
            status="finished",
        )
        atomic_json(directory / "comparison.json", comparison.model_dump(mode="json"))
        replace_report(directory, render_comparison(comparison))
    atomic_json(
        output / "summary.json",
        {
            "artifact": "static-context-integration-check",
            "schema_version": 1,
            "agent": "scripted machinery, NOT live model evidence",
            "runs": [entry.model_dump(mode="json") for entry in entries],
        },
    )
    print(f"PASS: {len(entries)} real-scanner context runs; evidence in {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("runs") / f"context-check-{uuid4()}"
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path("integrations/skillspector/.venv/bin/python"),
    )
    args = parser.parse_args()
    check(args.output.absolute(), args.python.absolute())
