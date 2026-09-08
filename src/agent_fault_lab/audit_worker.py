"""Offline subprocess entry point for one isolated evaluator variant."""

import json
import socket
import sys
from pathlib import Path

from pydantic import JsonValue

from agent_fault_lab.audit_corpus import corpus, seed
from agent_fault_lab.boundary_evaluation import evaluate
from agent_fault_lab.boundary_records import BoundaryState
from agent_fault_lab.evaluation import evaluate_run


def projection(value: JsonValue, path: str) -> JsonValue:
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            raise ValueError(f"Missing grade field: {path}")
        value = value[key]
    return value


def evaluate_corpus(directory: Path) -> list[dict[str, JsonValue]]:
    results: list[dict[str, JsonValue]] = []
    for reference in corpus():
        case_dir = directory / reference.name
        try:
            run = seed(reference, case_dir)
            grade = (
                evaluate(case_dir, run)
                if isinstance(run, BoundaryState)
                else evaluate_run(
                    case_dir / "tasks.sqlite3",
                    reference.title,
                    run,
                    client="independent-reference",
                )
            )
            raw = json.loads(grade.model_dump_json())
            mismatches: list[JsonValue] = []
            for key, expected in reference.expected.items():
                actual = projection(raw, key)
                if actual != expected:
                    mismatches.append(
                        {"field": key, "expected": expected, "actual": actual}
                    )
            results.append(
                {
                    "case": reference.name,
                    "equivalence": reference.equivalence,
                    "expected": reference.expected,
                    "grade": raw,
                    "mismatches": mismatches,
                    "error": None,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "case": reference.name,
                    "error": f"{type(exc).__name__}: {exc}",
                    "mismatches": [],
                    "expected": reference.expected,
                    "grade": None,
                    "equivalence": reference.equivalence,
                }
            )
    return results


def main() -> None:
    def blocked(*args: object, **kwargs: object) -> None:
        raise OSError("Network disabled in evaluator audit")

    socket.socket.connect = blocked  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked  # type: ignore[method-assign,assignment]
    socket.socket.bind = blocked  # type: ignore[method-assign]
    socket.socket.sendto = blocked  # type: ignore[method-assign,assignment]
    directory = Path(sys.argv[1])
    result = evaluate_corpus(directory)
    (directory / "result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
