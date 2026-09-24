"""Measure the offline suite and inherited Python children; preserve failures."""

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    environment = dict(
        os.environ, AFLAB_RUN_LIVE_TESTS="0", AFLAB_LIVE_TEST_COMMAND="0"
    )

    def coverage(*arguments: str) -> int:
        return subprocess.run(
            [sys.executable, "-m", "coverage", *arguments],
            cwd=root,
            env=environment,
            check=False,
        ).returncode

    erased = coverage("erase")
    if erased:
        return erased
    # Absolute source scope excludes disposable mutant copies, even when they
    # import the same package name from another directory. No path remapping.
    tested = coverage("run", f"--source={root / 'src/agent_fault_lab'}", "-m", "pytest")
    # Still produce evidence on failure; never let successful reporting mask a
    # failed test suite. Intentionally killed processes may not flush coverage.
    combined = coverage("combine", "--quiet")
    if combined:
        return tested or combined
    encoded = coverage("json")
    xml = coverage("xml")
    reported = coverage("report")
    return tested or encoded or xml or reported


if __name__ == "__main__":
    raise SystemExit(main())
