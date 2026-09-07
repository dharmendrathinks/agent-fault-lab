"""Capture a portable, explicitly scripted report excerpt through the real CLI."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_fault_lab.cli import main
from agent_fault_lab.comparison import Comparison


def capture(output: Path) -> None:
    # Refuse replacement, including an existing empty directory or symlink.
    output.mkdir(parents=True, exist_ok=False)
    with TemporaryDirectory(prefix="aflab-example-") as temporary:
        source = Path(temporary) / "comparison"
        result = main(
            ["compare", "--offline", "--trials", "1", "--output", str(source)]
        )
        if result != 0:
            raise RuntimeError(f"Scripted comparison failed with exit {result}")
        comparison = Comparison.model_validate_json(
            (source / "comparison.json").read_text(encoding="utf-8")
        )
        selected = [Path("comparison.json"), Path("report.md")]
        for entry in comparison.entries:
            selected.extend(
                Path(entry.spec.directory) / filename
                for filename in ("evaluation.json", "observation.json", "report.md")
            )
        for relative in selected:
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write((source / relative).read_bytes())
    print(f"Captured scripted JSON/report excerpt: {output}")
    print("Not live-model evidence. Raw traces, manifests and databases are omitted.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    capture(parser.parse_args().output)
