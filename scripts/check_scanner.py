"""Required real static-scanner acceptance; no semantic or agent inference."""

import argparse
import json
from pathlib import Path
from uuid import uuid4

from agent_fault_lab.boundaries import load_boundary
from agent_fault_lab.boundary_reports import read_evaluation
from agent_fault_lab.cli import main
from agent_fault_lab.journal import atomic_json
from agent_fault_lab.scanner import SkillSpector, read_skill


def check(output: Path, python: Path) -> None:
    output.mkdir(parents=True)
    engine = SkillSpector(python)
    identity = engine.doctor(output)
    atomic_json(output / "identity.json", identity)
    root = Path(__file__).resolve().parents[1]
    fixture = root / "integrations/skillspector/fixtures/suspicious/SKILL.md"
    suspicious = engine.scan(read_skill(fixture), output / "suspicious")
    assert suspicious.status == "blocked", suspicious.model_dump_json()
    raw = json.loads((output / "suspicious/raw-report.json").read_text())
    assert raw["issues"], "Suspicious fixture produced no static findings"
    print("Synthetic suspicious fixture: " + suspicious.model_dump_json())
    # Regression for the observed recommendation at this pin, not an accuracy claim.
    comparison = output / "missing"
    assert (
        main(
            [
                "boundaries",
                "compare",
                "missing",
                "--offline",
                "--output",
                str(comparison),
                "--scanner-python",
                str(python),
            ]
        )
        == 0
    )
    audit = read_evaluation(comparison / "audit")
    enforce = read_evaluation(comparison / "enforce")
    assert audit.scan.status == enforce.scan.status == "admitted"
    assert audit.scan.input_sha256 == enforce.scan.input_sha256
    assert audit.authorization.unauthorized_writes == 1
    assert audit.task_outcome == "completed" and audit.claim_support == "supported"
    assert enforce.authorization.unauthorized_writes == 0
    assert enforce.task_outcome == "not_completed"
    assert main(["report", str(comparison), "--check"]) == 0
    manual = output / "manual"
    assert (
        main(
            [
                "boundaries",
                "run",
                "manual",
                "--offline",
                "--output",
                str(manual),
                "--scanner-python",
                str(python),
            ]
        )
        == 3
    )
    state = load_boundary(manual).state
    assert state.operation_id and state.model_calls == 1
    assert main(["approval", "approve", str(manual), state.operation_id]) == 0
    assert read_evaluation(manual).state.rows == ()
    assert main(["resume", str(manual), "--offline"]) == 0
    complete = read_evaluation(manual)
    assert complete.authorization.authorized_writes == 1
    assert complete.claim_support == "supported" and complete.model_calls == 2
    assert main(["resume", str(manual), "--offline"]) == 0
    assert main(["report", str(manual), "--check"]) == 0
    print(f"PASS: real static SkillSpector; scripted agent; evidence in {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("runs") / f"scanner-check-{uuid4()}"
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path("integrations/skillspector/.venv/bin/python"),
    )
    args = parser.parse_args()
    check(args.output.absolute(), args.python.absolute())
