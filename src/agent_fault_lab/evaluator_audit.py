"""M15: run independent reference cases against disposable evaluator mutations."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal, Self

from pydantic import JsonValue, model_validator

from agent_fault_lab.audit_corpus import corpus
from agent_fault_lab.audit_mutations import MUTATIONS, Mutation, apply
from agent_fault_lab.journal import Versioned, atomic_json


class AuditCase(Versioned):
    case: str
    equivalence: str | None
    expected: dict[str, JsonValue]
    grade: dict[str, JsonValue] | None
    mismatches: tuple[dict[str, JsonValue], ...]
    error: str | None

    @model_validator(mode="after")
    def assertions(self) -> Self:
        from agent_fault_lab.audit_worker import projection

        if self.error is None:
            if self.grade is None:
                raise ValueError("Successful reference execution requires a grade")
            expected = tuple(
                {"field": key, "expected": value, "actual": projection(self.grade, key)}
                for key, value in self.expected.items()
                if projection(self.grade, key) != value
            )
            if self.mismatches != expected:
                raise ValueError("Assertion differences do not match saved grades")
        elif self.grade is not None or self.mismatches:
            raise ValueError("Harness error cannot claim assertion evidence")
        return self


class Variant(Versioned):
    name: str
    status: Literal["passed", "detected", "survived", "error"]
    cases: tuple[AuditCase, ...] = ()
    error: str | None = None
    mutation: dict[str, str] | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        has_error = bool(self.error or any(c.error for c in self.cases))
        mismatch = any(c.mismatches for c in self.cases)
        expected = (
            "error"
            if has_error
            else (
                ("detected" if mismatch else "survived")
                if self.name != "baseline"
                else ("error" if mismatch else "passed")
            )
        )
        if self.status != expected or (not self.cases and not self.error):
            raise ValueError("Variant verdict does not follow assertion evidence")
        return self


class Audit(Versioned):
    artifact: Literal["evaluator-audit"] = "evaluator-audit"
    corpus_version: Literal["m15-v1"] = "m15-v1"
    evaluator_versions: tuple[str, ...] = ("m03-v1", "boundary-evaluation/schema-1")
    source_sha256: str
    reference_count: int
    variants: tuple[Variant, ...]

    @property
    def passed(self) -> bool:
        return (
            len(self.variants) == 13
            and self.variants[0].status == "passed"
            and all(v.status == "detected" for v in self.variants[1:])
        )

    @model_validator(mode="after")
    def inventory(self) -> Self:
        names = tuple(v.name for v in self.variants)
        if names != ("baseline", *(m.name for m in MUTATIONS)):
            raise ValueError("Audit requires the baseline and all twelve mutant slots")
        for variant in self.variants:
            if variant.cases and len(variant.cases) != self.reference_count:
                raise ValueError("Incomplete reference-case inventory")
            if variant.cases:
                reference = self.variants[0].cases
                if (
                    tuple((c.case, c.expected, c.equivalence) for c in variant.cases)
                    != tuple((c.case, c.expected, c.equivalence) for c in reference)
                    or len({c.case for c in variant.cases}) != self.reference_count
                ):
                    raise ValueError(
                        "Variants must use the same unique reference cases"
                    )
        return self


def render_audit(audit: Audit) -> str:
    lines = [
        "# Evaluator audit",
        "",
        f"Result: {'PASS' if audit.passed else 'FAIL'}.",
        "",
        f"Corpus {audit.corpus_version}: {audit.reference_count} "
        "independent SQL fixtures.",
        "A detected mutant has an assertion mismatch; "
        "harness errors never count as detection.",
        "These fixtures test the evaluator, not model reliability.",
        "",
        "| Variant | Status | Mismatching cases | Errors |",
        "| --- | --- | ---: | ---: |",
    ]
    for v in audit.variants:
        lines.append(
            f"| {v.name} | {v.status} | "
            f"{sum(bool(c.mismatches) for c in v.cases)} | "
            f"{sum(bool(c.error) for c in v.cases) + bool(v.error)} |"
        )
    lines.extend(("", "## Assertion evidence", ""))
    for v in audit.variants:
        if v.error:
            lines.append(f"- {v.name}: {v.error}")
        for c in v.cases:
            if c.error or c.mismatches:
                detail = c.error or json.dumps(
                    c.mismatches, ensure_ascii=False, sort_keys=True
                )
                lines.append(f"- {v.name} / {c.case}: {detail}")
    return "\n".join(lines) + "\n"


def run_variant(package: Path, directory: Path, mutation: Mutation | None) -> Variant:
    directory.mkdir()
    name = mutation.name if mutation else "baseline"
    record = None
    try:
        with tempfile.TemporaryDirectory(prefix="aflab-evaluator-") as temporary:
            root = Path(temporary)
            copied = root / "agent_fault_lab"
            shutil.copytree(
                package, copied, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
            )
            if mutation:
                original = (copied / mutation.file).read_bytes()
                apply(copied, mutation)
                record = {
                    "file": mutation.file,
                    "before": mutation.before,
                    "after": mutation.after,
                    "original_sha256": hashlib.sha256(original).hexdigest(),
                    "mutated_sha256": hashlib.sha256(
                        (copied / mutation.file).read_bytes()
                    ).hexdigest(),
                }
            bootstrap = (
                "import sys; sys.path.insert(0, sys.argv.pop(1)); "
                "from agent_fault_lab.audit_worker import main; main()"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    bootstrap,
                    str(root),
                    str(directory.resolve()),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            (directory / "worker.log").write_text(
                result.stdout + result.stderr, encoding="utf-8"
            )
            if result.returncode:
                raise ValueError(
                    f"Isolated worker exited {result.returncode}; see worker.log"
                )
            raw = json.loads((directory / "result.json").read_text(encoding="utf-8"))
            cases = tuple(AuditCase.model_validate_json(json.dumps(c)) for c in raw)
            if tuple(c.case for c in cases) != tuple(r.name for r in corpus()):
                raise ValueError("Worker reference inventory mismatch")
            errors = any(c.error for c in cases)
            mismatch = any(c.mismatches for c in cases)
            status: Literal["passed", "detected", "survived", "error"] = (
                "error"
                if errors or (mutation is None and mismatch)
                else (
                    "passed"
                    if mutation is None
                    else "detected"
                    if mismatch
                    else "survived"
                )
            )
            return Variant(name=name, status=status, cases=cases, mutation=record)
    except Exception as exc:
        return Variant(
            name=name,
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            mutation=record,
        )


def run_audit(directory: Path) -> Audit:
    directory.mkdir()  # Never overwrite an earlier audit or reuse its databases.
    package = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(package.glob("*.py")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    baseline = run_variant(package, directory / "baseline", None)
    variants = [baseline]
    for mutation in MUTATIONS:
        variants.append(
            run_variant(package, directory / mutation.name, mutation)
            if baseline.status == "passed"
            else Variant(
                name=mutation.name, status="error", error="Not run: baseline failed"
            )
        )
    result = Audit(
        source_sha256=digest.hexdigest(),
        reference_count=len(corpus()),
        variants=tuple(variants),
    )
    atomic_json(directory / "comparison.json", result.model_dump(mode="json"))
    (directory / "report.md").write_text(render_audit(result), encoding="utf-8")
    return result


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser(
        "evaluator", help="Independent grader reference audit."
    )
    sub = parser.add_subparsers(dest="evaluator_command", required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--output", type=Path, required=True)


def command(args: argparse.Namespace) -> int:
    result = run_audit(args.output)
    print(render_audit(result))
    return 0 if result.passed else 2
