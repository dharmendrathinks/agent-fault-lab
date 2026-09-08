"""Reference contracts and mutation isolation must fail for the right reason."""

import json
from pathlib import Path

import pytest

from agent_fault_lab import evaluation
from agent_fault_lab.audit_corpus import corpus
from agent_fault_lab.audit_mutations import Mutation
from agent_fault_lab.audit_worker import projection
from agent_fault_lab.evaluator_audit import Audit, AuditCase, run_audit, run_variant
from agent_fault_lab.saved_reports import render_saved_report


def test_independent_corpus_and_all_mutants(tmp_path: Path) -> None:
    source = Path(evaluation.__file__)
    original = source.read_bytes()
    result = run_audit(tmp_path / "audit")
    assert result.passed
    assert result.reference_count == 43
    assert len(result.variants) == 13
    assert all(not c.error for v in result.variants for c in v.cases)
    assert all(any(c.mismatches for c in v.cases) for v in result.variants[1:])
    assert source.read_bytes() == original
    assert (
        render_saved_report(tmp_path / "audit")[1]
        == (tmp_path / "audit/report.md").read_text()
    )
    assert Audit.model_validate_json(result.model_dump_json()) == result
    groups: dict[str, list[dict[str, object]]] = {}
    for case in result.variants[0].cases:
        if case.equivalence:
            assert case.grade
            fields = ("task_outcome", "report.status", "claim_support", "state.status")
            groups.setdefault(case.equivalence, []).append(
                {p: projection(case.grade, p) for p in fields}
            )
    assert all(
        len(group) >= 2 and all(v == group[0] for v in group)
        for group in groups.values()
    )
    with pytest.raises(FileExistsError):
        run_audit(tmp_path / "audit")


@pytest.mark.parametrize(
    "before,after",
    [
        ("NOT AN ANCHOR", "anything"),
        ("state = inspect_state(database)", "this is invalid !!!"),
        ("state = inspect_state(database)", "raise RuntimeError('worker fault')"),
    ],
)
def test_broken_mutations_are_errors_not_detected(
    tmp_path: Path, before: str, after: str
) -> None:
    result = run_variant(
        Path(evaluation.__file__).parent,
        tmp_path / "variant",
        Mutation("broken", "evaluation.py", before, after),
    )
    assert result.status == "error"
    assert result.error or any(c.error for c in result.cases)


def test_reference_expectations_not_derived_from_grades() -> None:
    source = Path(__file__).parents[1] / "src/agent_fault_lab/audit_corpus.py"
    text = source.read_text()
    assert "evaluate_run(" not in text and "store.create" not in text
    refs = {r.name: r for r in corpus()}
    assert refs["missing-write"].expected["task_outcome"] == "not_completed"
    assert refs["uninspectable-missing"].expected["task_outcome"] == "unknown"
    assert refs["replay-after-expiry"].expected["context.new_effects"] == 1


def test_missing_mutants_cannot_claim_a_pass(tmp_path: Path) -> None:
    result = run_audit(tmp_path / "audit")
    raw = json.loads(result.model_dump_json())
    raw["variants"].pop()
    with pytest.raises(ValueError, match="twelve mutant"):
        Audit.model_validate_json(json.dumps(raw))


def test_fabricated_assertion_difference_is_rejected() -> None:
    with pytest.raises(ValueError, match="differences"):
        AuditCase(
            case="fixture",
            equivalence=None,
            expected={"task_outcome": "completed"},
            grade={"task_outcome": "completed"},
            error=None,
            mismatches=(
                {
                    "field": "task_outcome",
                    "expected": "completed",
                    "actual": "not_completed",
                },
            ),
        )
